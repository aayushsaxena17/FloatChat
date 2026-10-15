"""LLM configuration (ADR-0069, ADR-0070): env prefix ``LLM_`` plus the provider keys.

``provider`` defaults to ``gemini``; without ``GEMINI_API_KEY`` the chat answers
``llm_unavailable`` (PRD section 22). ``offline`` is opt-in and names itself wherever it answers.
"""

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIMENSIONS = 768
GEMINI_API_VERSION = "v1beta"
GEMINI_BASE_URL = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}"
OFFLINE_MODEL = "offline-rules-v1"
OFFLINE_EMBEDDING_MODEL = "hash-embed-v1"


class LlmSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_", env_file=None, extra="ignore", populate_by_name=True
    )

    provider: Literal["gemini", "openai", "offline"] = "gemini"
    model: str = "gemini-3.8-flash"
    embedding_model: str = "gemini-embedding-001"
    # Gemini 3 models think by default; LOW bounds the thinking tokens for a planning call.
    # An empty value omits thinkingConfig (models without thinking reject it).
    thinking_level: Literal["", "MINIMAL", "LOW", "MEDIUM", "HIGH"] = "LOW"
    # A planning call on a loaded Flash model took 14 s on 2026-10-13; 503 "high demand"
    # answers lasted minutes, hence the fallback model with its own breaker (ADR-0070).
    fallback_models: str = Field(
        default="gemini-3.7-flash,gemini-3-flash-preview",
        validation_alias=AliasChoices("LLM_FALLBACK_MODELS", "LLM_FALLBACK_MODEL"),
    )
    timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    # One retry per route and a whole-call budget: an overloaded provider answers 503 within
    # seconds, and a user should hear "busy, try again" within the budget, never after minutes.
    retries: int = Field(default=1, ge=0, le=5)
    total_budget_seconds: float = Field(default=45.0, gt=0, le=600)
    breaker_failures: int = Field(default=3, ge=1, le=100)
    breaker_seconds: float = Field(default=60.0, gt=0, le=3600)
    daily_usd_cap: float = Field(default=1.0, ge=0)
    daily_token_cap: int = Field(default=2_000_000, ge=0)
    # False answers with the deterministic template only: one generation call per message
    # instead of two, which matters on a rate-limited key (the template is always grounded).
    narrate_with_model: bool = True
    planner_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    narrator_max_output_tokens: int = Field(default=400, ge=50, le=4096)
    retrieval_top_k: int = Field(default=12, ge=1, le=100)
    # The second model for the ablation (ADR-0074): any OpenAI-compatible endpoint.
    second_model: str | None = None
    pricing_file: str | None = None

    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "LLM_GEMINI_API_KEY")
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "LLM_OPENAI_API_KEY")
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "LLM_OPENAI_BASE_URL"),
    )
    openai_embedding_model: str = "text-embedding-3-small"

    def key_for(self, provider: str) -> str | None:
        """The key for ``provider``; an empty value (the ``.env.example`` default) is no key."""
        key = {"gemini": self.gemini_api_key, "openai": self.openai_api_key}.get(provider)
        if key is None:
            return None
        value = key.get_secret_value().strip()
        return value or None

    @property
    def fallback_list(self) -> list[str]:
        seen: list[str] = []
        for name in self.fallback_models.split(","):
            name = name.strip()
            if name and name != self.model and name not in seen:
                seen.append(name)
        return seen

    @property
    def configured(self) -> bool:
        """True when the selected provider can answer (offline always, others with a key)."""
        return self.provider == "offline" or self.key_for(self.provider) is not None

    def secrets(self) -> list[str]:
        """Every configured secret value; tests assert none appears in a request body."""
        return [
            key.get_secret_value().strip()
            for key in (self.gemini_api_key, self.openai_api_key)
            if key is not None and key.get_secret_value().strip()
        ]
