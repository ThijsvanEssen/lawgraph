"""``GET /api/lookup`` on a real PostgreSQL: exactly the node a readable URL names, or 404
``not_in_data``; 422 for a parameter that is missing or malformed."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    put = store.bulk_insert_or_update_nodes
    put(
        "documents",
        [
            _node(
                "tk31",
                "document",
                ["TK"],
                dossier_number="36799",
                sequence=31,
                display_name="Motie",
            ),
            _node(
                "ek_kst_1",
                "document",
                ["EersteKamer", "EK"],
                dossier_number="36455",
                dossier_suffix="(R2188)",
                number="AB",
            ),
            _node(
                "tk8_3",
                "document",
                ["TK"],
                dossier_number="36600",
                dossier_suffix="VIII",
                sequence=3,
            ),
            _node("stb_stb_2010_350", "document", identifier="stb-2010-350"),
        ],
    )
    put(
        "dossiers",
        [
            _node("36799", "dossier", number="36799"),
            _node("36600_viii", "dossier", number="36600", suffix="VIII"),
        ],
    )
    put(
        "articles",
        [
            _node(
                "bwbr0005289_162", "article", bwb_id="BWBR0005289", article_number="162"
            ),
            _node("32016r0679_6", "article", celex="32016R0679", article_number="6"),
        ],
    )
    put(
        "instruments",
        [
            _node("bwbr0005289", "instrument", bwb_id="BWBR0005289"),
            _node(
                "stb_2016_288",
                "instrument",
                kind="publicatie",
                official_id="stb-2016-288",
            ),
        ],
    )
    put(
        "judgments",
        [
            _node(
                "ecli_nl_hr_2019_2006",
                "judgment",
                ecli="ECLI:NL:HR:2019:2006",
                text="long",
            ),
            _node(
                "ecli_nl_hr_1919_ag1776",
                "judgment",
                ecli="ECLI:NL:HR:1919:AG1776",
                stub=True,
            ),
            _node(
                "ecli_nl_x_1", "judgment", ecli="ECLI:NL:X:1", replaced_by="ECLI:NL:X:2"
            ),
        ],
    )
    put("commitments", [_node("tz", "commitment", number="TZ202609-011")])
    put("factions", [_node("sp", "faction", name="SP")])
    put("committees", [_node("c1", "committee", slug="justitie-en-veiligheid")])
    put("cabinets", [_node("schoof", "cabinet", name="kabinet-Schoof")])
    put(
        "annexes",
        [_node("bwbr0002741_annex_ii", "annex", bwb_id="BWBR0002741", label="II")],
    )
    put("cases", [_node("0a1b2c3d", "case", number="2025Z15468", kind="Motie")])
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


@pytest.mark.parametrize(
    ("params", "node_id", "kind"),
    [
        (
            {"kind": "document", "dossier": "36799", "number": "31"},
            "documents/tk31",
            "document",
        ),
        # the letter of the Eerste Kamer, any case, the suffix as the API writes it
        (
            {"kind": "document", "dossier": "36455-(R2188)", "number": "ab"},
            "documents/ek_kst_1",
            "document",
        ),
        (
            {"kind": "document", "dossier": "36600-VIII", "number": "3"},
            "documents/tk8_3",
            "document",
        ),
        ({"kind": "dossier", "number": "36600-VIII"}, "dossiers/36600_viii", "dossier"),
        (
            {"kind": "article", "law": "BWBR0005289", "number": "6:162"},
            "articles/bwbr0005289_162",
            "article",
        ),
        (
            {"kind": "article", "law": "bwbr0005289", "number": "162"},
            "articles/bwbr0005289_162",
            "article",
        ),
        (
            {"kind": "article", "law": "32016R0679", "number": "6"},
            "articles/32016r0679_6",
            "article",
        ),
        ({"kind": "law", "id": "BWBR0005289"}, "instruments/bwbr0005289", "instrument"),
        (
            {"kind": "judgment", "ecli": "ecli:nl:hr:2019:2006"},
            "judgments/ecli_nl_hr_2019_2006",
            "judgment",
        ),
        (
            {"kind": "publication", "series": "stb", "year": "2016", "number": "288"},
            "instruments/stb_2016_288",
            "instrument",
        ),
        (
            {"kind": "official", "id": "stb-2010-350"},
            "documents/stb_stb_2010_350",
            "document",
        ),
        ({"kind": "official", "id": "kst-36799-31"}, "documents/tk31", "document"),
        (
            {"kind": "commitment", "number": "tz202609-011"},
            "commitments/tz",
            "commitment",
        ),
        ({"kind": "faction", "id": "sp"}, "factions/sp", "faction"),
        (
            {"kind": "committee", "id": "justitie-en-veiligheid"},
            "committees/c1",
            "committee",
        ),
        ({"kind": "cabinet", "id": "schoof"}, "cabinets/schoof", "cabinet"),
        # an annex by its law and label, any case; a zaak by its number
        (
            {"kind": "annex", "law": "bwbr0002741", "label": "ii"},
            "annexes/bwbr0002741_annex_ii",
            "annex",
        ),
        ({"kind": "case", "number": "2025z15468"}, "cases/0a1b2c3d", "case"),
    ],
)
def test_each_kind_finds_its_node(
    client: TestClient, params: dict[str, str], node_id: str, kind: str
) -> None:
    response = client.get("/api/lookup", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["id"], body["kind"]) == (node_id, kind)


def test_the_answer_carries_what_the_url_is_built_back_from(client: TestClient) -> None:
    ek = client.get(
        "/api/lookup",
        params={"kind": "document", "dossier": "36455-(R2188)", "number": "AB"},
    ).json()
    assert ek["chamber"] == "EK"
    assert ek["props"] == {
        "dossier_number": "36455",
        "dossier_suffix": "(R2188)",
        "number": "AB",
    }
    publication = client.get(
        "/api/lookup", params={"kind": "official", "id": "stb-2016-288"}
    ).json()
    assert publication["props"]["official_id"] == "stb-2016-288"
    judgment = client.get(
        "/api/lookup", params={"kind": "judgment", "ecli": "ECLI:NL:HR:2019:2006"}
    ).json()
    assert judgment["props"] == {"ecli": "ECLI:NL:HR:2019:2006"}  # never its text
    annex = client.get(
        "/api/lookup", params={"kind": "annex", "law": "BWBR0002741", "label": "II"}
    ).json()
    assert annex["props"] == {"bwb_id": "BWBR0002741", "label": "II"}
    assert annex["path"] == "/wetten/BWBR0002741/bijlage/II"
    case = client.get(
        "/api/lookup", params={"kind": "case", "number": "2025Z15468"}
    ).json()
    assert (case["props"], case["path"]) == (
        {"number": "2025Z15468"},
        "/zaken/2025Z15468",
    )


def test_a_stub_and_a_replaced_judgment_are_answered(client: TestClient) -> None:
    stub = client.get(
        "/api/lookup", params={"kind": "judgment", "ecli": "ECLI:NL:HR:1919:AG1776"}
    ).json()
    assert stub["stub"] is True
    replaced = client.get(
        "/api/lookup", params={"kind": "judgment", "ecli": "ECLI:NL:X:1"}
    ).json()
    assert (replaced["stub"], replaced["props"]["replaced_by"]) == (
        False,
        "ECLI:NL:X:2",
    )


@pytest.mark.parametrize(
    "params",
    [
        # a paper that is not there is not its dossier
        {"kind": "document", "dossier": "36799", "number": "3"},
        {"kind": "dossier", "number": "99999"},
        {"kind": "article", "law": "BWBR0005289", "number": "999"},
        {"kind": "judgment", "ecli": "ECLI:NL:HR:2000:1"},
        {"kind": "official", "id": "h-tk-20252026-12-3"},
        {"kind": "faction", "id": "nope"},
        {"kind": "annex", "law": "BWBR0002741", "label": "IX"},
        {"kind": "annex", "law": "xyz", "label": "II"},
        {"kind": "case", "number": "2025Z99999"},
    ],
)
def test_what_is_not_in_the_data_is_404_not_in_data(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get("/api/lookup", params=params)
    assert (response.status_code, response.json()) == (404, {"detail": "not_in_data"})


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "document", "dossier": "36799"},
        {"kind": "article", "law": "BWBR0005289"},
        {"kind": "annex", "law": "BWBR0002741"},
        {"kind": "case"},
        {"kind": "publication", "series": "xyz", "year": "2016", "number": "1"},
        {"kind": "nothing", "id": "x"},
    ],
)
def test_a_missing_or_malformed_parameter_is_422(
    client: TestClient, params: dict[str, str]
) -> None:
    assert client.get("/api/lookup", params=params).status_code == 422


def test_a_paper_by_its_number_is_one_probe_of_an_index(
    client: TestClient, store: GraphStore
) -> None:
    """Of a budget dossier the props of thousands of papers were read for one lookup
    (1.8 s cold on prod): a number is looked up by the index on ``lg_document_light``."""
    from lawgraph.db.queries import lookup
    from lawgraph.db.store import _query

    ran: list[tuple[Any, Any]] = []
    stream = store._stream

    def recorded(statement: Any, params: Any, *a: Any, **k: Any) -> Any:
        ran.append((statement, params))
        return stream(statement, params, *a, **k)

    store._stream = recorded  # type: ignore[method-assign]
    try:
        assert lookup.find_document(store, "36799", "31") == "documents/tk31"
    finally:
        store._stream = stream  # type: ignore[method-assign]
    ((statement, params),) = ran
    with store.pool.connection() as conn:
        conn.execute("SET enable_seqscan = off")
        plan = conn.execute(
            b"EXPLAIN (FORMAT JSON) " + _query(statement).as_bytes(conn), params
        ).fetchone()[0]
    text = str(plan)
    assert "lg_document_light_paper" in text
    assert "'Relation Name': 'documents'" not in text
