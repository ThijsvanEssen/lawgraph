"""The ``lawgraph retrieve <source>`` commands: parse options, run the retrieve pipeline."""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.config.settings import BWB_IDS
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.pipelines.factory import add_since_argument, run_step
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

_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)
_EERSTEKAMER_FULL_MAX_RECORDS = 200_000
_KNOWN_CELEX_AQL = (
    f"FOR inst IN {COLLECTION_INSTRUMENTS} "
    "FILTER inst.props.celex != null RETURN inst.props.celex"
)


def _add_mode_argument(
    parser: argparse.ArgumentParser, *, extra_modes: tuple[str, ...] = ()
) -> None:
    parser.add_argument(
        "--mode", choices=["incremental", "full", *extra_modes], default="incremental"
    )


def _date(since: dt.datetime | None) -> str | None:
    return since.date().isoformat() if since else None


def retrieve_bwb(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve the current BWB toestand of regulations."
    )
    parser.add_argument(
        "--bwb-id",
        dest="bwb_ids",
        action="append",
        help="Incremental mode: regulation to fetch (repeatable); default is BWB_IDS.",
    )
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = BWBRetrievePipeline(store=ArangoStore())
        if args.mode == "full":
            return pipeline.run_full()
        return pipeline.run(bwb_ids=args.bwb_ids or BWB_IDS)

    run_step("BWB retrieve", run)


def retrieve_bwb_history(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve every historical BWB toestand."
    )
    parser.add_argument("bwb_ids", nargs="*", help="Default: all regulations.")
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = BWBRetrievePipeline(store=ArangoStore())
        if args.bwb_ids:
            return pipeline.run_history(bwb_ids=args.bwb_ids)
        return pipeline.run_history_full()

    run_step("BWB history retrieve", run)


def retrieve_echr(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieve ECHR HUDOC judgments.")
    parser.add_argument("--respondent", default="NLD")
    parser.add_argument("--max-records", type=int, default=10000)
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = ECHRRetrievePipeline(ArangoStore())
        if args.mode == "full":
            return pipeline.run_full(respondent=args.respondent)
        return pipeline.run(
            respondent=args.respondent,
            since_date=_date(args.since),
            max_records=args.max_records,
        )

    run_step("ECHR retrieve", run)


def retrieve_eerstekamer(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieve Eerste Kamer documents.")
    parser.add_argument("--max-records", type=int, default=50000)
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = EerstekamerRetrievePipeline(ArangoStore())
        if args.mode == "full":
            return pipeline.run(since=None, max_records=_EERSTEKAMER_FULL_MAX_RECORDS)
        return pipeline.run(since=_date(args.since), max_records=args.max_records)

    run_step("Eerste Kamer retrieve", run)


def retrieve_eurlex(argv: list[str] | None = None) -> None:
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
    _add_mode_argument(parser, extra_modes=("nim", "cjeu", "com"))
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        store = ArangoStore()
        pipeline = EurlexRetrievePipeline(store)
        if args.mode == "full":
            return pipeline.run_full(
                lang=args.lang, cdm_types=tuple(args.cdm_types or ("directive",))
            )
        if args.mode == "nim":
            return pipeline.run_nim(country_code=args.country, lang=args.lang)

        known_celex = args.celex or list(store.query(_KNOWN_CELEX_AQL))
        if args.mode == "cjeu":
            return pipeline.run_cjeu(
                celex_ids=known_celex or None,
                country_code=args.country,
                lang=args.lang,
            )
        if args.mode == "com":
            return pipeline.run_com(celex_ids=known_celex, lang=args.lang)
        return pipeline.run(celex_ids=known_celex, lang=args.lang)

    run_step("EUR-Lex retrieve", run)


def retrieve_rechtspraak(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve the Rechtspraak index and judgment contents."
    )
    parser.add_argument(
        "--ecli", action="append", help="Judgment whose content to fetch (repeatable)."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = RechtspraakRetrievePipeline(ArangoStore())
        if args.mode == "full":
            return pipeline.run_full()
        return pipeline.run(
            fetch_index=True, since=args.since, extra_params=None, eclis=args.ecli or []
        )

    run_step("Rechtspraak retrieve", run)


def retrieve_staatsblad(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve Staatsblad publications of AMvBs."
    )
    parser.add_argument("--mode", choices=["from-graph", "full"], default="from-graph")
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        store = ArangoStore()
        pipeline = StaatsbladRetrievePipeline(store=store)
        if args.mode == "full":
            return pipeline.run_full()
        return pipeline.run_from_bwb_graph(store)

    run_step("Staatsblad retrieve", run)


def retrieve_staatscourant(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve Staatscourant ministerial regulations."
    )
    parser.add_argument("--identifiers", nargs="*")
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = StaatscourantRetrievePipeline(ArangoStore())
        if args.identifiers:
            return pipeline.run(identifiers=args.identifiers)
        if args.mode == "full":
            return pipeline.run_full()
        return pipeline.run(since=_date(args.since))

    run_step("Staatscourant retrieve", run)


def retrieve_tk(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve Tweede Kamer cases and documents."
    )
    parser.add_argument("--limit", type=int, default=0)
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        since = _TK_EPOCH if args.mode == "full" else args.since
        return TKRetrievePipeline(ArangoStore()).run(since=since, limit=args.limit)

    run_step("TK retrieve", run)


def retrieve_tk_content(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve the PDF text of Tweede Kamer documents."
    )
    parser.add_argument("--kind", default="toelichting")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = TKContentRetrievePipeline(store=ArangoStore())
        return pipeline.run(kind_filter=args.kind, dry_run=args.dry_run)

    run_step("TK content retrieve", run)


def retrieve_tk_dossiers(argv: list[str] | None = None) -> None:
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
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        return TKDossiersRetrievePipeline(store=ArangoStore()).run(
            since=args.since,
            decisions_since=args.decisions_since,
            documents_since=args.documents_since,
            skip_members=args.skip_members,
            skip_decisions=args.skip_decisions,
            skip_documents=args.skip_documents,
            dossier_number=args.dossier_number,
        )

    run_step("TK dossiers retrieve", run)


def retrieve_verdragenbank(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve treaties from the Verdragenbank."
    )
    parser.add_argument("--max-records", type=int, default=10000)
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        pipeline = VerdragenbankRetrievePipeline(ArangoStore())
        return pipeline.run(max_records=args.max_records)

    run_step("Verdragenbank retrieve", run)
