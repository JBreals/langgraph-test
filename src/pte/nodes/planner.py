"""Planner Node.

가이드라인 §3:
- Planner = 컴파일러
- 사용자 목표 해석 + 실행 가능한 plan 생성
- 외부 데이터 접근 ❌
- tool 실행 ❌
- JSON Schema validation 실패 시 실행 금지
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings
from src.pte.state import PTEState
from src.pte.schemas import Plan


def parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON 추출.

    마크다운 코드 블록으로 감싸진 경우도 처리.
    """
    # 마크다운 코드 블록 제거
    text = text.strip()
    if text.startswith("```"):
        # ```json 또는 ``` 제거
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return json.loads(text)


PLANNER_PROMPT = """You are a Planner that analyzes user requests and creates execution plans.

## Current Time
{current_datetime}

## User Intent
{intent_context}

## Conversation History
{conversation_history}

## Rules
1. Only use available tools listed below
2. Each step calls exactly one tool
3. Assign step_id starting from 1
4. Return empty steps if no tool is needed
5. Simple time/date questions can be answered from "Current Time" above (no tool needed)
6. Exclusion keywords ("제외", "빼고", "없이") have limited effectiveness in search engines
   - Prefer positive phrasing: "고기 제외" → "채식 맛집", "매운음식 빼고" → "순한 음식"
   - If exclusion is essential, keep it but note that results may not be perfectly filtered

{tool_manifest}

## Handling Follow-up Questions
When intent is "follow_up" (user asking for more/different results):
- Include keywords like "추가", "다른", "더" in the search input
- Reference what category/angle to explore differently
- Example: Previous search was about "한식 맛집" → New search: "영등포 양식 이탈리안 맛집 추가 추천"

## Tool Chaining
To use output from a previous step as input, use `input_from: "step_N"` (N = step_id).

Search tools (`web_search`, `rag_retrieve`, `search_wikipedia`) automatically enhance queries using LLM.
They understand user intent from context, so just pass raw data - no formatting needed.

Example (multi-step with auto-enhancement):
```json
{{"steps": [
  {{"step_id": 1, "tool": "calculator", "input": "100 * 1350", "task": "환율 계산"}},
  {{"step_id": 2, "tool": "web_search", "input_from": "step_1", "task": "구매 가능 제품 검색"}}
]}}
```
→ Step 2: "135000" + 사용자 맥락 → 자동으로 "135000원 전자제품 추천" 검색

## Input Format
- No input required: `"input": null`
- String input: `"input": "query"`
- Complex input: `"input": {{"param1": "value1"}}`

## Output Format
Return JSON strictly following this schema:
{{
  "steps": [
    {{"step_id": 1, "tool": "tool_name", "input": "value", "task": "description"}},
    ...
  ],
  "reasoning": "why this plan"
}}"""


def _format_intent_context(intent: str, original_input: str, rewritten_query: str) -> str:
    """Intent 정보를 프롬프트용 컨텍스트로 포맷."""
    intent_descriptions = {
        "new_question": "새로운 질문",
        "follow_up": "후속 질문 (이전 답변에 대해 더 많은/다른 정보 요청)",
        "clarification": "명확화 요청 (이전 답변 재설명)",
        "chitchat": "일상 대화",
    }

    desc = intent_descriptions.get(intent, "알 수 없음")
    context = f"- Intent: {intent} ({desc})"

    if intent == "follow_up":
        context += "\n- ⚠️ 사용자가 이전과 다른/추가 정보를 원합니다. 검색 시 다른 카테고리나 관점으로 검색하세요."

    if rewritten_query and rewritten_query != original_input:
        context += f"\n- 원본 질문: {original_input}"
        context += f"\n- 재작성된 질문: {rewritten_query}"

    return context


def planner_node(state: PTEState) -> dict:
    """사용자 요청을 실행 계획으로 변환.

    Args:
        state: 현재 상태

    Returns:
        plan 또는 error가 설정된 상태 업데이트
    """
    # rewritten_query가 있으면 사용 (intent classifier가 명확하게 재작성한 질문)
    original_input = state["input"]
    rewritten_query = state.get("rewritten_query") or original_input
    user_input = rewritten_query

    messages = state["messages"]
    current_datetime = state["current_datetime"]
    tool_manifest = state["tool_manifest"]
    available_tools = state["available_tools"]
    intent = state.get("intent", "new_question")

    # Intent 컨텍스트 포맷팅
    intent_context = _format_intent_context(intent, original_input, rewritten_query)

    # 대화 히스토리 포맷팅 (최근 10개만)
    history_text = "(없음)"
    if messages:
        recent_messages = messages[-10:]  # 최근 10개만
        history_lines = []
        for msg in recent_messages:
            role = "사용자" if msg["role"] == "user" else "어시스턴트"
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            history_lines.append(f"- {role}: {content}")
        history_text = "\n".join(history_lines)

    # LLM 호출
    llm = get_llm(
        model=settings.planner_model,
        temperature=settings.planner_temperature,
    )

    system_prompt = PLANNER_PROMPT.format(
        current_datetime=current_datetime,
        intent_context=intent_context,
        conversation_history=history_text,
        tool_manifest=tool_manifest,
    )

    try:
        # 일반 LLM 호출 후 수동 파싱
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input),
        ])

        # JSON 파싱 (마크다운 코드 블록 처리)
        parsed = parse_json_response(response.content)
        plan = Plan.model_validate(parsed)

        # 계획 유효성 검사 및 정규화
        plan_dicts = []
        for idx, step in enumerate(plan.steps, 1):
            # 허용된 도구인지 확인
            if step.tool not in available_tools:
                return {
                    "error": f"허용되지 않은 도구: {step.tool}",
                    "plan": [],
                    "past_steps": [],
                }

            # step_id가 없으면 자동 부여
            step_dict = step.model_dump()
            if step_dict.get("step_id") is None:
                step_dict["step_id"] = idx

            # query를 input으로 정규화
            if step_dict.get("query") and not step_dict.get("input"):
                step_dict["input"] = step_dict["query"]

            plan_dicts.append(step_dict)

        return {
            "plan": plan_dicts,
            "past_steps": [],
            "replan_count": 0,
            "error": None,
        }

    except Exception as e:
        # Fail-closed: JSON 파싱 실패 시 실행 금지
        return {
            "error": f"계획 생성 실패: {e}",
            "plan": [],
            "past_steps": [],
        }
