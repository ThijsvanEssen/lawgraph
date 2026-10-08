"""``semantic echr-versions`` on a real PostgreSQL: the language versions of an ECHR decision
without an ECLI are SAME_AS the English one, which the list shows alone."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from lawgraph.pipelines.semantic.echr_versions import ECHRVersionsSemanticPipeline


def _echr(item: str, appno: str, date: str, language: str, **props: Any) -> dict:
    return {
        "_key": "echr_" + item.replace("-", "_"),
        "type": "judgment",
        "labels": ["ECHR"],
        "props": {
            "source": "echr",
            "external_id": item,
            "appno": appno,
            "date": date,
            "date_eff": date,
            "language": language,
            "display_name": f"{appno} {language}",
            **props,
        },
    }


def _same_as(store: GraphStore) -> dict[str, Any]:
    return {
        row["key"]: row["same_as"]
        for row in store.query(
            "SELECT key, same_as FROM judgments WHERE source = 'echr' ORDER BY key"
        )
    }


def _edges(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'SAME_AS'"
            " AND source = 'echr-version-linker'"
        )
    }


def test_the_french_version_is_the_same_as_the_english_one(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _echr("001-252192", "7481/23", "2026-03-10", "ENG"),
            _echr("001-252409", "7481/23", "2026-03-10", "FRE"),
            # the decision on admissibility of the same case, another day
            _echr("001-200000", "7481/23", "2024-01-15", "ENG"),
            # a decision with an ECLI is one node already
            _echr(
                "001-9",
                "9/20",
                "2021-01-01",
                "FRE",
                ecli="ECLI:CE:ECHR:2021:0101JUD000000920",
            ),
        ],
    )
    ECHRVersionsSemanticPipeline(store=store).run()

    assert _edges(store) == {("judgments/echr_001_252409", "judgments/echr_001_252192")}
    assert _same_as(store)["echr_001_252409"] == "001-252192"
    listed = get_judgments_list(store, JudgmentFilters(source="echr"), facets=False)
    keys = {str(item.get("_key") or item.get("key")) for item in listed["items"]}
    assert "echr_001_252409" not in keys and "echr_001_252192" in keys

    # the English version gone (its record deleted, say): the French one stands alone
    store.execute("DELETE FROM judgments WHERE key = 'echr_001_252192'")
    ECHRVersionsSemanticPipeline(store=store).run()
    assert _edges(store) == set()
    assert _same_as(store)["echr_001_252409"] is None
