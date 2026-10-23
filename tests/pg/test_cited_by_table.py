"""The judgments that cite an article, kept apart on a real PostgreSQL: ``lg_cited_by`` kept by
the triggers on ``edges`` (a citation, its mentions) and on ``judgments`` (written after its
edges, its date, court and citations, gone), filled by ``semantic graph-light`` for what was
written before them."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, schema, version_cache
from lawgraph.db.queries import cited_by_table
from lawgraph.db.queries.articles import get_article_cited_by

ARTICLE = "articles/bwbr0005289_6_162"


def _judgment(key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": "judgment", "labels": ["Rechtspraak"], "props": props}


def _citation(
    judgment: str,
    leden: list[list[str]],
    *,
    to: str = ARTICLE,
    relation: str = "REFERS_TO",
) -> dict[str, Any]:
    return {
        "key": f"e_{judgment}_{to.rsplit('/', 1)[1]}",
        "from_id": f"judgments/{judgment}",
        "to_id": to,
        "relation": relation,
        "meta": {"mentions": [{"leden": names, "snippet": "…"} for names in leden]},
    }


def _kept(store: GraphStore) -> dict[str, tuple[Any, ...]]:
    return {
        r["judgment_id"].rsplit("/", 1)[1]: (
            r["article_id"].rsplit("/", 1)[1],
            r["mentions"],
            r["leden"],
            r["date_eff"],
            r["tier"],
            r["cited"],
        )
        for r in store.query(f"SELECT * FROM {schema.CITED_BY_TABLE}")
    }


def test_a_citation_is_kept_with_its_mentions_and_its_judgment(
    store: GraphStore,
) -> None:
    """With the edge, its mentions and leden, and the judgment's date, tier and citations;
    again when its mentions change, when the judgment is written after its edge or changes;
    gone with its edge or its judgment. Another relation, another end or a judgment that is
    not there is not kept."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment("j1", date_eff="2020-01-01", tier="hoge_raad",
                   inbound_citation_count=4)],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _citation("j1", [["1"], []]),
            _citation("j2", [["2"]]),  # before its judgment
            _citation("j1", [], to="judgments/j9"),
            _citation("j1", [["1"]], to="articles/other", relation="EXPLAINS"),
        ]
    )
    assert _kept(store) == {
        "j1": ("bwbr0005289_6_162", 2, [["1"], []], "2020-01-01", "hoge_raad", 4.0)
    }
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("j2", date_eff="2021-02-02", tier="rechtbank"),
            _judgment("j1", date_eff="2020-01-01", tier="hoge_raad",
                      inbound_citation_count=7),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges([_citation("j2", [["2"], ["3"], []])])
    assert _kept(store) == {
        "j1": ("bwbr0005289_6_162", 2, [["1"], []], "2020-01-01", "hoge_raad", 7.0),
        "j2": (
            "bwbr0005289_6_162",
            3,
            [["2"], ["3"], []],
            "2021-02-02",
            "rechtbank",
            None,
        ),
    }
    # an edge that no longer cites the article
    store.execute(
        "UPDATE edges SET doc = json_build_object('relation', 'EXPLAINS')"
        " WHERE from_id = 'judgments/j2'"
    )
    assert list(_kept(store)) == ["j1"]
    store.execute("DELETE FROM edges WHERE from_id = 'judgments/j1'")
    store.execute("DELETE FROM judgments WHERE id = 'judgments/j2'")
    assert _kept(store) == {}


def _pages(store: GraphStore) -> list[Any]:
    version_cache.clear()
    return [
        get_article_cited_by(store, ARTICLE, sort=sort, lid=lid, limit=2, offset=offset)
        for sort in ("date_desc", "citation_count")
        for lid in (None, "2")
        for offset in (0, 1)
    ]


def test_the_pages_after_a_fill_are_those_the_triggers_kept(store: GraphStore) -> None:
    """The passages read the table as the triggers keep it; a fill of an empty table (one
    written before the triggers) gives the same passages."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment(f"j{n}", ecli=f"ECLI:NL:HR:2020:{n}", date_eff=f"2020-01-0{n}",
                   tier="hoge_raad", inbound_citation_count=n % 3) for n in range(1, 6)],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_citation(f"j{n}", [["1"], ["2"]][: 1 + n % 2]) for n in range(1, 6)]
    )
    kept = _pages(store)
    assert [len(page.rows) for page in kept] == [2] * len(kept)
    store.execute(
        f"DELETE FROM {schema.CITED_BY_TABLE}"
    )  # as written before the triggers
    assert cited_by_table.fill_cited_by(store) == 5
    assert _pages(store) == kept
    assert cited_by_table.fill_cited_by(store) == 0
    assert cited_by_table.fill_cited_by(store, every=True) == 5


def _areas(store: GraphStore) -> dict[str, Any]:
    return {
        r["judgment_id"].rsplit("/", 1)[1]: r["areas"]
        for r in store.query(f"SELECT judgment_id, areas FROM {schema.CITED_BY_TABLE}")
    }


def test_the_main_areas_of_law_of_a_judgment_are_kept_with_its_citations(
    store: GraphStore,
) -> None:
    """The areas of its ``subjects`` (each up to its first ';', once) with the edge, whichever
    is written first; again when its subjects change; a fill gives the same."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_judgment("j1", subjects=["Bestuursrecht; Belastingrecht", "Bestuursrecht"]),
         _judgment("j2"), _judgment("j3", subjects=["Strafrecht"])],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_citation("j1", [["1"]]), _citation("j2", [[]]), _citation("j4", [[]])]
    )
    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment("j4", subjects=["Civiel recht"])]
    )
    store.bulk_insert_or_update_edges([_citation("j3", [["1"]])])
    kept = {
        "j1": ["Bestuursrecht"],
        "j2": [],
        "j3": ["Strafrecht"],
        "j4": ["Civiel recht"],
    }
    assert _areas(store) == kept

    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment("j3", subjects=["Strafrecht", "Civiel recht; Familie"])]
    )
    kept["j3"] = ["Strafrecht", "Civiel recht"]
    assert _areas(store) == kept

    store.execute(f"UPDATE {schema.CITED_BY_TABLE} SET areas = NULL")
    assert cited_by_table.fill_cited_by(store) == 0
    assert cited_by_table.fill_cited_by(store, every=True) == 4
    assert _areas(store) == kept


def test_a_release_without_the_table_starts_on_a_database_with_it(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rollback: a release that knows no ``lg_cited_by`` checks only the tables of its own
    schema, so it starts on a database that has the table and its triggers; and those
    triggers go on keeping the table while it runs."""
    without = {
        table: columns
        for table, columns in schema.expected_columns().items()
        if table != schema.CITED_BY_TABLE
    }
    monkeypatch.setattr(schema, "expected_columns", lambda: without)
    with store.pool.connection() as conn:
        assert schema.schema_drift(conn) == []
    store.bulk_insert_or_update_nodes("judgments", [_judgment("j1", date_eff="2024")])
    store.bulk_insert_or_update_edges([_citation("j1", [["1"]])])
    assert list(_kept(store)) == ["j1"]
