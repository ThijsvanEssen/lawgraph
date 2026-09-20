"""Diagnose and fill knowledge gaps in the LawGraph database.

Three gap types are addressed:

1. **Stub laws** — articles that are referenced from loaded instruments but whose
   parent law has never been fetched.  Ranked by reference count so the most
   impactful additions come first.  With ``--apply`` the missing BWB IDs are
   retrieved and normalized.

2. **Stub judgments** — case-law nodes created as placeholders when a judgment
   ECLI was cited but the full document was never fetched.  With ``--apply`` the
   missing ECLIs are retrieved from the Rechtspraak API and normalized.

3. **MvT text** — documents whose ``props.kind`` contains "toelichting" but
   whose ``props.text`` is still empty.  With ``--apply`` the text is fetched from
   the TK API (PDF → plain text).

Usage examples::

    # Diagnose — print a report without changing anything
    python -m lawgraph fill-gaps

    # Fill everything with ≥3 stub references (default threshold)
    python -m lawgraph fill-gaps --apply

    # Only add a specific law
    python -m lawgraph fill-gaps --apply --bwb-id BWBR0005537

    # Lower threshold to catch laws with just 1 stub reference
    python -m lawgraph fill-gaps --apply --min-stubs 1

    # Skip case-law gap filling
    python -m lawgraph fill-gaps --apply --no-case-law
"""

from __future__ import annotations

import argparse
import datetime as dt
import textwrap
import time
from typing import Any, cast

from lawgraph.clients.bwb import BWBClient
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_EU_CELEX,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.bwb_xml import parse_toestand
from lawgraph.core.identifiers import CELEX_AQL_REGEX, find_celex_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import ArangoStore
from lawgraph.pipelines.factory import run_step
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline
from lawgraph.pipelines.semantic.bwb_articles import BWBArticlesSemanticPipeline
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
)
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    RechtspraakArticlesSemanticPipeline,
)

logger = get_logger(__name__)

# The most stub judgments and explanatory memoranda one run fetches; the rest is reported.
MAX_GAPS_PER_RUN = 50_000

# Minimum number of stub references before a law is shown/added automatically.
DEFAULT_MIN_STUBS = 3


# ── public entry point ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=textwrap.dedent(
            """\
            Diagnose and optionally fill knowledge gaps in the LawGraph database.

            By default the command prints a diagnostic report and exits.
            Pass --apply to actually run the pipelines and fill the gaps.
        """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run pipelines to fill identified gaps (default: dry-run).",
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

    def run() -> PipelineResult:
        store = ArangoStore()
        diag = _run_diagnostics(store, args)
        if not args.apply:
            print("\n[dry-run]  Run with --apply to fetch missing data.")
            return PipelineResult()

        return (
            _apply_bwb_gaps(store, args, diag["to_add"])
            .merge(_apply_case_law_gaps(store, args, diag["stub_judgment_eclis"]))
            .merge(_apply_eu_gaps(store, args, diag["stub_celex_ids"]))
            .merge(_apply_echr_gaps(store, args, diag["stub_echr_eclis"]))
            .merge(_apply_treaty_gaps(store, args, diag["stub_verdragen"]))
            .merge(_apply_mvt_gaps(store, args, diag["mvt_gap"]))
        )

    run_step("fill-gaps", run)


# ── phase helpers ─────────────────────────────────────────────────────────────


def _run_diagnostics(store: ArangoStore, args: argparse.Namespace) -> dict[str, Any]:
    """Run all six diagnostic phases, print reports, and return data for apply."""
    # ── 1. diagnose stub laws ─────────────────────────────────────────────────
    stub_rows = _query_stub_articles(store)

    aql_in_graph = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.bwb_id != null
      FILTER inst.props.stub != true
      RETURN UPPER(inst.props.bwb_id)
    """
    already_in_graph = {
        str(r) if not isinstance(r, str) else r for r in store.query(aql_in_graph)
    }

    missing: list[dict[str, Any]] = []
    known: list[dict[str, Any]] = []
    for row in stub_rows:
        bwb_id = row["bwb_id"]
        if not bwb_id:
            continue
        (known if bwb_id in already_in_graph else missing).append(row)

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

    # Resolve the BWB IDs to add during the apply phase.
    to_add = _resolve_bwb_ids_to_add(args, missing, stub_rows, already_in_graph)

    return {
        "to_add": to_add,
        "stub_judgment_eclis": stub_judgment_eclis,
        "mvt_gap": mvt_gap,
        "stub_celex_ids": stub_celex_ids,
        "stub_echr_eclis": stub_echr_eclis,
        "stub_verdragen": stub_verdragen,
    }


def _resolve_bwb_ids_to_add(
    args: argparse.Namespace,
    missing: list[dict[str, Any]],
    stub_rows: list[dict[str, Any]],
    already_in_graph: set[str],
) -> list[str]:
    """Return the list of BWB IDs to retrieve during the apply phase."""
    if args.bwb_ids:
        explicit = {b.upper() for b in args.bwb_ids}
        to_add = [r["bwb_id"] for r in missing if r["bwb_id"] in explicit]
        already_handled = {r["bwb_id"] for r in stub_rows}
        for bwb_id in explicit:
            if bwb_id not in already_in_graph and bwb_id not in already_handled:
                to_add.append(bwb_id)
        return to_add
    return [r["bwb_id"] for r in missing if r["count"] >= args.min_stubs]


def _logged(label: str, result: PipelineResult) -> PipelineResult:
    logger.info("%s: %s.", label, result.summary())
    return result


def _apply_bwb_gaps(
    store: ArangoStore, args: argparse.Namespace, to_add: list[str]
) -> PipelineResult:
    """Retrieve and normalize missing BWB laws, then detect their article references."""
    if not to_add:
        logger.info("No new BWB IDs to add.")
        return PipelineResult()

    started = dt.datetime.now(dt.timezone.utc)
    result = _logged(
        "BWB retrieve", BWBRetrievePipeline(store=store).run(bwb_ids=to_add)
    ).merge(
        _logged("BWB normalize", BWBNormalizePipeline(store=store).run(since=started))
    )
    if not args.no_semantic:
        result = result.merge(
            _logged("BWB semantic", BWBArticlesSemanticPipeline(store=store).run())
        )
    return result


def _apply_case_law_gaps(
    store: ArangoStore, args: argparse.Namespace, stub_eclis: list[str]
) -> PipelineResult:
    """Fetch stub judgments from Rechtspraak, normalize them and link their citations."""
    if args.no_case_law or not stub_eclis:
        return PipelineResult()

    result = _logged(
        "Rechtspraak retrieve",
        RechtspraakRetrievePipeline(store=store).run(eclis=stub_eclis),
    ).merge(
        _logged(
            "Rechtspraak normalize", RechtspraakNormalizePipeline(store=store).run()
        )
    )
    if not args.no_semantic:
        result = result.merge(
            _logged(
                "Judgment citations",
                JudgmentCitationsSemanticPipeline(store=store).run(),
            )
        ).merge(
            _logged(
                "Rechtspraak article links",
                RechtspraakArticlesSemanticPipeline(store=store).run(),
            )
        )
    return result


def _apply_eu_gaps(
    store: ArangoStore, args: argparse.Namespace, stub_celex_ids: list[str]
) -> PipelineResult:
    """Fetch stub EU instruments from EUR-Lex and normalize them."""
    if args.no_eurlex or not stub_celex_ids:
        return PipelineResult()

    started = dt.datetime.now(dt.timezone.utc)
    return _logged(
        "EUR-Lex retrieve",
        EurlexRetrievePipeline(store=store).run(celex_ids=stub_celex_ids),
    ).merge(
        _logged(
            "EUR-Lex normalize", EurlexNormalizePipeline(store=store).run(since=started)
        )
    )


def _apply_echr_gaps(
    store: ArangoStore, args: argparse.Namespace, stub_echr_eclis: list[str]
) -> PipelineResult:
    """Re-run the ECHR retrieval (HUDOC has no fetch per ECLI) and normalize the result."""
    if args.no_echr or not stub_echr_eclis:
        return PipelineResult()

    started = dt.datetime.now(dt.timezone.utc)
    return _logged("ECHR retrieve", ECHRRetrievePipeline(store=store).run()).merge(
        _logged("ECHR normalize", ECHRNormalizePipeline(store=store).run(since=started))
    )


def _apply_treaty_gaps(
    store: ArangoStore, args: argparse.Namespace, stub_treaties: list[str]
) -> PipelineResult:
    """Re-run the Verdragenbank retrieval (it has no fetch per treaty) and normalize."""
    if args.no_verdragen or not stub_treaties:
        return PipelineResult()

    started = dt.datetime.now(dt.timezone.utc)
    return _logged(
        "Verdragenbank retrieve", VerdragenbankRetrievePipeline(store=store).run()
    ).merge(
        _logged(
            "Verdragenbank normalize",
            VerdragenbankNormalizePipeline(store=store).run(since=started),
        )
    )


def _apply_mvt_gaps(
    store: ArangoStore, args: argparse.Namespace, mvt_gap: list[dict[str, Any]]
) -> PipelineResult:
    """Fetch the text of explanatory memoranda that have none."""
    if args.no_mvt or not mvt_gap:
        return PipelineResult()

    return _logged(
        "MvT text",
        TKContentRetrievePipeline(store=store).run(kind_filter="toelichting"),
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _query_stub_articles(store: ArangoStore) -> list[dict[str, Any]]:
    """Return stub article groups sorted by reference count descending."""
    aql = f"""
    FOR doc IN {COLLECTION_ARTICLES}
      FILTER doc.props.stub == true AND doc.props.bwb_id != null
      COLLECT bwb_id = doc.props.bwb_id WITH COUNT INTO cnt
      SORT cnt DESC
      RETURN {{ bwb_id, count: cnt }}
    """
    return list(store.query(aql))


def _capped(rows: list[Any], what: str) -> list[Any]:
    """The first ``MAX_GAPS_PER_RUN`` of *rows*; a longer list is said out loud."""
    if len(rows) > MAX_GAPS_PER_RUN:
        logger.warning(
            "%d %s found; this run takes the first %d (fill-gaps or expand-graph again "
            "for the rest).",
            len(rows),
            what,
            MAX_GAPS_PER_RUN,
        )
        return rows[:MAX_GAPS_PER_RUN]
    return rows


def _query_stub_judgments(store: ArangoStore) -> list[str]:
    """ECLIs of the Dutch stub judgments, sorted; Rechtspraak has no EU or ECHR judgments."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND j.props.ecli != null
      FILTER STARTS_WITH(j.props.ecli, "ECLI:NL:")
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    # Those Rechtspraak answered 404 for come out before the cap, not after it: they sort
    # where they sort, and a first 50,000 full of judgments that are not published would
    # keep every later one from ever being asked for.
    missing_aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r.source == @source AND r.kind == @kind AND r.meta.retry_after > @now
      RETURN r.external_id
    """
    missing = set(
        store.query(
            missing_aql,
            {
                "source": SOURCE_RECHTSPRAAK,
                "kind": RAW_KIND_RS_CONTENT + RAW_KIND_MISSING_SUFFIX,
                "now": iso_timestamp(dt.datetime.now(dt.timezone.utc)),
            },
        )
    )
    eclis = [ecli for ecli in store.query(aql) if ecli not in missing]
    return _capped(cast(list[str], eclis), "stub judgments")


def _query_mvt_gap(store: ArangoStore) -> list[dict[str, Any]]:
    """Return documents with kind ∋ 'toelichting' and no stored text."""
    aql = f"""
    FOR pub IN {COLLECTION_DOCUMENTS}
      FILTER CONTAINS(LOWER(pub.props.kind), 'toelichting')
        AND (pub.props.text == null OR pub.props.text == '')
        AND pub.props.external_id != null
      RETURN {{
        key: pub._key,
        title: pub.props.title,
        kind: pub.props.kind,
        external_id: pub.props.external_id
      }}
    """
    return _capped(list(store.query(aql)), "explanatory memoranda without text")


def _build_name_cache(store: ArangoStore) -> dict[str, str]:
    """Map bwb_id → best available title from the instruments collection."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.bwb_id != null
      RETURN {{
        bwb_id: inst.props.bwb_id,
        title: inst.props.citation_title OR inst.props.title OR inst.props.display_name
      }}
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
            citation_title = parse_toestand(xml_text).citation_title
            if citation_title:
                result[bwb_id.upper()] = citation_title
        except Exception as exc:
            logger.debug("Could not resolve title for %s: %s", bwb_id, exc)
        time.sleep(0.1)  # gentle rate limit

    return result


def _query_stub_echr_judgments(store: ArangoStore) -> list[str]:
    """Return ECLIs (or HUDOC app numbers) of stub ECHR judgment nodes."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
      FILTER j.props.stub == true AND j.props.source == "echr"
      SORT j.props.ecli
      RETURN j.props.ecli
    """
    return cast(list[str], [e for e in store.query(aql) if e])


def _query_stub_verdragen(store: ArangoStore) -> list[str]:
    """Return external IDs of stub verdrag instrument nodes."""
    aql = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.stub == true
        AND inst.props.kind IN ["verdrag", "bilateraalverdrag", "multilateraalverdrag"]
      RETURN inst.props.external_id
    """
    return cast(list[str], [e for e in store.query(aql) if e])


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


def _query_stub_celex_ids(store: ArangoStore) -> list[str]:
    """Find CELEX IDs referenced in BWB article text but not yet loaded from EUR-Lex."""
    # CELEX IDs already in instruments collection
    aql_loaded = f"""
    FOR inst IN {COLLECTION_INSTRUMENTS}
      FILTER inst.props.celex != null
      RETURN UPPER(inst.props.celex)
    """
    loaded: set[str] = cast(set[str], set(store.query(aql_loaded)))

    # CELEX IDs already retrieved into raw_sources
    aql_raw = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
      FILTER r.source == "eurlex" AND r.kind == @kind
      RETURN UPPER(r.external_id)
    """
    already_retrieved: set[str] = cast(
        set[str], set(store.query(aql_raw, {"kind": RAW_KIND_EU_CELEX}))
    )
    known = loaded | already_retrieved

    # Scan BWB article text for CELEX references; only the texts that can hold one are sent.
    aql_texts = f"""
    FOR art IN {COLLECTION_ARTICLES}
      FILTER art.props.bwb_id != null
      FILTER art.props.text != null
      FILTER REGEX_TEST(art.props.text, @celex)
      RETURN art.props.text
    """
    found: set[str] = set()
    for text in store.query(aql_texts, {"celex": CELEX_AQL_REGEX}):
        for celex in find_celex_ids(str(text)):
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
        kind = pub.get("kind") or ""
        print(f"    [{kind}] {title}")
    print()
    print("  Note: scanned PDFs may fail text extraction; check logs after --apply.")
