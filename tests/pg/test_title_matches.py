"""The Staatsblad and Staatscourant publications matched to an instrument by title, on a real
PostgreSQL: the pieces of a title find the same instrument as testing every title against
every publication, and do so on thousands of publications and tens of thousands of
instruments in seconds."""

from __future__ import annotations

import random
import time
from typing import Any

from lawgraph.config.constants import SOURCE_STAATSBLAD, SOURCE_STAATSCOURANT
from lawgraph.db import GraphStore
from lawgraph.db.queries.semantic import bwb as semantic_bwb

# Every title against every publication: what the query found before, and must still find.
_EVERY_TITLE = """
SELECT pub.id AS pub_id, pub.key AS pub_key, inst.id AS inst_id, inst.key AS inst_key,
       'title' AS match_type
FROM documents pub
CROSS JOIN LATERAL (
    SELECT i.id, i.key FROM instruments i
    WHERE i.citation_title IS NOT NULL {instruments}
      AND strpos(lower(coalesce(lg_str(pub.props -> 'title'), '')),
                 lower(i.citation_title)) > 0
    ORDER BY length(i.citation_title) DESC, i.key
    LIMIT 1
) inst
WHERE pub.source = %(source)s AND {filters}
ORDER BY pub.key
"""

# The words of a title: a few that many titles share, and many that few do (as "wet",
# "besluit" and the subject of a law), with letters lower() changes.
_COMMON = "wet besluit regeling van de op het en Ă‰Ă‰N İstanbul".split()
_SYLLABLES = (
    "be heer mi lieu stra ver keer zorg toe slag on der wijs ar beid pen sioen".split()
)


def _word(rng: random.Random) -> str:
    if rng.random() < 0.4:
        return rng.choice(_COMMON)
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


_LONG = "Nota van toelichting. " * 10


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [node_type], "props": props}


def _title(rng: random.Random, words: int) -> str:
    return " ".join(_word(rng) for _ in range(words))


def _graph(store: GraphStore, rng: random.Random, pubs: int, instruments: int) -> None:
    titles = [_title(rng, rng.randint(1, 5)) for _ in range(instruments)]
    titles += ["Wet", "Awb", "", "wet milieu", "WET MILIEU"]  # short, empty, a tie
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(f"i{n:06d}", "instrument", citation_title=t.capitalize())
            for n, t in enumerate(titles)
        ]
        + [_node("untitled", "instrument")],
    )
    docs = []
    for n in range(pubs):
        named = rng.sample(titles, 2)
        title = f"Wijziging van de {named[0].upper()} en {_title(rng, 3)}{named[1]}"
        props: dict[str, Any] = {"text": _LONG, "date": f"2026-0{n % 9 + 1}-01"}
        if n % 7:
            props["title"] = title if n % 11 else "Wet"
        source = SOURCE_STAATSBLAD if n % 2 else SOURCE_STAATSCOURANT
        docs.append(_node(f"p{n:06d}", "document", source=source, **props))
    store.bulk_insert_or_update_nodes("documents", docs)


def _every_title(store: GraphStore, source: str, since: str | None) -> list[Any]:
    if source == SOURCE_STAATSBLAD:
        statement = _EVERY_TITLE.format(
            instruments="",
            filters=f"{semantic_bwb._text_longer_than(50)} AND {semantic_bwb._NO_BWB_ID}",
        )
    else:
        statement = _EVERY_TITLE.format(
            instruments="AND length(i.citation_title) > 5",
            filters=(
                f"{semantic_bwb._NO_BWB_ID} AND length(lg_str(pub.props -> 'title')) > 5"
                f" AND {semantic_bwb._SINCE}"
            ),
        )
    return list(store.query(statement, {"source": source, "since_iso": since}))


def test_the_pieces_of_a_title_find_what_every_title_found(store: GraphStore) -> None:
    _graph(store, random.Random(7), pubs=400, instruments=600)
    for source, statement in (
        (SOURCE_STAATSBLAD, semantic_bwb._STAATSBLAD_BY_TITLE_SQL),
        (SOURCE_STAATSCOURANT, semantic_bwb._STAATSCOURANT_BY_TITLE_SQL),
    ):
        for since in (None, "2026-05-01"):
            expected = _every_title(store, source, since)
            params = {"source": source, "since_iso": since}
            found = list(store.query(statement, params, hash_joins=True))
            assert found == expected
            assert len(expected) > 50


def test_thousands_of_publications_are_matched_in_seconds(store: GraphStore) -> None:
    _graph(store, random.Random(11), pubs=3_000, instruments=30_000)
    started = time.monotonic()
    rows = semantic_bwb.staatsblad_instrument_matches(store)
    rows += semantic_bwb.staatscourant_instrument_matches(store, None)
    took = time.monotonic() - started
    assert len(rows) > 2_000
    assert took < 30, f"{took:.1f} s"
