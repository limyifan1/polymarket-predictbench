import argparse
import json
from datetime import datetime, timezone

from loguru import logger

from app.core.config import get_settings
from app.db import init_db
from ingestion.client import ALLOWED_FILTER_KEYS, PolymarketClient
from ingestion.normalize import normalize_market
from ingestion.service import session_scope
from app import crud


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _isoformat_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Polymarket open markets")
    parser.add_argument("--page-size", type=int, default=None, help="Override pagination size")
    parser.add_argument("--limit", type=int, default=None, help="Fetch up to N markets")
    parser.add_argument(
        "--filter",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Additional Polymarket query parameter (repeatable, e.g. --filter closed=false)",
    )
    parser.add_argument(
        "--force-close-after-now",
        action="store_true",
        help="Apply an end_date_min filter at runtime so only markets closing after now are fetched.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    init_db()

    ingested = 0
    client_filters = dict(settings.ingestion_filters)
    if args.filter:
        for raw_filter in args.filter:
            if not raw_filter or "=" not in raw_filter:
                logger.warning("Ignoring invalid filter argument: {}", raw_filter)
                continue
            key, value = raw_filter.split("=", 1)
            key = key.strip()
            raw_value = value.strip()
            if not key:
                logger.warning("Ignoring filter with empty key: {}", raw_filter)
                continue
            parsed_value: object
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                lowered = raw_value.lower()
                if lowered in {"true", "false"}:
                    parsed_value = lowered == "true"
                else:
                    parsed_value = raw_value
            if key not in ALLOWED_FILTER_KEYS:
                logger.warning(
                    "Ignoring unsupported filter '{}'. Allowed keys: {}",
                    key,
                    ", ".join(sorted(ALLOWED_FILTER_KEYS)),
                )
                continue
            client_filters[key] = parsed_value

    if args.force_close_after_now:
        now = datetime.now(timezone.utc)
        existing_end_min = _parse_datetime(client_filters.get("end_date_min"))
        target = existing_end_min if existing_end_min and existing_end_min > now else now
        client_filters["end_date_min"] = _isoformat_utc(target)

    client_kwargs = {
        "page_size": args.page_size or settings.ingestion_page_size,
        "filters": client_filters,
    }

    with PolymarketClient(**client_kwargs) as client:
        with session_scope() as session:
            for index, raw_market in enumerate(client.iter_markets(), start=1):
                normalized = normalize_market(raw_market)
                crud.upsert_market(session, normalized)
                if args.limit and index >= args.limit:
                    break
                ingested = index

    logger.info("Ingested {} markets", ingested)


if __name__ == "__main__":
    main()
