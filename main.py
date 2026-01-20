"""PTE Agent CLI."""

import json
import logging
import sys
from datetime import datetime

import pytz

from src.pte.graph import get_pte_graph
from src.pte.state import PTEState
from src.pte.tool_groups import get_tool_manifest_text, get_available_tools


def get_current_datetime_str() -> str:
    """현재 날짜/시간 문자열 반환 (KST)."""
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.now(kst)
    return now.strftime("%Y년 %m월 %d일 %H시 %M분 (%A, KST)")


def run_agent(
    user_input: str,
    messages: list[dict[str, str]],
    previous_rewritten_query: str | None = None,
    verbose: bool = False,
) -> tuple[str, str | None]:
    """에이전트 실행.

    Args:
        user_input: 사용자 입력
        messages: 대화 히스토리
        previous_rewritten_query: 이전 턴의 재작성된 쿼리 (맥락 유지용)
        verbose: 상세 로그 출력 여부

    Returns:
        Tuple of (최종 결과, 현재 턴의 rewritten_query)
    """
    graph = get_pte_graph()

    # 컨텍스트 주입
    current_datetime = get_current_datetime_str()
    tool_manifest = get_tool_manifest_text()
    available_tools = get_available_tools()

    initial_state: PTEState = {
        "input": user_input,
        "messages": messages,
        "previous_rewritten_query": previous_rewritten_query,
        "current_datetime": current_datetime,
        "tool_manifest": tool_manifest,
        "available_tools": available_tools,
        # Intent Classifier 결과 (초기값)
        "intent": "",
        "rewritten_query": "",
        "needs_tool": True,
        "time_sensitive": "none",
        # 계획 및 실행
        "plan": [],
        "past_steps": [],
        "replan_count": 0,
        "error": None,
        "result": None,
    }

    if verbose:
        # 스트리밍 모드: 각 노드 실행 과정 출력
        final_state = None
        for event in graph.stream(initial_state):
            for node_name, node_output in event.items():
                print(f"\n{'─' * 40}")
                print(f"📍 Node: {node_name}")
                print(f"{'─' * 40}")

                # Intent Classifier 결과 출력
                if node_name == "intent_classifier":
                    intent = node_output.get("intent", "")
                    rewritten = node_output.get("rewritten_query", "")
                    needs_tool = node_output.get("needs_tool", True)
                    print(f"🎯 Intent: {intent}")
                    print(f"   Rewritten Query: {rewritten}")
                    print(f"   Needs Tool: {needs_tool}")

                # Plan 출력 (planner/replanner 노드에서)
                if node_name in ("planner", "replanner") and "plan" in node_output:
                    print("📋 Plan:")
                    if node_output["plan"]:
                        print(json.dumps(node_output["plan"], indent=2, ensure_ascii=False))
                    else:
                        print("   (도구 실행 불필요 - 일반 대화)")

                # 실행 결과 출력
                if "past_steps" in node_output and node_output["past_steps"]:
                    last_step = node_output["past_steps"][-1]
                    status_icon = "✅" if last_step["status"] == "success" else "❌"
                    tool_name = last_step['step'].get('tool')
                    print(f"🔧 Executed: {tool_name} {status_icon}")
                    output_str = str(last_step.get('output') or '')
                    print(f"   Output:\n{output_str}")

                # 에러 출력
                if node_output.get("error"):
                    print(f"⚠️  Error: {node_output['error']}")

                # 최종 결과 출력
                if node_output.get("result"):
                    result_str = str(node_output['result'])[:100]
                    print(f"💬 Result: {result_str}...")

                final_state = node_output

        print(f"\n{'═' * 40}\n")
        result = final_state.get("result", "결과를 생성하지 못했습니다.") if final_state else "결과 없음"
        rewritten = final_state.get("rewritten_query") if final_state else None
        return result, rewritten
    else:
        # 일반 모드
        final_state = graph.invoke(initial_state)
        result = final_state.get("result", "결과를 생성하지 못했습니다.")
        rewritten = final_state.get("rewritten_query")
        return result, rewritten


def setup_logging(verbose: bool):
    """로깅 설정."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # httpx 로그 비활성화 (HTTP Request: POST ... 메시지)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main():
    """CLI 메인 함수."""
    # --verbose 또는 -v 플래그 확인
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    # 로깅 설정
    setup_logging(verbose)

    # 대화 히스토리
    conversation_history: list[dict[str, str]] = []
    # 이전 턴의 재작성된 쿼리 (맥락 유지용)
    previous_rewritten_query: str | None = None

    print("=" * 50)
    print("PTE (Plan-then-Execute) Agent")
    if verbose:
        print("🔍 Verbose mode ON")
    print("=" * 50)
    print("종료: 'quit' 또는 'exit'")
    print("대화 초기화: '/clear'")
    print()

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            # /verbose 명령으로 토글
            if user_input.lower() == "/verbose":
                verbose = not verbose
                print(f"Verbose mode: {'ON' if verbose else 'OFF'}")
                continue

            # /clear 명령으로 대화 초기화
            if user_input.lower() == "/clear":
                conversation_history.clear()
                previous_rewritten_query = None
                print("대화 히스토리가 초기화되었습니다.")
                continue

            print("\n[처리 중...]\n")
            result, current_rewritten = run_agent(
                user_input,
                conversation_history,
                previous_rewritten_query=previous_rewritten_query,
                verbose=verbose,
            )

            # 대화 히스토리에 추가
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": result})

            # 다음 턴을 위해 rewritten_query 저장
            previous_rewritten_query = current_rewritten

            print(f"Agent: {result}")
            print()

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\n오류 발생: {e}\n")


if __name__ == "__main__":
    main()
