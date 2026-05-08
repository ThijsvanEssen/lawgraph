"""CLI for retrieving BWB toestanden via the BWB SRU service."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from lawgraph.clients.bwb import BWBClient
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

from .retrieve_helpers import load_profile_config

load_dotenv()
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
        config=load_profile_config(profile),
    )

    if not candidate_ids:
        logger.warning(
            "No BWB IDs found for profile %s; nothing to do.",
            profile or "default",
        )
        return

    store = ArangoStore()
    pipeline = BWBRetrievePipeline(store=store, client=BWBClient())
    result = pipeline.run(bwb_ids=candidate_ids)

    logger.info(
        "BWB retrieve completed (profile=%s): %s.",
        profile or "default",
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("BWB retrieve error: %s", err)


def _resolve_bwb_ids(
    *,
    cli_ids: list[str] | None,
    env_ids: list[str],
    profile: str | None,
    config: dict | None,
) -> list[str]:
    if cli_ids:
        return _clean_ids(cli_ids)
    if env_ids:
        return env_ids
    if config:
        bwb_section = config.get("bwb")
        if isinstance(bwb_section, dict):
            ids = bwb_section.get("ids", [])
            return _clean_ids([str(v) for v in ids if v])
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
