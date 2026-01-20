"""Wikipedia search tool."""

from src.tools.query_enhancer import enhance_query_for_wikipedia


def search_wikipedia(
    query: str,
    lang: str = "ko",
    context: str | None = None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
    intent: str = "new_question",
    time_sensitive: str = "none",  # 사용하지 않음 (Wikipedia는 팩트 기반)
) -> str:
    """Wikipedia에서 정보를 검색합니다.

    Args:
        query: 검색어
        lang: 언어 코드 (기본: "ko", 결과 없으면 "en" 시도)
        context: 원래 사용자 요청 (쿼리 증강에 사용)
        from_previous_step: 이전 도구 출력을 입력으로 사용하는 경우 True
        history: 대화 히스토리 (검색 깊이 결정에 사용)
        intent: 질문 의도 (new_question, follow_up 등)
        time_sensitive: 시간 민감도 (Wikipedia에서는 사용하지 않음)

    Returns:
        Wikipedia 검색 결과
    """
    # Wikipedia용 쿼리 최적화 + 검색 깊이 결정 (Intent 기반)
    search_query, sentences, was_changed = enhance_query_for_wikipedia(
        query, context, from_previous_step, history, intent
    )

    # 결과 출력에 쿼리 정보 포함 (항상)
    original_preview = query[:50] + "..." if len(query) > 50 else query
    if was_changed:
        prefix = f"[Wikipedia 쿼리] {original_preview} → {search_query} (sentences={sentences})\n\n"
    else:
        prefix = f"[Wikipedia 쿼리] {search_query} (sentences={sentences})\n\n"

    try:
        import wikipedia

        # 한국어로 먼저 시도
        wikipedia.set_lang(lang)
        search_results = wikipedia.search(search_query, results=3)

        # 한국어 결과 없으면 영어로 시도
        if not search_results and lang == "ko":
            wikipedia.set_lang("en")
            search_results = wikipedia.search(search_query, results=3)
            if search_results:
                lang = "en"

        if not search_results:
            return prefix + f"'{search_query}'에 대한 Wikipedia 결과가 없습니다."

        # 첫 번째 결과의 요약 가져오기 (LLM이 결정한 sentences 수 사용)
        try:
            summary = wikipedia.summary(search_results[0], sentences=sentences)
            lang_label = "한국어" if lang == "ko" else "English"
            return prefix + f"[{search_results[0]}] ({lang_label} Wikipedia)\n{summary}"
        except wikipedia.DisambiguationError as e:
            # 동음이의어인 경우 첫 번째 옵션 시도
            if e.options:
                summary = wikipedia.summary(e.options[0], sentences=sentences)
                return prefix + f"[{e.options[0]}]\n{summary}"
            return prefix + f"'{search_query}'는 여러 의미가 있습니다: {', '.join(e.options[:5])}"

    except Exception as e:
        return f"Wikipedia 검색 실패: {e}"
