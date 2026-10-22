from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api import search_terms
from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import Invalid
from lawgraph.api.params import TopLimit, parse_choices
from lawgraph.api.routes.resolve import RESOLVE_MAX_LENGTH
from lawgraph.api.schemas.common import judgment_cite_dto
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.api.schemas.search import (
    SearchedDTO,
    SearchResponse,
    SearchResultItem,
    SignedForDTO,
)
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.concepts import Concept, concept_named
from lawgraph.core.logging import get_logger
from lawgraph.core.motion_kinds import MOTION_KINDS
from lawgraph.core.names import article_cite
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.resolve import CONFIDENCE_NAME, NO_MATCH
from lawgraph.db.queries.resolve import resolve as resolve_query
from lawgraph.db.queries.search.clause import Period, query_words
from lawgraph.db.queries.search.dispatch import (
    LIVE_STALE_WAIT,
    search_full,
    search_live,
    signed_of,
)
from lawgraph.db.queries.search.parser import kept_notation_parser
from lawgraph.db.queries.search.ranking import SCORE_IDENTIFIER, exact_hit
from lawgraph.db.queries.search.searched import SEARCHED
from lawgraph.db.queries.search.signers import Signed
from lawgraph.db.queries.search.types import SEARCH_TYPES, SEARCHES, hit_by_key
from lawgraph.db.version_cache import STALE_WAIT, stale_wait

router = APIRouter()
logger = get_logger(__name__)

_DEFAULT_SEARCH_TYPES = sorted(SEARCH_TYPES)


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search across several entity types",
    description=(
        "Searches articles, judgments, dossiers and documents. Use `types` to "
        "restrict the search to specific collections and `kind` to facet on "
        "document or dossier kinds. Every hit has a `score` between 0 and 1, its rank "
        "tier for the query: the query is an identifier of the hit (1), its whole "
        "name (0.75), the start of its name (0.5), part of its name (0.25) or the hit "
        "matched on words only (0.1). Hits of a type come best score first. With "
        "`resolve=true` the answer also holds `resolved`, what `/api/resolve` answers "
        "for `q`: one request for a search box that goes to the node a citation names "
        "and lists the hits otherwise."
        "\n\n"
        "text search over `types` (`articles`, `cabinets`, `commitments`, "
        "`committees`, `decisions`, `documents`, `dossiers`, `factions`, "
        "`instruments`, `judgments`, `members`; all by default), `kind`, `limit`, and "
        "a period `from`, `to` (YYYY-MM-DD, both days in it, either open; 422 for "
        "`from` after `to`): each hit by a date of its own, in full and live search "
        "alike: a judgment the day of its decision (`date_eff`), a paper its date, a "
        "dossier the day it was opened, a vote its date, a commitment the day it was "
        "made, a law the day it came into force (`date_in_force`), an article the day "
        "its law came into force; a type without a date of its own (a member, a "
        "faction, a committee, a cabinet) finds nothing within a period. A citation in "
        "`q` (`art. 6:162 BW`, `artikel 287 Sr`, `Sr 287`, a full ECLI) puts its "
        "article or judgment first, and so does the whole name of a judgment "
        "(`Urgenda`, `Lindenbaum/Cohen`: one of its `names`, any case). Every hit has "
        "a `score`, its rank tier for `q`: an identifier of the hit (1), its whole "
        "name (0.75), the start of its name (0.5), every word of `q` in its name "
        "(0.25), a match on words only (0.1), compared in lower case and without "
        "accents (`yesilgoz` is part of `Yeşilgöz-Zegerius`); a type lists its hits "
        "best first, ties in database order. The names of a hit are its "
        "`display_name`, citation title, the `heading` of an article and the `aliases` "
        "of an instrument (`BW`, `Boek 6 BW`, `6 BW`: 0.75, before the words); `q` "
        "inside the title of a division an article stands in counts as part of its "
        "name (0.25). Scores compare across types: a heading or alias that is `q` "
        "(0.75) outranks a judgment that only holds its words (0.1). A word of `q` "
        "also finds its plural or singular where the last consonant changes between "
        "them, which stem apart (`huurprijs` and `huurprijzen`, `brief` and "
        "`brieven`). Within a type the database orders by BM25 before the `limit` (on "
        "a large table its statistics, the number of rows and the mean length of a "
        "field, are an estimate from a fixed sample, at most 6 hours old; the number "
        "of rows that hold a common word is the planner's estimate from its "
        "statistics, a rare word is counted, and a count that takes over 5 s weighs "
        "its terms as held by every row; a word matches the start of a value or a part "
        "of it from three characters, the start in any case and, in a name or title, "
        "without accents), with a word in a heading (x4), a division title (x1.5), a "
        "display name (x2), an alias or short title (x3) weighing more than one in a "
        "text; an instrument whose alias or short title is the whole of `q` is always "
        "fetched. Of the articles the database orders by their tier before BM25, as far "
        "as the article says it (named by its terms, a heading or display name that "
        "starts with `q`, every word of `q` in its heading or the title of a division it "
        "stands in), so that the best tiers are among the hits however few are asked, "
        "while typing too (`onrechtmatige daad`: art. 6:162 BW, in the title "
        "Onrechtmatige daad, before the articles of the Wet conflictenrecht onrechtmatige "
        "daad). An article is also found by its terms, what the judgments that cite "
        "it call it (`noodweer`: art. 41 Sr, whose words do not hold it; "
        "`lg_article_terms`), as a match on words (0.1), ranked above those that only "
        "hold the word; such a hit has `extra.terms`, the words of `q` it was found "
        "by, which come from the case law, not from the law. An article of which every "
        "word of `q` is a strong term (a good share of the judgments that use the word "
        "cite it, and few judgments cite it at all: `verjaring`, art. 3:310 BW) scores "
        "as a whole name (0.75), the best by its words first; a word in more than one in "
        "50 summaries names no article and is left out of that (`ontslag op staande "
        "voet`: art. 7:677 BW, named by its other words). A word of `q` that is the "
        "short title or an alias of a law (as the instrument has it, whole, any case "
        "and without accents: `Cbw`, `Sr`, `BW` of every book) also matches each of "
        "its articles, as the name of the law in its `display_name` does (`zorgplicht "
        "cbw`: art. 21 of the Cyberbeveiligingswet), and each dossier the law is "
        "`LEGISLATED_IN` (`cbw`: dossier 36764, the bill that became it; ranked above "
        "a dossier that only holds the word), in full and live search alike. `dossier` "
        "and `dossiers` name the type and are left out of a search of dossiers unless "
        "they are all of `q` (`cbw dossier` asks for the dossier of the Cbw). `extra` "
        "of an article carries `instrument_title` (its law), `instrument_abbreviation`, "
        "`heading` and `division_titles` (its `display_name` the article as it is "
        "cited: `Art. 6:162 BW`), of an instrument `short_title`, `aliases`, `kind` and the "
        "dates `date_published`, `date_in_force` and `version_date_in_force` (as "
        "`/api/instruments/{identifier}` gives them; regulations of one title told "
        "apart by them); an article and an instrument `expired_on`, the first day it no "
        "longer holds (of an article the earlier of its law's and its own end, docs/api.md "
        '"Validity"): one expired by today comes after every hit of its score that '
        "holds, not left out; of a judgment `ecli`, `appno`, `names` and `cite` (as "
        "`/api/judgments` gives it; and `person` when it was found by one), of a "
        "document `dossier_number`, of a dossier `number`, "
        "`kind`, `current_phase`, `closed`, `outcome` and `short_title` (the name it "
        "goes by, as `/api/dossiers` gives it: `Wet betaalbare huur`; null without "
        "one). A judgment is also found by a person it names (`lg_judgment_persons`: a "
        "party not anonymised, whoever acts for a party) when every word of `q` is a "
        "word of that one name, whole (while typing, `mode=live`, the last word by its "
        "start): `R. van Gelder`, `Van Gelder` and `mr. drs. R. van Gelder` find `mr. "
        "drs. R. van Gelder`, `Vermeulen` finds `mr. I.T.F. Vermeulen`, `college van "
        "gedeputeerde staten van Zuid-Holland` finds that party; at least one word of "
        "three characters or more that is no title, article or particle (`van`, `mr`); "
        "the newest first of the first 2,000 names found. Such a hit has "
        "`extra.person` (`name` as written, `role`: the party's role, or `advocaat`, "
        "`gemachtigde`, `raadsman` of who acts for one, and `party`: the alias or name "
        "of the party they act for, null for a party) and scores 0.25 when `q` is all "
        "of the name but its titles, initials, articles and particles, else 0.1 after "
        "the judgments found by their words. A member is found by every word of its "
        "names (its name, party and the factions of its timeline), a faction by its "
        "name, abbreviation and aliases; a word without accents or in capitals finds a "
        "name with them (`yesilgoz`: Yeşilgöz; of a member in its own name only; a "
        "member without a role, `extra.has_role` false, after every member with one, "
        "whatever its score). A cabinet is found by every word of its name (`Rutte`, "
        "`kabinet Schoof`), newest first, with `from_date` and `to_date` in `extra`; a "
        "commitment by every word of its text or its number (`TZ202609-011`), newest "
        "first, with `number`, `made_on`, `status`, `minister_name`, `cabinet` and "
        "`ministry` in `extra`. A vote (`decisions`) by every word of what was voted "
        "on (`subject`) or its `kind` (`Motie`, `Wetgeving`), newest first, with "
        "`date`, `kind`, `passed`, `chamber` and `dossier_numbers` in `extra`; "
        "`stemming`, `stemmingen`, `besluit` and `besluiten` name the type and are "
        "left out (`stemming abortus` asks for the votes on abortion). Words of `q` that "
        "are the abbreviation, name or alias of a faction (of either chamber, past ones "
        "too; not when they are part of the name of a member, nor all of `q`) are no words "
        "of the search of the papers and the votes: their hits are signed for it (a paper "
        "by one of its Kamerleden for it, a vote on such a paper), and "
        "`searched.<type>.signed_for` names it (`motie stikstof VVD`). A document hit "
        "has in `extra` its `kind`, `external_id`, `dossier_number`, `sequence` (its "
        "number in the dossier: nr. 12), `number` (as above: `12`, the letter `A` of "
        "an Eerste Kamer paper), `date` (as the source gives it; null when it has "
        "none), `chamber` (`TK`, `EK`, null for Staatsblad and Staatscourant, as in "
        "`/api/documents`) and `dossier_short_title` (the name its dossier goes by, as "
        "`/api/dossiers` gives it; null without one); with `resolve=true` also "
        "`resolved`, what `/api/resolve` "
        "answers for `q` (kind `none` for a query over 200 characters), null without "
        "it: a search box resolves and searches in one request. `mode=live` (while "
        "typing; `full` is the default) answers all types within 250 ms together (a "
        "type that waited for a thread has what is left): a type not done by then is "
        'empty and named in `partial` (`{"judgments": true}`; a type not cut off is '
        "not in it); nothing is ranked by its words (no BM25): each word of `q` is a "
        "word of a field (every word it holds: `20/325` both 20 and 325), a whole "
        "value (a number, an identifier) or, from three characters, the start of a "
        "word of a name or title (`stik`: Stikstofwet; not `tikst`, which the full "
        "search finds), and of the first 2,000 rows found those whose name or title "
        "starts with `q` come first, then the most cited articles, the laws with the "
        "most articles, the dossiers with the latest activity and the newest papers; "
        "the judgments are found without ranking their summaries: by ECLI, by a part "
        "of a name (`Urgenda`), or by every word of three characters or more in the "
        "display name (court, date, case number), the most cited first, and when none "
        "does (a subject, `onrechtmatige daad`) the newest that hold the words "
        "(summary, name, display name; of the first 2,000 found, without a rank); a "
        "query of fewer than three characters finds no judgment. The full search ranks "
        "each type within 3 s: a type that takes longer answers what its live search "
        "finds (within 1 s more; for judgments that no name or display name holds: the "
        "newest that hold the words, of the first 2,000 found, without a rank) and is "
        "named in `partial` too, instead of the request answering 503 at its deadline; "
        "the next search of the same terms finds what it counted meanwhile. "
        "`searched` says per type of `types` what its search reads: `fields` (`title`, "
        "`name`, `number`, `summary`, `text`, `kind`) and `completeness.text`, `none` "
        "for a type whose text it does not read (judgments, documents)."
        "\n\n"
        "The stop words of `q` (the Dutch stop words of PostgreSQL's Snowball dictionary: "
        "`wat`, `is`, `de`, `van`, `mijn`) are no words of the search, unless they are all of "
        "it: `words` are those searched, `left_out` the others (`wat is de opzegtermijn van "
        "mijn huurcontract` searches `opzegtermijn huurcontract`). When no hit of any type "
        "holds every word of two or more, the full search (not `mode=live`) is asked again for "
        "the hits that hold one at least (of a ranked type those with more first; not of a "
        "citation, `Kamerstuk 35925 VI nr. 5`) and `matched` is `any`, else `all`. `toezegging`"
        " and `toezeggingen` name the type of a commitment and are left out of its search "
        "(`toezeggingen pensioenen`); a word of a commitment, a vote or a cabinet also finds "
        "the forms of its stem of four characters or more (`pensioenen`: nabestaandenpensioen)."
        " A word of the name of a kind of motion (`wantrouwen` of motie van wantrouwen, "
        "`afkeuring` of motie van afkeuring; `motion_kind`, `semantic tk-motion-kinds`) also "
        "finds the motions of that kind and the votes on them, whose subject does not hold it "
        "(`het opzeggen van het vertrouwen`), a motion above those that only hold the word; "
        "`motion_kind` keeps the papers and the votes to those motions. An LJN (`LJN AU3313`, "
        "`AU3313`: the number of the ECLI of a decision before 2013) is the judgment whose ECLI"
        " ends in it, as an ECLI is. A member is named whole by the name without the names or "
        "initials before it (`Rutte`: Mark Rutte, 0.75, before the Besluit archief Rutten that "
        "holds it). `exact` per hit says whether `q` names it as the one thing it is (its "
        "citation, ECLI, LJN, number, the abbreviation or whole title of a law, the name of a "
        "judgment, the whole name of a member, faction, committee or cabinet), never by a "
        "heading or words; `best` is the id of what a search box opens on Enter: the match of "
        "`resolved` of confidence 0.9 or more, else the hit of a concept, else the one "
        "`exact` hit, else null "
        "(`huurverhoging`: no hit it names, however its words match)."
        "\n\n"
        "A query that is a term of the curated list of concepts (`wanprestatie`, `ontslag "
        "op staande voet`, `GDPR`, `minimum wage`; the whole query or its words without its "
        'stop words, any case, without accents and punctuation; docs/api.md "Concepts") '
        "has the article or law the term is about first among the hits of its type, score "
        "1, `exact`, with `concept` the term (not with a period, nor when its type is not "
        "in `types`); it is `best` unless `resolved` names something with confidence 0.9 "
        "or more."
    ),
    tags=["search"],
)
def search(
    q: Annotated[
        str,
        Query(min_length=1, max_length=RESOLVE_MAX_LENGTH, description="Search term"),
    ],
    store: Annotated[GraphStore, Depends(get_store)],
    types: Annotated[
        list[str],
        Query(description="Entity types to search"),
    ] = _DEFAULT_SEARCH_TYPES,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kind filter (documents and dossiers)"),
    ] = None,
    limit: TopLimit = 20,
    resolve: Annotated[
        bool, Query(description="Also resolve `q`, as `/api/resolve` does")
    ] = False,
    mode: Annotated[
        Literal["full", "live"],
        Query(
            description=(
                "`live` while typing: all types within 250 ms, cut off types in `partial`, "
                "nothing ranked by its words (a word, or the start of a word of a name or "
                "title), the judgments by ECLI, name and display name (court, date, case number), "
                "the most cited first, and only from three characters; `full` (the "
                "default) ranks everything, a type within 3 s: past it, its `live` hits "
                "and the type in `partial`"
            )
        ),
    ] = "full",
    date_from: Annotated[
        dt.date | None,
        Query(
            alias="from",
            description="Hits dated on or after this day, YYYY-MM-DD: each by a date of its "
            "own; a type without one finds nothing with a period.",
        ),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Hits dated on or before this day, YYYY-MM-DD."),
    ] = None,
    motion_kind: Annotated[
        str | None,
        Query(
            description="Comma-separated kinds of motion: `censure` (motie van "
            "afkeuring), `no_confidence` (motie van wantrouwen). Of the papers and the "
            "votes only those motions and the votes on them."
        ),
    ] = None,
) -> SearchResponse:
    unknown = [t for t in types if t not in SEARCH_TYPES]
    if unknown:
        raise Invalid(
            "types",
            f"unknown {', '.join(sorted(set(unknown)))}. "
            f"Allowed: {', '.join(sorted(SEARCH_TYPES))}.",
        )
    requested_types = types or list(SEARCH_TYPES)
    if resolve and mode == "live":
        # once per query: of its lanes only the first resolves, and "Meer …" asks it again
        search_terms.COUNTER.add(q)  # the term alone: who asked is not kept

    kind_list = [s.strip() for s in kind.split(",")] if kind else None

    if date_from and date_to and date_from > date_to:
        raise Invalid("from", "after `to`.")
    period = Period(
        iso_day(date_from),
        iso_day(date_to),
    )
    motion_kinds = parse_choices(motion_kind, MOTION_KINDS, "motion_kind")
    search = search_live if mode == "live" else search_full
    words = query_words(store, q)
    signed = signed_of(store, q, requested_types, words)
    asked: dict[str, Any] = {
        "q": q,
        "types": requested_types,
        "kinds": kind_list,
        "limit": limit,
        "period": period,
        "signed": signed,
        "words": words,
        "motion_kinds": list(motion_kinds) if motion_kinds else None,
    }
    raw, partial = search(store, **asked)
    any_word = (
        mode == "full"
        and not any(raw.values())
        and not partial
        and len(words.words) > 1
    )
    if any_word:
        # no hit holds every word: those that hold one at least, said in ``matched``;
        # not while typing, where a word not yet typed whole holds nothing yet
        raw, partial = search(store, **asked, any_word=True)
        any_word = any(raw.values())

    names = load_dossier_names(store) if "documents" in raw else {}
    grouped = {t: [_item(q, hit, names) for hit in hits] for t, hits in raw.items()}
    named = None if period else concept_named(q, words.words)
    concept = _concept_item(store, q, named, requested_types) if named else None
    if concept is not None:
        others = [
            i for i in grouped.get(concept.collection, []) if i.key != concept.key
        ]
        grouped[concept.collection] = [concept, *others][:limit]
    total = sum(len(items) for items in grouped.values())

    logger.debug("Search '%s' → %d hits across %s", q, total, requested_types)
    resolved = _resolved(store, q, mode) if resolve else None

    return SearchResponse(
        q=q,
        types=requested_types,
        total=total,
        results=grouped,
        partial=dict.fromkeys(sorted(partial), True),
        searched={
            t: SearchedDTO(**SEARCHED[t], signed_for=_signed_for(t, signed))
            for t in requested_types
        },
        resolved=resolved,
        words=words.words,
        left_out=words.left_out,
        matched="any" if any_word else "all",
        best=_best(grouped, resolved, concept),
    )


def _concept_item(
    store: GraphStore, q: str, named: Concept, types: list[str]
) -> SearchResultItem | None:
    """The article or law of the concept *q* names (``core.concepts``) as a hit of score 1,
    ``exact``, with ``concept`` its term; None when its type is not searched or the graph
    does not have it."""
    if named.collection not in types:
        return None
    hit = hit_by_key(store, named.collection, named.key)
    if hit is None:
        return None
    item = _item(q, {**hit, "score": SCORE_IDENTIFIER, "exact": True}, {})
    return item.model_copy(update={"concept": named.term})


# A match of ``/api/resolve`` this sure is what the query names (``resolve.CONFIDENCE_NAME``:
# a law, faction or member by its whole name or abbreviation; a citation, an identifier).
BEST_CONFIDENCE = CONFIDENCE_NAME


def _best(
    grouped: dict[str, list[SearchResultItem]],
    resolved: ResolveResponse | None,
    concept: SearchResultItem | None = None,
) -> str | None:
    """The id of what the query names exactly: the match of *resolved* of
    ``BEST_CONFIDENCE`` or more (what the sources name: a citation, a law by its
    abbreviation), else the hit of the *concept* it names (``_concept_item``), else the one
    hit that is ``exact``; None when there is none or more than one (``BW``: every book),
    however well the words match."""
    match = resolved.match if resolved else None
    if match is not None and resolved and resolved.confidence >= BEST_CONFIDENCE:
        return match.id
    if concept is not None:
        return concept.id
    exact = {hit.id for hits in grouped.values() for hit in hits if hit.exact}
    return exact.pop() if len(exact) == 1 else None


def _signed_for(table: str, signed: Signed | None) -> list[SignedForDTO]:
    """The factions the query names, of a type kept to the hits signed for them."""
    if not signed or not SEARCHES[table].signatures:
        return []
    return [
        SignedForDTO(words=s.words, name=s.name, factions=s.factions) for s in signed.by
    ]


def _resolved(store: GraphStore, q: str, mode: str = "full") -> ResolveResponse:
    """``/api/resolve`` for *q*. While typing (``live``) it takes the parser of citations of
    the version before at once, as the search does (``LIVE_STALE_WAIT``); without one yet
    (after a start) no citation."""
    wait = LIVE_STALE_WAIT if mode == "live" else STALE_WAIT
    if kept_notation_parser(store, wait) is None:
        # not there yet (after a start): no citation for now, the search has the words
        return ResolveResponse(q=q, **NO_MATCH)
    with stale_wait(wait):
        return ResolveResponse(q=q, **resolve_query(store, q))


def _item(
    q: str, hit: dict[str, Any], names: dict[str, dict[str, Any]]
) -> SearchResultItem:
    """A hit of *q* as the answer gives it, after its rank, ``exact`` when *q* names it
    (``ranking.exact_hit``): an article named as it is cited
    (``core.names.article_cite``), a judgment with its ``cite`` in ``extra``, a paper
    with the name its first dossier goes by (``dossier_short_title``, by *names*:
    ``load_dossier_names``)."""
    extra = dict(hit.get("extra") or {})
    display_name = hit.get("display_name")
    if hit.get("collection") == COLLECTION_JUDGMENTS:
        cite = judgment_cite_dto(
            {**(hit.get("cite_props") or {}), "ecli": extra.get("ecli")}
        )
        extra["cite"] = cite.model_dump() if cite else None
    if hit.get("collection") == COLLECTION_DOCUMENTS:
        dossier = names.get(str(extra.get("dossier_number") or "")) or {}
        extra["dossier_short_title"] = dossier.get("short_title")
    if hit.get("collection") == COLLECTION_ARTICLES:
        display_name = (
            article_cite(
                {
                    "bwb_id": extra.get("bwb_id"),
                    "article_number": extra.get("article_number"),
                    "display_name": display_name,
                    "instrument_abbreviation": extra.get("instrument_abbreviation"),
                    "instrument_citation_title": extra.get("citation_title"),
                }
            )
            or display_name
        )
    return SearchResultItem(
        id=hit.get("id", ""),
        key=hit.get("key", ""),
        collection=hit.get("collection", ""),
        type=hit.get("type", ""),
        display_name=display_name,
        snippet=hit.get("snippet"),
        score=hit["score"],
        exact=exact_hit(q, hit),
        extra=extra,
        path_props=hit.get("path_props"),
    )
