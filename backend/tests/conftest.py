from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.core.config import Settings


@pytest.fixture
def sample_market_payload() -> dict[str, object]:
    path = Path(__file__).parent / "data" / "sample_market.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def pipeline_args(tmp_path) -> argparse.Namespace:
    return argparse.Namespace(
        suite=None,
        stage="both",
        include_research=None,
        include_forecast=None,
        list_experiments=False,
        dry_run=True,
        window_days=0,
        target_date=None,
        limit=None,
        summary_path=tmp_path / "summary.json",
        debug_dump_dir=None,
        no_debug_dump=True,
    )


@pytest.fixture
def test_settings(tmp_path, monkeypatch) -> Settings:
    settings = Settings(
        ingestion_page_size=5,
        ingestion_filters={},
        database_url=f"sqlite:///{tmp_path/'predictbench.db'}",
        pipeline_debug_dump_dir=str(tmp_path / "debug"),
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.config.settings", settings)
    return settings
