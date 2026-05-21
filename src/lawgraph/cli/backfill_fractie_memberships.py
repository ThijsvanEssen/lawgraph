"""CLI: backfill canonical Fractie nodes + date-bounded LID_VAN_FRACTIE edges.

Targeted backfill for the FractieZetelPersoon migration. Re-fetches just the
Fractie + FractieZetelPersoon endpoints and re-runs the matching slices of the
TK dossiers normalize pipeline (without re-processing dossiers, activiteiten,
or stemmingen).

Usage:
  lawgraph-backfill-fractie-memberships
  lawgraph-backfill-fractie-memberships --skip-fetch   # only re-normalize
"""

from __future__ import annotations

import argparse
import sys

from lawgraph.clients.tk import TKClient
from lawgraph.config.settings import (
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.pipelines.normalize.tk_dossiers import TkDossiersNormalizePipeline

logger = get_logger(__name__)


def _store_records(store: ArangoStore, kind: str, records: list[dict]) -> int:
    count = 0
    for record in records:
        external_id = str(record.get("Id") or "")
        if not external_id:
            continue
        try:
            store.insert_raw_source(
                source=SOURCE_TK,
                kind=kind,
                external_id=external_id,
                payload_json=record,
            )
            count += 1
        except Exception as exc:
            logger.error("Failed to store %s %s: %s", kind, external_id, exc)
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill canonical Fractie nodes and LID_VAN_FRACTIE edges "
            "from FractieZetelPersoon."
        )
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip the TK API fetch and only re-run the normalize step.",
    )
    args = parser.parse_args(argv)

    store = ArangoStore()

    if not args.skip_fetch:
        client = TKClient()
        try:
            fracties = client.fetch_fracties()
            stored_f = _store_records(store, RAW_KIND_TK_FRACTIE, fracties)
            logger.info("Stored %d Fractie raws.", stored_f)

            fzps = client.fetch_fractie_zetel_personen()
            stored_fzp = _store_records(store, RAW_KIND_TK_FRACTIEZETELPERSOON, fzps)
            logger.info("Stored %d FractieZetelPersoon raws.", stored_fzp)
        except Exception as exc:
            logger.error("Fetch failed: %s", exc)
            sys.exit(1)

    pipeline = TkDossiersNormalizePipeline(store=store)
    try:
        # Pull just the raw kinds we need; reuse the pipeline's
        # _query_raw_sources / _group_by_kind helpers via the public methods.
        kinds = [
            RAW_KIND_TK_PERSOON,
            RAW_KIND_TK_FRACTIE,
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            RAW_KIND_TK_STEMMING,
        ]
        rows = pipeline._query_raw_sources(source=SOURCE_TK, kinds=kinds, since=None)
        grouped = pipeline._group_by_kind(rows, kinds=kinds)
        for kind in kinds:
            logger.info(
                "Loaded %d raw records for kind=%s",
                len(grouped.get(kind, [])),
                kind,
            )

        # Make stemmingen raws available so _normalize_fracties can derive
        # cross-endpoint aliases (e.g. NSC ↔ 'Nieuw Sociaal Contract').
        pipeline._raw_stemmingen_cache = grouped.get(RAW_KIND_TK_STEMMING, [])

        lid_nodes = pipeline._normalize_personen(grouped.get(RAW_KIND_TK_PERSOON, []))
        fractie_raws = grouped.get(RAW_KIND_TK_FRACTIE, [])
        if not fractie_raws:
            logger.error(
                "No %s raws found — run without --skip-fetch first.",
                RAW_KIND_TK_FRACTIE,
            )
            sys.exit(1)
        fractie_nodes = pipeline._normalize_fracties(fractie_raws)
        edges = pipeline._normalize_fractie_memberships(
            grouped.get(RAW_KIND_TK_FRACTIEZETELPERSOON, []),
            lid_nodes,
            fractie_nodes,
        )
        logger.info(
            "Backfill complete: %d fracties, %d leden, %d membership edges.",
            len(fractie_nodes),
            len(lid_nodes),
            edges,
        )
    except Exception as exc:
        logger.error("Backfill failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
