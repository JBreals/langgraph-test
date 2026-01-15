"""도구 입출력 스키마 정의.

각 도구의 입력/출력 형태를 정의하여 executor에서 검증.
"""

from typing import Any, TypedDict, Literal


class ParamSchema(TypedDict, total=False):
    """파라미터 스키마."""
    type: str  # "str", "int", "float", "dict", "list"
    required: bool
    default: Any
    description: str


class ToolSchema(TypedDict, total=False):
    """도구 스키마."""
    description: str
    input: dict[str, ParamSchema] | None  # None = 입력 없음
    output: str


# 도구별 스키마 정의
TOOL_SCHEMAS: dict[str, ToolSchema] = {
    "get_current_datetime": {
        "description": "현재 날짜와 시간을 반환합니다 (KST 기준)",
        "input": None,  # 입력 없음
        "output": "str",
    },
    "calculator": {
        "description": "수학 표현식을 계산합니다",
        "input": {
            "expression": {
                "type": "str",
                "required": True,
                "description": "계산할 수학 표현식 (예: '2 + 3 * 4')",
            },
        },
        "output": "str",
    },
    "get_weather": {
        "description": "특정 도시의 현재 날씨 정보를 조회합니다",
        "input": {
            "city": {
                "type": "str",
                "required": True,
                "description": "날씨를 조회할 도시 이름 (예: 'Seoul', '서울')",
            },
        },
        "output": "str",
    },
    "web_search": {
        "description": "웹에서 정보를 검색합니다",
        "input": {
            "query": {
                "type": "str",
                "required": True,
                "description": "검색 쿼리",
            },
        },
        "output": "str",
    },
    "search_wikipedia": {
        "description": "위키피디아에서 정보를 검색합니다",
        "input": {
            "query": {
                "type": "str",
                "required": True,
                "description": "검색할 키워드",
            },
        },
        "output": "str",
    },
    "python_repl": {
        "description": "Python 코드를 실행합니다",
        "input": {
            "code": {
                "type": "str",
                "required": True,
                "description": "실행할 Python 코드",
            },
        },
        "output": "str",
    },
    "rag_retrieve": {
        "description": "벡터 저장소에서 관련 문서를 검색합니다",
        "input": {
            "query": {
                "type": "str",
                "required": True,
                "description": "검색 쿼리",
            },
            "top_k": {
                "type": "int",
                "required": False,
                "default": 3,
                "description": "반환할 문서 수",
            },
        },
        "output": "str",
    },
}


def get_tool_schema(tool_name: str) -> ToolSchema | None:
    """도구 스키마 반환."""
    return TOOL_SCHEMAS.get(tool_name)


def validate_tool_input(tool_name: str, tool_input: Any) -> dict[str, Any] | None:
    """도구 입력 검증 및 정규화.

    Args:
        tool_name: 도구 이름
        tool_input: 도구 입력 (str, dict, 또는 None)

    Returns:
        정규화된 입력 dict 또는 None (입력 없는 도구)

    Raises:
        ValueError: 스키마 검증 실패
    """
    schema = get_tool_schema(tool_name)

    if schema is None:
        # 스키마 없는 도구는 그대로 통과
        return {"_raw": tool_input} if tool_input else None

    input_schema = schema.get("input")

    # 입력이 필요 없는 도구
    if input_schema is None:
        return None  # 어떤 입력이 들어와도 무시

    # 입력이 필요한 도구인데 입력이 없는 경우
    if tool_input is None:
        # 필수 파라미터 확인
        required_params = [
            name for name, param in input_schema.items()
            if param.get("required", False)
        ]
        if required_params:
            raise ValueError(
                f"도구 '{tool_name}'에 필수 파라미터가 누락됨: {required_params}"
            )
        return {}

    # 문자열 입력 → 첫 번째 필수 파라미터로 매핑
    if isinstance(tool_input, str):
        required_params = [
            name for name, param in input_schema.items()
            if param.get("required", False)
        ]
        if required_params:
            return {required_params[0]: tool_input}
        # 필수 파라미터 없으면 첫 번째 파라미터로
        first_param = next(iter(input_schema.keys()), None)
        if first_param:
            return {first_param: tool_input}
        return {}

    # dict 입력 → 스키마 검증
    if isinstance(tool_input, dict):
        validated = {}

        for param_name, param_schema in input_schema.items():
            if param_name in tool_input:
                validated[param_name] = tool_input[param_name]
            elif param_schema.get("required", False):
                raise ValueError(
                    f"도구 '{tool_name}'에 필수 파라미터 '{param_name}' 누락"
                )
            elif "default" in param_schema:
                validated[param_name] = param_schema["default"]

        return validated

    # 기타 타입
    raise ValueError(f"지원하지 않는 입력 타입: {type(tool_input)}")


def generate_tool_manifest() -> str:
    """Planner용 도구 매니페스트 생성.

    Returns:
        도구 목록 및 스키마 설명 문자열
    """
    lines = ["사용 가능한 도구 목록:\n"]

    for tool_name, schema in TOOL_SCHEMAS.items():
        desc = schema.get("description", "설명 없음")
        lines.append(f"- {tool_name}: {desc}")

        input_schema = schema.get("input")
        if input_schema is None:
            lines.append("  입력: 없음")
        else:
            lines.append("  입력:")
            for param_name, param_schema in input_schema.items():
                param_type = param_schema.get("type", "any")
                required = "필수" if param_schema.get("required") else "선택"
                param_desc = param_schema.get("description", "")
                default = param_schema.get("default")
                default_str = f", 기본값: {default}" if default is not None else ""
                lines.append(
                    f"    - {param_name} ({param_type}, {required}{default_str}): {param_desc}"
                )

        lines.append("")

    return "\n".join(lines)
