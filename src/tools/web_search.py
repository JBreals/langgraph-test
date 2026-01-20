"""Web search tool with automatic query enhancement."""

import re

from src.config import settings
from src.tools.query_enhancer import maybe_enhance_query


def _extract_urls(query: str) -> list[str]:
    """쿼리에서 모든 URL 추출. 없으면 빈 리스트."""
    return re.findall(r'https?://[^\s]+', query)


def _extract_webpages(client, urls: list[str]) -> str:
    """Tavily extract API로 웹페이지 내용 추출 (여러 URL 지원)."""
    response = client.extract(urls=urls)
    results = response.get("results", [])

    if not results:
        return f"[URL 추출 실패] {', '.join(urls)}에서 내용을 가져올 수 없습니다."

    output = []
    for r in results:
        url = r.get("url", "")
        raw_content = r.get("raw_content", "")
        if raw_content:
            # 여러 URL일 때는 각각 더 짧게
            max_len = 5000 if len(urls) == 1 else 3000
            if len(raw_content) > max_len:
                raw_content = raw_content[:max_len] + "\n\n... (내용이 길어 일부만 표시)"
            output.append(f"[URL 추출] {url}\n\n{raw_content}")

    return "\n\n---\n\n".join(output)


def web_search(
    query: str,
    context: str | None = None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
    intent: str = "new_question",
    time_sensitive: str = "none",
) -> str:
    """웹에서 정보를 검색합니다.

    URL이 포함된 쿼리는 해당 페이지 내용을 직접 추출합니다.
    일반 쿼리는 웹 검색을 수행합니다.

    Args:
        query: 검색어 또는 URL
        context: 원래 사용자 요청 (쿼리 증강에 사용)
        from_previous_step: 이전 도구 출력을 입력으로 사용하는 경우 True
        history: 대화 히스토리 (중복 방지에 사용)
        intent: 질문 의도 (new_question, follow_up 등)
        time_sensitive: 시간 민감도 (none, current, specified)

    Returns:
        검색 결과 또는 URL 내용
    """
    api_key = settings.tavily_api_key

    if not api_key:
        raise ValueError("TAVILY_API_KEY가 설정되지 않았습니다.")

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)

        # URL이 포함된 경우 → extract API로 직접 추출 (LLM 안 태움)
        urls = _extract_urls(query)
        if urls:
            return _extract_webpages(client, urls)

        # 일반 검색 → 쿼리 증강 후 search API
        enhanced_query, was_enhanced = maybe_enhance_query(
            query, context, from_previous_step, history, intent, time_sensitive
        )

        response = client.search(
            query=enhanced_query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

        results = []

        # 검색 쿼리 정보 표시 (항상)
        original_preview = query[:50] + "..." if len(query) > 50 else query
        if was_enhanced:
            results.append(f"[검색 쿼리] {original_preview} → {enhanced_query}")
        else:
            results.append(f"[검색 쿼리] {enhanced_query}")

        # AI 요약이 있으면 먼저 추가
        if response.get("answer"):
            results.append(f"[요약] {response['answer']}")

        # 검색 결과
        for r in response.get("results", []):
            title = r.get("title", "")
            content = r.get("content", "")[:300]
            url = r.get("url", "")
            results.append(f"- {title}\n  {content}\n  출처: {url}")

        if results:
            return "\n\n".join(results)
        return "검색 결과가 없습니다."

    except Exception as e:
        raise RuntimeError(f"웹 검색 실패: {e}")
