from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings


@dataclass(slots=True)
class PipelineContext:
    """Runtime context passed to experiments during processing."""

    run_id: str
    run_date: date
    target_date: date
    window_days: int
    settings: Settings
    db_session: Session
    dry_run: bool
