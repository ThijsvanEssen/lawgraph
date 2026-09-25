"""``lawgraph gaps``: what the graph refers to and does not hold. Reads only.

The report of what ``retrieve all --mode gaps`` (a round of ``expand-graph``) would fetch,
from the same queries (``pipelines/retrieve/_gaps.py``):

- laws whose articles are referred to and that are not loaded, by number of references;
- judgments that are cited and not loaded (Rechtspraak, ECHR);
- EU acts that BWB regulations name and that are not loaded;
- treaties that are referred to and not loaded;
- explanatory memoranda without their text.

To fetch them: ``lawgraph retrieve <source> --mode gaps``, all of them with ``lawgraph
retrieve all --mode gaps``, or until nothing new turns up with ``lawgraph expand-graph``.
"""

from __future__ import annotations

import argparse
from typing import Any

from lawgraph.clients.bwb import BWBClient
from lawgraph.core.judgments import Referral
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.retrieve import _gaps

logger = get_logger(__name__)


# ── public entry point ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--min-stubs",
        type=int,
        default=_gaps.DEFAULT_MIN_STUBS,
        metavar="N",
        help="Laws with at least N referred articles are what a run fetches (default: "
        "%(default)s); the others are listed below them.",
    )
    args = parser.parse_args(argv)
    _report(ArangoStore(), args.min_stubs)
    return PipelineResult()


def _report(store: ArangoStore, min_stubs: int) -> None:
    stub_rows = _gaps.stub_article_counts(store)
    loaded = _gaps.loaded_bwb_ids(store)
    missing = [
        row for row in stub_rows if row["bwb_id"] and row["bwb_id"] not in loaded
    ]
    known = [row for row in stub_rows if row["bwb_id"] in loaded]

    name_cache = _build_name_cache(store)
    unknown_ids = [
        r["bwb_id"] for r in missing if r["bwb_id"].upper() not in name_cache
    ]
    if unknown_ids:
        name_cache = _resolve_names_from_bwb(unknown_ids, name_cache)
    _print_stub_report(missing, known, name_cache, min_stubs)

    _print_judgment_stub_report(
        _gaps.rechtspraak_gaps(store), _gaps.unanswered_referrals(store)
    )
    _print_mvt_report(_gaps.kamerstuk_gaps(store, "toelichting"))
    _print_celex_stub_report(_gaps.eurlex_gaps(store))
    _print_echr_stub_report(_gaps.echr_gaps(store))
    _print_verdrag_stub_report(_gaps.verdragenbank_gaps(store))


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_name_cache(store: ArangoStore) -> dict[str, str]:
    """Map bwb_id → best available title from the instruments collection."""
    cache: dict[str, str] = {}
    for row in gap_queries.instrument_titles(store):
        bwb = row.get("bwb_id")
        title = row.get("title")
        if bwb and title:
            cache[str(bwb).upper()] = str(title)
    return cache


def _resolve_names_from_bwb(
    bwb_ids: list[str],
    known: dict[str, str],
    max_lookups: int = 15,
) -> dict[str, str]:
    """The titles of the laws not in *known*, from their SRU record (for the report).

    At most *max_lookups* searches. The title is in the record: the toestand itself (the
    whole law, which a gaps run fetches later) is not downloaded for its name.
    """
    result = dict(known)
    client = BWBClient()
    for bwb_id in [b for b in bwb_ids if b.upper() not in result][:max_lookups]:
        try:
            meta = client.latest_toestand(bwb_id)
        except Exception as exc:
            logger.debug("Could not resolve title for %s: %s", bwb_id, exc)
            continue
        if meta and meta.get("title"):
            result[bwb_id.upper()] = str(meta["title"])
    return result


def _print_echr_stub_report(eclis: list[str]) -> None:
    print()
    print("═" * 60)
    print("  ECHR JUDGMENT STUBS")
    print("═" * 60)
    if not eclis:
        print("\n  No stub ECHR judgments found.")
        return
    print(f"\n  {len(eclis)} ECHR judgment stub(s) (`retrieve echr --mode gaps`):\n")
    for ecli in eclis[:20]:
        print(f"    {ecli}")
    if len(eclis) > 20:
        print(f"    … and {len(eclis) - 20} more")


def _print_verdrag_stub_report(ids: list[str]) -> None:
    print()
    print("═" * 60)
    print("  VERDRAG STUBS")
    print("═" * 60)
    if not ids:
        print("\n  No stub verdragen found.")
        return
    print(f"\n  {len(ids)} verdrag stub(s) (`retrieve verdragenbank --mode gaps`):\n")
    for ext_id in ids[:20]:
        print(f"    {ext_id}")
    if len(ids) > 20:
        print(f"    … and {len(ids) - 20} more")


def _print_celex_stub_report(celex_ids: list[str]) -> None:
    print()
    print("═" * 60)
    print("  EU CELEX STUB GAPS")
    print("═" * 60)
    if not celex_ids:
        print("\n  No EU stub instruments found.")
        return
    print(
        f"\n  {len(celex_ids)} EU instrument(s) named by BWB regulations but not yet loaded:\n"
    )
    for celex in celex_ids[:30]:
        print(f"    {celex}")
    if len(celex_ids) > 30:
        print(f"    … and {len(celex_ids) - 30} more")


# ── reporting ─────────────────────────────────────────────────────────────────


def _print_stub_report(
    missing: list[dict[str, Any]],
    known: list[dict[str, Any]],
    name_cache: dict[str, str],
    min_stubs: int,
) -> None:
    print()
    print("═" * 60)
    print("  STUB ARTICLE GAPS")
    print("═" * 60)

    if not missing and not known:
        print("  No stub articles found — graph is complete!")
        return

    above = [r for r in missing if r["count"] >= min_stubs]
    below = [r for r in missing if r["count"] < min_stubs]

    if above:
        print(
            f"\n  Laws NOT in graph with ≥{min_stubs} stub references"
            f" ({len(above)} laws, fetched by `retrieve bwb --mode gaps`):\n"
        )
        _print_stub_table(above, name_cache)

    if below:
        print(
            f"\n  Laws NOT in graph with <{min_stubs} stub references"
            f" ({len(below)} laws, use --min-stubs 1 to include):\n"
        )
        _print_stub_table(below, name_cache)

    if known:
        stubs_in_graph = sum(r["count"] for r in known)
        print(
            f"\n  Laws already in graph: {len(known)} laws "
            f"with {stubs_in_graph} stub article(s) total."
        )
        print(
            "  These stubs resolve automatically once you re-run the normalize pipeline."
        )


def _print_stub_table(rows: list[dict[str, Any]], name_cache: dict[str, str]) -> None:
    for r in rows:
        bwb_id = r["bwb_id"]
        count = r["count"]
        name = name_cache.get(bwb_id.upper(), "")
        name_str = f"  {name}" if name else ""
        print(f"    {count:>4}×  {bwb_id}{name_str}")


def _print_judgment_stub_report(eclis: list[str], referrals: list[Referral]) -> None:
    print()
    print("═" * 60)
    print("  STUB JUDGMENT GAPS")
    print("═" * 60)

    if referrals:
        print(
            f"\n  {len(referrals)} referral(s) of preliminary rulings to look up in the "
            "index of their date:\n"
        )
        for referral in referrals[:30]:
            print(f"    {referral.date}  {', '.join(referral.case_numbers)}")
    if not eclis:
        print("\n  No stub judgments found — case law is complete!")
        return

    print(
        f"\n  {len(eclis)} judgment(s) cited and not loaded (`retrieve rechtspraak --mode gaps`):\n"
    )
    for ecli in eclis[:30]:
        print(f"    {ecli}")
    if len(eclis) > 30:
        print(f"    … and {len(eclis) - 30} more")


def _print_mvt_report(gap: list[dict[str, Any]]) -> None:
    print()
    print("═" * 60)
    print("  MvT XML STATUS")
    print("═" * 60)

    if not gap:
        print("\n  Every MvT document has its XML.")
        return

    print(f"\n  {len(gap)} MvT document(s) without XML (`retrieve tk-content`):\n")
    for pub in gap:
        title = (pub.get("title") or pub.get("key") or "")[:70]
        print(f"    [{pub['number']} nr. {pub['sequence']}] {title}")
    print()
    print(
        "  Note: papers from before December 1994 exist as PDF only; a paper this week may "
        "still have to be published as XML."
    )
