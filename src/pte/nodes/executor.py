"""Executor Node.

가이드라인 §4:
- Executor = 런타임
- plan에 정의된 step을 그대로 실행
- 결과 기록
- 판단 ❌
- 전략 수정 ❌
"""

from src.pte.state import PTEState
from src.tools import run_tool

# 검색 도구 목록 (context 자동 주입 대상)
SEARCH_TOOLS = {"web_search", "rag_retrieve", "search_wikipedia"}


def executor_node(state: PTEState) -> dict:
    """plan의 첫 번째 step을 실행.

    Args:
        state: 현재 상태

    Returns:
        past_steps에 실행 결과가 추가된 상태 업데이트
    """
    plan = list(state["plan"])  # 복사본 생성
    past_steps = list(state["past_steps"])
    user_input = state["input"]  # 원래 사용자 요청
    messages = state.get("messages", [])  # 대화 히스토리
    intent = state.get("intent", "new_question")  # 질문 의도
    time_sensitive = state.get("time_sensitive", "none")  # 시간 민감도

    if not plan:
        return {"plan": [], "past_steps": past_steps}

    # 첫 번째 step 가져오기 (FIFO)
    step = plan.pop(0)

    # 입력 결정
    tool_input = step.get("input")
    from_previous_step = False

    # input_from이 있으면 이전 step의 output 사용
    input_from = step.get("input_from")

    if input_from and past_steps:
        # "step_N" 형식에서 N 추출
        try:
            ref_step_id = int(input_from.replace("step_", ""))
            for past in past_steps:
                if past["step"].get("step_id") == ref_step_id:
                    tool_input = past["output"]
                    from_previous_step = True
                    break
        except (ValueError, KeyError):
            pass

    # 도구 실행
    tool_name = step.get("tool")

    try:
        # 검색 도구인 경우 context, from_previous_step, history, intent, time_sensitive 자동 주입
        if tool_name in SEARCH_TOOLS:
            output = run_tool(
                tool_name,
                tool_input,
                context=user_input,
                from_previous_step=from_previous_step,
                history=messages,
                intent=intent,
                time_sensitive=time_sensitive,
            )
        else:
            output = run_tool(tool_name, tool_input)
        status = "success"
    except Exception as e:
        output = str(e)
        status = "failure"

    # 결과 기록
    past_steps.append({
        "step": step,
        "status": status,
        "output": output,
    })

    return {
        "plan": plan,
        "past_steps": past_steps,
    }
