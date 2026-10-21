"""Old EU act to new for real: the concordance tables of a codification (Verordening (EU)
2017/1001 of Verordening (EG) nr. 207/2009) and of a recast of four directives with a column
each (Richtlijn (EU) 2018/1972), excerpts of their CELLAR HTML as ``retrieve eurlex`` stores
it, with the articles of the acts as ``normalize eurlex`` makes them, through ``semantic
tk-transposition-tables``, the API and ``lawgraph succession-gaps``.

- A row that holds is a part of the ``TRANSPOSED_TO`` of its pair of articles, its source the
  CELEX number of the new act; a run placed in a run as long pairs them one by one.
- An article the table names that the old act does not have (one inserted later: "Artikel 9
  bis"), and an article of the repealed act without a row, is a gap in the report.
- An old article the table places nowhere ("—") is not taken over: an edge to the new act.
- An old act the graph does not hold places nothing and says which retrieve fetches it;
  ``retrieve eurlex --mode gaps`` (and ``lawgraph gaps``) lists it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EURLEX_CELEX,
    RELATION_PART_OF,
    RELATION_TRANSPOSED_TO,
    SOURCE_EURLEX,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import EdgeWriter, GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve import _gaps
from tests.databases import Api, ModuleStore, module_store
from tests.paths import FIXTURES

TRADE_MARK = "32017R1001"
OLD_TRADE_MARK = "32009R0207"
CODE = "32018L1972"
# The text of the article that says the table is read for references to the old acts.
_READ_BY_TABLE = (
    "Verwijzingen naar de ingetrokken verordening gelden als verwijzingen naar de "
    "onderhavige verordening en worden gelezen volgens de concordantietabel in bijlage III."
)


def _act(store: GraphStore, celex: str, articles: dict[str, Any]) -> None:
    """An EU act and its articles (number -> leden, or the text of the article), as
    ``normalize eurlex`` writes them."""
    key = make_node_key(celex)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": key,
                "type": "instrument",
                "labels": ["EU"],
                "props": {"celex": celex, "jurisdiction": "eu", "title": celex},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": make_node_key(celex, number),
                "type": "article",
                "labels": ["EU", "Article"],
                "props": {
                    "celex": celex,
                    "article_number": number,
                    "text": leden if isinstance(leden, str) else "…",
                    "parts": [
                        {
                            "id": f"lid-{n}",
                            "kind": "lid",
                            "number": n,
                            "start": 0,
                            "end": 1,
                        }
                        for n in (() if isinstance(leden, str) else leden)
                    ],
                    "position": position,
                },
            }
            for position, (number, leden) in enumerate(articles.items())
        ],
    )
    with EdgeWriter(store, what=None) as edges:
        for number in articles:
            edges.add(
                f"articles/{make_node_key(celex, number)}",
                f"instruments/{key}",
                RELATION_PART_OF,
                source="test",
            )


def _seed(store: GraphStore) -> None:
    numbers = [str(n) for n in range(1, 18)]
    _act(
        store,
        TRADE_MARK,
        {
            **dict.fromkeys(numbers, ()),
            "8": ("1", "2", "3", "4", "5", "6"),
            "211": _READ_BY_TABLE,
        },
    )
    # the original text: no 9 bis, 9 ter or 13 bis (inserted by Verordening 2015/2424)
    _act(store, OLD_TRADE_MARK, {**{str(n): () for n in range(1, 16)}, "8": ("1", "5")})
    _act(store, CODE, {"1": tuple("123456"), "2": (), "125": _READ_BY_TABLE})
    for old in ("32002L0021", "32002L0020", "32002L0022"):  # not 2002/19
        _act(store, old, {"1": (), "2": ()})
    with RawSourceWriter(store) as writer:
        for celex in (TRADE_MARK, CODE):
            writer.add(
                raw_source_doc(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EURLEX_CELEX,
                    external_id=celex,
                    payload_text=(
                        FIXTURES / f"eurlex_{celex.lower()}_concordance.html"
                    ).read_text(),
                    meta={"celex": celex, "lang": "NL"},
                )
            )


# The tests read one database built for them all.
pytestmark = pytest.mark.xdist_group("eu_concordance")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleStore]:
    with module_store(tmp_path_factory) as built:
        store, cli = built
        _seed(store)
        cli("semantic", "tk-transposition-tables")
        cli("semantic", "tk-transposition-tables")  # a second run changes nothing
        yield built


@pytest.fixture(scope="module")
def store(built: ModuleStore) -> GraphStore:
    return built.store


def _transposed(store: GraphStore) -> dict[tuple[str, str], Any]:
    return {
        (row["from_id"], row["to_id"]): row["meta"]
        for row in store.query(
            "SELECT from_id, to_id, doc -> 'meta' AS meta FROM edges "
            "WHERE relation = %(r)s",
            {"r": RELATION_TRANSPOSED_TO},
        )
    }


def _id(celex: str, number: str) -> str:
    return f"articles/{make_node_key(celex, number)}"


def test_a_row_that_holds_is_a_part_of_the_edge_of_its_pair(store: GraphStore) -> None:
    edges = {
        pair: meta
        for pair, meta in _transposed(store).items()
        if pair[1].startswith("articles/")
    }
    pairs = {
        (old, new)
        for old, new in [
            *((n, n) for n in "1234567"),  # "Artikelen 1 tot en met 7", one by one
            ("8", "8"),
            ("9", "9"),
            ("10", "12"),
            ("11", "13"),
            ("12", "14"),
            ("13", "15"),
            ("14", "17"),
        ]
    }
    assert {
        (o.rsplit("_", 1)[1], n.rsplit("_", 1)[1])
        for o, n in edges
        if o.startswith(f"articles/{OLD_TRADE_MARK.lower()}")
    } == pairs
    assert edges[(_id(OLD_TRADE_MARK, "8"), _id(TRADE_MARK, "8"))] == {
        "basis": "transposition_table",
        "source": TRADE_MARK,
        "parts": [
            {
                "from": "leden 1 tot en met 4",
                "to": "Artikel 8, leden 1 tot en met 4",
                "article": "8",
                "leden": ["1", "2", "3", "4"],
            },
            {
                "from": "lid 4 bis",
                "to": "Artikel 8, lid 6",
                "article": "8",
                "leden": ["6"],
            },
            {"from": "lid 5", "to": "Artikel 8, lid 5", "article": "8", "leden": ["5"]},
        ],
    }
    # a column per old act
    assert {(o, n) for o, n in edges if n.startswith(f"articles/{CODE.lower()}")} == {
        (_id("32002L0021", "1"), _id(CODE, "1")),
        (_id("32002L0021", "2"), _id(CODE, "2")),
        (_id("32002L0020", "1"), _id(CODE, "1")),
        (_id("32002L0022", "1"), _id(CODE, "1")),
    }


def test_what_the_table_answers_is_an_edge_to_the_new_act(store: GraphStore) -> None:
    answers = {
        (o, n): meta
        for (o, n), meta in _transposed(store).items()
        if n.startswith("instruments/")
    }
    assert answers
    assert {meta["outcome"] for meta in answers.values()} == {"niet_overgenomen"}
    assert {
        (part["to"], part["outcome"])
        for meta in answers.values()
        for part in meta["parts"]
    } == {("—", "niet_overgenomen")}


def test_the_api_links_the_source_on_eur_lex(api: Api) -> None:
    old = api.get_json(f"/api/articles/{OLD_TRADE_MARK}/10")
    (successor,) = old["successors"]
    assert successor["article"]["id"] == _id(TRADE_MARK, "12")
    assert successor["source"] == TRADE_MARK
    assert successor["source_url"] == (
        f"https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:{TRADE_MARK}"
    )


def test_the_report_lists_what_does_not_hold(built: ModuleStore) -> None:
    out = built.cli("succession-gaps").stdout
    assert (
        f"instruments/{OLD_TRADE_MARK.lower()} -> instruments/{TRADE_MARK.lower()}"
        in out
    )
    assert (
        f"  {TRADE_MARK} BIJLAGE III Concordantietabel, Verordening (EG) nr. 207/2009: "
        "rows that do not hold (3)"
    ) in out
    assert "rij 6: art. 9 bis: Artikel 10 [the old law has no such article]" in out
    # the old act is repealed: an article of it without a row is a gap
    assert "art. 15 [no row]" in out
    # an old part the table places nowhere ("—"): no gap, what the table answers
    assert "art. 2: —" not in out
    assert "What the tables say instead of a place (no gap): niet_overgenomen" in out
    # an old act the graph does not hold
    assert (
        f"{CODE} BIJLAGE XIII CONCORDANTIETABEL, Richtlijn 2002/19/EG: places nothing: "
        "the act 32002L0019 is not in the graph (retrieve eurlex --celex 32002L0019)."
    ) in out


def test_the_gaps_mode_fetches_an_old_act_the_graph_does_not_hold(
    store: GraphStore,
) -> None:
    # 2002/19 is named by the table of 2018/1972 and not in the graph; the other old acts
    # are, and an act stored but not normalized yet is not fetched again
    assert _gaps.concordance_gaps(store) == ["32002L0019"]
    assert "32002L0019" in _gaps.eurlex_gaps(store)
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EURLEX_CELEX,
                external_id="32002L0019",
                payload_text="<html></html>",
                meta={"celex": "32002L0019", "lang": "NL"},
            )
        )
    assert _gaps.concordance_gaps(store) == []
