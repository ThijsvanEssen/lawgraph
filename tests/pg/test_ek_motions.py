"""The page of a motion of the Eerste Kamer on its Kamerstuk: what it asks, its key data, and
its signers as members (``normalize eerstekamer-motions``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_EK_MOTION,
    RAW_KIND_EK_PERSON,
    SOURCE_EERSTEKAMER,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.normalize.eerstekamer_motions import (
    EerstekamerMotionsNormalizePipeline,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MOTION_PATH = "/motiedossier/37020_m_motie_beukering_fractie"
# Beukering's page (a sitting member: their birth date) in the form of the real pages
BEUKERING_PAGE = (
    "<html><head><title>A.J.A. Beukering - Eerste Kamer der Staten-Generaal</title></head>"
    "<body><p>Arjen Beukering (1959) is vanaf 13 juni 2023 lid van de Fractie-Beukering"
    " in de Eerste Kamer.</p><p>Personalia geboren te Utrecht, 4 maart 1959</p></body>"
    "</html>"
)


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _store(store: GraphStore) -> None:
    """The motion's Kamerstuk; Lagas a member by the composition's path, Beukering by birth
    date and surname; the other signers no member; another motion without a Kamerstuk."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {
                "_key": "ek_kst_1000001",
                "type": "document",
                "labels": ["EersteKamer", "EK"],
                "props": {
                    "kind": "Motie",
                    "number": "M",
                    "dossier_number": "37020",
                    "dossier_numbers": ["37020"],
                    "title": "Motie van het lid Beukering c.s.",
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(
                "lagas",
                "member",
                name="I.M. Lagas",
                external_id="tk-lagas",
                ek={"path": "/persoon/i_m_lagas_mdr_bbb"},
            ),
            _node(
                "beukering",
                "member",
                name="A.J.A. Beukering",
                external_id="tk-beukering",
                family_name="Beukering",
                birth_date="1959-03-04",
            ),
        ],
    )
    other = (
        (FIXTURES / "ek_motion_37020_m.html")
        .read_text()
        .replace("37.020, M", "37.020, Z")
    )
    with RawSourceWriter(store) as writer:
        for kind, path, page in (
            (
                RAW_KIND_EK_MOTION,
                MOTION_PATH,
                (FIXTURES / "ek_motion_37020_m.html").read_text(),
            ),
            (RAW_KIND_EK_MOTION, "/motiedossier/37020_z", other),
            (
                RAW_KIND_EK_PERSON,
                "/persoon/bgen_b_d_drs_a_j_a_beukering",
                BEUKERING_PAGE,
            ),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=kind,
                    external_id=path,
                    payload_text=page,
                    meta={"url": "https://www.eerstekamer.nl" + path},
                )
            )


def test_a_motion_page_writes_on_its_kamerstuk_with_its_signers(
    store: GraphStore,
) -> None:
    _store(store)
    EerstekamerMotionsNormalizePipeline(store=store).run()

    props = store.get_document("documents", "ek_kst_1000001")["props"]
    assert props["summary"].startswith("In deze motie wordt de regering verzocht")
    assert (props["submitted_on"], props["status"]) == ("2026-10-06", "verworpen")
    assert props["debate"] == "de Algemene Politieke Beschouwingen"
    assert props["motion_url"] == "https://www.eerstekamer.nl" + MOTION_PATH
    assert props["pdf_url"].endswith(".pdf")
    actors = [(a["name"], a["role"], a["person_id"]) for a in props["actors"]]
    assert actors[:2] == [
        ("A.J.A. Beukering", "Eerste ondertekenaar", "tk-beukering"),  # by birth date
        ("I.M. Lagas", "Mede ondertekenaar", "tk-lagas"),  # by the composition's path
    ]
    assert all(person_id is None for _, _, person_id in actors[2:])  # no member
    authored = set(
        store.query(
            "SELECT from_id || ' ' || (doc -> 'meta' ->> 'role') FROM edges"
            " WHERE relation = 'AUTHORED' AND to_id = 'documents/ek_kst_1000001'"
        )
    )
    assert authored == {
        "members/beukering Eerste ondertekenaar",
        "members/lagas Mede ondertekenaar",
    }

    # the API names the signers of a motion of the Eerste Kamer as those of the Tweede
    app.dependency_overrides[get_store] = lambda: store
    try:
        paper = TestClient(app).get("/api/documents/ek_kst_1000001").json()
        assert [(s["name"], s["role"], s["member_key"]) for s in paper["submitters"]][
            :2
        ] == [
            ("A.J.A. Beukering", "indiener", "tk_beukering"),
            ("I.M. Lagas", "medeindiener", "tk_lagas"),
        ]
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_retrieve_wants_each_motion_voted_on_once(store: GraphStore) -> None:
    """The pages of the motions the votes named (``motion_url``), those not stored yet."""
    from lawgraph.pipelines.retrieve.eerstekamer_motions import (
        EerstekamerMotionsRetrievePipeline,
    )

    site = "https://www.eerstekamer.nl"
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                f"ek_2026_10_06_37020_{letter.lower()}",
                "decision",
                chamber="EK",
                kind="Motie",
                date="2026-10-06",
                motion_url=f"{site}/motiedossier/37020_{letter.lower()}",
            )
            for letter in ("M", "J")
        ]
        + [_node("ek_2026_10_06_36920_1", "decision", chamber="EK", date="2026-10-06")],
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_MOTION,
                external_id="/motiedossier/37020_m",
                payload_text="<main></main>",
            )
        )
    pipeline = EerstekamerMotionsRetrievePipeline(store, client=object())  # type: ignore[arg-type]
    assert pipeline.wanted() == ["/motiedossier/37020_j"]
