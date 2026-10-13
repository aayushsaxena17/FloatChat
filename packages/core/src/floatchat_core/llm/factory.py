"""Build the configured provider behind the policy wrapper (ADR-0069, ADR-0070)."""

from pathlib import Path

from ..query.errors import QueryError
from .config import LlmSettings
from .ledger import Ledger
from .policy import ResilientProvider
from .pricing import PriceTable
from .provider import Provider


def raw_provider(
    settings: LlmSettings, *, provider: str | None = None, model: str | None = None
) -> Provider:
    name = provider or settings.provider
    if name == "offline":
        from .offline import OfflineProvider

        return OfflineProvider()
    key = settings.key_for(name)
    if key is None:
        raise QueryError("llm_unavailable")
    if name == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider(
            key,
            model or settings.model,
            settings.embedding_model,
            timeout_seconds=settings.timeout_seconds,
            thinking_level=settings.thinking_level,
        )
    if name == "openai":
        from .openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            key,
            model or settings.second_model or settings.model,
            settings.openai_embedding_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.timeout_seconds,
        )
    raise QueryError("llm_unavailable")


def build_provider(
    settings: LlmSettings,
    ledger: Ledger | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ResilientProvider:
    prices = (
        PriceTable.from_file(Path(settings.pricing_file)) if settings.pricing_file else PriceTable()
    )
    name = provider or settings.provider
    primary = raw_provider(settings, provider=provider, model=model)
    fallbacks: list[Provider] = []
    if name != "offline":
        fallbacks = [
            raw_provider(settings, provider=provider, model=candidate)
            for candidate in settings.fallback_list
            if candidate != primary.model
        ]
    return ResilientProvider(primary, settings, ledger, prices, fallbacks=fallbacks)
