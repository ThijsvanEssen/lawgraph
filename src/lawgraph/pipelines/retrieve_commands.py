"""The ``lawgraph retrieve <source>`` commands: parse options, run the retrieve pipeline."""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.config.constants import (
    RECHTSPRAAK_COURT_GROUPS,
    RECHTSPRAAK_COURTS,
    RECHTSPRAAK_DEFAULT_COURTS,
    RECHTSPRAAK_MODIFIED_WINDOW_DAYS,
    RECHTSPRAAK_PUBLICATION_LAG_DAYS,
)
from lawgraph.config.settings import BWB_IDS
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.command import add_since_argument
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline
from lawgraph.pipelines.retrieve.wikidata import WikidataRetrievePipeline

_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)


GAPS = "gaps"  # fetch what the graph refers to and only holds a stub of (``_gaps.py``)


def _add_mode_argument(
    parser: argparse.ArgumentParser, *, extra_modes: tuple[str, ...] = ()
) -> None:
    """What to fetch: what changed (``incremental``), all of it (``full``), or an extra mode."""
    parser.add_argument(
        "--mode", choices=["incremental", "full", *extra_modes], default="incremental"
    )


def _date(since: dt.datetime | None) -> str | None:
    return since.date().isoformat() if since else None


def retrieve_bwb(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve the current BWB toestand of regulations."
    )
    parser.add_argument(
        "--bwb-id",
        dest="bwb_ids",
        action="append",
        help="Incremental mode: regulation to fetch (repeatable); default is BWB_IDS.",
    )
    parser.add_argument(
        "--min-stubs",
        type=int,
        default=_gaps.DEFAULT_MIN_STUBS,
        metavar="N",
        help="Gaps mode: a law is fetched when N of its articles are referred to.",
    )
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = ArangoStore()
    pipeline = BWBRetrievePipeline(store=store)
    if args.mode == "full":
        return pipeline.run_full()
    if args.mode == GAPS:
        return pipeline.run(bwb_ids=_gaps.bwb_gaps(store, min_stubs=args.min_stubs))
    return pipeline.run(bwb_ids=args.bwb_ids or BWB_IDS)


def retrieve_bwb_history(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve every historical BWB toestand."
    )
    parser.add_argument("bwb_ids", nargs="*", help="Default: all regulations.")
    args = parser.parse_args(argv)

    pipeline = BWBRetrievePipeline(store=ArangoStore())
    if args.bwb_ids:
        return pipeline.run_history(bwb_ids=args.bwb_ids)
    return pipeline.run_history_full()


def retrieve_echr(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Retrieve ECHR HUDOC judgments.")
    parser.add_argument("--respondent", default="NLD")
    parser.add_argument("--max-records", type=int, default=10000)
    add_since_argument(parser)
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = ArangoStore()
    pipeline = ECHRRetrievePipeline(store)
    if args.mode == "full":
        return pipeline.run_full(respondent=args.respondent)
    if args.mode == GAPS:  # the cited judgments, against any state
        return pipeline.run(eclis=_gaps.echr_gaps(store))
    return pipeline.run(
        respondent=args.respondent,
        since_date=_date(args.since),
        max_records=args.max_records,
    )


def retrieve_eurlex(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve EUR-Lex acts by CELEX number."
    )
    parser.add_argument(
        "--celex",
        action="append",
        help="Incremental mode: act to fetch (repeatable); default is every act in the graph.",
    )
    parser.add_argument("--lang", default="NL")
    parser.add_argument("--country", default="NLD")
    parser.add_argument(
        "--type",
        dest="cdm_types",
        action="append",
        choices=["directive", "regulation", "decision"],
        help="Full mode: act type to list (repeatable, default: directive). "
        "The listing is incomplete for recent years and stops at 10000 acts per type.",
    )
    _add_mode_argument(parser, extra_modes=("nim", "cjeu", "com", GAPS))
    args = parser.parse_args(argv)

    store = ArangoStore()
    pipeline = EurlexRetrievePipeline(store)
    if args.mode == "full":
        return pipeline.run_full(
            lang=args.lang, cdm_types=tuple(args.cdm_types or ("directive",))
        )
    if args.mode == "nim":
        return pipeline.run_nim(country_code=args.country, lang=args.lang)
    if args.mode == GAPS:  # the acts BWB regulations name
        return pipeline.run(celex_ids=_gaps.eurlex_gaps(store), lang=args.lang)

    known_celex = args.celex or list(gap_queries.known_celex_ids(store))
    if args.mode == "cjeu":
        return pipeline.run_cjeu(
            celex_ids=known_celex or None,
            country_code=args.country,
            lang=args.lang,
        )
    if args.mode == "com":
        return pipeline.run_com(celex_ids=known_celex, lang=args.lang)
    return pipeline.run(celex_ids=known_celex, lang=args.lang)


def retrieve_eerstekamer(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve the Eerste Kamer Kamerstukken (KOOP SRU)."
    )
    parser.add_argument("--max-records", type=int, default=None)
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    pipeline = EerstekamerRetrievePipeline(ArangoStore())
    since = None if args.mode == "full" else _date(args.since)
    return pipeline.run(since=since, limit=args.max_records)


def retrieve_rechtspraak(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve Rechtspraak judgments of chosen courts, by decision date."
    )
    parser.add_argument(
        "--court",
        action="append",
        metavar="NAME",
        help="Court or group to read (repeatable): "
        f"{', '.join(sorted({*RECHTSPRAAK_COURTS, *RECHTSPRAAK_COURT_GROUPS}))}. "
        f"Default: {', '.join(RECHTSPRAAK_DEFAULT_COURTS)}; none when only --ecli is given.",
    )
    parser.add_argument(
        "--ecli", action="append", help="Judgment to fetch as it is (repeatable)."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = ArangoStore()
    if args.mode == GAPS:  # the cited judgments, of whatever court
        eclis = _gaps.rechtspraak_gaps(store)
        return RechtspraakRetrievePipeline(store).run(courts=[], eclis=eclis)

    courts = args.court or ([] if args.ecli else list(RECHTSPRAAK_DEFAULT_COURTS))
    date_from = modified_from = None
    if args.mode == "incremental":
        lag = dt.timedelta(days=RECHTSPRAAK_PUBLICATION_LAG_DAYS)
        date_from = (args.since - lag).date()
        window = dt.datetime.now(dt.timezone.utc) - args.since
        if window <= dt.timedelta(days=RECHTSPRAAK_MODIFIED_WINDOW_DAYS):
            modified_from = args.since
    pipeline = RechtspraakRetrievePipeline(store)
    return pipeline.run(
        courts=courts,
        date_from=date_from,
        modified_from=modified_from,
        eclis=args.ecli or [],
    )


def retrieve_staatsblad(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve Staatsblad publications of AMvBs."
    )
    parser.add_argument("--mode", choices=["from-graph", "full"], default="from-graph")
    args = parser.parse_args(argv)

    store = ArangoStore()
    pipeline = StaatsbladRetrievePipeline(store=store)
    if args.mode == "full":
        return pipeline.run_full()
    return pipeline.run_from_bwb_graph(store)


def retrieve_staatscourant(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve Staatscourant ministerial regulations."
    )
    parser.add_argument("--identifiers", nargs="*")
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    pipeline = StaatscourantRetrievePipeline(ArangoStore())
    if args.identifiers:
        return pipeline.run(identifiers=args.identifiers)
    if args.mode == "full":
        return pipeline.run_full()
    return pipeline.run(since=_date(args.since))


def retrieve_tk(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Retrieve Tweede Kamer cases.")
    parser.add_argument("--limit", type=int, default=0)
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    since = _TK_EPOCH if args.mode == "full" else args.since
    return TKRetrievePipeline(ArangoStore()).run(since=since, limit=args.limit)


def retrieve_tk_content(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve the XML of Tweede Kamer documents."
    )
    parser.add_argument("--kind", default="toelichting")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--mode",
        choices=[GAPS],
        default=GAPS,
        help="The only mode: the papers of --kind of which no XML is stored yet.",
    )
    args = parser.parse_args(argv)

    pipeline = TKContentRetrievePipeline(store=ArangoStore())
    return pipeline.run(kind_filter=args.kind, dry_run=args.dry_run)


def retrieve_tk_dossiers(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve Tweede Kamer dossiers, decisions, votes, committees and members."
    )
    add_since_argument(parser)
    add_since_argument(
        parser, "--decisions-since", help="Votes only: overrides --since."
    )
    add_since_argument(
        parser,
        "--documents-since",
        help="Documents only: overrides --since (a full fetch is over 400K records).",
    )
    parser.add_argument("--skip-members", action="store_true")
    parser.add_argument("--skip-decisions", action="store_true")
    parser.add_argument("--skip-documents", action="store_true")
    parser.add_argument("--dossier-number", type=int, default=None, metavar="N")
    parser.add_argument(
        "--mode",
        choices=["window", GAPS],
        default="window",
        help="gaps: the dossiers the graph names and lacks (those of the publications that "
        "changed an article, and the first reading of a change in the Grondwet), with "
        "their documents; the other options are then not used.",
    )
    args = parser.parse_args(argv)

    store = ArangoStore()
    if args.mode == GAPS:
        return TKDossiersRetrievePipeline(store=store).run_gaps(
            _gaps.tk_dossier_gaps(store)
        )
    return TKDossiersRetrievePipeline(store=store).run(
        since=args.since,
        decisions_since=args.decisions_since,
        documents_since=args.documents_since,
        skip_members=args.skip_members,
        skip_decisions=args.skip_decisions,
        skip_documents=args.skip_documents,
        dossier_number=args.dossier_number,
    )


def retrieve_verdragenbank(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(
        description="Retrieve treaties from the Verdragenbank."
    )
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument(
        "--mode",
        choices=["full", GAPS],
        default="full",
        help="gaps: only when a treaty is referred to that is not loaded (the register "
        "has no fetch per treaty, so it is read again in full).",
    )
    args = parser.parse_args(argv)

    store = ArangoStore()
    if args.mode == GAPS and not _gaps.verdragenbank_gaps(store):
        return PipelineResult()
    return VerdragenbankRetrievePipeline(store).run(max_records=args.max_records)


def retrieve_wikidata(argv: list[str] | None = None) -> PipelineResult:
    argparse.ArgumentParser(
        description="Retrieve the posts people held in Dutch cabinets, from Wikidata."
    ).parse_args(argv)
    return WikidataRetrievePipeline(ArangoStore()).run()
