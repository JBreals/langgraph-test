"""PTE Graph Builder.

가이드라인 §5:
- 제어 흐름은 그래프(State + Edge)로만 결정
"""

from langgraph.graph import StateGraph, START, END

from src.pte.state import PTEState
from src.pte.nodes import (
    planner_node,
    executor_node,
    replanner_node,
    final_answer_node,
    error_handler_node,
)
from src.pte.nodes.intent_classifier import intent_classifier_node


def after_intent_classifier(state: PTEState) -> str:
    """Intent Classifier 후 분기 결정.

    - needs_tool=True → planner
    - needs_tool=False → final_answer (도구 없이 바로 응답)
    """
    if state.get("needs_tool", True):
        return "planner"
    return "final_answer"


def after_planner(state: PTEState) -> str:
    """Planner 후 분기 결정.

    - error 있음 → error_handler
    - plan 있음 → executor
    - plan 없음 → final_answer
    """
    if state.get("error"):
        return "error_handler"
    if state.get("plan"):
        return "executor"
    return "final_answer"


def after_executor(state: PTEState) -> str:
    """Executor 후 분기 결정.

    - 마지막 step 실패 → replanner
    - plan에 더 있음 → executor
    - plan 완료 → final_answer
    """
    if not state.get("past_steps"):
        return "final_answer"

    last_step = state["past_steps"][-1]

    if last_step.get("status") == "failure":
        return "replanner"

    if state.get("plan"):
        return "executor"

    return "final_answer"


def after_replanner(state: PTEState) -> str:
    """Re-planner 후 분기 결정.

    - error 있음 → error_handler
    - 정상 → executor
    """
    if state.get("error"):
        return "error_handler"
    return "executor"


def build_pte_graph() -> StateGraph:
    """PTE 그래프 생성.

    그래프 구조:
    ```
    START → intent_classifier → planner → [executor ↔ replanner] → final_answer → END
                    ↘ final_answer (chitchat)              ↘ error_handler → END
    ```

    Returns:
        컴파일된 StateGraph
    """
    # 그래프 생성
    workflow = StateGraph(PTEState)

    # 노드 추가
    workflow.add_node("intent_classifier", intent_classifier_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("replanner", replanner_node)
    workflow.add_node("final_answer", final_answer_node)
    workflow.add_node("error_handler", error_handler_node)

    # 엣지 추가
    workflow.add_edge(START, "intent_classifier")

    # Intent Classifier 후 분기
    workflow.add_conditional_edges(
        "intent_classifier",
        after_intent_classifier,
        {
            "planner": "planner",
            "final_answer": "final_answer",
        },
    )

    # Planner 후 분기
    workflow.add_conditional_edges(
        "planner",
        after_planner,
        {
            "executor": "executor",
            "final_answer": "final_answer",
            "error_handler": "error_handler",
        },
    )

    # Executor 후 분기
    workflow.add_conditional_edges(
        "executor",
        after_executor,
        {
            "executor": "executor",
            "replanner": "replanner",
            "final_answer": "final_answer",
        },
    )

    # Re-planner 후 분기
    workflow.add_conditional_edges(
        "replanner",
        after_replanner,
        {
            "executor": "executor",
            "error_handler": "error_handler",
        },
    )

    # 종료 엣지
    workflow.add_edge("final_answer", END)
    workflow.add_edge("error_handler", END)

    return workflow.compile()


# 싱글톤 그래프 인스턴스
_graph = None


def get_pte_graph() -> StateGraph:
    """PTE 그래프 싱글톤 반환."""
    global _graph
    if _graph is None:
        _graph = build_pte_graph()
    return _graph
