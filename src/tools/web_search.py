"""Web search tool with automatic query enhancement."""

from src.config import settings
from src.tools.query_enhancer import maybe_enhance_query


def web_search(
    query: str,
    context: str | None = None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
) -> str:
    """웹에서 정보를 검색합니다.

    Args:
        query: 검색어
        context: 원래 사용자 요청 (쿼리 증강에 사용)
        from_previous_step: 이전 도구 출력을 입력으로 사용하는 경우 True
        history: 대화 히스토리 (중복 방지에 사용)

    Returns:
        검색 결과
    """
    api_key = settings.tavily_api_key

    if not api_key:
        raise ValueError("TAVILY_API_KEY가 설정되지 않았습니다.")

    # LLM 기반 쿼리 증강 (대화 히스토리 포함)
    enhanced_query, was_enhanced = maybe_enhance_query(
        query, context, from_previous_step, history
    )

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
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
