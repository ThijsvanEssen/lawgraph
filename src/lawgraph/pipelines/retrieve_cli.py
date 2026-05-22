"""Per-source retrieve entry points.

Each function has the same interface as the old cli/retrieve_xxx.py main()
functions: it accepts an optional argv list and handles its own argument
parsing, store setup, and pipeline invocation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import cast

from dotenv import load_dotenv

from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.db import ArangoStore


def _setup() -> None:
    """Load environment variables and configure logging for CLI entry points."""
    load_dotenv()
    setup_logging()


_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)

# ── BWB ───────────────────────────────────────────────────────────────────────


def retrieve_bwb(argv: list[str] | None = None) -> None:
    import os

    from lawgraph.clients.bwb import BWBClient
    from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

    def _clean_ids(values: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for v in values:
            s = v.strip()
            if s:
                seen[s] = None
        return list(seen)

    def _ids_from_env() -> list[str]:
        raw = os.getenv("BWB_IDS", "")
        return _clean_ids(raw.split(",")) if raw else []

    def _resolve_ids(*, cli_ids: list[str] | None) -> list[str]:
        if cli_ids:
            return _clean_ids(cli_ids)
        return _ids_from_env()

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Haal de nieuwste BWB-toestanden op via de BWB SRU service."
    )
    parser.add_argument("--bwb-id", dest="bwb_ids", action="append")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    mode = args.mode

    _setup()
    store = ArangoStore()
    client = BWBClient()
    pipeline = BWBRetrievePipeline(store=store, client=client)

    if mode == "full":
        result = pipeline.run_full()
    else:
        candidate_ids = _resolve_ids(cli_ids=args.bwb_ids)
        if not candidate_ids:
            logger.warning("No BWB IDs found; nothing to do.")
            return
        result = pipeline.run(bwb_ids=candidate_ids)

    logger.info("BWB retrieve completed (mode=%s): %s.", mode, result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("BWB retrieve error: %s", err)
        sys.exit(1)


# ── BWB history ───────────────────────────────────────────────────────────────


def retrieve_bwb_history(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve ALL historical BWB toestanden."
    )
    parser.add_argument("bwb_ids", nargs="*")
    args = parser.parse_args(argv)

    _setup()
    store = ArangoStore()
    pipeline = BWBRetrievePipeline(store=store)

    try:
        if args.bwb_ids:
            result = pipeline.run_history(bwb_ids=args.bwb_ids)
        else:
            result = pipeline.run_history_full()
    except Exception as exc:
        logger.error("BWB history retrieval failed: %s", exc)
        sys.exit(1)

    logger.info("BWB history retrieval complete: %s", result.summary())


# ── ECHR ─────────────────────────────────────────────────────────────────────


def retrieve_echr(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.echr import EchrRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(description="Retrieve ECHR HUDOC judgments.")
    parser.add_argument("--respondent", default="NLD")
    parser.add_argument("--since")
    parser.add_argument("--max-records", type=int, default=10000)
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    mode = args.mode

    _setup()
    store = ArangoStore()
    pipeline = EchrRetrievePipeline(store)

    if mode == "full":
        result = pipeline.run_full(respondent=args.respondent)
    else:
        result = pipeline.run(
            respondent=args.respondent,
            since_date=args.since,
            max_records=args.max_records,
        )

    logger.info("ECHR retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("ECHR retrieve error: %s", err)
        sys.exit(1)


# ── Eerste Kamer ──────────────────────────────────────────────────────────────


def retrieve_eerstekamer(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(description="Retrieve Eerste Kamer Kamerstukken.")
    parser.add_argument("--since")
    parser.add_argument("--max-records", type=int, default=50000)
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    mode = args.mode
    since = args.since if mode == "incremental" else None
    max_records = args.max_records if mode == "incremental" else 200000

    _setup()
    store = ArangoStore()
    pipeline = EerstekamerRetrievePipeline(store)
    result = pipeline.run(since=since, max_records=max_records)

    logger.info(
        "Eerste Kamer retrieve completed (mode=%s): %s.", mode, result.summary()
    )
    if result.errors:
        for err in result.errors:
            logger.warning("EK retrieve error: %s", err)
        sys.exit(1)


# ── EUR-Lex ───────────────────────────────────────────────────────────────────


def retrieve_eurlex(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(description="Retrieve EUR-Lex CELEX html pages.")
    parser.add_argument("--celex", action="append")
    parser.add_argument("--lang", default="NL")
    parser.add_argument("--country", default="NLD")
    parser.add_argument(
        "--mode",
        choices=["incremental", "full", "nim", "cjeu", "com"],
        default="incremental",
    )
    args = parser.parse_args(argv)

    mode = args.mode

    _setup()
    store = ArangoStore()
    pipeline = EurlexRetrievePipeline(store)

    _celex_aql = "FOR inst IN instruments FILTER inst.props.celex != null RETURN inst.props.celex"

    if mode == "full":
        result = pipeline.run_full(lang=args.lang)
    elif mode == "nim":
        result = pipeline.run_nim(country_code=args.country, lang=args.lang)
    elif mode == "cjeu":
        existing_celex = cast(list[str], list(store.query(_celex_aql)))
        result = pipeline.run_cjeu(
            celex_ids=existing_celex or None, country_code=args.country, lang=args.lang
        )
    elif mode == "com":
        existing_celex = cast(list[str], list(store.query(_celex_aql)))
        result = pipeline.run_com(celex_ids=existing_celex, lang=args.lang)
    else:
        # incremental: retrieve CELEX IDs already in the graph
        if args.celex:
            candidates = args.celex
        else:
            candidates = list(store.query(_celex_aql))
        if not candidates:
            logger.warning("No EUR-Lex CELEX identifiers found; nothing to retrieve.")
            return
        result = pipeline.run(celex_ids=candidates, lang=args.lang)

    logger.info("EUR-Lex retrieve completed (mode=%s): %s.", mode, result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("EUR-Lex retrieve error: %s", err)
        sys.exit(1)


# ── Rechtspraak ───────────────────────────────────────────────────────────────


def retrieve_rechtspraak(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve Rechtspraak index and contents."
    )
    parser.add_argument("--since-days", type=int, default=1)
    parser.add_argument("--ecli", action="append")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    mode = args.mode

    _setup()
    store = ArangoStore()
    pipeline = RechtspraakRetrievePipeline(store)

    if mode == "full":
        result = pipeline.run_full()
    else:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
        eclis: list[str] = args.ecli or []
        result = pipeline.run(
            fetch_index=True, since=since, extra_params=None, eclis=eclis
        )

    logger.info("Rechtspraak retrieve completed (mode=%s): %s.", mode, result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Rechtspraak retrieve error: %s", err)
        sys.exit(1)


# ── Staatsblad ────────────────────────────────────────────────────────────────


def retrieve_staatsblad(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve Dutch Staatsblad AMvB XML publications."
    )
    parser.add_argument("--mode", choices=["from-graph", "full"], default="from-graph")
    args = parser.parse_args(argv)

    _setup()
    store = ArangoStore()
    pipeline = StaatsbladRetrievePipeline(store=store)

    if args.mode == "full":
        result = pipeline.run_full()
    else:
        result = pipeline.run_from_bwb_graph(store)

    logger.info(
        "Staatsblad retrieve completed (mode=%s): %s.", args.mode, result.summary()
    )
    if result.errors:
        for err in result.errors:
            logger.warning("Staatsblad retrieve error: %s", err)
        sys.exit(1)


# ── Staatscourant ─────────────────────────────────────────────────────────────


def retrieve_staatscourant(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve Staatscourant ministeriele regelingen."
    )
    parser.add_argument("--since")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    parser.add_argument("--identifiers", nargs="*")
    args = parser.parse_args(argv)

    _setup()
    store = ArangoStore()
    pipeline = StaatscourantRetrievePipeline(store)

    if args.identifiers:
        result = pipeline.run(identifiers=args.identifiers)
    elif args.mode == "full":
        result = pipeline.run_full()
    else:
        result = pipeline.run(since=args.since)

    logger.info(
        "Staatscourant retrieve completed (mode=%s): %s.", args.mode, result.summary()
    )
    if result.errors:
        for err in result.errors:
            logger.warning("Staatscourant retrieve error: %s", err)
        sys.exit(1)


# ── Tweede Kamer ──────────────────────────────────────────────────────────────


def retrieve_tk(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve TK zaak and documentversie data."
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--since-days", type=int, default=1)
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help=(
            "'incremental' fetches records modified since --since-days; "
            f"'full' fetches all since {_TK_EPOCH.date().isoformat()}."
        ),
    )
    args = parser.parse_args(argv)

    mode = args.mode
    since = (
        _TK_EPOCH
        if mode == "full"
        else dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
    )

    _setup()
    store = ArangoStore()
    pipeline = TKRetrievePipeline(store)

    result = pipeline.run(since=since, limit=args.limit)

    logger.info("TK retrieve completed (mode=%s): %s.", mode, result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("TK retrieve error: %s", err)
        sys.exit(1)


# ── TK content hydration ──────────────────────────────────────────────────────


def retrieve_tk_content(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.tk_content import TKTextHydratePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Fetch full-text PDF content for TK publications."
    )
    parser.add_argument("--soort", default="toelichting")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _setup()
    store = ArangoStore()
    pipeline = TKTextHydratePipeline(store=store)
    result = pipeline.run(soort_filter=args.soort, dry_run=args.dry_run)
    logger.info("Done: %s.", result.summary())

    if result.errors:
        for err in result.errors:
            logger.warning("Error: %s", err)
        sys.exit(1)


# ── TK dossiers ───────────────────────────────────────────────────────────────


def retrieve_tk_dossiers(argv: list[str] | None = None) -> None:
    from lawgraph.core.time import parse_since as _parse_since
    from lawgraph.pipelines.retrieve.tk_dossiers import TkDossiersRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve parliamentary dossier entities from the TK OData API.",
    )
    parser.add_argument("--since", default=None)
    parser.add_argument("--skip-personen", action="store_true")
    parser.add_argument("--skip-stemmingen", action="store_true")
    parser.add_argument("--stemmingen-since", default=None, metavar="DATE")
    parser.add_argument("--skip-documents", action="store_true")
    parser.add_argument("--documents-since", default=None, metavar="DATE")
    parser.add_argument("--dossier-nummer", type=int, default=None, metavar="N")
    args = parser.parse_args(argv)

    try:
        since = _parse_since(args.since)
        stemmingen_since = _parse_since(args.stemmingen_since)
        documents_since = _parse_since(args.documents_since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    _setup()
    store = ArangoStore()
    pipeline = TkDossiersRetrievePipeline(store=store)
    result = pipeline.run(
        since=since,
        stemmingen_since=stemmingen_since,
        documents_since=documents_since,
        skip_personen=args.skip_personen,
        skip_stemmingen=args.skip_stemmingen,
        skip_documents=args.skip_documents,
        dossier_nummer=args.dossier_nummer,
    )
    logger.info("%s", result.summary())
    if result.errors:
        for err in result.errors:
            logger.error("%s", err)
        sys.exit(1)


# ── Verdragenbank ─────────────────────────────────────────────────────────────


def retrieve_verdragenbank(argv: list[str] | None = None) -> None:
    from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline

    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Retrieve treaties from the Dutch Verdragenbank."
    )
    parser.add_argument("--max-records", type=int, default=10000)
    args = parser.parse_args(argv)

    _setup()
    store = ArangoStore()
    pipeline = VerdragenbankRetrievePipeline(store)
    result = pipeline.run(max_records=args.max_records)

    logger.info("Verdragenbank retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Verdragenbank retrieve error: %s", err)
        sys.exit(1)
