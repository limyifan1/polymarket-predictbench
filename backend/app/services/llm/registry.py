"""Runtime registry for LLM providers."""

from __future__ import annotations

from typing import Dict

from .base import LLMProvider


class UnknownLLMProviderError(LookupError):
    """Raised when an experiment requests an unregistered provider."""


_PROVIDERS: Dict[str, LLMProvider] = {}


def register_provider(provider: LLMProvider) -> None:
    """Register or replace an LLM provider."""

    _PROVIDERS[provider.name.lower()] = provider


def get_provider(name: str) -> LLMProvider:
    """Return the provider registered under ``name``."""

    try:
        return _PROVIDERS[name.lower()]
    except KeyError as exc:  # pragma: no cover - defensive
        raise UnknownLLMProviderError(f"LLM provider '{name}' is not registered") from exc


def available_providers() -> tuple[str, ...]:
    """Return the tuple of registered provider names."""

    return tuple(sorted(_PROVIDERS))


# Register built-in providers at import time.
from .openai import OpenAIProvider  # noqa: E402  (lazy import for registration)
from .gemini import GeminiProvider  # noqa: E402

register_provider(OpenAIProvider())
register_provider(GeminiProvider())


__all__ = [
    "UnknownLLMProviderError",
    "available_providers",
    "get_provider",
    "register_provider",
]
