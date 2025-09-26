"""Shared repository result types."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Event, Market


@dataclass(slots=True)
class EventGroupRecord:
    """Bundle events with their associated markets for listing operations."""

    event: Event | None
    markets: list[Market] = field(default_factory=list)


__all__ = ["EventGroupRecord"]
