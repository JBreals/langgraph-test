"""LLM-based query enhancement for search tools."""

import json
import re
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm
from src.config import settings


# =============================================================================
# Web Search Query Enhancement
# =============================================================================

WEB_SEARCH_ENHANCE_PROMPT = """You are a web search query optimizer.

## Input
- Query: {query}
- User's request: {context}
- Current time: {current_datetime}
- Conversation history: {history}

## Task
Create an effective web search query based on the input and conversation context.

## Rules
1. Output ONLY the search query, nothing else
2. Keep it concise (under 50 characters if possible)
3. Use Korean
4. If user asks for "more", "additional", "other" info:
   - Look at what categories/topics were already discussed
   - Search for a DIFFERENT category/angle instead
   - Do NOT use "제외" or exclusion keywords (they don't work)

## Examples (basic)
- Query: "135000", Context: "그 금액으로 살 수 있는 전자제품"
  → "135000원 전자제품 추천"

- Query: "서울 맛집", Context: "오늘 저녁 뭐 먹지"
  → "서울 저녁 맛집 추천 2025"

## Examples (follow-up questions - use different angle)
- Context: "더 알려줘", History: "1940년: 2차대전, 한국전쟁 언급됨"
  → "1940년 과학 기술 발전" (다른 카테고리로 검색)

- Context: "다른 건?", History: "AI: GPT, 딥러닝 언급됨"
  → "AI 로보틱스 자율주행 동향" (다른 분야로 검색)

- Context: "또 뭐 있어?", History: "맛집: 한식, 중식 추천됨"
  → "서울 양식 이탈리안 맛집" (다른 종류로 검색)

Output the search query:"""


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


def _format_history(history: list[dict[str, str]] | None, max_items: int = 5) -> str:
    """대화 히스토리를 문자열로 포맷."""
    if not history:
        return "(없음)"

    recent = history[-max_items * 2:]  # user/assistant 쌍으로 max_items개
    lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")[:100]
        if len(msg.get("content", "")) > 100:
            content += "..."
        lines.append(f"- {role}: {content}")

    return "\n".join(lines) if lines else "(없음)"


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
) -> str:
    """Web Search용 쿼리 증강.

    Args:
        query: 원본 쿼리
        context: 사용자 요청
        history: 대화 히스토리

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
        history_text = _format_history(history)

        prompt = WEB_SEARCH_ENHANCE_PROMPT.format(
            query=safe_query[:200],
            context=safe_context[:200],
            current_datetime=current_dt,
            history=history_text,
        )

        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the search query:"),
        ])

        enhanced = response.content.strip()
        enhanced = re.sub(r'^["\']|["\']$', '', enhanced)

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
) -> tuple[str, bool]:
    """Web Search용 쿼리 증강.

    Args:
        query: Original query
        context: User's original request (optional)
        from_previous_step: True if query comes from previous tool output
        history: 대화 히스토리

    Returns:
        Tuple of (enhanced_query, was_enhanced)
    """
    if not context:
        return query, False

    enhanced = enhance_query_for_web_search(query, context, history)
    was_changed = (enhanced != query.strip())

    return enhanced, was_changed


def enhance_query_for_wikipedia(
    query: str,
    context: str | None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, int, bool]:
    """Wikipedia 검색용 쿼리 최적화 + 검색 깊이 결정.

    Args:
        query: 원본 쿼리
        context: 사용자 요청 (optional)
        from_previous_step: 이전 도구 출력인 경우 True
        history: 대화 히스토리

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
        history_text = _format_history(history)

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

        was_changed = (optimized != query_stripped)
        return optimized, sentences, was_changed

    except Exception:
        return query_stripped, 5, False
