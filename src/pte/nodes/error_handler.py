"""Error Handler Node.

가이드라인 §10 (Fail-Closed 정책):
- Planner JSON 파싱 실패
- Schema validation 실패
- 허용되지 않은 tool 등장
- 무한 재시도 루프 감지
→ 모두 즉시 중단
"""

from src.pte.state import PTEState


def error_handler_node(state: PTEState) -> dict:
    """Fail-closed 에러 처리.

    Args:
        state: 현재 상태

    Returns:
        result에 에러 메시지가 설정된 상태 업데이트
    """
    error = state.get("error", "알 수 없는 오류")

    # 실행 기록이 있으면 포함
    context = ""
    if state.get("past_steps"):
        context = "\n\n실행된 단계:\n"
        for i, step_result in enumerate(state["past_steps"], 1):
            step = step_result["step"]
            status = step_result["status"]
            context += f"  {i}. {step.get('tool')} [{status}]\n"

    return {
        "result": f"실행이 중단되었습니다.\n\n오류: {error}{context}",
    }
