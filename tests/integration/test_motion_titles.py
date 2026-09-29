"""A motie or amendement is named by its own subject, not by its dossier, and its text is
retrieved; a record the Tweede Kamer deleted is no node."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from tests.integration.seed import FIXTURES, uid

DOSSIER_TITLE = "Rechtsstaat en Rechtsorde"
DOSSIER = {"Id": uid(1, 3), "Nummer": 29279, "Toevoeging": None, "Titel": DOSSIER_TITLE}
FABER, ELLIAN = uid(1, 9), uid(2, 9)
PVV, VVD = uid(1, 8), uid(2, 8)
MOTION_SUBJECT = (
    "Motie van het lid Faber over wettelijk regelen dat de politie altijd de "
    "bevoegdheid heeft om preventief te fouilleren"
)
AMENDMENT_SUBJECT = "Amendement van het lid Ellian over de bewaartermijn"


def _zaak(number: int, kind: str, subject: str) -> dict[str, Any]:
    return {
        "Id": uid(number, 2),
        "Nummer": f"2026Z1828{number}",
        "Soort": kind,
        "Titel": DOSSIER_TITLE,
        "Onderwerp": subject + " ",
        "Kamerstukdossier": [{"Id": DOSSIER["Id"], "Nummer": 29279}],
    }


def _signature(person: str, faction: str, name: str, role: str) -> dict[str, Any]:
    return {
        "Persoon_Id": person,
        "Fractie_Id": faction,
        "ActorNaam": name,
        "ActorFractie": "PVV" if faction == PVV else "VVD",
        "Functie": "Tweede Kamerlid",
        "Relatie": role,
    }


def _document(number: int, kind: str, subject: str, signatures: list) -> dict:
    zaak = _zaak(number, kind, subject)
    return {
        "Id": uid(number, 1),
        "DocumentNummer": f"2026D4583{number}",
        "Soort": kind,
        "Titel": DOSSIER_TITLE,
        "Onderwerp": subject + " ",
        "Datum": "2026-09-10T00:00:00+02:00",
        "Volgnummer": 1300 + number,
        "Verwijderd": False,
        # The Zaak as the Document expansion gives it: without its Onderwerp.
        "Zaak": [
            {
                **{k: zaak[k] for k in ("Id", "Nummer", "Soort", "Titel")},
                "Kamerstukdossier": [DOSSIER],
            }
        ],
        "DocumentActor": signatures,
    }


def _deleted(record_id: str) -> dict[str, Any]:
    """A record the Tweede Kamer deleted: its id and nothing else, as the API sends it."""
    return {
        "Id": record_id,
        "Soort": None,
        "Titel": None,
        "Onderwerp": None,
        "Datum": None,
        "GewijzigdOp": "2026-09-16T14:20:51.093+02:00",
        "Verwijderd": True,
        "Zaak": [],
        "DocumentActor": [],
    }


MOTION = _document(
    1,
    "Motie",
    MOTION_SUBJECT,
    [
        _signature(ELLIAN, VVD, "I. Ellian", "Mede ondertekenaar"),
        _signature(FABER, PVV, "M.H.M. Faber-van de Klashorst", "Eerste ondertekenaar"),
    ],
)
AMENDMENT = _document(
    2,
    "Amendement",
    AMENDMENT_SUBJECT,
    [_signature(ELLIAN, VVD, "I. Ellian", "Eerste ondertekenaar")],
)
LETTER_SUBJECT = "Voortgang aanpak ondermijning"
LETTER = {
    **_document(3, "Brief regering", LETTER_SUBJECT, []),
    "Zaak": [],
}
LETTER_CASE = _zaak(5, "Brief regering", LETTER_SUBJECT)
# Papers whose Onderwerp names only their kind: they keep the title of the dossier.
BILL = {**_document(6, "Voorstel van wet", "Voorstel van wet", []), "Zaak": []}
NOTICE = {**_document(7, "Mededeling", "Mededeling", []), "Zaak": []}
GONE = _document(4, "Motie", "Motie van het lid Faber over iets anders", [])
GONE_CASE = _zaak(4, "Motie", "Motie van het lid Faber over iets anders")
GONE_ACTIVITY = {
    "Id": uid(4, 6),
    "Soort": "Plenair debat",
    "Onderwerp": "Debat over de rechtsstaat",
    "Datum": "2026-09-09T00:00:00+02:00",
    "Verwijderd": False,
    "Agendapunt": [],
}


def _write(store: ArangoStore, records: list[tuple[str, dict[str, Any]]]) -> None:
    with RawSourceWriter(store) as writer:
        for kind, payload in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )


def _records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (RAW_KIND_TK_DOSSIER, DOSSIER),
        (RAW_KIND_TK_FRACTIE, {"Id": PVV, "Afkorting": "PVV", "NaamNL": "PVV"}),
        (RAW_KIND_TK_FRACTIE, {"Id": VVD, "Afkorting": "VVD", "NaamNL": "VVD"}),
        (RAW_KIND_TK_PERSOON, {"Id": FABER, "Voornamen": "M.", "Achternaam": "Faber"}),
        (
            RAW_KIND_TK_PERSOON,
            {"Id": ELLIAN, "Voornamen": "I.", "Achternaam": "Ellian"},
        ),
        (RAW_KIND_TK_ZAAK, _zaak(1, "Motie", MOTION_SUBJECT)),
        (RAW_KIND_TK_ZAAK, _zaak(2, "Amendement", AMENDMENT_SUBJECT)),
        (RAW_KIND_TK_ZAAK, GONE_CASE),
        (RAW_KIND_TK_ZAAK, LETTER_CASE),
        (RAW_KIND_TK_DOCUMENT, MOTION),
        (RAW_KIND_TK_DOCUMENT, AMENDMENT),
        (RAW_KIND_TK_DOCUMENT, LETTER),
        (RAW_KIND_TK_DOCUMENT, BILL),
        (RAW_KIND_TK_DOCUMENT, NOTICE),
        (RAW_KIND_TK_DOCUMENT, GONE),
        (RAW_KIND_TK_ACTIVITEIT, GONE_ACTIVITY),
    ]


def test_a_motion_is_named_by_its_subject_with_its_submitters(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _write(store, _records())
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        motion = client.get(f"/api/documents/{make_node_key(MOTION['Id'])}").json()
        assert motion["title"] == MOTION_SUBJECT
        assert motion["submitters"] == [
            {
                "name": "M.H.M. Faber-van de Klashorst",
                "faction": "PVV",
                "member_key": make_node_key(FABER),
                "role": "indiener",
            },
            {
                "name": "I. Ellian",
                "faction": "VVD",
                "member_key": make_node_key(ELLIAN),
                "role": "medeindiener",
            },
        ]
        amendment = client.get(
            f"/api/documents/{make_node_key(AMENDMENT['Id'])}"
        ).json()
        assert amendment["title"] == AMENDMENT_SUBJECT
        assert [s["name"] for s in amendment["submitters"]] == ["I. Ellian"]

        # A letter is named by its own subject too, and has no submitters; so is its case.
        letter = client.get(f"/api/documents/{make_node_key(LETTER['Id'])}").json()
        assert (letter["title"], letter["submitters"]) == (LETTER_SUBJECT, [])
        letter_case = client.get(
            f"/api/nodes/cases/{make_node_key(LETTER_CASE['Id'])}"
        ).json()
        assert letter_case["node"]["props"]["title"] == LETTER_SUBJECT

        # A paper whose subject is its kind keeps the title of the dossier.
        for paper in (BILL, NOTICE):
            response = client.get(f"/api/documents/{make_node_key(paper['Id'])}")
            assert response.json()["title"] == DOSSIER_TITLE, paper["Soort"]

        # The case of a motie is named by it too: a decision on a day of seven moties
        # names seven different cases.
        case = client.get(f"/api/nodes/cases/{make_node_key(uid(1, 2))}").json()
        assert case["node"]["props"]["title"] == MOTION_SUBJECT

        # The dossier keeps its own title.
        dossier = client.get("/api/nodes/dossiers/29279").json()
        assert dossier["node"]["props"]["title"] == DOSSIER_TITLE

        # The Kamer deletes a motie, its case and an activity: each becomes a record with
        # an id and nothing else. The next run takes their nodes and edges away.
        _write(
            store,
            [
                (RAW_KIND_TK_DOCUMENT, _deleted(GONE["Id"])),
                (RAW_KIND_TK_ZAAK, _deleted(GONE_CASE["Id"])),
                (RAW_KIND_TK_ACTIVITEIT, _deleted(GONE_ACTIVITY["Id"])),
            ],
        )
        cli("normalize", "tk")
        cli("normalize", "tk-dossiers")

        assert (
            client.get(f"/api/documents/{make_node_key(GONE['Id'])}").status_code == 404
        )
        for collection, key in (
            ("cases", GONE_CASE["Id"]),
            ("activities", GONE_ACTIVITY["Id"]),
        ):
            response = client.get(f"/api/nodes/{collection}/{make_node_key(key)}")
            assert response.status_code == 404, collection
        dangling = store.query(
            "FOR e IN edges FILTER e._from IN @ids OR e._to IN @ids RETURN e._key",
            {
                "ids": [
                    f"documents/{make_node_key(GONE['Id'])}",
                    f"cases/{make_node_key(GONE_CASE['Id'])}",
                ]
            },
        )
        assert list(dangling) == []
        kinds = list(store.query("FOR d IN documents RETURN d.props.kind"))
        assert len(kinds) == 5 and all(kinds)
    finally:
        app.dependency_overrides.pop(get_store, None)


class _Repository:
    """The KOOP repository: the XML of the motie, HTTP 404 for any other paper."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch_kamerstuk_xml(self, identifier: str) -> str | None:
        self.fetched.append(identifier)
        if identifier == "kst-29279-1301":
            return (FIXTURES / "kst_35786_7.xml").read_text(encoding="utf-8")
        return None


def test_the_text_of_a_motion_is_retrieved_by_default(database: str, cli: Any) -> None:
    store = ArangoStore()
    _write(store, _records())
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    repository = _Repository()
    TKContentRetrievePipeline(store=store, client=repository).run()  # type: ignore[arg-type]
    # The moties and amendementen are asked for, the letter is not.
    assert sorted(repository.fetched) == [
        "kst-29279-1301",
        "kst-29279-1302",
        "kst-29279-1304",
    ]
    cli("normalize", "tk-content")

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        motion = client.get(f"/api/documents/{make_node_key(MOTION['Id'])}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert motion["text"].startswith("MOTIE VAN HET LID VAN DER GRAAF C.S.\nDe Kamer,")
    assert motion["title"] == MOTION_SUBJECT
