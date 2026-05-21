"""Diagnose and fill knowledge gaps in the LawGraph database.

Three gap types are addressed:

1. **Stub laws** — articles that are referenced from loaded instruments but whose
   parent law has never been fetched.  Ranked by reference count so the most
   impactful additions come first.  With ``--apply`` the missing BWB IDs are
   appended to the profile's ``bwb.ids`` list, then the retrieve + normalize +
   semantic pipelines are run for each new ID.

2. **Stub judgments** — case-law nodes created as placeholders when a judgment
   ECLI was cited but the full document was never fetched.  With ``--apply`` the
   missing ECLIs are retrieved from the Rechtspraak API and normalized.

3. **MvT text** — publications whose ``props.soort`` contains "toelichting" but
   whose ``props.text`` is still empty.  With ``--apply`` the text is fetched from
   the TK API (PDF → plain text).

Usage examples::

    # Diagnose — print a report without changing anything
    python -m lawgraph.cli.fill_gaps --profile strafrecht

    # Fill everything with ≥3 stub references (default threshold)
    python -m lawgraph.cli.fill_gaps --profile strafrecht --apply

    # Only add a specific law
    python -m lawgraph.cli.fill_gaps --profile strafrecht --apply --bwb-id BWBR0005537

    # Lower threshold to catch laws with just 1 stub reference
    python -m lawgraph.cli.fill_gaps --profile strafrecht --apply --min-stubs 1

    # Skip case-law gap filling
    python -m lawgraph.cli.fill_gaps --profile strafrecht --apply --no-case-law
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import textwrap
import time
from typing import Any

from dotenv import load_dotenv

from lawgraph.clients.bwb import BWBClient
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.tk_content import TKTextHydratePipeline
from lawgraph.pipelines.semantic.bwb_articles import BwbArticlesSemanticPipeline
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    RechtspraakArticleSemanticPipeline,
)

logger = get_logger(__name__)

# Minimum number of stub references before a law is shown/added automatically.
DEFAULT_MIN_STUBS = 3


# ── public entry point ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:  # noqa: C901
    parser = argparse.ArgumentParser(
        description=textwrap.dedent(
            """\
            Diagnose and optionally fill knowledge gaps in the LawGraph database.

            By default the command prints a diagnostic report and exits.
            Pass --apply to actually extend the profile and run the pipelines.
        """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile to diagnose / extend (e.g. strafrecht).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the profile YAML and run pipelines (default: dry-run).",
    )
    parser.add_argument(
        "--min-stubs",
        type=int,
        default=DEFAULT_MIN_STUBS,
        metavar="N",
        help=(
            f"Only add laws that have at least N stub references "
            f"(default: {DEFAULT_MIN_STUBS}).  Ignored when --bwb-id is used."
        ),
    )
    parser.add_argument(
        "--bwb-id",
        dest="bwb_ids",
        action="append",
        metavar="BWBR…",
        help="Add a specific BWB ID regardless of its stub count; repeatable.",
    )
    parser.add_argument(
        "--no-mvt",
        action="store_true",
        help="Skip MvT text hydration even with --apply.",
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Skip re-running the BWB semantic pipeline after normalization.",
    )
    parser.add_argument(
        "--no-case-law",
        action="store_true",
        help="Skip fetching stub judgments from the Rechtspraak API.",
    )
    parser.add_argument(
        "--no-eurlex",
        action="store_true",
        help="Skip fetching stub EU instruments from EUR-Lex.",
    )
    parser.add_argument(
        "--no-echr",
        action="store_true",
        help="Skip re-fetching ECHR judgment stubs from HUDOC.",
    )
    parser.add_argument(
        "--no-verdragen",
        action="store_true",
        help="Skip re-fetching stub verdragen from Verdragenbank.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()

    # ── 1. diagnose stub laws ─────────────────────────────────────────────────
    stub_rows = _query_stub_articles(store)

    # Query BWB IDs already fully loaded in the graph (non-stub instruments).
    aql_in_graph = """
    FOR inst IN instruments
      FILTER inst.props.bwb_id != null
      FILTER inst.props.stub != true
      RETURN UPPER(inst.props.bwb_id)
    """
    already_in_graph = set(store.query(aql_in_graph))

    # Partition by whether the law is already in the graph.
    missing: list[dict[str, Any]] = []
    known: list[dict[str, Any]] = []
    for row in stub_rows:
        bwb_id = row["bwb_id"]
        if not bwb_id:
            continue
        (known if bwb_id in already_in_graph else missing).append(row)

    # Resolve display names: DB first (instant), then BWB API for unknowns.
    name_cache = _build_name_cache(store)
    unknown_ids = [
        r["bwb_id"] for r in missing if r["bwb_id"].upper() not in name_cache
    ]
    if unknown_ids:
        print("  Resolving law names from BWB API…", end="\r", flush=True)
        name_cache = _resolve_names_from_bwb(unknown_ids, name_cache)
        print(" " * 40, end="\r")  # clear the line

    _print_stub_report(missing, known, name_cache, args.min_stubs)

    # ── 2. diagnose stub judgments ────────────────────────────────────────────
    stub_judgment_eclis = _query_stub_judgments(store)
    _print_judgment_stub_report(stub_judgment_eclis)

    # ── 3. diagnose MvT ──────────────────────────────────────────────────────
    mvt_gap = _query_mvt_gap(store)
    _print_mvt_report(mvt_gap)

    # ── 4. diagnose EU CELEX stubs ────────────────────────────────────────────
    stub_celex_ids = _query_stub_celex_ids(store)
    _print_celex_stub_report(stub_celex_ids)

    # ── 5. diagnose ECHR judgment stubs ──────────────────────────────────────
    stub_echr_eclis = _query_stub_echr_judgments(store)
    _print_echr_stub_report(stub_echr_eclis)

    # ── 6. diagnose stub verdragen ────────────────────────────────────────────
    stub_verdragen = _query_stub_verdragen(store)
    _print_verdrag_stub_report(stub_verdragen)

    if not args.apply:
        print("\n[dry-run]  Run with --apply to fetch missing data.")
        return

    # ── 4. determine BWB IDs to add ───────────────────────────────────────────
    if args.bwb_ids:
        # Explicit IDs override the threshold filter.
        to_add = [
            r["bwb_id"]
            for r in missing
            if r["bwb_id"] in {b.upper() for b in args.bwb_ids}
        ]
        # Also accept IDs not yet in stub list (user may be proactive).
        explicit = {b.upper() for b in args.bwb_ids}
        already_handled = {r["bwb_id"] for r in stub_rows}
        for bwb_id in explicit:
            if bwb_id not in already_in_graph and bwb_id not in already_handled:
                to_add.append(bwb_id)
    else:
        to_add = [r["bwb_id"] for r in missing if r["count"] >= args.min_stubs]

    if not to_add:
        logger.info("No new BWB IDs to add — nothing to do.")
    else:
        # ── 5. retrieve new laws from BWB ──────────────────────────────────────
        logger.info("Retrieving %d new BWB laws…", len(to_add))
        retrieve_since = dt.datetime.now(dt.timezone.utc)
        bwb_client = BWBClient()
        retrieve_result = BWBRetrievePipeline(store=store, client=bwb_client).run(
            bwb_ids=to_add
        )
        logger.info("BWB retrieve: %s.", retrieve_result.summary())

        # ── 6. normalize new laws ──────────────────────────────────────────────
        logger.info("Normalizing new laws…")
        norm_result = BWBNormalizePipeline(store=store).run(since=retrieve_since)
        logger.info("BWB normalize: %s.", norm_result.summary())

        # ── 7. semantic pipeline for new laws ──────────────────────────────────
        if not args.no_semantic:
            logger.info("Running BWB semantic pipeline for new laws…")
            sem_result = BwbArticlesSemanticPipeline(
                store=store,
                domain_profile=args.profile or None,
            ).run()
            logger.info("BWB semantic: %s.", sem_result.summary())

    # ── 9. fetch stub judgments ───────────────────────────────────────────────
    if not args.no_case_law and stub_judgment_eclis:
        logger.info(
            "Fetching %d stub judgment(s) from Rechtspraak…", len(stub_judgment_eclis)
        )
        rs_retrieve = RechtspraakRetrievePipeline(store=store)
        rs_retrieve_result = rs_retrieve.run(eclis=stub_judgment_eclis)
        logger.info("Rechtspraak retrieve: %s.", rs_retrieve_result.summary())

        logger.info("Normalizing fetched judgments…")
        rs_norm_result = RechtspraakNormalizePipeline(store=store).run()
        logger.info("Rechtspraak normalize: %s.", rs_norm_result.summary())

        if not args.no_semantic:
            logger.info("Running judgment citation semantic pipeline…")
            jc_result = JudgmentCitationsSemanticPipeline(store=store).run()
            logger.info("Judgment citations: %s.", jc_result.summary())

            logger.info("Running rechtspraak article semantic pipeline…")
            ra_result = RechtspraakArticleSemanticPipeline(
                store=store,
                domain_profile=args.profile or None,
            ).run()
            logger.info("Rechtspraak article links: %s.", ra_result.summary())

    elif args.no_case_law:
        logger.info("Skipping case law gap filling (--no-case-law).")
    else:
        logger.info("No stub judgments found — case law is complete.")

    # ── Phase: EU CELEX stubs ───────────────────────────────────────────────
    if not args.no_eurlex and stub_celex_ids:
        logger.info(
            "Fetching %d stub EU instruments from EUR-Lex…", len(stub_celex_ids)
        )
        from lawgraph.pipelines.normalize.eurlex import EUNormalizePipeline
        from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline

        eu_retrieve_since = dt.datetime.now(dt.timezone.utc)
        eu_retrieve_result = EurlexRetrievePipeline(store=store).run(
            celex_ids=stub_celex_ids
        )
        logger.info("EUR-Lex retrieve: %s.", eu_retrieve_result.summary())
        eu_norm_result = EUNormalizePipeline(store=store).run(since=eu_retrieve_since)
        logger.info("EUR-Lex normalize: %s.", eu_norm_result.summary())

    # ── Phase: ECHR judgment stubs ────────────────────────────────────────────
    if not args.no_echr and stub_echr_eclis:
        logger.info(
            "Re-fetching %d stub ECHR judgment(s) from HUDOC…", len(stub_echr_eclis)
        )
        from lawgraph.pipelines.normalize.echr import EchrNormalizePipeline
        from lawgraph.pipelines.retrieve.echr import EchrRetrievePipeline

        echr_retrieve_since = dt.datetime.now(dt.timezone.utc)
        echr_retrieve_result = EchrRetrievePipeline(store=store).run()
        logger.info("ECHR retrieve: %s.", echr_retrieve_result.summary())
        echr_norm_result = EchrNormalizePipeline(store=store).run(
            since=echr_retrieve_since
        )
        logger.info("ECHR normalize: %s.", echr_norm_result.summary())
    elif args.no_echr:
        logger.info("Skipping ECHR gap filling (--no-echr).")
    else:
        logger.info("No stub ECHR judgments found.")

    # ── Phase: stub verdragen ─────────────────────────────────────────────────
    if not args.no_verdragen and stub_verdragen:
        logger.info(
            "%d stub verdrag(en) found — re-running Verdragenbank retrieve…",
            len(stub_verdragen),
        )
        from lawgraph.pipelines.normalize.verdragenbank import (
            VerdragenbankNormalizePipeline,
        )
        from lawgraph.pipelines.retrieve.verdragenbank import (
            VerdragenbankRetrievePipeline,
        )

        vdb_retrieve_since = dt.datetime.now(dt.timezone.utc)
        vdb_retrieve_result = VerdragenbankRetrievePipeline(store=store).run()
        logger.info("Verdragenbank retrieve: %s.", vdb_retrieve_result.summary())
        vdb_norm_result = VerdragenbankNormalizePipeline(store=store).run(
            since=vdb_retrieve_since
        )
        logger.info("Verdragenbank normalize: %s.", vdb_norm_result.summary())
    elif args.no_verdragen:
        logger.info("Skipping Verdragenbank gap filling (--no-verdragen).")
    else:
        logger.info("No stub verdragen found.")

    # ── 10. MvT hydration ─────────────────────────────────────────────────────
    if not args.no_mvt and mvt_gap:
        logger.info("Fetching %d missing MvT text(s)…", len(mvt_gap))
        mvt_result = TKTextHydratePipeline(store=store).run(soort_filter="toelichting")
        logger.info("MvT hydration: %s.", mvt_result.summary())
    elif args.no_mvt:
        logger.info("Skipping MvT hydration (--no-mvt).")
    else:
        logger.info("No MvT texts missing — nothing to hydrate.")


# ── helpers ───────────────────────────────────────────────────────────────────


def _query_stub_articles(store: ArangoStore) -> list[dict[str, Any]]:
    """Return stub article groups sorted by reference count descending."""
    aql = """
    FOR doc IN instrument_articles
      FILTER doc.props.stub == true AND doc.props.bwb_id != null
      COLLECT bwb_id = doc.props.bwb_id WITH COUNT INTO cnt
      SORT cnt DESC
      RETURN { bwb_id, count: cnt }
    """
    return list(store.query(aql))


def _query_stub_judgments(store: ArangoStore) -> list[str]:
    """Return ECLIs of stub judgment nodes, sorted for stable ordering."""
    aql = """
    FOR j IN judgments
      FILTER j.props.stub == true AND j.props.ecli != null
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return list(store.query(aql))


def _query_mvt_gap(store: ArangoStore) -> list[dict[str, Any]]:
    """Return publications with soort ∋ 'toelichting' and no stored text."""
    aql = """
    FOR pub IN publications
      FILTER CONTAINS(LOWER(pub.props.soort), 'toelichting')
        AND (pub.props.text == null OR pub.props.text == '')
        AND pub.props.external_id != null
      RETURN {
        key: pub._key,
        title: pub.props.title,
        soort: pub.props.soort,
        external_id: pub.props.external_id
      }
    """
    return list(store.query(aql))


def _build_name_cache(store: ArangoStore) -> dict[str, str]:
    """Map bwb_id → best available title from the instruments collection."""
    aql = """
    FOR inst IN instruments
      FILTER inst.props.bwb_id != null
      RETURN {
        bwb_id: inst.props.bwb_id,
        title: inst.props.citation_title OR inst.props.title OR inst.props.display_name
      }
    """
    cache: dict[str, str] = {}
    for row in store.query(aql):
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
    """Fetch law titles from the BWB API for IDs not already in *known*.

    Caps at *max_lookups* HTTP calls so the diagnostic stays fast.  Only fetches
    the XML toestand (small — header only is enough for the <citeertitel> tag).
    """
    import xml.etree.ElementTree as ET

    from lawgraph.clients.bwb import BWBClient

    result = dict(known)
    to_resolve = [b for b in bwb_ids if b.upper() not in result][:max_lookups]
    if not to_resolve:
        return result

    client = BWBClient()
    for bwb_id in to_resolve:
        try:
            meta = client.latest_toestand(bwb_id)
            if not meta:
                continue
            xml_text = client.fetch_toestand_xml(meta)
            root = ET.fromstring(xml_text)
            for node in root.iter():
                if node.tag.split("}")[-1] == "citeertitel" and node.text:
                    result[bwb_id.upper()] = node.text.strip()
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not resolve title for %s: %s", bwb_id, exc)
        time.sleep(0.1)  # gentle rate limit

    return result


def _query_stub_echr_judgments(store: ArangoStore) -> list[str]:
    """Return ECLIs (or HUDOC app numbers) of stub ECHR judgment nodes."""
    aql = """
    FOR j IN judgments
      FILTER j.props.stub == true AND j.props.source == "echr"
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return [e for e in store.query(aql) if e]


def _query_stub_verdragen(store: ArangoStore) -> list[str]:
    """Return external IDs of stub verdrag instrument nodes."""
    aql = """
    FOR inst IN instruments
      FILTER inst.props.stub == true
        AND inst.props.kind IN ["verdrag", "bilateraalverdrag", "multilateraalverdrag"]
      RETURN inst.props.external_id
    """
    return [e for e in store.query(aql) if e]


def _print_echr_stub_report(eclis: list[str]) -> None:
    print()
    print("═" * 60)
    print("  ECHR JUDGMENT STUBS")
    print("═" * 60)
    if not eclis:
        print("\n  No stub ECHR judgments found.")
        return
    print(f"\n  {len(eclis)} ECHR judgment stub(s) — re-run retrieval with --apply:\n")
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
    print(
        f"\n  {len(ids)} verdrag stub(s) — re-run Verdragenbank retrieval with --apply:\n"
    )
    for ext_id in ids[:20]:
        print(f"    {ext_id}")
    if len(ids) > 20:
        print(f"    … and {len(ids) - 20} more")


_CELEX_PATTERN = re.compile(r"\b3\d{4}[CLRDF]\d{4}\b", re.IGNORECASE)


def _query_stub_celex_ids(store: ArangoStore) -> list[str]:
    """Find CELEX IDs referenced in BWB article text but not yet loaded from EUR-Lex."""
    # CELEX IDs already in instruments collection
    aql_loaded = """
    FOR inst IN instruments
      FILTER inst.props.celex != null
      RETURN UPPER(inst.props.celex)
    """
    loaded: set[str] = set(store.query(aql_loaded))

    # CELEX IDs already retrieved into raw_sources
    aql_raw = """
    FOR r IN raw_sources
      FILTER r.source == "eurlex"
      RETURN UPPER(r.external_id)
    """
    already_retrieved: set[str] = set(store.query(aql_raw))
    known = loaded | already_retrieved

    # Scan BWB article text for CELEX references
    aql_texts = """
    FOR art IN instrument_articles
      FILTER art.props.bwb_id != null
      FILTER art.props.text != null
      RETURN art.props.text
    """
    found: set[str] = set()
    for text in store.query(aql_texts):
        for m in _CELEX_PATTERN.finditer(str(text)):
            celex = m.group(0).upper()
            if celex not in known:
                found.add(celex)

    return sorted(found)


def _print_celex_stub_report(celex_ids: list[str]) -> None:
    print()
    print("═" * 60)
    print("  EU CELEX STUB GAPS")
    print("═" * 60)
    if not celex_ids:
        print("\n  No EU stub instruments found.")
        return
    print(
        f"\n  {len(celex_ids)} EU instrument(s) referenced in BWB text but not yet loaded:\n"
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
            f" ({len(above)} laws, would be added with --apply):\n"
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


def _print_judgment_stub_report(eclis: list[str]) -> None:
    print()
    print("═" * 60)
    print("  STUB JUDGMENT GAPS")
    print("═" * 60)

    if not eclis:
        print("\n  No stub judgments found — case law is complete!")
        return

    print(
        f"\n  {len(eclis)} judgment(s) cited but not yet fetched (--apply will retrieve them):\n"
    )
    for ecli in eclis[:30]:
        print(f"    {ecli}")
    if len(eclis) > 30:
        print(f"    … and {len(eclis) - 30} more")


def _print_mvt_report(gap: list[dict[str, Any]]) -> None:
    print()
    print("═" * 60)
    print("  MvT HYDRATION STATUS")
    print("═" * 60)

    if not gap:
        print("\n  All MvT documents have been hydrated.")
        return

    print(
        f"\n  {len(gap)} MvT document(s) missing text (--apply will attempt fetch):\n"
    )
    for pub in gap:
        title = (pub.get("title") or pub.get("key") or "")[:70]
        soort = pub.get("soort") or ""
        print(f"    [{soort}] {title}")
    print()
    print("  Note: scanned PDFs may fail text extraction; check logs after --apply.")
