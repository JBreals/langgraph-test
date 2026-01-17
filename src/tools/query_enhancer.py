"""LLM-based query enhancement for search tools."""

import json
import re
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings


# =============================================================================
# Web Search Query Enhancement (Intent-based)
# =============================================================================

# 새로운 질문용 프롬프트 - CoT 방식
WEB_SEARCH_NEW_QUESTION_PROMPT = """You are a web search query optimizer.

## Input
- Query: {query}
- User's request: {context}
- Current time: {current_datetime}

## Think step by step, then output:

1. **Core intent**: What is the user really looking for?
2. **Essential keywords only**: What are the minimum necessary keywords?
3. **Negative to positive**: Any avoidance expressions to convert?

## Rules
- CONCISE IS BETTER: Keep query short (under 30 characters ideal, max 50)
- Fewer keywords = better search results
- Only extract essential terms, remove filler words
- Convert negative expressions to positive:
  - "X 알러지/알레르기 안전한" → "알레르기 프렌들리" (remove the allergen name)
  - "X 없는" → positive alternative (e.g., "조용한")

## Output format:
---
Core intent: [one line]
Search query: [SHORT query - essential keywords only]
---"""


# 후속 질문용 프롬프트 - CoT 방식 (중복 방지 강조)
WEB_SEARCH_FOLLOW_UP_PROMPT = """You are a web search query optimizer for FOLLOW-UP questions.

## CRITICAL: User wants DIFFERENT results, not the same ones!

## Conversation History
{history}

## Current Request
- Query: {query}
- User's request: {context}
- Current time: {current_datetime}

## Think step by step:

1. **Already covered**: What was already recommended/discussed?
2. **New angle**: What DIFFERENT category/type should I search?

## Rules
- CONCISE IS BETTER: Keep query short (under 30 characters ideal, max 50)
- Search for a DIFFERENT category/angle than what's in history
- Preserve location/constraints from original query
- Convert "X 알러지 안전한" → "알레르기 프렌들리"

## Output format:
---
Already covered: [what was discussed]
New angle: [different direction]
Search query: [SHORT query - different category, same constraints]
---"""


# 기존 프롬프트 (fallback용으로 유지)
WEB_SEARCH_ENHANCE_PROMPT = WEB_SEARCH_NEW_QUESTION_PROMPT


def _parse_cot_response(response_text: str, fallback_query: str) -> tuple[str, dict]:
    """CoT 응답에서 검색 쿼리와 메타데이터 추출.

    Args:
        response_text: LLM 응답 텍스트
        fallback_query: 파싱 실패 시 사용할 기본 쿼리

    Returns:
        Tuple of (search_query, metadata)
    """
    text = response_text.strip()

    # "Search query:" 라인 찾기 (대소문자 무시)
    query_match = re.search(
        r'Search query:\s*(.+?)(?:\n|---|$)',
        text,
        re.IGNORECASE
    )

    if query_match:
        query = query_match.group(1).strip()
        # 따옴표, 대괄호 제거
        query = re.sub(r'^[\["\']|[\]"\']$', '', query)
        query = query.strip()

        if query and len(query) <= 100:
            # 메타데이터 추출 (디버깅/로깅용)
            metadata = {}

            # Already covered 추출
            covered_match = re.search(
                r'Already covered:\s*(.+?)(?:\n|---|$)',
                text,
                re.IGNORECASE
            )
            if covered_match:
                metadata["already_covered"] = covered_match.group(1).strip()

            # New direction 추출
            direction_match = re.search(
                r'New direction:\s*(.+?)(?:\n|---|$)',
                text,
                re.IGNORECASE
            )
            if direction_match:
                metadata["new_direction"] = direction_match.group(1).strip()

            # Core intent 추출 (new_question용)
            intent_match = re.search(
                r'Core intent:\s*(.+?)(?:\n|---|$)',
                text,
                re.IGNORECASE
            )
            if intent_match:
                metadata["core_intent"] = intent_match.group(1).strip()

            # User wants 추출
            wants_match = re.search(
                r'User wants:\s*(.+?)(?:\n|---|$)',
                text,
                re.IGNORECASE
            )
            if wants_match:
                metadata["user_wants"] = wants_match.group(1).strip()

            return query, metadata

    # Fallback: 마지막 줄을 쿼리로 시도
    lines = [l.strip() for l in text.split('\n') if l.strip() and not l.startswith('#')]
    if lines:
        last_line = lines[-1]
        # 마크다운 형식 제거
        last_line = re.sub(r'^[-*]\s*', '', last_line)
        last_line = re.sub(r'^[\["\']|[\]"\']$', '', last_line)
        if last_line and len(last_line) <= 100 and not last_line.startswith('---'):
            return last_line, {"fallback": True}

    return fallback_query, {"fallback": True, "parse_failed": True}


# =============================================================================
# Wikipedia Query Enhancement (with depth/sentences)
# =============================================================================

WIKIPEDIA_ENHANCE_PROMPT = """You are a Wikipedia search optimizer.

## Input
- Query: {query}
- User's request: {context}
- Conversation history: {history}

## Task
1. Extract the main entity/topic for Wikipedia search
2. Decide how many sentences to retrieve based on query complexity

## Sentence Guidelines
- Simple fact (생년월일, 정의, 뜻): 3-5 sentences
- General topic: 7-10 sentences
- Broad topic (연도, 역사, 국가): 10-15 sentences
- User asks "더 알려줘", "자세히": add 5-10 more sentences

## Output Format (JSON)
{{"query": "검색어", "sentences": 5}}

## Examples
- Query: "아인슈타인 생년월일" → {{"query": "아인슈타인", "sentences": 3}}
- Query: "머신러닝의 정의" → {{"query": "머신러닝", "sentences": 5}}
- Query: "1940년 역사적 사건" → {{"query": "1940년", "sentences": 12}}
- Query: "한국전쟁", History: "더 자세히 알려줘" → {{"query": "한국전쟁", "sentences": 15}}

Output JSON:"""


def _format_history_by_intent(
    history: list[dict[str, str]] | None,
    intent: str = "new_question",
    max_chars: int = 5000,
) -> str:
    """Intent에 따라 히스토리 포맷을 다르게 처리.

    Args:
        history: 대화 히스토리
        intent: 질문 의도 (new_question, follow_up, clarification, chitchat)
        max_chars: 최대 문자 수 (follow_up일 때만 적용)

    Returns:
        포맷된 히스토리 문자열
    """
    if not history:
        return "(없음)"

    if intent == "new_question":
        # 새 질문: 히스토리 최소화 (직전 맥락 참고용으로만)
        recent = history[-2:] if len(history) >= 2 else history
        lines = []
        for msg in recent:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:200]
            if len(msg.get("content", "")) > 200:
                content += "..."
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines) if lines else "(없음)"

    elif intent == "follow_up":
        # 후속 질문: 히스토리 전체 사용 (중복 방지를 위해 최신 것 우선 보존)
        lines = []
        total_chars = 0

        for msg in reversed(history):
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            line = f"[{role}]: {content}"

            if total_chars + len(line) > max_chars:
                # 남은 공간에 맞게 자르기
                remaining = max_chars - total_chars
                if remaining > 100:  # 최소 100자는 포함
                    truncated = content[: remaining - 50] + "..."
                    lines.insert(0, f"[{role}]: {truncated}")
                break

            lines.insert(0, line)  # 순서 유지를 위해 앞에 삽입
            total_chars += len(line) + 2  # \n\n 고려

        return "\n\n".join(lines) if lines else "(없음)"

    else:  # clarification, chitchat
        return "(없음)"


# 기존 함수 유지 (하위 호환성)
def _format_history(history: list[dict[str, str]] | None, max_items: int = 5) -> str:
    """대화 히스토리를 문자열로 포맷 (legacy)."""
    return _format_history_by_intent(history, intent="new_question")


def _parse_wikipedia_response(response_text: str, fallback_query: str) -> tuple[str, int]:
    """Wikipedia LLM 응답 파싱. JSON 실패 시 fallback."""
    text = response_text.strip()

    # JSON 파싱 시도
    try:
        # 마크다운 코드블록 제거
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        data = json.loads(text)
        query = data.get("query", fallback_query)
        sentences = data.get("sentences", 5)

        # 유효성 검사
        if not query or len(query) > 50:
            query = fallback_query
        sentences = max(3, min(20, int(sentences)))  # 3-20 범위

        return query, sentences

    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Fallback: 텍스트에서 쿼리 추출 시도
    # "query": "값" 패턴 찾기
    query_match = re.search(r'"query"\s*:\s*"([^"]+)"', text)
    sentences_match = re.search(r'"sentences"\s*:\s*(\d+)', text)

    if query_match:
        query = query_match.group(1)
        sentences = int(sentences_match.group(1)) if sentences_match else 5
        return query, max(3, min(20, sentences))

    # 최종 fallback: 첫 줄을 쿼리로 사용
    first_line = text.split('\n')[0].strip()
    first_line = re.sub(r'^["\']|["\']$', '', first_line)
    if first_line and len(first_line) <= 50:
        return first_line, 5

    return fallback_query, 5


def enhance_query_for_web_search(
    query: str,
    context: str | None,
    history: list[dict[str, str]] | None = None,
    intent: str = "new_question",
) -> str:
    """Web Search용 쿼리 증강 (Intent 기반).

    Args:
        query: 원본 쿼리
        context: 사용자 요청
        history: 대화 히스토리
        intent: 질문 의도 (new_question, follow_up, clarification, chitchat)

    Returns:
        증강된 검색 쿼리
    """
    try:
        llm = get_llm(
            model=settings.default_model,
            temperature=0.0,
        )

        current_dt = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        safe_query = query.replace("{", "{{").replace("}", "}}")
        safe_context = (context or "").replace("{", "{{").replace("}", "}}")

        # Intent에 따라 프롬프트와 히스토리 처리 분기
        if intent == "follow_up":
            # 후속 질문: 전체 히스토리 + 중복 방지 강조 프롬프트
            history_text = _format_history_by_intent(history, intent="follow_up")
            prompt = WEB_SEARCH_FOLLOW_UP_PROMPT.format(
                query=safe_query[:200],
                context=safe_context[:200],
                current_datetime=current_dt,
                history=history_text,
            )
        else:
            # 새 질문: 히스토리 최소화 + 단순 프롬프트
            prompt = WEB_SEARCH_NEW_QUESTION_PROMPT.format(
                query=safe_query[:200],
                context=safe_context[:200],
                current_datetime=current_dt,
            )

        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"Query to optimize: {safe_query[:200]}"),
        ])

        # CoT 응답 파싱
        enhanced, metadata = _parse_cot_response(response.content, query.strip())

        # 디버깅용 로그 (필요시 활성화)
        # if metadata:
        #     print(f"[QueryEnhancer] {intent}: {metadata}")

        if not enhanced or len(enhanced) > 100:
            return query.strip()

        return enhanced

    except Exception:
        return query.strip()


def maybe_enhance_query(
    query: str,
    context: str | None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
    intent: str = "new_question",
) -> tuple[str, bool]:
    """Web Search용 쿼리 증강.

    Args:
        query: Original query
        context: User's original request (optional)
        from_previous_step: True if query comes from previous tool output
        history: 대화 히스토리
        intent: 질문 의도 (new_question, follow_up, clarification, chitchat)

    Returns:
        Tuple of (enhanced_query, was_enhanced)
    """
    if not context:
        return query, False

    enhanced = enhance_query_for_web_search(query, context, history, intent)
    was_changed = (enhanced != query.strip())

    return enhanced, was_changed


def enhance_query_for_wikipedia(
    query: str,
    context: str | None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
    intent: str = "new_question",
) -> tuple[str, int, bool]:
    """Wikipedia 검색용 쿼리 최적화 + 검색 깊이 결정.

    Args:
        query: 원본 쿼리
        context: 사용자 요청 (optional)
        from_previous_step: 이전 도구 출력인 경우 True
        history: 대화 히스토리
        intent: 질문 의도 (new_question, follow_up, clarification, chitchat)

    Returns:
        Tuple of (optimized_query, sentences, was_changed)
    """
    query_stripped = query.strip()

    try:
        llm = get_llm(
            model=settings.default_model,
            temperature=0.0,
        )

        safe_query = query.replace("{", "{{").replace("}", "}}")
        safe_context = (context or "").replace("{", "{{").replace("}", "}}")
        # Intent에 따라 히스토리 처리
        history_text = _format_history_by_intent(history, intent)

        prompt = WIKIPEDIA_ENHANCE_PROMPT.format(
            query=safe_query[:500],
            context=safe_context[:200],
            history=history_text,
        )

        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content="Output JSON:"),
        ])

        optimized, sentences = _parse_wikipedia_response(
            response.content, query_stripped
        )

        # follow_up이면 더 많은 sentences 반환 (추가 정보 요청)
        if intent == "follow_up":
            sentences = min(20, sentences + 5)

        was_changed = (optimized != query_stripped)
        return optimized, sentences, was_changed

    except Exception:
        return query_stripped, 5, False
