"""A faction a query names (``signed_for``): "motie stikstof VVD" asks for the motions on
stikstof that the VVD submitted, not for those whose title holds "VVD". The words that are
the abbreviation, name or alias of a faction (of the ``factions``, the Tweede Kamer's and the
Eerste Kamer's, past ones too) keep the hits of a type with signatures
(``SearchType.signatures``) to those signed for it: a paper one of its Kamerleden signed for
it, a vote on such a paper, as the ``faction`` filter of the feed reads them; and are no
words of their search. Not a word that is part of the name of a member: a faction named
after its one member (Omtzigt, Krol) is the name a title holds ("Motie van het lid
Omtzigt"), and the member signed for other factions too. A query that is a faction and
nothing else asks for the faction: then nothing is a filter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_FACTIONS, COLLECTION_MEMBERS
from lawgraph.db import GraphStore
from lawgraph.db.queries._json_sql import array_or_empty
from lawgraph.db.queries.search.ranking import folded
from lawgraph.db.version_cache import cached


@dataclass(frozen=True)
class SignedFor:
    """The words of a query that name a faction (*words*, lower case as typed), the name the
    answer says (*name*: the abbreviation, else the name, of the faction of the Tweede
    Kamer first), the *factions* of that name (keys) and the Fractie records a signature
    names them by (*records*)."""

    words: str
    name: str
    factions: list[str]
    records: list[str]


@dataclass(frozen=True)
class Signed:
    """A query without the words that name a faction (*words*) and the factions they name
    (*by*, in the order of the query)."""

    words: list[str]
    by: list[SignedFor]


@dataclass(frozen=True)
class Faction:
    """A faction as a query names it: its key, the name the answer says, its Fractie
    records and whether it is of the Eerste Kamer."""

    key: str
    name: str
    records: tuple[str, ...]
    ek: bool


_FACTIONS = f"""
SELECT key, lg_str(props -> 'abbreviation') AS abbreviation, lg_str(props -> 'name') AS name,
       props -> 'aliases' AS aliases, props -> 'external_ids' AS external_ids,
       lg_str(props -> 'external_id') AS external_id, lg_str(props -> 'chamber') AS chamber
FROM {COLLECTION_FACTIONS}
ORDER BY key
"""
# The name of every member, folded, its words split as ``_words`` splits them.
_MEMBERS = f"SELECT lg_fold(name) FROM {COLLECTION_MEMBERS} WHERE name IS NOT NULL"


def _words(name: str) -> str:
    """*name* folded, its runs of letters and digits each between single spaces: a run of
    words is in it as `` w1 w2 ``."""
    return f" {' '.join(w for w in re.split(r'[^0-9a-z]+', folded(name)) if w)} "


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _factions(store: GraphStore) -> dict[str, list[Faction]]:
    """Per name (abbreviation, name or alias, ``_words``) the factions that have it, those
    of the Tweede Kamer first, kept per data version of the factions."""

    def read() -> dict[str, list[Faction]]:
        by_name: dict[str, list[Faction]] = {}
        for row in store.query(_FACTIONS):
            names = [row["abbreviation"], row["name"], *_list(row["aliases"])]
            records = (row["external_id"], *_list(row["external_ids"]))
            faction = Faction(
                row["key"],
                row["abbreviation"] or row["name"] or row["key"],
                tuple(sorted({r for r in records if isinstance(r, str) and r})),
                row["chamber"] is not None,
            )
            for name in {_words(n) for n in names if isinstance(n, str) and n.strip()}:
                by_name.setdefault(name, []).append(faction)
        return {
            name: sorted(found, key=lambda f: (f.ek, f.key))
            for name, found in by_name.items()
        }

    return cached(
        store, ("faction-names",), read, tables=(COLLECTION_FACTIONS,), inline=True
    )


def _members(store: GraphStore) -> tuple[str, ...]:
    """The name of every member (``_words``), kept per data version of the members."""
    return cached(
        store,
        ("member-names",),
        lambda: tuple(_words(name) for name in store.query(_MEMBERS)),
        tables=(COLLECTION_MEMBERS,),
        inline=True,
    )


def signed_for(store: GraphStore, tokens: list[str]) -> Signed:
    """*tokens* without the runs of them that are the name of a faction, the longest
    first, and the factions those name; none when the query is no more than that."""
    factions = _factions(store)
    longest = max((len(name.split()) for name in factions), default=0)
    words: list[str] = []
    by: list[SignedFor] = []
    i = 0
    while i < len(tokens):
        for n in range(min(longest, len(tokens) - i), 0, -1):
            run = " ".join(tokens[i : i + n])
            named = factions.get(_words(run), [])
            if named and not any(_words(run) in m for m in _members(store)):
                by.append(
                    SignedFor(
                        run,
                        named[0].name,
                        [f.key for f in named],
                        sorted({r for f in named for r in f.records}),
                    )
                )
                i += n
                break
        else:
            words.append(tokens[i])
            i += 1
    if not words:
        return Signed(tokens, [])
    return Signed(words, by)


def signed_sql(signatures: str, signed: Signed) -> tuple[str, dict[str, Any]]:
    """``AND`` a row whose signatures (the SQL *signatures*, a JSON array of ``actors``)
    hold one signed for each faction of *signed*, and its parameters; empty without one."""
    parts, params = [], {}
    for n, faction in enumerate(signed.by):
        params[f"_signed_{n}"] = faction.records
        parts.append(
            f"EXISTS (SELECT 1 FROM json_array_elements({array_or_empty(signatures)})"
            f" AS s(a) WHERE s.a ->> 'faction_id' = ANY(%(_signed_{n})s::text[]))"
        )
    return "".join(f" AND {part}" for part in parts), params
