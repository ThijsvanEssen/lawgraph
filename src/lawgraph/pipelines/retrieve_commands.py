"""The ``lawgraph retrieve <source>`` commands: parse options, run the retrieve pipeline."""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.config.constants import (
    RECHTSPRAAK_DEFAULT_COURTS,
    RECHTSPRAAK_EVERY_COURT,
    RECHTSPRAAK_MODIFIED_WINDOW_DAYS,
    RECHTSPRAAK_PUBLICATION_LAG_DAYS,
)
from lawgraph.config.settings import BWB_IDS
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.command import add_since_argument, command_parser
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline
from lawgraph.pipelines.retrieve.eerstekamer_agenda import (
    EerstekamerAgendaRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_bills import (
    EerstekamerBillsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_composition import (
    EerstekamerCompositionRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eerstekamer_votes import (
    EerstekamerVotesRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.eurlex_nim import EurlexNimRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak_instanties import (
    RechtspraakInstantiesRetrievePipeline,
)
from lawgraph.pipelines.retrieve.rijksoverheid import RijksoverheidRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant_posts import (
    StaatscourantPostsRetrievePipeline,
)
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline
from lawgraph.pipelines.retrieve.tk_case_actors import TKCaseActorsRetrievePipeline
from lawgraph.pipelines.retrieve.tk_content import (
    DEFAULT_KINDS,
    TKContentRetrievePipeline,
)
from lawgraph.pipelines.retrieve.tk_document_links import (
    TKDocumentLinksRetrievePipeline,
)
from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from lawgraph.pipelines.retrieve.tooi import TooiRetrievePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline

_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)


GAPS = "gaps"  # fetch what the graph refers to and only holds a stub of (``_gaps.py``)


def _add_mode_argument(
    parser: argparse.ArgumentParser, *, extra_modes: tuple[str, ...] = ()
) -> None:
    """What to fetch: what changed (``incremental``), all of it (``full``), or an extra mode."""
    extra = (
        f"; also {', '.join(extra_modes)} (see docs/pipelines.md)"
        if extra_modes
        else ""
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full", *extra_modes],
        default="incremental",
        help=f"incremental (default): what changed since --since; full: all of it{extra}.",
    )


def _date(since: dt.datetime | None) -> str | None:
    return since.date().isoformat() if since else None


def retrieve_bwb(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the current BWB toestand of regulations."
    )
    parser.add_argument(
        "--bwb-id",
        dest="bwb_ids",
        action="append",
        help="Incremental mode: regulation to fetch (repeatable); default: the "
        "BWB_IDS environment variable.",
    )
    parser.add_argument(
        "--min-stubs",
        type=int,
        default=_gaps.DEFAULT_MIN_STUBS,
        metavar="N",
        help="Gaps mode: a law is fetched when N of its articles are referred to "
        "(default: %(default)s).",
    )
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = GraphStore()
    pipeline = BWBRetrievePipeline(store=store)
    if args.mode == "full":
        return pipeline.run_full()
    if args.mode == GAPS:
        return pipeline.run(bwb_ids=_gaps.bwb_gaps(store, min_stubs=args.min_stubs))
    return pipeline.run(bwb_ids=args.bwb_ids or BWB_IDS)


def retrieve_bwb_history(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the historical BWB toestanden that are not stored yet."
    )
    parser.add_argument(
        "bwb_ids",
        nargs="*",
        help="Default: every regulation of which the current toestand is stored.",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="incremental: only the toestanden not stored yet; full: every one again.",
    )
    args = parser.parse_args(argv)

    pipeline = BWBRetrievePipeline(store=GraphStore())
    return pipeline.run_history(bwb_ids=args.bwb_ids, refetch=args.mode == "full")


def retrieve_echr(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Retrieve ECHR HUDOC judgments.")
    parser.add_argument(
        "--respondent",
        default="NLD",
        help="The state the judgments are against (default: %(default)s).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=10000,
        help="Incremental mode: at most this many judgments (default: %(default)s).",
    )
    add_since_argument(parser)
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = GraphStore()
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
    parser = command_parser(description="Retrieve EUR-Lex acts by CELEX number.")
    parser.add_argument(
        "--celex",
        action="append",
        help="Incremental mode: act to fetch (repeatable); default is every act in the graph.",
    )
    parser.add_argument(
        "--lang", default="NL", help="Language of the text (default: %(default)s)."
    )
    parser.add_argument(
        "--country",
        default="NLD",
        help="nim and cjeu: the country of the measures or judgments (default: "
        "%(default)s).",
    )
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

    store = GraphStore()
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


def retrieve_eurlex_nim(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the national implementing measures of EUR-Lex (CELLAR)."
    )
    parser.add_argument(
        "--country",
        default="NLD",
        help="The country of the measures (default: %(default)s).",
    )
    add_since_argument(parser, default="30d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    pipeline = EurlexNimRetrievePipeline(GraphStore())
    since = None if args.mode == "full" else _date(args.since)
    return pipeline.run(country_code=args.country, since=since)


def retrieve_eerstekamer(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the Eerste Kamer Kamerstukken (KOOP SRU)."
    )
    parser.add_argument(
        "--max-records", type=int, default=None, help="At most this many papers."
    )
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    pipeline = EerstekamerRetrievePipeline(GraphStore())
    since = None if args.mode == "full" else _date(args.since)
    return pipeline.run(since=since, limit=args.max_records)


def retrieve_eerstekamer_votes(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the votes of the Eerste Kamer on bills and the list of the "
        "bills it rejected (eerstekamer.nl)."
    )
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)
    since = None if args.mode == "full" or args.since is None else args.since.date()
    return EerstekamerVotesRetrievePipeline(GraphStore()).run(since=since)


def retrieve_eerstekamer_composition(argv: list[str] | None = None) -> PipelineResult:
    command_parser(
        description="Retrieve the factions and committees of the Eerste Kamer as they are "
        "today (eerstekamer.nl): a snapshot of about 40 pages."
    ).parse_args(argv)
    return EerstekamerCompositionRetrievePipeline(GraphStore()).run()


def retrieve_eerstekamer_agenda(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the agendas of the plenary sittings and committee meetings of "
        "the Eerste Kamer (eerstekamer.nl): those planned, and back to --since (without "
        "it back to June 2015, a long run that goes on where one broke off)."
    )
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)
    since = None if args.mode == "full" or args.since is None else args.since.date()
    return EerstekamerAgendaRetrievePipeline(GraphStore()).run(since=since)


def retrieve_eerstekamer_bills(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the pages of the bills of the Eerste Kamer (eerstekamer.nl): "
        "those its committees list and those it voted on since --since."
    )
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)
    since = None if args.mode == "full" or args.since is None else args.since.date()
    return EerstekamerBillsRetrievePipeline(GraphStore()).run(since=since)


def retrieve_rechtspraak(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve Rechtspraak judgments of every court (--court narrows it), "
        "by decision date."
    )
    parser.add_argument(
        "--court",
        action="append",
        metavar="NAME",
        help="Court to read (repeatable): an ECLI court code (HR, RVS, GHAMS), a tier "
        "of the court table (gerechtshof, rechtbank, ...: every court of it), or "
        f"{RECHTSPRAAK_EVERY_COURT} for every court of the index (the rechtbanken too). "
        f"Default: {', '.join(RECHTSPRAAK_DEFAULT_COURTS)}; none when only --ecli is given.",
    )
    parser.add_argument(
        "--ecli", action="append", help="Judgment to fetch as it is (repeatable)."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser, extra_modes=(GAPS,))
    args = parser.parse_args(argv)

    store = GraphStore()
    if args.mode == GAPS:  # the cited and the referring judgments, of whatever court
        eclis = _gaps.rechtspraak_gaps(store)
        result = RechtspraakRetrievePipeline(store).run(
            courts=[], eclis=eclis, referrals=_gaps.unanswered_referrals(store)
        )
        return _gaps.noted(result, eclis)

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
    parser = command_parser(description="Retrieve Staatsblad publications of AMvBs.")
    parser.add_argument(
        "--mode",
        choices=["from-graph", "full"],
        default="from-graph",
        help="from-graph (default): the publications the stored BWB toestanden name; "
        "full: every AMvB the SRU lists.",
    )
    args = parser.parse_args(argv)

    store = GraphStore()
    pipeline = StaatsbladRetrievePipeline(store=store)
    if args.mode == "full":
        return pipeline.run_full()
    return pipeline.run_from_bwb_graph(store)


def retrieve_staatscourant(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve Staatscourant ministerial regulations."
    )
    parser.add_argument(
        "--identifiers",
        nargs="*",
        help="Fetch these publications (stcrt-…) as they are.",
    )
    add_since_argument(parser)
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    pipeline = StaatscourantRetrievePipeline(GraphStore())
    if args.identifiers:
        return pipeline.run(identifiers=args.identifiers)
    if args.mode == "full":
        return pipeline.run_full()
    return pipeline.run(since=_date(args.since))


def retrieve_tk(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Retrieve Tweede Kamer cases.")
    parser.add_argument(
        "--limit", type=int, default=0, help="At most this many cases (0: every one)."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    since = _TK_EPOCH if args.mode == "full" else args.since
    return TKRetrievePipeline(GraphStore()).run(since=since, limit=args.limit)


def retrieve_tk_content(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Retrieve the XML of Tweede Kamer documents.")
    parser.add_argument(
        "--kind",
        action="append",
        help="A word of the kind of paper to fetch (repeatable; default: "
        f'{", ".join(DEFAULT_KINDS)}; "" for every paper).',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Say which papers would be fetched; fetch nothing.",
    )
    parser.add_argument(
        "--mode",
        choices=[GAPS],
        default=GAPS,
        help="The only mode: the papers of --kind of which no XML is stored yet.",
    )
    args = parser.parse_args(argv)

    pipeline = TKContentRetrievePipeline(store=GraphStore())
    return pipeline.run(kinds=args.kind or DEFAULT_KINDS, dry_run=args.dry_run)


def retrieve_tk_document_links(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the links of Tweede Kamer documents: the activity a document "
        "is the record of, its attachments and the letters it is an attachment of."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    since = None if args.mode == "full" else args.since
    return TKDocumentLinksRetrievePipeline(GraphStore()).run(since=since)


def retrieve_tk_case_actors(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve the actors of Tweede Kamer cases: who submitted a case and "
        "which committee leads it."
    )
    add_since_argument(parser, default="1d")
    _add_mode_argument(parser)
    args = parser.parse_args(argv)

    since = None if args.mode == "full" else args.since
    return TKCaseActorsRetrievePipeline(GraphStore()).run(since=since)


def retrieve_tk_dossiers(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
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
    add_since_argument(
        parser,
        "--commitments-since",
        help="Commitments (Toezegging) only: overrides --since.",
    )
    parser.add_argument(
        "--skip-members",
        action="store_true",
        help="Skip persons, factions and their seats.",
    )
    parser.add_argument(
        "--skip-decisions", action="store_true", help="Skip votes and decisions."
    )
    parser.add_argument("--skip-documents", action="store_true", help="Skip documents.")
    parser.add_argument(
        "--dossier-number",
        type=int,
        default=None,
        metavar="N",
        help="Only this dossier and its documents, whatever the dates.",
    )
    parser.add_argument(
        "--mode",
        choices=["window", GAPS],
        default="window",
        help="gaps: the dossiers the graph names and lacks (those of the publications that "
        "changed an article, and the first reading of a change in the Grondwet), with "
        "their documents; the other options are then not used.",
    )
    args = parser.parse_args(argv)

    store = GraphStore()
    if args.mode == GAPS:
        numbers = _gaps.tk_dossier_gaps(store)
        result = TKDossiersRetrievePipeline(store=store).run_gaps(numbers)
        return _gaps.noted(result, numbers)
    return TKDossiersRetrievePipeline(store=store).run(
        since=args.since,
        decisions_since=args.decisions_since,
        documents_since=args.documents_since,
        commitments_since=args.commitments_since,
        skip_members=args.skip_members,
        skip_decisions=args.skip_decisions,
        skip_documents=args.skip_documents,
        dossier_number=args.dossier_number,
    )


def retrieve_verdragenbank(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Retrieve treaties from the Verdragenbank.")
    parser.add_argument(
        "--max-records", type=int, default=None, help="At most this many treaties."
    )
    parser.add_argument(
        "--mode",
        choices=["full", GAPS],
        default="full",
        help="gaps: only when a treaty is referred to that is not loaded (the register "
        "has no fetch per treaty, so it is read again in full).",
    )
    parser.add_argument(
        "--only-stored",
        action="store_true",
        help="only the treaties whose record is stored already (their changes and item "
        "XML); no new treaties",
    )
    args = parser.parse_args(argv)

    store = GraphStore()
    if args.mode == GAPS and not _gaps.verdragenbank_gaps(store):
        return PipelineResult()
    return VerdragenbankRetrievePipeline(store).run(
        max_records=args.max_records, only_stored=args.only_stored
    )


def retrieve_rijksoverheid(argv: list[str] | None = None) -> PipelineResult:
    command_parser(
        description="Retrieve the page of every cabinet since 1945 from rijksoverheid.nl."
    ).parse_args(argv)
    return RijksoverheidRetrievePipeline(GraphStore()).run()


def retrieve_tooi(argv: list[str] | None = None) -> PipelineResult:
    command_parser(
        description="Retrieve the TOOI value list of every ministry (KOOP)."
    ).parse_args(argv)
    return TooiRetrievePipeline(GraphStore()).run()


def retrieve_rechtspraak_instanties(argv: list[str] | None = None) -> PipelineResult:
    command_parser(
        description="Retrieve the Instanties value list of the Rechtspraak (every court)."
    ).parse_args(argv)
    return RechtspraakInstantiesRetrievePipeline(GraphStore()).run()


def retrieve_staatscourant_posts(argv: list[str] | None = None) -> PipelineResult:
    command_parser(
        description="Retrieve per cabinet post whose function names no ministry which "
        "ministries issued the publications naming it (KOOP SRU)."
    ).parse_args(argv)
    return StaatscourantPostsRetrievePipeline(GraphStore()).run()
