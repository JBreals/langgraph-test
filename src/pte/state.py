"""PTE Agent State definition.

가이드라인 §2.2:
- plan은 반드시 구조화(JSON)
- past_steps에는 판단/의미 해석 금지
- 상태는 사실(fact)만 담는다
"""

from typing import TypedDict, Any


class PTEState(TypedDict):
    """Plan-then-Execute 에이전트 상태.

    Attributes:
        input: 사용자 요청 원문
        messages: 대화 히스토리 [{"role": "user"|"assistant", "content": "..."}]
        current_datetime: 현재 날짜/시간 (KST)
        tool_manifest: 사용 가능한 도구 목록 (텍스트)
        available_tools: 허용된 도구 이름 목록
        intent: 질문 의도 (follow_up, new_question, chitchat, clarification)
        rewritten_query: 명확하게 재작성된 질문
        needs_tool: 도구 사용 필요 여부
        plan: 실행 대기 중인 step 목록 [{step_id, tool, input, task?}]
        past_steps: 실행 완료된 step과 결과 [{step, status, output}]
        replan_count: 재계획 횟수 (무한 루프 방지)
        error: 에러 메시지 (있으면 Fail-closed)
        result: 사용자에게 반환할 최종 결과
    """

    # 입력
    input: str

    # 대화 히스토리 (주입)
    messages: list[dict[str, str]]

    # 컨텍스트 (주입)
    current_datetime: str

    # 도구 (주입)
    tool_manifest: str
    available_tools: list[str]

    # 의도 분류 (Intent Classifier 결과)
    intent: str  # follow_up, new_question, chitchat, clarification
    rewritten_query: str  # 명확하게 재작성된 질문
    needs_tool: bool  # 도구 사용 필요 여부

    # 계획
    plan: list[dict[str, Any]]

    # 실행 로그
    past_steps: list[dict[str, Any]]

    # 제어
    replan_count: int
    error: str | None

    # 출력
    result: str | None
