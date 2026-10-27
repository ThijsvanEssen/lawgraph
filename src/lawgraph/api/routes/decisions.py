"""Decision (vote) endpoints.

GET /api/decisions            — the vote browser
GET /api/decisions/{key}      — one decision with every vote cast on it
GET /api/decisions/{key}/document — the motion or bill it decided on
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import Invalid
from lawgraph.api.params import (
    DOSSIER_NUMBER_PATTERN,
    PageLimit,
    parse_choices,
)
from lawgraph.api.schemas.common import dossier_names_of
from lawgraph.api.schemas.decisions import (
    DecisionDTO,
    DecisionFacets,
    DecisionListResponse,
    DecisionSummaryDTO,
)
from lawgraph.api.schemas.documents import DocumentTextResponse
from lawgraph.core.motion_kinds import MOTION_KINDS
from lawgraph.core.time import iso_day
from lawgraph.core.votes import VOTE_PARAMETER, VoteParameter
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import (
    DecisionFilters,
    decision_document,
    get_decision_detail,
    get_decision_document,
    get_decisions,
    motion_documents,
)
from lawgraph.db.queries.documents import document_xml_retrieval, get_document_links
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.not_found import require
from lawgraph.db.queries.search.clause import queries_words
from lawgraph.db.queries.unlinked_references import reference_counts

router = APIRouter()


@router.get(
    "",
    response_model=DecisionListResponse,
    summary="Decision browser",
    description=(
        "A page of decisions — one per Besluit — newest first, optionally "
        "filtered by kind, outcome, party (and how it voted), chamber, dossier, date "
        "and subject. ``total`` is the absolute count, independent of ``limit``. "
        "``facets`` counts the decisions under the filters: per ``kind`` (without the "
        "kind filter; with how many carried and did not), per outcome ``passed`` "
        "(without the passed filter), per day and per year (under all filters), and with "
        "``party_votes`` how the factions asked voted on them. ``facets=false`` gives "
        "null for ``total`` and ``facets`` and counts nothing: the pages after the first "
        "need neither."
        "\n\n"
        "decisions with every vote cast — per member on a roll-call, per faction "
        "otherwise; the decided motion, amendment or bill with text. The list filters "
        "on `kind` (comma-separated: the `Zaak.Soort` of the case decided as the Kamer "
        "writes it, `Motie`, `Amendement`, `Wetgeving`, `Begroting`, …; see data model "
        "(docs/data-model.md)), `passed`, `party` (the decisions its faction voted on; "
        "with `vote` `voor`/`tegen` the ones it voted that way on; a roll-call has no "
        "faction vote), `chamber` `TK`/`EK` (the votes of the Eerste Kamer: a decision "
        "per vote of its list, with `result` `Aangenomen`/`Verworpen` as it shows it, "
        "`method` as its report names it, `bill_decision` (whether it is the vote that "
        "decided the bill: the list names a vote on a motion by its bill too), `kind` "
        "(of the vote that decided the bill: the kind of its dossier, `Wetgeving`, …; "
        "null for a vote on a motion, which the list names no kind of), and in the "
        "detail `factions_for`, `factions_against`, `factions_noted`, `bill_url`, "
        "`source_url`, `retrieved_on`; no votes per faction, so no `tally`), `dossier` "
        "number, `from` and `to` (the date of the vote, YYYY-MM-DD) and `q` (the "
        "decisions whose subject or kind holds every word of it, in any order and any "
        "case, as `/api/search` finds a vote: its stop words left out unless they are all "
        "of it, a word also by its stem of four characters or more (`afkeuringen`: "
        "afkeuring), a word of the name of a kind of motion (`wantrouwen`) the votes on "
        "those motions too (`motion_kind`); each word from the start of a word, one of "
        "at most four characters as a whole word: `ai` finds AI-modellen, not AIV or "
        "universitaire; `algoritme` algoritmes, not rekenalgoritme; `vertrouwen "
        "opzeggen` the motion over het opzeggen van het vertrouwen; repeated, any of "
        "them: `q=AI&q=kunstmatige intelligentie`, each decision once). The list "
        "holds the decisions with an outcome (`passed` set), and its "
        "facets count those; `unvoted=true` also those that never came to a vote: a "
        "motion or amendment withdrawn, postponed, held or lapsed (`decision_kind` "
        "`Stemmen - ingetrokken`, `- uitstellen`, `- aangehouden`, `- vervallen`), "
        "`passed` null. Each item has `kind` and `decision_kind` (the `BesluitSoort`: "
        "`Stemmen - aangenomen`, `Stemmen - zonder stemming aannemen` for a hamerstuk "
        "without votes, `Stemmen - uitstellen`, whose `passed` is null); `total` is "
        "the matches, independent of `limit`. `facets` counts the decisions under the "
        "filters: `kind` (`value`, `count`, how many `passed` and `rejected` (the rest "
        "have no outcome), most first; without the `kind` filter), `passed` (`value` "
        "`true`/`false`/null, `count`; without the `passed` filter), `days` (`date`, "
        "`count`, how many `passed`, oldest first) and `years` (`year`, `count`, "
        "`passed`, `rejected`, oldest first) under every filter, and `party_votes`: "
        "with `party_votes` (comma-separated faction keys, or `all` for every faction "
        "that voted on one of them; it keeps no decision out, unlike `party`), per "
        "faction by key (`party`, `name` its abbreviation) how it voted on the "
        "decisions under every filter, `voor`, `tegen` and `none` (another choice, or "
        "no vote of the faction: a roll-call vote is one of members), in all, per "
        "`kind` and per `years`; `[]` without it. They are counted on demand and kept "
        "an hour under each filter, whatever the data does; a request waits for them 3 "
        "s at most, then the page comes with `[]` and `partial` true, and a request "
        "after the count has them. The page is read first and alone (in the order of "
        "the list, as far as it goes: `decisions_list_date`); `total` and the other "
        "facets are counted per filter and kept until the decisions change (an hour at "
        "most): a request waits for them 3 s at most, then the page comes whole with "
        "`total` null, empty facets and `partial` true, and a request after the count "
        "has them (the lists the explorer opens, of both Kamers and of the Tweede "
        "Kamer, are counted in the warm-up); `facets=false` gives null for `total` and "
        "`facets` and counts nothing (not `party_votes` either), the choice for the "
        "pages after the first. An item has `display_name` (the heading of the vote, "
        "distinct per motion on one agenda item: `Motie 2024Z17945: …`); list and "
        "detail have `primary_case_kind`, `dossier_numbers` and `chamber` A vote on a "
        "motion has `dictum`, what the motion asks or says as it writes it (from "
        "`verzoekt`, `roept … op`, `spreekt uit`, `draagt … op` or `vraagt` to `en "
        "gaat over tot de orde van de dag`), in the list and the detail; null for any "
        "other vote and for a motion without text. List and detail have `motion` "
        "(`collection`, `key`, `path`), the motion or amendment the vote was taken on: "
        "the oldest paper of the case the vote singled out (`primary_case_kind` "
        "`Motie` or `Amendement`; the paper `/{key}/document` and the dictum come "
        "from), else, for a vote whose `kind` is one, the Kamerstuk it is `ABOUT` (a "
        "vote of the Eerste Kamer on a motion); null for any other vote and for a case "
        "without a paper. The detail has `primary_document` (`id`, `key`, `kind`, "
        "`title`, `number`, `dossier_number`, `date`, `path`), the Kamerstuk the vote "
        "was taken on as `/{key}/document` finds it (of the case it singled out, then "
        "of its other cases, the oldest paper; else the Kamerstuk it is `ABOUT`): the "
        "motion, the amendment or the bill; null without one. A vote of the Tweede "
        "Kamer under a cabinet carries `coalition` (on the list and the detail; "
        "`semantic tk-coalition-votes`): the `cabinet`, the seats `coalition_for`, "
        "`coalition_against`, `opposition_for`, `opposition_against` (a faction with "
        "its seats that day, a member of a roll call as one), `pattern` (`together`, "
        "`split`, `wissel`: split, and the side with the most coalition seats lost, a "
        "wisselmeerderheid), `carried` (passed with the coalition's seats alone more "
        "than half cast) and `decisive` (the opposition alone would have decided "
        "otherwise); null without a cabinet or a coalition vote and in the Eerste "
        "Kamer. `coalition=together|split|wissel|carried|decisive` filters on it, and "
        "`facets.coalition` counts each under every filter but its own; "
        "`facets.coalition_cabinets` gives per cabinet (`cabinet`, `name`, newest "
        "first) under every filter, a topic of the Overzicht being its words, Kamer "
        "and period, its `votes` and how many were `together`, `split`, `wissel`, "
        "`carried` and `decisive`. A vote on a motion of censure (motie van afkeuring) "
        "or of no confidence (motie van wantrouwen) has `motion_kind` `censure` or "
        "`no_confidence` (on the list and the detail; `semantic tk-motion-kinds`, from the "
        "fixed wording of its subject), null for any other; "
        "`motion_kind=censure,no_confidence` keeps those votes, and `facets.motion_kind` "
        "counts them per kind (`value`, `count`, `passed`, `rejected`) under every filter "
        "but its own"
    ),
    tags=["decisions"],
)
def list_decisions(
    store: Annotated[GraphStore, Depends(get_store)],
    kind: Annotated[
        str | None,
        Query(
            description="Comma-separated kinds (``Zaak.Soort`` as the Kamer writes it): "
            "``Motie``, ``Amendement``, ``Wetgeving``, ..."
        ),
    ] = None,
    passed: Annotated[
        bool | None, Query(description="Only decisions that carried, or did not.")
    ] = None,
    party: Annotated[
        str | None, Query(description="Only decisions this party voted on.")
    ] = None,
    vote: Annotated[
        VoteParameter | None,
        Query(description="With `party`: only decisions it voted for, or against."),
    ] = None,
    chamber: Annotated[str | None, Query(description="'TK' or 'EK'.")] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="Only decisions on this dossier number, e.g. 29684.",
            pattern=DOSSIER_NUMBER_PATTERN,
        ),
    ] = None,
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Voted on or after this date, YYYY-MM-DD."),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Voted on or before this date, YYYY-MM-DD."),
    ] = None,
    q: Annotated[
        list[str] | None,
        Query(
            description="Words of the subject or kind, every one, in any order and any "
            "case: each from the start of a word, one of at most four characters as a "
            "whole word. Repeat it for decisions that hold any of them "
            "(``q=AI&q=kunstmatige intelligentie``)."
        ),
    ] = None,
    party_votes: Annotated[
        str | None,
        Query(
            description="Comma-separated faction keys, or ``all`` for every faction "
            "that voted on one: ``facets.party_votes`` says how each voted on the "
            "decisions under the filters (``voor``, ``tegen``, ``none``; in all, per "
            "kind and per year). Keeps no decision out, unlike ``party``."
        ),
    ] = None,
    coalition: Annotated[
        Literal["together", "split", "wissel", "carried", "decisive"] | None,
        Query(
            description="Only the votes of the Tweede Kamer on which the coalition voted "
            "`together`, `split` (no wisselmeerderheid) or as a `wissel`, or which it "
            "`carried` or was `decisive` on."
        ),
    ] = None,
    motion_kind: Annotated[
        str | None,
        Query(
            description="Comma-separated kinds of motion: ``censure`` (motie van "
            "afkeuring), ``no_confidence`` (motie van wantrouwen). Only the votes on such a "
            "motion."
        ),
    ] = None,
    unvoted: Annotated[
        bool,
        Query(
            description="Also the decisions that never came to a vote (withdrawn, "
            "postponed, held, lapsed: ``passed`` null, the reason in ``decision_kind``); "
            "without it only those with an outcome, and the facets count those."
        ),
    ] = False,
    limit: PageLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    facets: Annotated[
        bool, Query(description="Count the total and the facets.")
    ] = True,
) -> DecisionListResponse:
    if vote is not None and not party:
        raise Invalid("vote", "needs `party`.")
    filters = DecisionFilters(
        kinds=parse_choices(kind, None, "kind"),
        passed=passed,
        faction=party,
        choice=VOTE_PARAMETER[vote] if vote else None,
        chamber=chamber,
        dossier_number=dossier,
        from_date=iso_day(date_from),
        to_date=iso_day(date_to),
        q=queries_words(store, q or ()),
        faction_votes=tuple(
            key.strip() for key in (party_votes or "").split(",") if key.strip()
        ),
        coalition=coalition,
        unvoted=unvoted,
        motion_kinds=parse_choices(motion_kind, MOTION_KINDS, "motion_kind"),
    )
    raw = get_decisions(store, filters, limit=limit, offset=offset, facets=facets)
    names = load_dossier_names(store)
    return DecisionListResponse(
        total=raw.get("total"),
        items=[
            DecisionSummaryDTO(
                **row,
                dossiers=dossier_names_of(row.get("dossier_numbers") or [], names),
            )
            for row in raw.get("items") or []
        ],
        facets=DecisionFacets(**(raw.get("facets") or {})) if facets else None,
        partial=bool(raw.get("partial")),
    )


@router.get(
    "/{key}",
    response_model=DecisionDTO,
    summary="Decision detail",
    description=(
        "One decision with every vote cast on it — per member on a roll-call, "
        "per faction otherwise — the Kamerstuk it was taken on (``primary_document``) and, "
        "of a motion, its dictum."
    ),
    tags=["decisions"],
)
def get_decision(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DecisionDTO:
    doc = require(get_decision_detail(store, key), "Decision", key)
    ((motion, dictum),) = motion_documents(store, [{**doc["props"], "id": doc["id"]}])
    return DecisionDTO.from_document(
        doc,
        load_dossier_names(store),
        motion=motion,
        dictum=dictum,
        document=decision_document(store, doc),
    )


@router.get(
    "/{key}/document",
    response_model=DocumentTextResponse,
    summary="The document behind a decision",
    description=(
        "The motion, amendment or bill this decision was about, with its full text."
    ),
    tags=["decisions"],
)
def get_decision_document_route(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DocumentTextResponse:
    decision = require(get_decision_detail(store, key), "Decision", key)
    document = require(
        get_decision_document(store, decision), "Document of decision", key
    )
    return DocumentTextResponse.from_document(
        document,
        get_document_links(store, document["id"]),
        references=reference_counts(store, document["id"]),
        retrieval=document_xml_retrieval(store, document),
    )
