from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.db import GraphStore
from lawgraph.db.queries.resolve import resolve as resolve_query

router = APIRouter()

# The longest query read as a citation or a name; a longer one is words for the search.
RESOLVE_MAX_LENGTH = 200


@router.get(
    "",
    response_model=ResolveResponse,
    summary="Resolve a citation, identifier or law name to one node",
    description=(
        "Reads `q` as a citation (`art. 6:162 BW`, `artikel 287 Sr`, `Sr 287`), an "
        "identifier (ECLI, BWB id, CELEX id), a Kamerstuk (`36327`, `36327-3`, "
        "`Kamerstukken II 2020/21, 36327, nr. 3`) or the name of a law, and answers with "
        "the one best match (`id`, `key`, `collection`) and up to five alternatives. "
        "A citation that leaves the book of the Burgerlijk Wetboek open (`art. 3 BW`) "
        "has no match: its alternatives are the article in every book, in book order. "
        "`confidence` says how sure the match is. Nothing that fits answers 200 with "
        "kind `none` and no match: the query is then words for `/api/search`."
        "\n\n"
        "the one node a citation, identifier or law name names (an article also "
        "without the word artikel, law first or number first: `Sr 287`, `6:162 BW`, "
        "`287 Sr`; a paper by its number in the Tweede Kamer, `Kamerstukken II "
        "2025/26, 36799, nr. 3`, or by its letter in the Eerste Kamer, `Kamerstukken I "
        "2025/26, 36799, A`; a number right behind the dossier number and a hyphen is "
        "the subdossier with that suffix when there is one (`21501-31`), else the "
        "paper (`36799-3`); a publication, `Staatsblad 2026, 94`, `Stb. 2026, 94`, "
        "`Stcrt. 2026, nr. 12345` or `Trb. 2018, 201`, as the `instrument` it is): "
        "`kind` (`article`, `instrument`, "
        "`judgment`, `dossier`, `document`, `commitment`, `faction`, `member`, or "
        "`none`), `match` (`id`, `key`, `collection`, `kind`, `display_name`, "
        "`title` as `/api/nodes` gives it, `confidence`), `confidence`, "
        "`alternatives` (up to five, same shape, best first; an article, also a stub "
        "without a name of its own, named as it is cited: `Art. 7:162 BW`), "
        "`alternatives_total` (how many alternatives were found), `qualifier` "
        "(`derde lid` of `artikel 287, derde "
        "lid, Sr`) and `notation`, the notation `q` is (`kind` and its `parts`), with a "
        "match or without one (`TZ202603-130` that names no commitment of the graph), "
        "null for words. A query that is the whole abbreviation, name or alias of a "
        "faction, or the whole name of a member, any case and without accents, is that "
        "faction or member (`VVD`, `dilan yesilgoz-zegerius`; confidence 0.9; of "
        "several factions the seated one, then the most seats), before a law of the "
        "same name, which is then an alternative (`VVD` is also the abbreviation of "
        "the Warenwetregeling Vrijstelling vitamine D). A citation of the Burgerlijk "
        "Wetboek that leaves the book open (`art. 3 BW`, `3 BW`, `artikel 162 BW`) is "
        "a choice: `kind` `article`, `match` null, `confidence` 0.5 and as "
        "`alternatives` the article of that number in every book that has one, the "
        "most cited first, of as many in the order of the books (`artikel 162 BW`: "
        "Boek 6 first; up to ten), the `qualifier` for each; one book that has it is "
        "the match. A book and a number without a law (`art. 6:162`) is that article "
        "of the book, or of a law whose own number it is (`art. 8:69`: the Awb's 8:69 "
        "and Boek 8 BW article 69, a choice, the most cited first); `boek 6 art 162` "
        "is article 162 of book 6. Nothing that fits is 200 with `kind` `none` and "
        "`match` null, so the caller searches the words instead; only an empty or "
        "over-long `q` is 422"
    ),
    tags=["resolve"],
)
def resolve(
    q: Annotated[
        str,
        Query(
            min_length=1, max_length=RESOLVE_MAX_LENGTH, description="Citation or name"
        ),
    ],
    store: Annotated[GraphStore, Depends(get_store)],
) -> ResolveResponse:
    return ResolveResponse(q=q, **resolve_query(store, q))
