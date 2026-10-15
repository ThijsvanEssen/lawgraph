from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api import search_terms
from lawgraph.api.dependencies import get_store
from lawgraph.api.params import iso_day
from lawgraph.api.routes.resolve import RESOLVE_MAX_LENGTH
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.api.schemas.search import SearchResponse, SearchResultItem
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries.resolve import NO_MATCH
from lawgraph.db.queries.resolve import resolve as resolve_query
from lawgraph.db.queries.search.clause import Period
from lawgraph.db.queries.search.dispatch import (
    LIVE_STALE_WAIT,
    search_full,
    search_live,
)
from lawgraph.db.queries.search.parser import kept_notation_parser
from lawgraph.db.queries.search.types import SEARCH_TYPES
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
        "fetched. An article is also found by its terms, what the judgments that cite "
        "it call it (`noodweer`: art. 41 Sr, whose words do not hold it; "
        "`lg_article_terms`), as a match on words (0.1), ranked above those that only "
        "hold the word; such a hit has `extra.terms`, the words of `q` it was found "
        "by, which come from the case law, not from the law. A word of `q` that is the "
        "short title or an alias of a law (as the instrument has it, whole, any case "
        "and without accents: `Cbw`, `Sr`, `BW` of every book) also matches each of "
        "its articles, as the name of the law in its `display_name` does (`zorgplicht "
        "cbw`: art. 21 of the Cyberbeveiligingswet), and each dossier the law is "
        "`LEGISLATED_IN` (`cbw`: dossier 36764, the bill that became it; ranked above "
        "a dossier that only holds the word), in full and live search alike. `dossier` "
        "and `dossiers` name the type and are left out of a search of dossiers unless "
        "they are all of `q` (`cbw dossier` asks for the dossier of the Cbw). `extra` "
        "of an article carries `instrument_title` (its law), `heading` and "
        "`division_titles`, of an instrument `short_title`, `aliases`, `kind` and the "
        "dates `date_published`, `date_in_force` and `version_date_in_force` (as "
        "`/api/instruments/{identifier}` gives them; regulations of one title told "
        "apart by them), of a judgment `ecli`, `appno` and `names` (and `person` when "
        "it was found by one), of a document `dossier_number`, of a dossier `number`, "
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
        "left out (`stemming abortus` asks for the votes on abortion). A document hit "
        "has in `extra` its `kind`, `external_id`, `dossier_number`, `sequence` (its "
        "number in the dossier: nr. 12), `number` (as above: `12`, the letter `A` of "
        "an Eerste Kamer paper), `date` (as the source gives it; null when it has "
        "none) and `chamber` (`TK`, `EK`, null for Staatsblad and Staatscourant, as in "
        "`/api/documents`) ; with `resolve=true` also `resolved`, what `/api/resolve` "
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
        "the next search of the same terms finds what it counted meanwhile"
    ),
    tags=["search"],
)
def search(
    q: Annotated[str, Query(min_length=1, description="Search term")],
    store: Annotated[GraphStore, Depends(get_store)],
    types: Annotated[
        list[str],
        Query(description="Entity types to search"),
    ] = _DEFAULT_SEARCH_TYPES,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kind filter (documents and dossiers)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
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
) -> SearchResponse:
    unknown = [t for t in types if t not in SEARCH_TYPES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown types: {', '.join(sorted(set(unknown)))}. "
                f"Allowed: {', '.join(sorted(SEARCH_TYPES))}."
            ),
        )
    requested_types = types or list(SEARCH_TYPES)
    search_terms.COUNTER.add(q)  # the term alone: who asked is not kept

    kind_list = [s.strip() for s in kind.split(",")] if kind else None

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="`from` is after `to`.")
    period = Period(
        iso_day(date_from),
        iso_day(date_to),
    )
    search = search_live if mode == "live" else search_full
    raw, partial = search(
        store,
        q=q,
        types=requested_types,
        kinds=kind_list,
        limit=limit,
        period=period,
    )

    grouped: dict[str, list[SearchResultItem]] = {}
    total = 0
    for type_key, hits in raw.items():
        items = []
        for hit in hits:
            items.append(
                SearchResultItem(
                    id=hit.get("id", ""),
                    key=hit.get("key", ""),
                    collection=hit.get("collection", ""),
                    type=hit.get("type", ""),
                    display_name=hit.get("display_name"),
                    snippet=hit.get("snippet"),
                    score=hit["score"],
                    extra=hit.get("extra") or {},
                    path_props=hit.get("path_props"),
                )
            )
        grouped[type_key] = items
        total += len(items)

    logger.debug("Search '%s' → %d hits across %s", q, total, requested_types)

    return SearchResponse(
        q=q,
        types=requested_types,
        total=total,
        results=grouped,
        partial=dict.fromkeys(sorted(partial), True),
        resolved=_resolved(store, q, mode) if resolve else None,
    )


def _resolved(store: GraphStore, q: str, mode: str = "full") -> ResolveResponse:
    """``/api/resolve`` for *q*; a query too long for it is no citation (kind ``none``).
    While typing (``live``) it takes the parser of citations of the version before at once,
    as the search does (``LIVE_STALE_WAIT``); without one yet (after a start) no citation."""
    if len(q) > RESOLVE_MAX_LENGTH:
        return ResolveResponse(q=q, **NO_MATCH)
    wait = LIVE_STALE_WAIT if mode == "live" else STALE_WAIT
    if kept_notation_parser(store, wait) is None:
        # not there yet (after a start): no citation for now, the search has the words
        return ResolveResponse(q=q, **NO_MATCH)
    with stale_wait(wait):
        return ResolveResponse(q=q, **resolve_query(store, q))
