"""The court map per municipality (``lg_court_districts``) on a real PostgreSQL: written
whole, and the text of the articles of the law it is checked against."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.court_districts import LAW_BWB_ID
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries import court_districts as queries


def _row(year: int, code: str, check: str | None) -> dict[str, Any]:
    return {
        "year": year,
        "municipality_code": code,
        "municipality": "’s-Hertogenbosch",
        "province": "Noord-Brabant",
        "district": "Oost-Brabant",
        "district_code": "AR09",
        "circuit": "Gerechtshof ’s-Hertogenbosch",
        "circuit_code": "RE04",
        "district_article": "9",
        "circuit_article": "16",
        "law_district": "Oost-Brabant" if check else None,
        "district_check": check,
        "circuit_check": check,
    }


def test_the_table_is_written_whole(store: GraphStore) -> None:
    queries.write(store, [_row(2025, "GM0796", None), _row(2026, "GM0796", "agrees")])
    queries.write(store, [_row(2026, "GM0796", "agrees")])

    rows = list(store.query("SELECT * FROM lg_court_districts"))
    assert rows == [_row(2026, "GM0796", "agrees")]


def test_the_years_newest_first_and_the_rows_of_one(store: GraphStore) -> None:
    rows = [_row(2025, "GM0796", None), _row(2026, "GM0796", "agrees")]
    queries.write(store, rows + [_row(2026, "GM0001", "agrees")])

    assert queries.years(store) == [2026, 2025]
    assert queries.districts_of(store, 2025) == [rows[0]]
    assert len(queries.districts_of(store, 2026)) == 2


def test_the_text_of_each_numbered_article(store: GraphStore) -> None:
    docs = [
        {
            "key": make_node_key(LAW_BWB_ID, number),
            "type": "article",
            "labels": [],
            "props": {"bwb_id": LAW_BWB_ID, "article_number": number, "text": text},
        }
        for number, text in (("4", "Het arrondissement …"), ("5", ""))
    ]
    store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, docs)

    assert queries.article_texts(store, LAW_BWB_ID) == {"4": "Het arrondissement …"}
