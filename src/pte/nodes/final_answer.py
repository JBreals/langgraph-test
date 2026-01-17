"""Final Answer Node.

가이드라인 §11:
- Final Answer = 결과 정리 전용
- past_steps, result만 사용
- 새로운 tool 호출 ❌
- 새로운 plan 생성 ❌
"""

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings
from src.pte.state import PTEState


FINAL_ANSWER_PROMPT = """You are a Final Answer node that delivers execution results to the user.

## Current Time
{current_datetime}

## Conversation History
{conversation_history}

## Current Request
- 사용자 원본: {original_input}
- 시스템 해석: {rewritten_query}

## Execution Results
{execution_results}

## Rules
1. Answer based on execution results, naturally incorporating the system's interpretation
2. If original and rewritten queries differ, smoothly acknowledge what you understood
   - Example: User said "더 있어?" → "네, 영등포 견과류 알레르기 안전한 다른 맛집도 찾아봤어요..."
3. If the interpretation seems wrong, you may ask for clarification
4. Do NOT call new tools or create new plans
5. Be honest if results are missing or failed
6. Be concise and clear
7. Respond in the same language as the user's input"""


GENERAL_CONVERSATION_PROMPT = """You are a friendly AI assistant.

## Current Time
{current_datetime}

## Conversation History
{conversation_history}

## User's Request
{original_input}

## How to respond:
1. If user gave an instruction (번역, 요약, 분석, 설명 등) with content → perform that action
2. If user only provided content without clear instruction → analyze the content
   - Identify what type of content it is (article, code, data, etc.)
   - Provide key insights, main points, or notable aspects
   - Ask if they'd like further action (번역, 요약, 상세 설명 등)
3. If it's a simple question or chat → respond naturally

Respond in the same language as the user's input."""


def format_conversation_history(messages: list[dict[str, str]], max_messages: int = 10) -> str:
    """대화 히스토리를 텍스트로 포맷팅."""
    if not messages:
        return "(없음)"

    recent_messages = messages[-max_messages:]
    history_lines = []
    for msg in recent_messages:
        role = "사용자" if msg["role"] == "user" else "어시스턴트"
        content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        history_lines.append(f"- {role}: {content}")
    return "\n".join(history_lines)


def final_answer_node(state: PTEState) -> dict:
    """실행 결과를 사용자 친화적으로 정리.

    Args:
        state: 현재 상태

    Returns:
        result가 설정된 상태 업데이트
    """
    current_datetime = state["current_datetime"]
    messages = state["messages"]
    history_text = format_conversation_history(messages)

    # 원본 입력과 재작성된 쿼리 모두 사용
    original_input = state["input"]
    rewritten_query = state.get("rewritten_query") or original_input

    # 실행 결과가 없는 경우 (도구 불필요 - 일반 대화/콘텐츠 처리)
    if not state["past_steps"]:
        llm = get_llm(
            model=settings.final_model,
            temperature=0.7,
        )

        system_prompt = GENERAL_CONVERSATION_PROMPT.format(
            current_datetime=current_datetime,
            conversation_history=history_text,
            original_input=original_input,
        )

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content="Respond to the user's request above."),
        ])

        return {"result": response.content}

    # 실행 결과 포맷팅
    results_text = ""
    for i, step_result in enumerate(state["past_steps"], 1):
        step = step_result["step"]
        status = step_result["status"]
        output = step_result["output"]

        tool_name = step.get("tool", "unknown")
        task = step.get("task", "")

        if task:
            results_text += f"### Step {i}: {task}\n"
        else:
            results_text += f"### Step {i}: {tool_name}\n"

        results_text += f"- 상태: {status}\n"
        results_text += f"- 결과: {output}\n\n"

    # LLM 호출
    llm = get_llm(
        model=settings.final_model,
        temperature=0.7,
    )

    system_prompt = FINAL_ANSWER_PROMPT.format(
        current_datetime=current_datetime,
        conversation_history=history_text,
        original_input=original_input,
        rewritten_query=rewritten_query,
        execution_results=results_text,
    )

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content="위 결과를 바탕으로 답변해주세요."),
    ])

    return {
        "result": response.content,
    }
