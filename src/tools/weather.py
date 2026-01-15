"""Weather tool."""

import requests
from src.config import settings


def get_weather(city: str) -> str:
    """특정 도시의 현재 날씨를 조회합니다.

    Args:
        city: 도시명 (영문)

    Returns:
        날씨 정보 문자열
    """
    api_key = settings.openweather_api_key

    if not api_key:
        raise ValueError("OPENWEATHER_API_KEY가 설정되지 않았습니다.")

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": city,
            "appid": api_key,
            "units": "metric",
            "lang": "kr",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        weather = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        humidity = data["main"]["humidity"]

        return f"{city}의 날씨: {weather}, {temp}°C, 습도 {humidity}%"

    except requests.RequestException as e:
        # Re-planner가 대안을 찾을 수 있도록 예외 발생
        raise RuntimeError(f"날씨 조회 실패: {e}")
