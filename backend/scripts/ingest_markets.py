import argparse

from loguru import logger

from app.core.config import get_settings
from app.db import init_db
from ingestion.client import PolymarketClient
from ingestion.normalize import normalize_market
from ingestion.service import session_scope
from app import crud


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Polymarket open markets")
    parser.add_argument("--status", default=None, help="Market status to ingest (default uses settings)")
    parser.add_argument("--page-size", type=int, default=None, help="Override pagination size")
    parser.add_argument("--limit", type=int, default=None, help="Fetch up to N markets")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    init_db()

    ingested = 0
    client_kwargs = {
        "market_status": args.status or settings.ingestion_status,
        "page_size": args.page_size or settings.ingestion_page_size,
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
