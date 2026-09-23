"""The instrument detail, the identifier of the sub-routes and /eu-links: identifier
handling and the shape of the answers, on stubbed queries (the queries run in
tests/integration/test_instrument_links.py)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.instruments import (
    IMPLEMENTS_BASES,
    EuLinkDTO,
    InstrumentDetailDTO,
    InstrumentEuLinksResponse,
)
from lawgraph.config.constants import EDGE_SOURCE_BWB_IMPLEMENTS
from lawgraph.db.queries.instrument_links import EuLinksData, InternationalLinksData
from lawgraph.db.queries.instrument_scope import (
    InstrumentScope,
    scope_of,
    scope_of_node,
)

client = TestClient(app)

_REGULATION = {
    "_id": "instruments/bwbr0001854",
    "_key": "bwbr0001854",
    "labels": ["BWB"],
    "props": {
        "bwb_id": "BWBR0001854",
        "title": "Wetboek van Strafrecht",
        "kind": "wet",
        "jurisdiction": "nl",
        "article_count": 12,
        "date_in_force": "2024-01-01",
        "dossier_numbers": [33000, "29684-I"],
    },
}
_DIRECTIVE = {
    "_id": "instruments/32016l0680",
    "_key": "32016l0680",
    "labels": ["EU"],
    "props": {"celex": "32016L0680", "jurisdiction": "eu", "display_name": "Richtlijn"},
}


@pytest.mark.parametrize(
    ("identifier", "prop", "value"),
    [
        ("BWBR0001854", "bwb_id", "BWBR0001854"),
        ("bwbr0001854", "bwb_id", "BWBR0001854"),
        ("BWBV0001000", "bwb_id", "BWBV0001000"),
        ("ECHR-CONVENTION", "bwb_id", "ECHR-CONVENTION"),
        ("32016L0680", "celex", "32016L0680"),
        ("32016l0680", "celex", "32016L0680"),
        ("32002F0584", "celex", "32002F0584"),
        (" 32016L0680 ", "celex", "32016L0680"),
    ],
)
def test_the_scope_of_an_identifier(identifier: str, prop: str, value: str) -> None:
    assert scope_of(identifier) == InstrumentScope(prop, value)  # type: ignore[arg-type]


def test_the_key_of_a_scope_is_the_node_key_of_the_instrument() -> None:
    assert scope_of("32016L0680").node_key == "32016l0680"
    assert scope_of("BWBR0001854").node_key == "bwbr0001854"


def test_the_scope_of_a_resolved_node_follows_its_props() -> None:
    assert scope_of_node(_REGULATION) == InstrumentScope("bwb_id", "BWBR0001854")
    assert scope_of_node(_DIRECTIVE) == InstrumentScope("celex", "32016L0680")
    assert scope_of_node({"props": {"title": "Verdrag"}}) is None


def test_the_detail_dto_reads_a_node() -> None:
    dto = InstrumentDetailDTO.from_document(_REGULATION)
    assert (dto.key, dto.bwb_id, dto.celex, dto.kind) == (
        "bwbr0001854",
        "BWBR0001854",
        None,
        "wet",
    )
    assert dto.labels == ["BWB"] and dto.article_count == 12
    assert dto.dossier_numbers == ["33000", "29684-I"]
    assert dto.stub is False


def test_the_eu_link_says_what_it_rests_on() -> None:
    row = {
        "instrument": _DIRECTIVE,
        "edge": {
            "confidence": 0.75,
            "source": EDGE_SOURCE_BWB_IMPLEMENTS,
            "meta": {"celex": "32016L0680"},
        },
    }
    link = EuLinkDTO.from_row(row)
    assert link.basis == "celex_named_in_text" and link.relation == "IMPLEMENTS"
    assert link.instrument.celex == "32016L0680" and link.meta == {
        "celex": "32016L0680"
    }
    assert IMPLEMENTS_BASES == {EDGE_SOURCE_BWB_IMPLEMENTS: "celex_named_in_text"}

    unknown = EuLinkDTO.from_row({**row, "edge": {"source": "somebody-else"}})
    assert unknown.basis is None and unknown.confidence is None


def test_the_eu_link_has_no_articles_field() -> None:
    assert "articles" not in EuLinkDTO.model_fields
    assert "articles" not in InstrumentEuLinksResponse.model_fields
    assert "IMPLEMENTS" in (EuLinkDTO.__doc__ or "")
    assert "transposition signal" in (EuLinkDTO.model_fields["basis"].description or "")


def _stub(monkeypatch: pytest.MonkeyPatch, doc: dict[str, Any] | None) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.instruments.resolve_instrument",
        lambda store, identifier: doc,
    )


def test_the_detail_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _DIRECTIVE)
    body = client.get("/api/instruments/32016L0680").json()
    assert (body["id"], body["celex"], body["jurisdiction"]) == (
        "instruments/32016l0680",
        "32016L0680",
        "eu",
    )
    _stub(monkeypatch, None)
    assert client.get("/api/instruments/BWBR0000000").status_code == 404
    assert client.get("/api/instruments/BWBR0000000/eu-links").status_code == 404


def test_the_eu_links_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _DIRECTIVE)
    seen: dict[str, Any] = {}

    def eu_links(store: Any, instrument_id: str, *, limit: int) -> EuLinksData:
        seen["eu"] = (instrument_id, limit)
        row = {
            "instrument": _REGULATION,
            "edge": {
                "confidence": 0.75,
                "source": EDGE_SOURCE_BWB_IMPLEMENTS,
                "meta": {"celex": "32016L0680"},
            },
        }
        return EuLinksData([], 0, [row], 7)

    def international(
        store: Any, instrument_id: str, scope: Any, *, limit: int
    ) -> InternationalLinksData:
        seen["international"] = (instrument_id, scope, limit)
        treaty = {
            "instrument": {**_REGULATION, "_id": "instruments/bwbv1", "_key": "bwbv1"},
            "own_article": {"id": "articles/a_1", "key": "a_1", "article_number": "1"},
            "counterpart_article": None,
            "edge": {"confidence": 1.0, "source": "x", "meta": {"raw_match": "r"}},
        }
        echr = {
            "judgment": {
                "_id": "judgments/echr_1",
                "_key": "echr_1",
                "props": {"ecli": "ECLI:CE:ECHR:2020:2"},
            },
            "own_article": None,
            "edge": {"confidence": 0.8, "source": "y", "meta": {}},
        }
        return InternationalLinksData([treaty], 5, [echr], 40)

    monkeypatch.setattr("lawgraph.api.routes.instruments.get_eu_links", eu_links)
    monkeypatch.setattr(
        "lawgraph.api.routes.instruments.get_international_links", international
    )

    body = client.get("/api/instruments/32016L0680/eu-links?limit=2").json()

    assert seen["eu"] == ("instruments/32016l0680", 2)
    assert seen["international"] == (
        "instruments/32016l0680",
        InstrumentScope("celex", "32016L0680"),
        2,
    )
    assert body["instrument"]["celex"] == "32016L0680"
    assert body["implements"] == [] and body["implements_total"] == 0
    assert body["implemented_by_total"] == 7
    assert body["implemented_by"][0]["instrument"]["bwb_id"] == "BWBR0001854"
    assert body["implemented_by"][0]["basis"] == "celex_named_in_text"
    assert body["international_total"] == 45  # absolute; the list is cut at `limit`
    kinds = [i["kind"] for i in body["international"]]
    assert kinds == ["treaty", "echr_judgment"]
    assert body["international"][0]["meta"] == {"raw_match": "r"}
    assert body["international"][1]["judgment"]["ecli"] == "ECLI:CE:ECHR:2020:2"


def test_the_eu_links_limit_is_bounded() -> None:
    assert (
        client.get("/api/instruments/BWBR0001854/eu-links?limit=0").status_code == 422
    )
    assert (
        client.get("/api/instruments/BWBR0001854/eu-links?limit=2001").status_code
        == 422
    )


def test_a_sub_route_takes_a_celex_number(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def articles(store: Any, identifier: str, **kwargs: Any) -> tuple[list, int]:
        seen.append(identifier)
        return (
            [
                {
                    "_id": "articles/32016l0680_1",
                    "_key": "32016l0680_1",
                    "props": {"celex": "32016L0680", "article_number": "1"},
                }
            ],
            1,
        )

    monkeypatch.setattr("lawgraph.api.routes.instruments.get_articles", articles)
    body = client.get("/api/instruments/32016L0680/articles").json()
    assert seen == ["32016L0680"]
    assert body["bwb_id"] == "32016L0680" and body["total"] == 1
    assert body["items"][0]["celex"] == "32016L0680"
    assert body["items"][0]["bwb_id"] is None


def test_the_routes_are_in_the_schema() -> None:
    paths = app.openapi()["paths"]
    assert "/api/instruments/{identifier}" in paths
    assert "/api/instruments/{identifier}/eu-links" in paths
    schemas = app.openapi()["components"]["schemas"]
    assert "articles" not in schemas["EuLinkDTO"]["properties"]
    assert (
        "transposition signal"
        in schemas["EuLinkDTO"]["properties"]["basis"]["description"]
    )
    assert schemas["InstrumentArticlesResponse"]["properties"]["bwb_id"]["description"]
