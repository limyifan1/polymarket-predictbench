"""Helpers for constructing OpenAI API clients."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from openai import OpenAI

from app.core.config import Settings


@lru_cache(maxsize=4)
def _client_cache(
    api_key: str,
    base_url: str | None,
    organization: str | None,
    project: str | None,
) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if organization:
        kwargs["organization"] = organization
    if project:
        kwargs["project"] = project
    return OpenAI(**kwargs)


def get_openai_client(settings: Settings) -> OpenAI:
    """Build or reuse an OpenAI client for the supplied settings."""

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    base_url = str(settings.openai_api_base) if settings.openai_api_base else None
    return _client_cache(
        settings.openai_api_key,
        base_url,
        settings.openai_org_id,
        settings.openai_project_id,
    )


__all__ = ["get_openai_client"]
