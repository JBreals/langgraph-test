"""Datetime tool."""

from datetime import datetime
import pytz


def get_current_datetime() -> str:
    """현재 날짜와 시간을 반환합니다.

    Returns:
        현재 날짜/시간 문자열 (KST 기준)
    """
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.now(kst)
    return now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초 (KST)")
