"""The routes of Rechtsgang (``/api/judgments/routes``) find the articles of the regeling by
an index on their BWB id, not by reading every article, and keep their answer while the
articles and instruments stand still."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.judgment_routes import judgment_routes
from tests.pg.plans import explain, plan_nodes, recorded


def _article(number: int) -> dict[str, Any]:
    return {
        "key": f"bwbr0005537_bijlage_2_artikel_{number}",
        "type": "article",
        "labels": [],
        "props": {
            "bwb_id": "BWBR0005537",
            "article_number": f"bijlage 2 artikel {number}",
            "heading": f"Artikel {number}",
            "text": "De volgende wetten:\nWet een",
            "breadcrumb": [{"type": "divisie", "label": "Hoofdstuk 1"}],
            "references": [],
        },
    }


def test_the_regeling_is_found_by_the_index_and_kept(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.bulk_insert_or_update_nodes("articles", [_article(2), _article(1)])
    version_cache.clear()
    calls = recorded(store, monkeypatch)

    routes = judgment_routes(store)

    (chapter,) = routes.regeling
    assert [a["number"] for a in chapter["articles"]] == [
        "bijlage 2 artikel 1",
        "bijlage 2 artikel 2",
    ]
    (regeling,) = [c for c in calls if "FROM articles" in c.text]
    plan = explain(store, regeling.statement, regeling.params, disable=("seqscan",))
    scans = [n for n in plan_nodes(plan) if n.get("Relation Name") == "articles"]
    assert scans
    assert all("bwb_id" in (n.get("Index Cond") or "") for n in scans), plan

    calls.clear()
    assert judgment_routes(store) == routes
    assert not [c for c in calls if "lg_data_version" not in c.text]
