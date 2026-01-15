"""Tool registry for PTE agent."""

from typing import Any, Callable

from .calculator import calculator
from .datetime_tool import get_current_datetime
from .weather import get_weather
from .web_search import web_search
from .wikipedia_tool import search_wikipedia
from .python_repl import python_repl
from .rag_retrieve import rag_retrieve
from .schemas import validate_tool_input, get_tool_schema


# 도구 레지스트리
TOOLS: dict[str, Callable] = {
    "calculator": calculator,
    "get_current_datetime": get_current_datetime,
    "get_weather": get_weather,
    "web_search": web_search,
    "search_wikipedia": search_wikipedia,
    "python_repl": python_repl,
    "rag_retrieve": rag_retrieve,
}


def get_tool(name: str) -> Callable | None:
    """도구 함수 반환."""
    return TOOLS.get(name)


def get_all_tools() -> dict[str, Callable]:
    """모든 도구 반환."""
    return TOOLS.copy()


def run_tool(
    tool_name: str,
    tool_input: Any,
    context: str | None = None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
) -> str:
    """도구 실행 (스키마 기반 검증 포함).

    Args:
        tool_name: 도구 이름
        tool_input: 도구 입력 (str, dict, 또는 None)
        context: 검색 도구용 컨텍스트 (쿼리 증강에 사용)
        from_previous_step: 이전 도구 출력을 입력으로 사용하는 경우 True
        history: 대화 히스토리 (검색 도구에서 중복 방지에 사용)

    Returns:
        실행 결과 문자열

    Raises:
        ValueError: 알 수 없는 도구 또는 스키마 검증 실패
    """
    tool_fn = get_tool(tool_name)

    if tool_fn is None:
        raise ValueError(f"알 수 없는 도구: {tool_name}")

    # 스키마 기반 입력 검증 및 정규화
    validated_input = validate_tool_input(tool_name, tool_input)

    # 실행
    if validated_input is None:
        # 입력 없는 도구
        return tool_fn()
    elif "_raw" in validated_input:
        # 스키마 없는 도구 (raw 입력 그대로 전달)
        raw = validated_input["_raw"]
        if isinstance(raw, dict):
            return tool_fn(**raw)
        elif raw is not None:
            return tool_fn(raw)
        else:
            return tool_fn()
    else:
        # 정규화된 dict 입력
        # 검색 도구인 경우 context, from_previous_step, history 추가
        if tool_name in ("web_search", "rag_retrieve", "search_wikipedia"):
            if context:
                validated_input["context"] = context
            validated_input["from_previous_step"] = from_previous_step
            validated_input["history"] = history
        return tool_fn(**validated_input)
