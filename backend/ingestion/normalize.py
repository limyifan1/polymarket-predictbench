from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from app import crud


def _as_list(value: Any) -> list[Any]:
    """Return value as a list when possible, decoding JSON strings."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _build_contracts(raw_market: dict[str, Any], market_id: str) -> list[dict[str, Any]]:
    contracts = raw_market.get("contracts")
    if isinstance(contracts, list) and all(isinstance(item, dict) for item in contracts):
        return contracts

    outcomes = _as_list(raw_market.get("outcomes"))
    if not outcomes:
        return []

    prices = _as_list(raw_market.get("outcomePrices"))
    token_ids = _as_list(raw_market.get("clobTokenIds")) or _as_list(raw_market.get("tokenIds"))

    built_contracts: list[dict[str, Any]] = []
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, dict):
            contract: dict[str, Any] = outcome.copy()
        else:
            contract = {"name": str(outcome)}

        if token_ids and index < len(token_ids) and token_ids[index]:
            contract.setdefault("id", token_ids[index])
        else:
            contract.setdefault("id", f"{market_id}-{index}")

        if prices and index < len(prices):
            contract.setdefault("price", prices[index])
            contract.setdefault("impliedProbability", prices[index])

        market_type = raw_market.get("marketType") or raw_market.get("type")
        if market_type:
            contract.setdefault("outcomeType", market_type)

        built_contracts.append(contract)

    return built_contracts


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.isoparse(str(value))
    except (ValueError, TypeError):
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        float_val = _parse_float(value)
        if float_val is None:
            return None
        return int(round(float_val))


def _normalize_fee_bps(raw_fee: Any) -> int | None:
    fee = _parse_float(raw_fee)
    if fee is None:
        return None
    if fee > 1:
        return int(round(fee * 100))
    return int(round(fee * 10_000))


def normalize_contract(raw_contract: dict[str, Any], market_id: str) -> crud.NormalizedContract:
    raw_id = raw_contract.get("id") or raw_contract.get("contractId") or raw_contract.get("_id")
    if raw_id:
        contract_id = str(raw_id)
    else:
        fallback_name = raw_contract.get("name") or raw_contract.get("title") or "contract"
        contract_id = f"{market_id}-{fallback_name}"
    name = raw_contract.get("name") or raw_contract.get("title") or "Unknown"
    outcome_type = (
        raw_contract.get("outcomeType")
        or raw_contract.get("type")
        or raw_contract.get("outcome_type")
    )

    price = _parse_float(raw_contract.get("price") or raw_contract.get("lastPrice"))
    implied_probability = _parse_float(
        raw_contract.get("impliedProbability") or raw_contract.get("impliedProbabilityRounded")
    )
    if implied_probability is None and price is not None:
        implied_probability = price

    return crud.NormalizedContract(
        contract_id=contract_id,
        name=name,
        outcome_type=outcome_type,
        current_price=price,
        confidence=_parse_float(raw_contract.get("confidence")),
        implied_probability=implied_probability,
        raw_data=raw_contract,
    )


def normalize_market(raw_market: dict[str, Any]) -> crud.NormalizedMarket:
    market_id = str(raw_market.get("id") or raw_market.get("marketId") or raw_market.get("_id"))
    contracts_raw = _build_contracts(raw_market, market_id)
    contracts = [normalize_contract(contract, market_id) for contract in contracts_raw]

    return crud.NormalizedMarket(
        market_id=market_id,
        slug=raw_market.get("slug"),
        question=raw_market.get("question") or raw_market.get("title") or "",
        category=raw_market.get("category"),
        sub_category=raw_market.get("subCategory") or raw_market.get("subcategory"),
        open_time=_parse_datetime(raw_market.get("openTime") or raw_market.get("startDate")),
        close_time=_parse_datetime(raw_market.get("closeTime") or raw_market.get("endDate")),
        volume_usd=_parse_float(raw_market.get("volume") or raw_market.get("volumeUsd")),
        liquidity_usd=_parse_float(raw_market.get("liquidity") or raw_market.get("liquidityUsd")),
        fee_bps=_normalize_fee_bps(raw_market.get("fee")),
        status=str(raw_market.get("status") or "open").lower(),
        description=raw_market.get("description"),
        icon_url=raw_market.get("icon") or raw_market.get("image"),
        contracts=contracts,
    )
