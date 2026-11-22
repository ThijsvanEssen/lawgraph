"""``semantic tk-dossier-eu``: the COM documents a dossier is about and the EU acts it
implements, stored on the dossier; ``GET /api/dossiers`` filters on them (``eu``,
``celex``)."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries.dossier_filters import DossierFilters
from lawgraph.db.queries.dossiers import get_dossiers
from lawgraph.pipelines.semantic.tk_dossier_eu import TKDossierEuSemanticPipeline
from tests.asserts import assert_status
from tests.databases import Api


def _dossier(key: str, title: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": "dossier",
        "labels": [],
        "props": {"number": key, "label": key, "title": title},
    }


def _instrument(key: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "type": "instrument", "labels": [], "props": props}


def _edge(key: str, from_id: str, to_id: str, relation: str, meta: Any) -> Any:
    return {
        "key": key,
        "from_id": from_id,
        "to_id": to_id,
        "relation": relation,
        "source": "test",
        "meta": meta,
    }


def _graph(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _dossier("36982", "EU-voorstel: Omnibus over belastingen COM (2026) 560"),
            _dossier(
                "36712", "EU-voorstellen: Omnibus I COM (2025) 80 en COM (2025) 81"
            ),
            _dossier(
                "36930",
                "Wijziging van de Wet op het financieel toezicht ter implementatie van "
                "Richtlijn (EU) 2024/2811 (Implementatiewet noteringen)",
            ),
            _dossier("35000", "Wet bescherming klokkenluiders"),
            _dossier("36100", "Begroting Defensie 2027"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _instrument("52025PC0080", {"celex": "52025PC0080", "source": "eurlex"}),
            _instrument("32019L1937", {"celex": "32019L1937", "source": "eurlex"}),
            _instrument("BWBR0045000", {"bwb_id": "BWBR0045000", "source": "bwb"}),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("l1", "instruments/BWBR0045000", "dossiers/35000", "LEGISLATED_IN", {}),
            _edge(
                "i1",
                "instruments/BWBR0045000",
                "instruments/32019L1937",
                "IMPLEMENTS",
                {"bases": ["national_implementing_measure"]},
            ),
        ]
    )  # fmt: skip


def _props(store: GraphStore, key: str) -> dict[str, Any]:
    return dict(store.get_document("dossiers", key)["props"])  # type: ignore[index]


def test_the_step_stores_eu_ref_and_implements(store: GraphStore) -> None:
    _graph(store)
    result = TKDossierEuSemanticPipeline(store).run()
    assert result.updated == 4
    assert _props(store, "36982")["eu_ref"] == [{"com": "COM(2026) 560", "celex": None}]
    assert _props(store, "36712")["eu_ref"] == [
        {"com": "COM(2025) 80", "celex": "52025PC0080"},
        {"com": "COM(2025) 81", "celex": None},
    ]
    assert _props(store, "36930")["implements"] == [
        {"celex": "32024L2811", "bases": ["title"]}
    ]
    assert _props(store, "35000")["implements"] == [
        {"celex": "32019L1937", "bases": ["national_implementing_measure"]}
    ]
    # a dossier that says nothing of the EU gets no key
    assert "eu_ref" not in _props(store, "36100")
    # a second run has nothing left to write
    assert TKDossierEuSemanticPipeline(store).run().updated == 0


def test_a_title_that_no_longer_names_it_clears_it(store: GraphStore) -> None:
    _graph(store)
    TKDossierEuSemanticPipeline(store).run()
    store.bulk_insert_or_update_nodes(
        "dossiers", [_dossier("36982", "Omnibus over belastingen")]
    )
    assert TKDossierEuSemanticPipeline(store).run().updated == 1
    assert _props(store, "36982")["eu_ref"] is None


def _keys(store: GraphStore, **filters: Any) -> list[str]:
    page = get_dossiers(store, DossierFilters(**filters), sort="title", facets=False)
    return sorted(item["key"] for item in page["items"])


def test_the_list_filters_on_eu_and_celex(store: GraphStore) -> None:
    _graph(store)
    TKDossierEuSemanticPipeline(store).run()
    assert _keys(store, eu="proposal") == ["36712", "36982"]
    assert _keys(store, eu="implementation") == ["35000", "36930"]
    assert _keys(store, celex="32019L1937") == ["35000"]
    assert _keys(store, celex="52025PC0080") == ["36712"]
    assert _keys(store, celex="32016R0679") == []


def test_the_api_lists_eu_proposals_with_their_ref(store: GraphStore, api: Api) -> None:
    _graph(store)
    TKDossierEuSemanticPipeline(store).run()
    body = api.get("/api/dossiers?eu=proposal&sort=title&facets=false").json()
    assert body["total"] == 2
    first = {item["number"]: item for item in body["items"]}["36712"]
    assert first["eu_ref"][0] == {"com": "COM(2025) 80", "celex": "52025PC0080"}
    assert first["implements"] == []
    body = api.get("/api/dossiers?celex=32024L2811&facets=false").json()
    assert [i["implements"] for i in body["items"]] == [
        [{"celex": "32024L2811", "bases": ["title"]}]
    ]
    assert_status(api.get("/api/dossiers?eu=other"), 422)
