"""Which Dutch law implements which EU act, on trimmed real XML of the Awb (BWBR0005537) and
the UAVG (BWBR0040940) and national implementing measures as CELLAR records them: the real
``normalize bwb``, ``normalize bwb-history``, ``semantic bwb-amendments`` and ``semantic
bwb-implements``, then the API.

- The UAVG implements the GDPR: its considerans says "ter uitvoering van Verordening (EU)
  2016/679"; Richtlijn 95/46/EG, which the title of the GDPR repeals, it does not.
- The Awb names EMIR (648/2012) in bijlage 2: a reference, not an implementation.
- EUR-Lex lists the Awb itself (Stb. 1992, 315) as a measure implementing the European
  electronic communications code (2018/1972): the Awb implements it.
- A measure that made a version of an article (Stb. 2022, 332, which gave the Grondwet its
  Algemene bepaling; the measure is made for the test) implements an act: the publication
  and the regulation it changed implement it.
- A second run changes nothing, and an IMPLEMENTS from a mention alone (as it was written
  before) goes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_EU_NIM,
    RELATION_IMPLEMENTS,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AWB, UAVG, GW = "BWBR0005537", "BWBR0040940", "BWBR0001840"
GDPR, DPD, EMIR, EECC, SRM = (
    "32016R0679",
    "31995L0046",
    "32012R0648",
    "32018L1972",
    "32014R0806",
)
_STAATSBLAD = "Staatsblad (Bulletin des Lois et des Décrets royaux)"
# As CELLAR records them; the second is made for the test (a measure changing the Grondwet).
MEASURES = [
    {
        "id": "202205778",
        "modified": "2022-09-15T10:04:45.876+02:00",
        "celex": [EECC],
        "journal": _STAATSBLAD,
        "number": "315",
        "date": "1992-06-30",
        "type": "Wet",
        "title": "Wet van 4 juni 1992, houdende algemene regels van bestuursrecht",
    },
    {
        "id": "900000001",
        "modified": "2024-01-01T00:00:00+01:00",
        "celex": [SRM],
        "journal": _STAATSBLAD,
        "number": "332",
        "date": "2022-08-30",
        "type": "Wet",
        "title": "Wet van 6 juli 2022 houdende verandering in de Grondwet",
    },
    {
        "id": "900000002",
        "modified": "2024-01-01T00:00:00+01:00",
        "celex": [GDPR],
        "journal": "Administrative measures",
        "number": "17708",
        "type": "Bekendmaking",
    },
]


def _seed(store: GraphStore) -> None:
    with RawSourceWriter(store) as writer:
        for bwb_id, fixture in (
            (AWB, "bwb_awb_annexes_toestand.xml"),
            (UAVG, "bwb_uavg_toestand.xml"),
            (GW, "bwb_grondwet_toestand.xml"),
        ):
            xml = (FIXTURES / fixture).read_text()
            meta = {"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}.xml"}
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=xml,
                    meta=meta,
                )
            )
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=f"{bwb_id}@2024-01-01",
                    payload_text=xml,
                    meta={**meta, "start_date": "2024-01-01", "end_date": "9999-12-31"},
                )
            )
        for measure in MEASURES:
            writer.add(
                raw_source_doc(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EU_NIM,
                    external_id=measure["id"],
                    payload_json=measure,
                    meta={"country": "NLD"},
                )
            )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": celex.lower(),
                "type": "instrument",
                "labels": ["EU"],
                "props": {"celex": celex, "jurisdiction": "eu", "source": "eurlex"},
            }
            for celex in (GDPR, DPD, EMIR, EECC, SRM)
        ],
    )
    # what the step wrote before: an IMPLEMENTS for every CELEX number named
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "instruments/bwbr0005537",
                "instruments/32012r0648",
                RELATION_IMPLEMENTS,
                source="bwb-implements-directive",
                confidence=0.75,
                meta={"celex": EMIR},
            )
        ]
    )


def _links(store: GraphStore) -> dict[tuple[str, str, str], dict[str, Any]]:
    statement = """
    SELECT from_id, to_id, relation, doc -> 'meta' AS meta FROM edges
    WHERE relation IN ('IMPLEMENTS', 'REFERS_TO') AND from_collection = 'instruments'
    """
    return {
        (e["from_id"].split("/")[1], e["relation"], e["to_id"].split("/")[1]): e["meta"]
        for e in store.query(statement)
    }


@pytest.fixture()
def store(database: str, cli: Any) -> GraphStore:
    store = GraphStore()
    _seed(store)
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("semantic", "bwb-amendments")
    cli("semantic", "bwb-implements")
    return store


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_considerans_says_what_a_uitvoeringswet_implements(
    store: GraphStore,
) -> None:
    links = _links(store)
    assert links[("bwbr0040940", "IMPLEMENTS", "32016r0679")] == {
        "celex": GDPR,
        "bases": ["considerans"],
    }
    assert not any(
        source == "bwbr0040940" and target == "31995l0046"
        for source, _, target in links
    )


def test_an_act_named_in_the_text_is_a_reference(store: GraphStore) -> None:
    links = _links(store)
    assert ("bwbr0005537", "IMPLEMENTS", "32012r0648") not in links
    assert links[("bwbr0005537", "REFERS_TO", "32012r0648")] == {"celex": EMIR}


def test_a_measure_of_eur_lex_implements(store: GraphStore) -> None:
    links = _links(store)
    # the Awb as enacted
    assert links[("bwbr0005537", "IMPLEMENTS", "32018l1972")] == {
        "celex": EECC,
        "bases": ["national_implementing_measure"],
        "publications": ["stb-1992-315"],
        "measures": [
            {
                "publication": "stb-1992-315",
                "citation": "Stb. 1992, 315",
                "title": "Wet van 4 juni 1992, houdende algemene regels van bestuursrecht",
                "type": "Wet",
            }
        ],
    }
    # the publication that made a version of an article, and the regulation it changed
    srm = {
        "celex": SRM,
        "bases": ["national_implementing_measure"],
        "publications": ["stb-2022-332"],
        "measures": [
            {
                "publication": "stb-2022-332",
                "citation": "Stb. 2022, 332",
                "title": "Wet van 6 juli 2022 houdende verandering in de Grondwet",
                "type": "Wet",
            }
        ],
    }
    assert links[("stb_2022_332", "IMPLEMENTS", "32014r0806")] == srm
    assert links[("bwbr0001840", "IMPLEMENTS", "32014r0806")] == srm
    # the Awb names SRM and implements it not: a reference
    assert ("bwbr0005537", "IMPLEMENTS", "32014r0806") not in links
    assert links[("bwbr0005537", "REFERS_TO", "32014r0806")] == {"celex": SRM}
    # a measure outside the Staatsblad and the Staatscourant names no publication
    assert not any(
        target == "32016r0679" and source != "bwbr0040940"
        for source, _, target in links
    )


def test_a_second_run_changes_nothing(store: GraphStore, cli: Any) -> None:
    before = _links(store)
    cli("semantic", "bwb-implements")
    assert _links(store) == before


def test_the_eu_links_of_a_law(client: TestClient) -> None:
    body = client.get(f"/api/instruments/{AWB}/eu-links").json()
    implements = {
        link["instrument"]["celex"]: link["bases"] for link in body["implements"]
    }
    assert implements == {EECC: ["national_implementing_measure"]}
    [eecc] = body["implements"]
    assert [m["citation"] for m in eecc["via"]] == ["Stb. 1992, 315"]
    grondwet = client.get("/api/instruments/BWBR0001840/eu-links").json()
    [srm] = grondwet["implements"]
    assert srm["via"] == [
        {
            "publication": "stb-2022-332",
            "citation": "Stb. 2022, 332",
            "title": "Wet van 6 juli 2022 houdende verandering in de Grondwet",
            "type": "Wet",
        }
    ]
    assert {link["instrument"]["celex"] for link in body["mentions"]} == {EMIR, SRM}
    down = client.get(f"/api/instruments/{GDPR}/eu-links").json()
    assert [link["instrument"]["bwb_id"] for link in down["implemented_by"]] == [UAVG]
