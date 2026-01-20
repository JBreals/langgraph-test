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
- Previous context: {previous_context}
- Conversation history: {history}
- Current time: {current_datetime}

## Intent Types
- new_question: 새로운 주제에 대한 질문
- follow_up: 이전 대화의 후속 질문 ("더 있어?", "또?", "다른 건?", "자세히")
- clarification: 이전 답변에 대한 명확화 요청 ("무슨 말이야?", "예시 들어줘")
- chitchat: 인사, 감사, 잡담 ("고마워", "안녕", "ㅋㅋ", "오키")

## Think step by step, then output:

### Step 1: Intent Classification
What type of message is this? (new_question / follow_up / clarification / chitchat)

### Step 2: Constraints Extraction (for follow_up)
If follow_up, list ALL constraints that must be preserved.
**IMPORTANT**: Use "Previous context" first (if available), then conversation history.
- Time/Year (연도, 기간) - e.g., "2022년", "2020~2024년"
- Location (지역, 위치)
- Preferences (알레르기, 채식, 예산, 분위기)
- Subject (what they were asking about)
- Any other requirements

⚠️ Time constraints are especially important! If "Previous context" has a year, PRESERVE it.

### Step 3: Time Sensitive
Is this query time-sensitive?
- current: 현재/최신 기준 (요즘, 최신, 트렌드, 인기, 핫한, 올해)
- specified: 사용자가 연도/기간 지정 (2020년, 작년, 90년대)
- none: 시간 무관 (정의, 개념, 역사적 사실, 원리)

⚠️ IMPORTANT: Time expression handling:
- current: PRESERVE existing time expressions ("요즘", "최신", "트렌드")
- specified: PRESERVE user's year/period, do NOT add new time expressions like "최신"
  - "2024년 쿠버네티스 정보" → "2024년 쿠버네티스 정보" (O)
  - "2024년 쿠버네티스 정보" → "2024년 쿠버네티스 최신 정보" (X) ← 불필요한 "최신" 추가
- none: No time expressions needed

### Step 4: Rewritten Query
Rewrite the query to be explicit, preserving all constraints from Step 2.
Do NOT add time expressions that user didn't use.

### Step 5: Tool Needed?
Does this require external tools (search, calculator, etc.)?
- new_question: 대부분 true (검색, 계산 등 필요)
- follow_up: 새로운 정보 요청이면 true, 이전 답변 재설명만이면 false
- clarification: 이전 답변 재설명이면 false, 추가 정보 필요하면 true
- chitchat: 항상 false

## Output format:
---
Intent: [new_question|follow_up|clarification|chitchat]
Constraints: [list of preserved constraints, or "none" for new questions]
Time sensitive: [none|current|specified]
Rewritten query: [explicit query with all constraints, preserve time expressions]
Needs tool: [true|false]
---

## Examples

User: "더 있어?"
History: "[User]: 영등포 견과류 알레르기 안전한 맛집 추천해줘 [Assistant]: A식당, B식당을 추천드립니다..."
---
Intent: follow_up
Constraints: 위치(영등포), 제약사항(견과류 알레르기 안전), 주제(맛집)
Time sensitive: none
Rewritten query: 영등포 견과류 알레르기 안전한 다른 맛집 추천
Needs tool: true
---

User: "고마워!"
History: (any)
---
Intent: chitchat
Constraints: none
Time sensitive: none
Rewritten query:
Needs tool: false
---

User: "요즘 핫한 카페 알려줘"
History: (없음), Current time: 2025년 1월
---
Intent: new_question
Constraints: none
Time sensitive: current
Rewritten query: 요즘 핫한 카페 추천
Needs tool: true
---

User: "2024년 쿠버네티스 정보 알려줘"
History: (없음)
---
Intent: new_question
Constraints: none
Time sensitive: specified
Rewritten query: 2024년 쿠버네티스 정보
Needs tool: true
---

User: "무슨 말이야? 다시 설명해줘"
History: "[User]: 쿠버네티스 뭐야? [Assistant]: 쿠버네티스는 컨테이너 오케스트레이션 플랫폼입니다..."
---
Intent: clarification
Constraints: 주제(쿠버네티스)
Time sensitive: none
Rewritten query: 쿠버네티스 설명 재요청
Needs tool: false
---

User: "그럼 2022년에는 어떤 기능이 추가됐어?"
History: "[User]: 쿠버네티스 뭐야? [Assistant]: 쿠버네티스는 컨테이너 오케스트레이션 플랫폼입니다..."
---
Intent: follow_up
Constraints: 주제(쿠버네티스)
Time sensitive: specified
Rewritten query: 2022년 쿠버네티스 추가된 기능
Needs tool: true
---

User: "보안 측면에서 더 알려줘"
Previous context: "2022년 쿠버네티스 정보"
History: "[User]: 2022년 쿠버네티스 정보 알려줘 [Assistant]: 2022년 쿠버네티스는..."
---
Intent: follow_up
Constraints: 연도(2022년), 주제(쿠버네티스)
Time sensitive: specified
Rewritten query: 2022년 쿠버네티스 보안
Needs tool: true
---

User: "오늘 서울시는 미세먼지 저감 대책의 일환으로 차량 2부제를 시행한다고 발표했다. 이에 따라 홀수 날짜에는 홀수 번호판 차량만... (긴 본문)"
History: (없음)
---
Intent: new_question
Constraints: none
Time sensitive: none
Rewritten query: (사용자가 제공한 콘텐츠 분석/처리)
Needs tool: false
---"""


def _format_history(messages: list[dict[str, str]], max_chars: int = 3000) -> str:
    """대화 히스토리를 문자열로 포맷 (최신 우선 보존).

    Args:
        messages: 대화 히스토리
        max_chars: 최대 문자 수

    Returns:
        포맷된 히스토리 문자열
    """
    if not messages:
        return "(없음)"

    lines = []
    total_chars = 0

    # 최신 메시지부터 역순으로 추가 (최근 게 더 중요)
    for msg in reversed(messages):
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")
        line = f"[{role}]: {content}"

        if total_chars + len(line) > max_chars:
            # 남은 공간에 맞게 자르기
            remaining = max_chars - total_chars
            if remaining > 100:
                truncated = content[: remaining - 50] + "..."
                lines.insert(0, f"[{role}]: {truncated}")
            break

        lines.insert(0, line)  # 순서 유지를 위해 앞에 삽입
        total_chars += len(line) + 2  # \n\n 고려

    return "\n\n".join(lines) if lines else "(없음)"


def _parse_intent_response(response_text: str, fallback_query: str) -> dict:
    """Intent classifier CoT 응답 파싱.

    Args:
        response_text: LLM 응답 텍스트
        fallback_query: 파싱 실패 시 사용할 기본 쿼리

    Returns:
        파싱된 결과 dict (intent, rewritten_query, needs_tool, time_sensitive, metadata)
    """
    text = response_text.strip()

    result = {
        "intent": "new_question",
        "rewritten_query": fallback_query,
        "needs_tool": True,
        "time_sensitive": "none",
        "constraints": "",
    }

    # Intent 추출
    intent_match = re.search(
        r'Intent:\s*(new_question|follow_up|clarification|chitchat)',
        text,
        re.IGNORECASE
    )
    if intent_match:
        result["intent"] = intent_match.group(1).lower()

    # Constraints 추출 (디버깅/로깅용)
    constraints_match = re.search(
        r'Constraints:\s*(.+?)(?:\n|---|$)',
        text,
        re.IGNORECASE
    )
    if constraints_match:
        result["constraints"] = constraints_match.group(1).strip()

    # Time sensitive 추출
    time_match = re.search(
        r'Time sensitive:\s*(none|current|specified)',
        text,
        re.IGNORECASE
    )
    if time_match:
        result["time_sensitive"] = time_match.group(1).lower()

    # Rewritten query 추출
    query_match = re.search(
        r'Rewritten query:\s*(.+?)(?:\n|---|$)',
        text,
        re.IGNORECASE
    )
    if query_match:
        query = query_match.group(1).strip()
        # 대괄호, 따옴표 제거
        query = re.sub(r'^[\["\']|[\]"\']$', '', query)
        if query and query.lower() != "none":
            result["rewritten_query"] = query

    # Needs tool 추출
    needs_tool_match = re.search(
        r'Needs tool:\s*(true|false)',
        text,
        re.IGNORECASE
    )
    if needs_tool_match:
        result["needs_tool"] = needs_tool_match.group(1).lower() == "true"

    # chitchat이면 needs_tool = False 강제
    if result["intent"] == "chitchat":
        result["needs_tool"] = False
        result["rewritten_query"] = ""

    return result


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
    previous_rewritten_query = state.get("previous_rewritten_query")

    # LLM 호출
    llm = get_llm(
        model=settings.default_model,
        temperature=0.0,
    )

    history_text = _format_history(messages)

    # 이전 맥락 포맷팅
    previous_context = previous_rewritten_query if previous_rewritten_query else "(없음)"

    prompt = INTENT_CLASSIFIER_PROMPT.format(
        user_input=user_input,
        previous_context=previous_context,
        history=history_text,
        current_datetime=current_datetime,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"User message: {user_input}"),
        ])

        result = _parse_intent_response(response.content, user_input)

        # 디버깅용 로그 (필요시 활성화)
        # if result.get("constraints"):
        #     print(f"[IntentClassifier] Constraints: {result['constraints']}")

        return {
            "intent": result["intent"],
            "rewritten_query": result["rewritten_query"] or user_input,
            "needs_tool": result["needs_tool"],
            "time_sensitive": result["time_sensitive"],
        }

    except Exception as e:
        # 에러 시 기본값 (새 질문으로 처리)
        return {
            "intent": "new_question",
            "rewritten_query": user_input,
            "needs_tool": True,
            "time_sensitive": "none",
        }
