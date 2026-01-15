"""OpenRouter LLM configuration."""

from langchain_openai import ChatOpenAI
from src.config import settings


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    **kwargs,
) -> ChatOpenAI:
    """Get configured ChatOpenAI instance for OpenRouter.

    Args:
        model: Model name (e.g., "anthropic/claude-sonnet-4")
        temperature: Sampling temperature
        **kwargs: Additional arguments for ChatOpenAI

    Returns:
        Configured ChatOpenAI instance
    """
    return ChatOpenAI(
        model=model or settings.default_model,
        temperature=temperature if temperature is not None else settings.default_temperature,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={
            "HTTP-Referer": settings.app_url,
            "X-Title": settings.app_name,
        },
        **kwargs,
    )
