from __future__ import annotations

from ingestion.normalize import normalize_market


def test_normalize_market_handles_real_payload(sample_market_payload):
    normalized = normalize_market(sample_market_payload)

    assert normalized.market_id == str(sample_market_payload.get("id"))
    assert normalized.question
    assert normalized.contracts, "normalized market is missing contracts"
    assert normalized.raw_data == sample_market_payload

    for contract in normalized.contracts:
        assert contract.contract_id
        assert contract.name

    if normalized.event:
        assert normalized.event.event_id
        assert normalized.event.title
