"""Application settings."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Application configuration."""

    # OpenRouter
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Models
    default_model: str = field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL", "anthropic/claude-sonnet-4")
    )
    planner_model: str = field(
        default_factory=lambda: os.getenv("PLANNER_MODEL", "anthropic/claude-sonnet-4")
    )
    replanner_model: str = field(
        default_factory=lambda: os.getenv("REPLANNER_MODEL", "anthropic/claude-sonnet-4")
    )
    final_model: str = field(
        default_factory=lambda: os.getenv("FINAL_MODEL", "anthropic/claude-sonnet-4")
    )

    # Temperature
    default_temperature: float = 0.7
    planner_temperature: float = 0.0  # Planner needs deterministic output
    replanner_temperature: float = 0.0

    # PTE Settings
    max_replan_count: int = 3  # Maximum re-planning attempts

    # App metadata (for OpenRouter headers)
    app_name: str = "LangGraph PTE Agent"
    app_url: str = "https://github.com/langgraph-pte"

    # API Keys for tools
    openweather_api_key: str = field(
        default_factory=lambda: os.getenv("OPENWEATHER_API_KEY", "")
    )
    tavily_api_key: str = field(
        default_factory=lambda: os.getenv("TAVILY_API_KEY", "")
    )


settings = Settings()
