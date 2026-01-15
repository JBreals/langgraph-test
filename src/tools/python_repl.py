"""Python REPL tool."""

import sys
from io import StringIO


def python_repl(code: str) -> str:
    """Python 코드를 실행합니다.

    Args:
        code: 실행할 Python 코드

    Returns:
        실행 결과 또는 출력
    """
    # stdout 캡처
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        # 코드 실행
        exec_globals = {"__builtins__": __builtins__}
        exec(code, exec_globals)

        # 출력 가져오기
        output = sys.stdout.getvalue()

        if output:
            return output.strip()
        return "코드가 실행되었습니다. (출력 없음)"

    except Exception as e:
        return f"실행 오류: {type(e).__name__}: {e}"

    finally:
        sys.stdout = old_stdout
