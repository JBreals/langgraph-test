"""Calculator tool."""

import math


def calculator(expression: str) -> str:
    """수학 계산을 수행합니다.

    Args:
        expression: 계산할 수식 (예: "2 + 2", "sqrt(16)")

    Returns:
        계산 결과
    """
    try:
        # 안전한 수학 함수들만 허용
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "pi": math.pi,
            "e": math.e,
        }

        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"계산 오류: {e}"
