"""The ``lawgraph retrieve <source>`` commands: what a retrieve reads, how one runs, and the
retrieves that parse options of their own.

A retrieve without options of its own is its pipeline class, registered as it is
(``sources/registry``). One with options is a pair here: ``<name>_args`` adds them to the
parser, ``retrieve_<name>`` runs the pipeline on what was parsed. ``RetrieveCommand`` joins
them with the description of the registry, so ``--help`` and ``lawgraph sources`` say one
text.

Most retrieve pipelines ask their source what there is. A few choose from what a normalize
pipeline wrote: ``retrieve tk-content`` fetches the XML of the documents of ``normalize
tk-dossiers``, ``retrieve eerstekamer-bills`` the pages of the bills ``normalize
eerstekamer-votes`` names, ``retrieve eurlex`` the acts ``normalize eurlex`` holds. On a graph
without those rows such a pipeline finds nothing to do and ends ``ok``, which looks like done.
``Reads`` names those rows in the registry, and the command says, before it runs, that they
are not there: in the log, and in a note of its result that the table of ``retrieve all``
shows.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lawgraph.config.constants import (
    RECHTSPRAAK_DEFAULT_COURTS,
    RECHTSPRAAK_EVERY_COURT,
    RECHTSPRAAK_MODIFIED_WINDOW_DAYS,
    RECHTSPRAAK_PUBLICATION_LAG_DAYS,
)
from lawgraph.config.settings import BWB_IDS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.command import add_since_argument, command_parser, takes_option
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
from lawgraph.pipelines.retrieve.eerstekamer_votes import (
    EerstekamerVotesRetrievePipeline,
)
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.eurlex_nim import EurlexNimRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
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
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline

logger = get_logger(__name__)


class RetrieveMode(StrEnum):
    """What a retrieve fetches (``--mode``); each command takes some of them."""

    INCREMENTAL = "incremental"  # what changed since --since
    FULL = "full"  # all of it
    GAPS = "gaps"  # what the graph refers to and only holds a stub of (``_gaps.py``)
    WINDOW = "window"  # tk-dossiers: what changed since --since and its overrides
    # tk-dossiers: only the Besluiten without a vote on an amendment or a motion
    UNVOTED = "unvoted"
    FROM_GRAPH = "from-graph"  # staatsblad: the publications the stored BWB XML names
    NIM = "nim"  # eurlex: the national implementing measures
    CJEU = "cjeu"  # eurlex: the judgments of the Court of Justice on the acts
    COM = "com"  # eurlex: the Commission proposals of the acts


_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)
DEFAULT_COUNTRY = "NLD"  # of the ECHR judgments, the EU measures and the EU rulings
ECHR_MAX_RECORDS = 10000  # the judgments an incremental ECHR run reads at most


# ── what a retrieve reads, and how one runs ──────────────────────────────────


@dataclass(frozen=True)
class Reads:
    """The nodes a retrieve pipeline chooses its work from, and the pipeline that writes them."""

    pipeline: str  # the normalize pipeline: tk-dossiers
    collection: str  # documents
    label: str  # TK
    # The modes of the command that choose from them; empty: every mode.
    modes: tuple[RetrieveMode, ...] = ()

    def applies(self, mode: RetrieveMode | None) -> bool:
        return not self.modes or mode in self.modes

    @property
    def note(self) -> str:
        return f"no {self.label} {self.collection} yet: run normalize {self.pipeline} first"


def missing(reads: Sequence[Reads]) -> list[Reads]:
    """Those of *reads* the graph does not hold; no query when there are none."""
    if not reads:
        return []
    store = GraphStore()
    return [
        r for r in reads if not gap_queries.holds_label(store, r.collection, r.label)
    ]


Run = Callable[[argparse.Namespace], PipelineResult]
AddArgs = Callable[[argparse.ArgumentParser], None]


@dataclass(frozen=True)
class RetrieveCommand:
    """The command of a retrieve pipeline: *add_args* builds its options, *run* does the work
    on them; the registry gives its description and what it reads. It takes ``--since`` when
    *add_args* adds it."""

    run: Run
    description: str
    add_args: AddArgs | None = None
    reads: tuple[Reads, ...] = ()

    def parser(self) -> argparse.ArgumentParser:
        parser = command_parser(self.description)
        if self.add_args:
            self.add_args(parser)
        return parser

    @property
    def accepts_since(self) -> bool:
        return takes_option(self.parser(), "--since")

    @property
    def accepts_touched_since(self) -> bool:
        return takes_option(self.parser(), "--touched-since")

    def parse(self, argv: Sequence[str] | None) -> argparse.Namespace:
        """The options of *argv*; ``--help`` prints them and ends here, before a query."""
        return self.parser().parse_args(argv)

    def reads_in(self, args: argparse.Namespace) -> list[Reads]:
        """What a run with *args* chooses its work from: in the mode argparse read."""
        mode = getattr(args, "mode", None)
        return [r for r in self.reads if r.applies(mode)]

    def __call__(self, argv: list[str] | None = None) -> PipelineResult:
        args = self.parse(argv)
        absent = missing(self.reads_in(args))
        for r in absent:
            logger.warning(
                "This run chooses from the %s %s of normalize %s, and the graph holds none: "
                "what it would fetch for them is not fetched now. Run normalize %s first.",
                r.label,
                r.collection,
                r.pipeline,
                r.pipeline,
            )
        result = self.run(args)
        result.notes += [r.note for r in absent]
        return result


# ── shared options ───────────────────────────────────────────────────────────


def _as_mode(value: str) -> RetrieveMode | str:
    """A mode as typed; what is no mode stays text, so argparse names the choices."""
    try:
        return RetrieveMode(value)
    except ValueError:
        return value


def add_mode_argument(
    parser: argparse.ArgumentParser,
    modes: Sequence[RetrieveMode],
    *,
    default: RetrieveMode,
    help: str,
) -> None:
    parser.add_argument(
        "--mode", type=_as_mode, choices=modes, default=default, help=help
    )


def _add_incremental_or_full(
    parser: argparse.ArgumentParser, *extra_modes: RetrieveMode
) -> None:
    """What to fetch: what changed (``incremental``), all of it (``full``), or an extra mode."""
    extra = (
        f"; also {', '.join(extra_modes)} (see docs/pipelines.md)"
        if extra_modes
        else ""
    )
    add_mode_argument(
        parser,
        (RetrieveMode.INCREMENTAL, RetrieveMode.FULL, *extra_modes),
        default=RetrieveMode.INCREMENTAL,
        help=f"incremental (default): what changed since --since; full: all of it{extra}.",
    )


def windowed_args(parser: argparse.ArgumentParser) -> None:
    """``--since`` without a default, and incremental or full."""
    add_since_argument(parser)
    _add_incremental_or_full(parser)


def windowed_from_a_day_args(parser: argparse.ArgumentParser) -> None:
    """``--since`` a day back by default, and incremental or full."""
    add_since_argument(parser, default="1d")
    _add_incremental_or_full(parser)


def _since_unless_full(args: argparse.Namespace) -> dt.datetime | None:
    """The moment of ``--since``; none in full mode, which reads everything."""
    return None if args.mode is RetrieveMode.FULL else args.since


def _day(since: dt.datetime | None) -> dt.date | None:
    return since.date() if since else None


def _iso_day(since: dt.datetime | None) -> str | None:
    return since.date().isoformat() if since else None


# ── BWB ──────────────────────────────────────────────────────────────────────


def bwb_args(parser: argparse.ArgumentParser) -> None:
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
    _add_incremental_or_full(parser, RetrieveMode.GAPS)


def retrieve_bwb(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    pipeline = BWBRetrievePipeline(store=store)
    if args.mode is RetrieveMode.FULL:
        return pipeline.run_full()
    if args.mode is RetrieveMode.GAPS:
        return pipeline.run(bwb_ids=_gaps.bwb_gaps(store, min_stubs=args.min_stubs))
    return pipeline.run(bwb_ids=args.bwb_ids or BWB_IDS)


def bwb_history_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "bwb_ids",
        nargs="*",
        help="Default: every regulation of which the current toestand is stored.",
    )
    add_mode_argument(
        parser,
        (RetrieveMode.INCREMENTAL, RetrieveMode.FULL),
        default=RetrieveMode.INCREMENTAL,
        help="incremental: only the toestanden not stored yet; full: every one again.",
    )


def retrieve_bwb_history(args: argparse.Namespace) -> PipelineResult:
    pipeline = BWBRetrievePipeline(store=GraphStore())
    return pipeline.run_history(
        bwb_ids=args.bwb_ids, refetch=args.mode is RetrieveMode.FULL
    )


# ── ECHR and EUR-Lex ─────────────────────────────────────────────────────────


def echr_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--respondent",
        default=DEFAULT_COUNTRY,
        help="The state the judgments are against (default: %(default)s).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=ECHR_MAX_RECORDS,
        help="Incremental mode: at most this many judgments (default: %(default)s).",
    )
    add_since_argument(parser)
    _add_incremental_or_full(parser, RetrieveMode.GAPS)


def retrieve_echr(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    pipeline = ECHRRetrievePipeline(store)
    if args.mode is RetrieveMode.FULL:
        return pipeline.run_full(respondent=args.respondent)
    if args.mode is RetrieveMode.GAPS:  # the cited judgments, against any state
        return pipeline.run(eclis=_gaps.echr_gaps(store))
    return pipeline.run(
        respondent=args.respondent,
        since_date=_iso_day(args.since),
        max_records=args.max_records,
    )


def eurlex_args(parser: argparse.ArgumentParser) -> None:
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
        default=DEFAULT_COUNTRY,
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
    _add_incremental_or_full(
        parser, RetrieveMode.NIM, RetrieveMode.CJEU, RetrieveMode.COM, RetrieveMode.GAPS
    )


def retrieve_eurlex(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    pipeline = EurlexRetrievePipeline(store)
    if args.mode is RetrieveMode.FULL:
        return pipeline.run_full(
            lang=args.lang, cdm_types=tuple(args.cdm_types or ("directive",))
        )
    if args.mode is RetrieveMode.NIM:
        return pipeline.run_nim(country_code=args.country, lang=args.lang)
    if args.mode is RetrieveMode.GAPS:  # the acts BWB regulations name
        return pipeline.run(celex_ids=_gaps.eurlex_gaps(store), lang=args.lang)

    known_celex = args.celex or list(gap_queries.known_celex_ids(store))
    if args.mode is RetrieveMode.CJEU:
        return pipeline.run_cjeu(
            celex_ids=known_celex or None,
            country_code=args.country,
            lang=args.lang,
        )
    if args.mode is RetrieveMode.COM:
        return pipeline.run_com(celex_ids=known_celex, lang=args.lang)
    return pipeline.run(celex_ids=known_celex, lang=args.lang)


def eurlex_nim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help="The country of the measures (default: %(default)s).",
    )
    add_since_argument(parser, default="30d")
    _add_incremental_or_full(parser)


def retrieve_eurlex_nim(args: argparse.Namespace) -> PipelineResult:
    pipeline = EurlexNimRetrievePipeline(GraphStore())
    return pipeline.run(
        country_code=args.country, since=_iso_day(_since_unless_full(args))
    )


# ── Eerste Kamer ─────────────────────────────────────────────────────────────


def eerstekamer_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-records", type=int, default=None, help="At most this many papers."
    )
    windowed_args(parser)


def retrieve_eerstekamer(args: argparse.Namespace) -> PipelineResult:
    pipeline = EerstekamerRetrievePipeline(GraphStore())
    return pipeline.run(
        since=_iso_day(_since_unless_full(args)), limit=args.max_records
    )


def retrieve_eerstekamer_votes(args: argparse.Namespace) -> PipelineResult:
    pipeline = EerstekamerVotesRetrievePipeline(GraphStore())
    return pipeline.run(since=_day(_since_unless_full(args)))


def retrieve_eerstekamer_agenda(args: argparse.Namespace) -> PipelineResult:
    pipeline = EerstekamerAgendaRetrievePipeline(GraphStore())
    return pipeline.run(since=_day(_since_unless_full(args)))


def retrieve_eerstekamer_bills(args: argparse.Namespace) -> PipelineResult:
    pipeline = EerstekamerBillsRetrievePipeline(GraphStore())
    return pipeline.run(since=_day(_since_unless_full(args)))


def eerstekamer_persons_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sitting",
        action="store_true",
        help="Fetch the page of every sitting member again (the weekly run).",
    )


def eerstekamer_motions_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="At most this many pages in this run (the rest in the next).",
    )


# ── Rechtspraak ──────────────────────────────────────────────────────────────


def rechtspraak_args(parser: argparse.ArgumentParser) -> None:
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
    _add_incremental_or_full(parser, RetrieveMode.GAPS)


def retrieve_rechtspraak(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    if args.mode is RetrieveMode.GAPS:
        # the cited and the referring judgments, of whatever court
        eclis = _gaps.rechtspraak_gaps(store)
        result = RechtspraakRetrievePipeline(store).run(
            courts=[], eclis=eclis, referrals=_gaps.unanswered_referrals(store)
        )
        return _gaps.noted(result, eclis)

    courts = args.court or ([] if args.ecli else list(RECHTSPRAAK_DEFAULT_COURTS))
    date_from = modified_from = None
    if args.mode is RetrieveMode.INCREMENTAL:
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


# ── Staatsblad and Staatscourant ─────────────────────────────────────────────


def staatsblad_args(parser: argparse.ArgumentParser) -> None:
    add_mode_argument(
        parser,
        (RetrieveMode.FROM_GRAPH, RetrieveMode.FULL),
        default=RetrieveMode.FROM_GRAPH,
        help="from-graph (default): the publications the stored BWB toestanden name; "
        "full: every AMvB the SRU lists.",
    )


def retrieve_staatsblad(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    pipeline = StaatsbladRetrievePipeline(store=store)
    if args.mode is RetrieveMode.FULL:
        return pipeline.run_full()
    return pipeline.run_from_bwb_graph(store)


def staatscourant_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--identifiers",
        nargs="*",
        help="Fetch these publications (stcrt-…) as they are.",
    )
    windowed_args(parser)


def retrieve_staatscourant(args: argparse.Namespace) -> PipelineResult:
    pipeline = StaatscourantRetrievePipeline(GraphStore())
    if args.identifiers:
        return pipeline.run(identifiers=args.identifiers)
    if args.mode is RetrieveMode.FULL:
        return pipeline.run_full()
    return pipeline.run(since=_iso_day(args.since))


# ── Tweede Kamer ─────────────────────────────────────────────────────────────


def tk_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit", type=int, default=0, help="At most this many cases (0: every one)."
    )
    parser.add_argument(
        "--replacing",
        action="store_true",
        help="Only the cases that replace another (an amended amendment or motion, "
        "Zaak.VervangenVanuit); with --mode full every one of them, once after the "
        "retrieve began to read that relation.",
    )
    windowed_from_a_day_args(parser)


def retrieve_tk(args: argparse.Namespace) -> PipelineResult:
    since = _TK_EPOCH if args.mode is RetrieveMode.FULL else args.since
    return TKRetrievePipeline(GraphStore()).run(
        since=since, limit=args.limit, replacing=args.replacing
    )


def tk_content_args(parser: argparse.ArgumentParser) -> None:
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
        "--limit",
        type=int,
        default=None,
        help="At most this many papers in this run (the rest in the next).",
    )
    add_mode_argument(
        parser,
        (RetrieveMode.GAPS,),
        default=RetrieveMode.GAPS,
        help="The only mode: the papers of --kind of which no XML is stored yet.",
    )


def retrieve_tk_content(args: argparse.Namespace) -> PipelineResult:
    pipeline = TKContentRetrievePipeline(store=GraphStore())
    return pipeline.run(
        kinds=args.kind or DEFAULT_KINDS, limit=args.limit, dry_run=args.dry_run
    )


def retrieve_tk_document_links(args: argparse.Namespace) -> PipelineResult:
    return TKDocumentLinksRetrievePipeline(GraphStore()).run(
        since=_since_unless_full(args)
    )


def retrieve_tk_case_actors(args: argparse.Namespace) -> PipelineResult:
    return TKCaseActorsRetrievePipeline(GraphStore()).run(
        since=_since_unless_full(args)
    )


def tk_dossiers_args(parser: argparse.ArgumentParser) -> None:
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
    add_mode_argument(
        parser,
        (RetrieveMode.WINDOW, RetrieveMode.GAPS, RetrieveMode.UNVOTED),
        default=RetrieveMode.WINDOW,
        help="gaps: the dossiers the graph names and lacks (those of the publications that "
        "changed an article, and the first reading of a change in the Grondwet), with "
        "their documents; unvoted: only the Besluiten without a vote on an amendment or a "
        "motion (withdrawn, postponed, held, lapsed), since --decisions-since or --since, "
        "else all; the other options are then not used.",
    )


def retrieve_tk_dossiers(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    pipeline = TKDossiersRetrievePipeline(store=store)
    if args.mode is RetrieveMode.GAPS:
        numbers = _gaps.tk_dossier_gaps(store)
        return _gaps.noted(pipeline.run_gaps(numbers), numbers)
    if args.mode is RetrieveMode.UNVOTED:
        return pipeline.run_unvoted(args.decisions_since or args.since)
    return pipeline.run(
        since=args.since,
        decisions_since=args.decisions_since,
        documents_since=args.documents_since,
        commitments_since=args.commitments_since,
        skip_members=args.skip_members,
        skip_decisions=args.skip_decisions,
        skip_documents=args.skip_documents,
        dossier_number=args.dossier_number,
    )


# ── Verdragenbank ────────────────────────────────────────────────────────────


def verdragenbank_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-records", type=int, default=None, help="At most this many treaties."
    )
    add_mode_argument(
        parser,
        (RetrieveMode.FULL, RetrieveMode.GAPS),
        default=RetrieveMode.FULL,
        help="gaps: only when a treaty is referred to that is not loaded (the register "
        "has no fetch per treaty, so it is read again in full).",
    )
    parser.add_argument(
        "--only-stored",
        action="store_true",
        help="only the treaties whose record is stored already (their changes and item "
        "XML); no new treaties",
    )


def retrieve_verdragenbank(args: argparse.Namespace) -> PipelineResult:
    store = GraphStore()
    if args.mode is RetrieveMode.GAPS and not _gaps.verdragenbank_gaps(store):
        return PipelineResult()
    return VerdragenbankRetrievePipeline(store).run(
        max_records=args.max_records, only_stored=args.only_stored
    )
