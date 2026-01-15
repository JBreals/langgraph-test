"""PTE 에이전트용 도구 그룹 및 위험도 정의.

가이드라인 §7.1:
- 각 도구는 단일 목적만 수행
- 블랙박스 도구(search_and_read 등) 금지
- 위험도별 접근 제어
"""

from enum import Enum
from dataclasses import dataclass


class ToolGroup(str, Enum):
    """도구 그룹 분류."""

    SEARCH = "search"  # 검색 (웹, Wikipedia)
    QUERY = "query"  # 데이터 조회 (날씨, 시간)
    COMPUTE = "compute"  # 계산 (calculator, python)


class ToolRiskLevel(str, Enum):
    """도구 위험도 수준."""

    LOW = "low"  # 읽기 전용, 외부 API
    MEDIUM = "medium"  # 로컬 파일 접근
    HIGH = "high"  # 코드 실행


@dataclass
class ToolDefinition:
    """도구 정의."""

    name: str
    description: str
    group: ToolGroup
    risk: ToolRiskLevel
    parameters: dict


# 도구 정의
TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "web_search": ToolDefinition(
        name="web_search",
        description="웹에서 정보를 검색합니다.",
        group=ToolGroup.SEARCH,
        risk=ToolRiskLevel.LOW,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어"}},
            "required": ["query"],
        },
    ),
    "search_wikipedia": ToolDefinition(
        name="search_wikipedia",
        description="Wikipedia에서 정보를 검색합니다.",
        group=ToolGroup.SEARCH,
        risk=ToolRiskLevel.LOW,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어"}},
            "required": ["query"],
        },
    ),
    "rag_retrieve": ToolDefinition(
        name="rag_retrieve",
        description="내부 문서(회사 정책, 매뉴얼 등)에서 정보를 검색합니다.",
        group=ToolGroup.SEARCH,
        risk=ToolRiskLevel.LOW,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어"}},
            "required": ["query"],
        },
    ),
    "get_weather": ToolDefinition(
        name="get_weather",
        description="특정 도시의 현재 날씨를 조회합니다.",
        group=ToolGroup.QUERY,
        risk=ToolRiskLevel.LOW,
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string", "description": "도시명 (영문)"}},
            "required": ["city"],
        },
    ),
    "get_current_datetime": ToolDefinition(
        name="get_current_datetime",
        description="현재 날짜와 시간을 조회합니다.",
        group=ToolGroup.QUERY,
        risk=ToolRiskLevel.LOW,
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    "calculator": ToolDefinition(
        name="calculator",
        description="수학 계산을 수행합니다.",
        group=ToolGroup.COMPUTE,
        risk=ToolRiskLevel.LOW,
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "계산식"}},
            "required": ["expression"],
        },
    ),
    "python_repl": ToolDefinition(
        name="python_repl",
        description="Python 코드를 실행합니다.",
        group=ToolGroup.COMPUTE,
        risk=ToolRiskLevel.HIGH,
        parameters={
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python 코드"}},
            "required": ["code"],
        },
    ),
}


def get_tool_risk(tool_name: str) -> ToolRiskLevel:
    """도구의 위험도 반환."""
    if tool_name in TOOL_DEFINITIONS:
        return TOOL_DEFINITIONS[tool_name].risk
    return ToolRiskLevel.HIGH  # 알 수 없는 도구는 HIGH


def is_tool_allowed_for_replan(tool_name: str) -> bool:
    """Re-planner가 새로 추가할 수 있는 도구인지 확인.

    가이드라인 §6.3: 고위험 도구는 새로 추가 불가
    """
    return get_tool_risk(tool_name) != ToolRiskLevel.HIGH


def get_available_tools() -> list[str]:
    """사용 가능한 도구 이름 목록."""
    return list(TOOL_DEFINITIONS.keys())


def get_tool_manifest_text() -> str:
    """Planner 프롬프트에 넣을 도구 설명 (입출력 스키마 포함)."""
    lines = ["사용 가능한 도구:", ""]

    risk_emoji = {
        ToolRiskLevel.LOW: "🟢",
        ToolRiskLevel.MEDIUM: "🟡",
        ToolRiskLevel.HIGH: "🔴",
    }

    for group in ToolGroup:
        group_tools = [
            t for t in TOOL_DEFINITIONS.values() if t.group == group
        ]
        if not group_tools:
            continue

        lines.append(f"## {group.value.upper()}")
        for tool in group_tools:
            emoji = risk_emoji[tool.risk]
            lines.append(f"- **{tool.name}** {emoji}: {tool.description}")

            # 입력 파라미터 정보 추가
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])

            if params:
                lines.append("  - 입력:")
                for param_name, param_info in params.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    req_str = "필수" if param_name in required else "선택"
                    lines.append(f"    - `{param_name}` ({param_type}, {req_str}): {param_desc}")
            else:
                lines.append("  - 입력: 없음")

            # 출력 형식
            lines.append("  - 출력: string")
            lines.append("")

    return "\n".join(lines)
