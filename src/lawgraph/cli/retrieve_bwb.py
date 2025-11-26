from __future__ import annotations

"""CLI for retrieving BWB toestanden via the BWB SRU service."""

import argparse
import os

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.clients.bwb import BWBClient
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    """Entry point that resolves IDs and runs the BWB retrieve pipeline."""
    parser = argparse.ArgumentParser(
        description="Haal de nieuwste BWB-toestanden op via de BWB SRU service."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Optioneel domeinprofiel dat een set standaard BWB-IDs kiest.",
    )
    parser.add_argument(
        "--bwb-id",
        dest="bwb_ids",
        action="append",
        help="Specifieke BWB-ID om op te halen; herhaalbaar.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info("Starting BWB retrieve (profile=%s).", profile or "default")
    normalized_profile = profile.lower() if profile else None

    candidate_ids = _resolve_bwb_ids(
        cli_ids=args.bwb_ids,
        env_ids=_ids_from_env(),
        profile=normalized_profile,
    )

    if not candidate_ids:
        logger.warning(
            "Geen BWB-IDs gevonden voor profiel %s; niks te doen.",
            profile or "default",
        )
        return

    store = ArangoStore()
    pipeline = BWBRetrievePipeline(
        store=store,
        client=BWBClient(),
        bwb_ids=candidate_ids,
    )
    records = pipeline.fetch()

    logger.info(
        "BWB retrieve run completed (profile=%s); %d raw_sources opgeslagen.",
        profile or "default",
        len(records),
    )


def _resolve_bwb_ids(
    *,
    cli_ids: list[str] | None,
    env_ids: list[str],
    profile: str | None,
) -> list[str]:
    if cli_ids:
        return _clean_ids(cli_ids)
    if env_ids:
        return env_ids
    return []


def _ids_from_env() -> list[str]:
    env_value = os.getenv("BWB_IDS")
    if not env_value:
        return []
    return _clean_ids(env_value.split(","))


def _clean_ids(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        if not value:
            continue
        candidate = value.strip()
        if candidate:
            cleaned.append(candidate)
    return list(dict.fromkeys(cleaned))
