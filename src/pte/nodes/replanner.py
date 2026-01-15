"""Re-planner Node.

가이드라인 §6:
- 실패 원인 분석
- 기존 plan을 부분 수정
- 즉흥 실행 금지
- 최대 재계획 횟수 제한
- 새로운 고위험 tool 추가 금지
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings
from src.pte.state import PTEState
from src.pte.schemas import Plan
from src.pte.tool_groups import is_tool_allowed_for_replan


def parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON 추출."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


REPLANNER_PROMPT = """You are a Re-planner that fixes failed execution plans.

## Current Time
{current_datetime}

## Failure Information
Original request: {original_input}

Execution history:
{past_steps}

Remaining plan:
{remaining_plan}

## Rules
1. Analyze the failure cause
2. Modify the plan with alternative approaches
3. HIGH-risk tools (python_repl, etc.) cannot be newly added
4. You can reuse results from successful steps

{tool_manifest}

## Tool Chaining
To use output from a previous step, use `input_from: "step_N"` (N = step_id).

Search tools automatically enhance queries - just pass raw data via `input_from`.

## Input Format
- No input required: `"input": null`
- String input: `"input": "query"`
- Complex input: `"input": {{"param1": "value1"}}`

## Output Format
Return the modified plan in JSON:
{{
  "steps": [...],
  "reasoning": "why this modification"
}}"""


def replanner_node(state: PTEState) -> dict:
    """실패한 계획을 수정.

    Args:
        state: 현재 상태

    Returns:
        수정된 plan 또는 error가 설정된 상태 업데이트
    """
    # 재계획 횟수 체크
    replan_count = state.get("replan_count", 0)
    max_replan = settings.max_replan_count

    if replan_count >= max_replan:
        return {
            "error": f"최대 재계획 횟수({max_replan})를 초과했습니다.",
        }

    # 실패 정보 포맷팅
    past_steps_text = ""
    for i, step_result in enumerate(state["past_steps"], 1):
        step = step_result["step"]
        status = step_result["status"]
        output = step_result["output"][:200]  # 길이 제한
        past_steps_text += f"{i}. [{status}] {step.get('tool')}: {output}\n"

    remaining_plan_text = ""
    for step in state["plan"]:
        remaining_plan_text += f"- {step.get('tool')}: {step.get('input')}\n"

    # LLM 호출
    llm = get_llm(
        model=settings.replanner_model,
        temperature=settings.replanner_temperature,
    )

    system_prompt = REPLANNER_PROMPT.format(
        current_datetime=state["current_datetime"],
        original_input=state["input"],
        past_steps=past_steps_text or "(없음)",
        remaining_plan=remaining_plan_text or "(없음)",
        tool_manifest=state["tool_manifest"],
    )

    try:
        # 일반 LLM 호출 후 수동 파싱
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content="위 실패를 분석하고 수정된 계획을 JSON 형식으로 제시해주세요."),
        ])

        # JSON 파싱
        try:
            parsed = parse_json_response(response.content)
        except json.JSONDecodeError as e:
            return {"error": f"Re-planner JSON 파싱 실패: {e}\n응답: {response.content[:200]}"}

        plan = Plan.model_validate(parsed)

        # 새 계획 유효성 검사
        available_tools = state["available_tools"]
        plan_dicts = []

        for idx, step in enumerate(plan.steps, 1):
            # 허용된 도구인지 확인
            if step.tool not in available_tools:
                return {"error": f"허용되지 않은 도구: {step.tool}"}

            # 고위험 도구 추가 제한
            if not is_tool_allowed_for_replan(step.tool):
                # 기존 계획에 있던 도구인지 확인
                was_in_original = any(
                    s.get("tool") == step.tool
                    for s in state["past_steps"]
                )
                if not was_in_original:
                    return {"error": f"Re-plan에서 고위험 도구 추가 불가: {step.tool}"}

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
            "replan_count": replan_count + 1,
        }

    except Exception as e:
        return {"error": f"재계획 실패: {e}"}
