"""Article history, amended-by and instrument dossiers (AMENDS / LEGISLATED_IN model).

The fake store answers by looking at the collection an AQL statement reads, records
every ``query`` call, and lets the tests assert that the query count per request is
constant.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

client = TestClient(app)

BWB = "BWBR0001854"


def _article(stam_id: str | None = "stam-1") -> dict[str, Any]:
    props: dict[str, Any] = {"bwb_id": BWB, "article_number": "287"}
    if stam_id:
        props["stam_id"] = stam_id
    return {
        "_id": f"articles/{BWB}_287",
        "_key": f"{BWB}_287",
        "props": props,
    }


def _pub(number: int, dossiers: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": f"stb-2019-{number}",
        "kind": "Stb",
        "year": 2019,
        "number": str(number),
        "effect": "wijziging",
        "signed": "2019-01-01",
        "published": "2019-01-02",
        "dossiers": dossiers or [],
    }


def _version(
    i: int, *, effect: str | None = "wijziging", dossiers: list[str] | None = None
) -> dict[str, Any]:
    return {
        "_id": f"article_versions/v{i}",
        "_key": f"v{i}",
        "props": {
            "bwb_id": BWB,
            "stam_id": "stam-1",
            "versie_id": f"ver-{i}",
            "article_number": "287" if i else "286",
            "valid_from": f"2000-01-{i + 1:02d}",
            "valid_until": None,
            "current": False,
            "text": f"text {i}",
            "effect": effect,
            "source_publication": f"Stb.2019-{i}",
            "origin_publication": _pub(i, dossiers),
            "commencement_publication": _pub(100 + i, dossiers),
        },
    }


class _Collection:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self._doc = doc

    def get(self, key: str) -> dict[str, Any] | None:
        return self._doc


class FakeStore:
    """Dispatches on the collection named in the AQL; counts ``query`` calls."""

    def __init__(
        self,
        *,
        article: dict[str, Any] | None = None,
        versions: list[dict[str, Any]] | None = None,
        dossier_rows: list[dict[str, Any]] | None = None,
        aggregate_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.articles = _Collection(article)
        self.versions = versions or []
        self.dossier_rows = dossier_rows or []
        self.aggregate_rows = aggregate_rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def query(self, aql: str, bind_vars: dict[str, Any] | None = None):
        bind = bind_vars or {}
        self.calls.append((aql, bind))
        if "FOR v IN article_versions" in aql:
            return self.versions
        if "FOR d IN dossiers" in aql:
            keys = set(bind["keys"])
            return [r for r in self.dossier_rows if r["key"] in keys]
        return self.aggregate_rows


@pytest.fixture
def use_store() -> Generator[Any, None, None]:
    def _install(store: FakeStore) -> FakeStore:
        app.dependency_overrides[get_store] = lambda: store
        return store

    yield _install
    app.dependency_overrides.pop(get_store, None)


# ── GET /api/articles/{bwb_id}/{article_number}/history ─────────────────────


def test_history_returns_versions_with_documents_and_dossier_titles(use_store):
    store = use_store(
        FakeStore(
            article=_article(),
            versions=[
                _version(0, effect="nieuw", dossiers=["35786"]),
                _version(1, effect="wijziging"),
                _version(2, effect="vervallen"),
                _version(3, effect="onbekend"),
            ],
            dossier_rows=[{"key": "35786", "title": "Wijziging Burgerlijk Wetboek"}],
        )
    )

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert response.status_code == 200
    body = response.json()
    assert body["bwb_id"] == BWB
    assert body["article_number"] == "287"
    assert body["stam_id"] == "stam-1"
    assert [v["key"] for v in body["versions"]] == ["v0", "v1", "v2", "v3"]
    first = body["versions"][0]
    assert first["article_number"] == "286"  # number at that version
    assert first["effect"] == "nieuw"
    assert first["change"] == "introduces"
    assert body["versions"][1]["change"] == "amends"
    assert body["versions"][2]["change"] == "repeals"
    assert body["versions"][3]["change"] is None
    assert first["amended_by"]["id"] == "stb-2019-0"
    assert first["amended_by"]["kind"] == "Stb"
    assert first["amended_by"]["year"] == 2019
    assert first["amended_by"]["dossiers"] == [
        {"number": "35786", "key": "35786", "title": "Wijziging Burgerlijk Wetboek"}
    ]
    assert first["commencement"]["id"] == "stb-2019-100"
    # the version query filters on the stable identity
    versions_aql, bind = store.calls[0]
    assert "v.props.stam_id == @identity" in versions_aql
    assert bind == {"bwb_id": BWB, "identity": "stam-1"}


def test_history_unknown_article_is_404(use_store):
    store = use_store(FakeStore(article=None))

    response = client.get(f"/api/articles/{BWB}/999/history")

    assert response.status_code == 404
    assert store.calls == []


def test_history_without_stam_id_falls_back_to_article_number(use_store):
    store = use_store(FakeStore(article=_article(stam_id=None), versions=[_version(1)]))

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert response.status_code == 200
    assert response.json()["stam_id"] is None
    aql, bind = store.calls[0]
    assert "v.props.article_number == @identity" in aql
    assert "stam_id" not in aql
    assert bind["identity"] == "287"


def test_history_without_versions_or_dossiers_skips_the_dossier_lookup(use_store):
    store = use_store(FakeStore(article=_article(), versions=[]))

    response = client.get(f"/api/articles/{BWB}/287/history")

    assert response.status_code == 200
    assert response.json()["versions"] == []
    assert len(store.calls) == 1  # no dossier query when nothing names a dossier


def test_history_unknown_dossier_title_is_null(use_store):
    use_store(FakeStore(article=_article(), versions=[_version(1, dossiers=["12345"])]))

    body = client.get(f"/api/articles/{BWB}/287/history").json()

    assert body["versions"][0]["amended_by"]["dossiers"] == [
        {"number": "12345", "key": "12345", "title": None}
    ]


def test_history_query_count_is_constant(use_store):
    def run(n_versions: int) -> int:
        versions = [_version(i, dossiers=[str(30000 + i)]) for i in range(n_versions)]
        rows = [{"key": str(30000 + i), "title": f"t{i}"} for i in range(n_versions)]
        store = use_store(
            FakeStore(article=_article(), versions=versions, dossier_rows=rows)
        )
        response = client.get(f"/api/articles/{BWB}/287/history")
        assert response.status_code == 200
        assert len(response.json()["versions"]) == n_versions
        return len(store.calls)

    assert run(2) == run(40) == 2  # versions + one bulk dossier lookup


# ── GET /api/instruments/{bwb_id}/amended-by ────────────────────────────────


def _amending(number: int, **extra: Any) -> dict[str, Any]:
    props = {
        "display_name": f"Stb. 2019, {number}",
        "publication_kind": "Stb",
        "publication_year": 2019,
        "publication_number": str(number),
        "date_signed": "2019-01-01",
        "date_published": "2019-01-02",
        "dossier_numbers": ["35786"],
    }
    props.update(extra)
    return {
        "_id": f"instruments/stb-2019-{number}",
        "_key": f"stb-2019-{number}",
        "props": props,
    }


def _aggregate(number: int, **counts: Any) -> dict[str, Any]:
    row = {
        "instrument": _amending(number),
        "amends": 2,
        "introduces": 1,
        "repeals": 0,
        "articles_affected": 3,
        "first_effective_date": "2019-07-01",
    }
    row.update(counts)
    return row


def test_amended_by_maps_rows_and_dossier_titles(use_store):
    store = use_store(
        FakeStore(
            aggregate_rows=[
                {"total": 7, "items": [_aggregate(33), _aggregate(12, repeals=4)]}
            ],
            dossier_rows=[{"key": "35786", "title": "Klimaatwet"}],
        )
    )

    response = client.get(f"/api/instruments/{BWB}/amended-by?limit=2&offset=5")

    assert response.status_code == 200
    body = response.json()
    assert body["bwb_id"] == BWB
    assert body["total"] == 7  # absolute count, not len(items)
    assert len(body["items"]) == 2
    item = body["items"][0]
    assert item["id"] == "instruments/stb-2019-33"
    assert item["key"] == "stb-2019-33"
    assert item["identifier"] == "stb-2019-33"
    assert item["display_name"] == "Stb. 2019, 33"
    assert (item["kind"], item["year"], item["number"]) == ("Stb", 2019, "33")
    assert item["date_signed"] == "2019-01-01"
    assert item["date_published"] == "2019-01-02"
    assert item["dossiers"] == [
        {"number": "35786", "key": "35786", "title": "Klimaatwet"}
    ]
    assert (item["amends"], item["introduces"], item["repeals"]) == (2, 1, 0)
    assert item["articles_affected"] == 3
    assert item["first_effective_date"] == "2019-07-01"
    assert body["items"][1]["repeals"] == 4
    aggregate_bind = store.calls[0][1]
    assert aggregate_bind["bwb"] == BWB
    assert aggregate_bind["limit"] == 2
    assert aggregate_bind["offset"] == 5
    assert set(aggregate_bind["mutations"]) == {"AMENDS", "INTRODUCES", "REPEALS"}


def test_amended_by_empty(use_store):
    store = use_store(FakeStore(aggregate_rows=[{"total": 0, "items": []}]))

    response = client.get(f"/api/instruments/{BWB}/amended-by")

    assert response.status_code == 200
    assert response.json() == {"bwb_id": BWB, "total": 0, "items": []}
    assert len(store.calls) == 1  # no dossier lookup for an empty page


def test_amended_by_no_rows_at_all(use_store):
    use_store(FakeStore(aggregate_rows=[]))

    response = client.get(f"/api/instruments/{BWB}/amended-by")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_amended_by_rejects_bad_pagination(use_store):
    use_store(FakeStore())
    assert client.get(f"/api/instruments/{BWB}/amended-by?limit=0").status_code == 422
    assert client.get(f"/api/instruments/{BWB}/amended-by?offset=-1").status_code == 422


def test_amended_by_query_count_is_constant(use_store):
    def run(n: int) -> int:
        items = [
            {**_aggregate(i), "instrument": _amending(i, dossier_numbers=[str(i)])}
            for i in range(1, n + 1)
        ]
        store = use_store(
            FakeStore(
                aggregate_rows=[{"total": n, "items": items}],
                dossier_rows=[
                    {"key": str(i), "title": f"t{i}"} for i in range(1, n + 1)
                ],
            )
        )
        response = client.get(f"/api/instruments/{BWB}/amended-by")
        assert response.status_code == 200
        assert len(response.json()["items"]) == n
        return len(store.calls)

    assert run(2) == run(40) == 2  # one aggregate + one bulk dossier lookup


# ── GET /api/instruments/{bwb_id}/dossiers (LEGISLATED_IN) ──────────────────


def _dossier(number: str, opened: str) -> dict[str, Any]:
    return {
        "_id": f"dossiers/{number}",
        "_key": number,
        "props": {
            "number": number,
            "title": f"Dossier {number}",
            "opened_on": opened,
        },
    }


def test_instrument_dossiers_report_how_they_are_linked(use_store):
    store = use_store(
        FakeStore(
            aggregate_rows=[
                {
                    "total": 3,
                    "items": [
                        {
                            "dossier": _dossier("111", "2020-01-01"),
                            "direct": True,
                            "publications": [{"key": "stb-2019-1", "published": "x"}],
                        },
                        {
                            "dossier": _dossier("222", "2019-01-01"),
                            "direct": False,
                            "publications": [
                                {
                                    "key": "stb-2018-5",
                                    "identifier": "stb-2018-5",
                                    "published": "2018-03-01",
                                },
                                {
                                    "key": "stb-2019-33",
                                    "identifier": None,
                                    "published": "2019-04-01",
                                },
                            ],
                        },
                        {
                            "dossier": _dossier("333", "2018-01-01"),
                            "direct": False,
                            "publications": [],
                        },
                    ],
                }
            ]
        )
    )

    response = client.get(f"/api/instruments/{BWB}/dossiers")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    by_number = {i["dossier_number"]: i for i in body["items"]}
    assert by_number["111"]["via"] == "instrument"
    assert by_number["111"]["publication"] is None
    assert by_number["222"]["via"] == "amending_publication"
    assert by_number["222"]["publication"] == "stb-2019-33"  # newest, key fallback
    assert by_number["333"]["via"] == "amending_publication"
    assert by_number["333"]["publication"] is None
    assert by_number["111"]["title"] == "Dossier 111"
    assert by_number["111"]["opened_on"] == "2020-01-01"
    aql, bind = store.calls[0]
    assert bind["legislated_in"] == "LEGISLATED_IN"
    assert bind["instrument_id"] == f"instruments/{BWB.lower()}"  # make_node_key
    assert len(store.calls) == 1


def test_instrument_dossiers_empty(use_store):
    use_store(FakeStore(aggregate_rows=[{"total": 0, "items": []}]))

    body = client.get(f"/api/instruments/{BWB}/dossiers").json()

    assert body == {"bwb_id": BWB, "total": 0, "items": []}


def test_instrument_dossiers_query_count_is_constant(use_store):
    def run(n: int) -> int:
        items = [
            {
                "dossier": _dossier(str(i), "2020-01-01"),
                "direct": False,
                "publications": [{"key": f"stb-2019-{i}", "published": "2019"}],
            }
            for i in range(n)
        ]
        store = use_store(FakeStore(aggregate_rows=[{"total": n, "items": items}]))
        response = client.get(f"/api/instruments/{BWB}/dossiers")
        assert len(response.json()["items"]) == n
        return len(store.calls)

    assert run(1) == run(30) == 1


# ── OpenAPI ─────────────────────────────────────────────────────────────────


def test_openapi_lists_new_endpoints():
    schema = app.openapi()
    assert "/api/articles/{bwb_id}/{article_number}/history" in schema["paths"]
    assert "/api/instruments/{bwb_id}/amended-by" in schema["paths"]
