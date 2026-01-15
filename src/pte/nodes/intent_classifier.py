"""Intent Classifier Node.

사용자 질문의 의도를 파악하고 필요시 질문을 재작성합니다.

의도 유형:
- new_question: 새로운 질문
- follow_up: 후속 질문 (더 있어?, 또?, 다른 건?)
- clarification: 명확화 요청 (무슨 말이야?, 예시 들어줘)
- chitchat: 잡담 (고마워, 안녕, 잘가)
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings
from src.pte.state import PTEState


INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a Korean AI assistant.

## Input
- User message: {user_input}
- Conversation history: {history}
- Current time: {current_datetime}

## Task
1. Classify the user's intent
2. If the query is ambiguous (like "더 있어?"), rewrite it to be explicit
3. Determine if tools are needed

## Intent Types
- new_question: 새로운 주제에 대한 질문
- follow_up: 이전 대화의 후속 질문 ("더 있어?", "또?", "다른 건?", "자세히")
- clarification: 이전 답변에 대한 명확화 요청 ("무슨 말이야?", "예시 들어줘")
- chitchat: 인사, 감사, 잡담 ("고마워", "안녕", "ㅋㅋ", "오키")

## CRITICAL: Context Preservation for Follow-up Questions
When rewriting follow-up questions, you MUST preserve ALL important constraints from the conversation history.

Ask yourself: "What conditions/requirements from the original question still apply?"
- User preferences (알레르기, 채식, 예산, 분위기, etc.)
- Location constraints (지역, 위치)
- Any specific requirements the user mentioned
- Target subject (what they were asking about)

These constraints should be carried forward into the rewritten query, even if the user's follow-up is brief like "더 있어?".

## Time Context Awareness
Current time is provided above. Ask yourself: "Would adding time context make this query more relevant?"

Consider adding time (year/month) when:
- The query implies recency (최신, 요즘, 현재, 지금, 올해, etc.)
- The results would be significantly different based on time (트렌드, 뉴스, 인기, 랭킹, etc.)
- The information is time-sensitive (이벤트, 세일, 공연, 전시, etc.)

Handling '요즘/최근/올해' expressions:
- If currently 연초 (early in the year): include BOTH current and previous year for richer results (e.g., "2025-2026 맛집 추천")
- Otherwise: use current year or recent timeframe

Do NOT add time when:
- The query is about timeless facts (역사, 정의, 개념 설명)
- Adding time would make the query unnatural

## Output Format (JSON)
{{
  "intent": "new_question|follow_up|clarification|chitchat",
  "rewritten_query": "명확하게 재작성된 질문 (chitchat인 경우 빈 문자열)",
  "needs_tool": true|false,
  "reasoning": "판단 이유 (한 줄)"
}}

## Examples

User: "1940년에 무슨 일이 있었어?"
History: (없음)
→ {{"intent": "new_question", "rewritten_query": "1940년 역사적 사건", "needs_tool": true, "reasoning": "새로운 질문, 검색 필요"}}

User: "더 있어?"
History: "User: 영등포 견과류 알레르기 안전한 맛집 추천 / Assistant: A식당, B식당 추천..."
→ {{"intent": "follow_up", "rewritten_query": "영등포 견과류 알레르기 안전한 다른 맛집 추천", "needs_tool": true, "reasoning": "후속 질문, 위치+알레르기 조건 유지하며 추가 검색"}}

User: "더 알려줘"
History: "User: 1940년 역사적 사건 / Assistant: 2차대전, 한국전쟁..."
→ {{"intent": "follow_up", "rewritten_query": "1940년 다른 역사적 사건 (과학, 문화, 경제 등)", "needs_tool": true, "reasoning": "후속 질문, 다른 카테고리로 검색"}}

User: "고마워!"
History: (any)
→ {{"intent": "chitchat", "rewritten_query": "", "needs_tool": false, "reasoning": "감사 인사, 도구 불필요"}}

User: "그게 무슨 뜻이야?"
History: "머신러닝 설명함"
→ {{"intent": "clarification", "rewritten_query": "머신러닝 쉽게 설명", "needs_tool": false, "reasoning": "명확화 요청, 이전 답변 재설명"}}

User: "오늘 날씨 어때?"
History: (any)
→ {{"intent": "new_question", "rewritten_query": "오늘 날씨", "needs_tool": true, "reasoning": "새로운 질문, 날씨 도구 필요"}}

User: "요즘 핫한 카페 알려줘"
History: (없음), Current time: 2025년 1월
→ {{"intent": "new_question", "rewritten_query": "2025년 인기 카페 추천", "needs_tool": true, "reasoning": "시간 민감 질문, 현재 연도 추가"}}

Output JSON:"""


def _format_history(messages: list[dict[str, str]], max_items: int = 5) -> str:
    """대화 히스토리를 문자열로 포맷."""
    if not messages:
        return "(없음)"

    recent = messages[-max_items * 2:]
    lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")[:150]
        if len(msg.get("content", "")) > 150:
            content += "..."
        lines.append(f"- {role}: {content}")

    return "\n".join(lines) if lines else "(없음)"


def _parse_intent_response(response_text: str, fallback_query: str) -> dict:
    """Intent classifier 응답 파싱. JSON 실패 시 fallback."""
    text = response_text.strip()

    # 마크다운 코드블록 제거
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        data = json.loads(text)
        return {
            "intent": data.get("intent", "new_question"),
            "rewritten_query": data.get("rewritten_query", fallback_query),
            "needs_tool": data.get("needs_tool", True),
            "reasoning": data.get("reasoning", ""),
        }
    except json.JSONDecodeError:
        pass

    # Fallback: regex로 파싱 시도
    intent_match = re.search(r'"intent"\s*:\s*"([^"]+)"', text)
    query_match = re.search(r'"rewritten_query"\s*:\s*"([^"]*)"', text)
    needs_tool_match = re.search(r'"needs_tool"\s*:\s*(true|false)', text, re.I)

    return {
        "intent": intent_match.group(1) if intent_match else "new_question",
        "rewritten_query": query_match.group(1) if query_match else fallback_query,
        "needs_tool": needs_tool_match.group(1).lower() == "true" if needs_tool_match else True,
        "reasoning": "fallback parsing",
    }


def intent_classifier_node(state: PTEState) -> dict:
    """사용자 질문의 의도를 파악하고 필요시 재작성.

    Args:
        state: 현재 상태

    Returns:
        intent, rewritten_query, needs_tool이 설정된 상태 업데이트
    """
    user_input = state["input"]
    messages = state.get("messages", [])
    current_datetime = state.get("current_datetime", "")

    # LLM 호출
    llm = get_llm(
        model=settings.default_model,
        temperature=0.0,
    )

    history_text = _format_history(messages)

    prompt = INTENT_CLASSIFIER_PROMPT.format(
        user_input=user_input,
        history=history_text,
        current_datetime=current_datetime,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content="Output JSON:"),
        ])

        result = _parse_intent_response(response.content, user_input)

        return {
            "intent": result["intent"],
            "rewritten_query": result["rewritten_query"] or user_input,
            "needs_tool": result["needs_tool"],
        }

    except Exception as e:
        # 에러 시 기본값 (새 질문으로 처리)
        return {
            "intent": "new_question",
            "rewritten_query": user_input,
            "needs_tool": True,
        }
