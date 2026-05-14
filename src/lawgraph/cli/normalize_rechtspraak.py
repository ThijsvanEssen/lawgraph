from __future__ import annotations

import argparse
import datetime as dt
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline

logger = get_logger(__name__)


def _parse_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("d") and value[:-1].isdigit():
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(value[:-1]))
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Cannot parse --since value '{value}'.") from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Normalize raw Rechtspraak records.")
    parser.add_argument(
        "--since",
        default=None,
        help="Only process raw records fetched since this date (ISO 8601 or '7d').",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    try:
        since = _parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    store = ArangoStore()
    pipeline = RechtspraakNormalizePipeline(store=store)
    try:
        pipeline.run(since=since)
    except Exception as exc:
        logger.error("Rechtspraak normalization failed: %s", exc)
        sys.exit(1)

    logger.info("Rechtspraak normalization completed.")
