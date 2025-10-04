from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.schemas import ContractBase, MarketBase


def test_contract_base_coerces_decimal_fields():
    """Verify that Decimal fields are correctly coerced to floats."""
    contract = ContractBase(
        contract_id="1",
        market_id="1",
        name="Test Contract",
        current_price=Decimal("99.9"),
        confidence=Decimal("0.5"),
        implied_probability=Decimal("0.25"),
    )
    assert isinstance(contract.current_price, float)
    assert contract.current_price == 99.9
    assert isinstance(contract.confidence, float)
    assert contract.confidence == 0.5
    assert isinstance(contract.implied_probability, float)
    assert contract.implied_probability == 0.25


def test_market_base_coerces_numeric_fields():
    """Verify that numeric fields are correctly coerced to floats."""
    market = MarketBase(
        market_id="1",
        question="Test Question",
        status="open",
        archived=False,
        last_synced_at=datetime.now(),
        volume_usd=Decimal("1000.50"),
        liquidity_usd=Decimal("500.25"),
    )
    assert isinstance(market.volume_usd, float)
    assert market.volume_usd == 1000.50
    assert isinstance(market.liquidity_usd, float)
    assert market.liquidity_usd == 500.25