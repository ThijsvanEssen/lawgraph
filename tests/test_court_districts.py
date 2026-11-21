"""The court map per municipality (``retrieve cbs``, ``normalize cbs``): the CBS table read by
the titles of its groups, the text of the Wet op de rechterlijke indeling read per article,
and how the two compare."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.clients.cbs import CbsClient
from lawgraph.config.constants import RAW_KIND_CBS_REGIONS, SOURCE_CBS
from lawgraph.config.sources import CBS
from lawgraph.core import court_districts as cd
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import court_districts as queries
from lawgraph.pipelines.normalize import cbs as normalize_cbs
from lawgraph.pipelines.normalize.cbs import CbsNormalizePipeline
from lawgraph.pipelines.retrieve.cbs import CbsRetrievePipeline
from tests.asserts import show_items
from tests.fakes import InMemoryStore, ScriptedSession, Sent
from tests.fakes.store import raw_record

# The articles as the RI writes them, shortened; Den Helder left out as in the consolidation.
ARTICLES = {
    "4": "1. Het arrondissement Noord-Holland omvat het grondgebied van de gemeenten "
    "Alkmaar, Bergen en Zaanstad. 2. Een tweede lid zonder belang.",
    "7": "Het arrondissement Midden-Nederland omvat het grondgebied van de provincies "
    "Flevoland en Utrecht alsmede de gemeenten Blaricum en Huizen.",
    "9": "Het arrondissement Oost-Brabant omvat het grondgebied van de gemeenten "
    "Nuenen, Gerwen en Nederwetten, Oss en Uden.",
    "10": "Het arrondissement Limburg omvat het grondgebied van de provincie Limburg.",
    "14": "Het ressort Amsterdam omvat de volgende arrondissementen: Noord-Holland.",
    "15": "Het ressort Arnhem-Leeuwarden omvat de volgende arrondissementen: "
    "Midden-Nederland.",
    "16": "Het ressort ’s-Hertogenbosch omvat de volgende arrondissementen: "
    "Limburg; Oost-Brabant.",
    "1": "Deze wet verstaat onder ... iets anders.",
}

# The columns of a table, keys of a year (they differ per year, the group titles do not).
GROUPS = {
    "G1": (cd.MUNICIPALITIES, "Code_1", "Naam_2"),
    "G2": (cd.DISTRICTS, "Code_33", "Naam_34"),
    "G3": (cd.CIRCUITS, "Code_35", "Naam_36"),
    "G4": (cd.PROVINCES, "Code_29", "Naam_30"),
}
PROPERTIES = [{"ID": 0, "Type": "Dimension", "Key": "RegioS", "Title": "Regio's"}] + [
    item
    for group, (title, code, name) in GROUPS.items()
    for item in (
        {"ID": group, "Type": "TopicGroup", "Title": title},
        {"ParentID": group, "Type": "Topic", "Key": code, "Title": "Code"},
        {"ParentID": group, "Type": "Topic", "Key": name, "Title": "Naam"},
    )
]
CIRCUIT = {
    "Amsterdam": "Gerechtshof Amsterdam",
    "Arnhem-Leeuwarden": "Gerechtshof Arnhem-Leeuwarden",
    "'s-Hertogenbosch": "Gerechtshof ’s-Hertogenbosch",
}
PLACES = [  # code, name, province, district, circuit
    ("GM0361", "Alkmaar", "Noord-Holland", "Noord-Holland", "Amsterdam"),
    ("GM0373", "Bergen (NH.)", "Noord-Holland", "Noord-Holland", "Amsterdam"),
    ("GM0893", "Bergen (L.)", "Limburg", "Limburg", "'s-Hertogenbosch"),
    ("GM0400", "Den Helder", "Noord-Holland", "Noord-Holland", "Amsterdam"),
    ("GM0406", "Huizen", "Noord-Holland", "Noord-Holland", "Amsterdam"),
    ("GM0344", "Utrecht", "Utrecht", "Midden-Nederland", "Arnhem-Leeuwarden"),
    (
        "GM0820",
        "Nuenen, Gerwen en Nederwetten",
        "Noord-Brabant",
        "Oost-Brabant",
        "'s-Hertogenbosch",
    ),
]


def _row(code: str, name: str, province: str, district: str, circuit: str) -> dict:
    return {
        "ID": 0,
        "RegioS": code,
        "Code_1": f"{code}  ",
        "Naam_2": f"{name}  ",
        "Code_29": "PV",
        "Naam_30": province,
        "Code_33": "AR",
        "Naam_34": district,
        "Code_35": "RE",
        "Naam_36": CIRCUIT[circuit],
    }


def _payload(year: int = 2026) -> dict[str, Any]:
    return {"year": year, "properties": PROPERTIES, "rows": [_row(*p) for p in PLACES]}


def _checked() -> dict[str, dict[str, Any]]:
    municipalities = cd.read_table(_payload())
    rows = cd.rows(2026, municipalities, cd.read_law(ARTICLES), checked=True)
    return {r["municipality_code"]: r for r in rows}


# ── reading ────────────────────────────────────────────────────────────────


def test_the_table_is_read_by_the_titles_of_its_groups() -> None:
    first = cd.read_table(_payload())[0]
    assert first == cd.Municipality(
        code="GM0361",
        name="Alkmaar",
        province="Noord-Holland",
        district="Noord-Holland",
        district_code="AR",
        circuit="Gerechtshof Amsterdam",
        circuit_code="RE",
    )


def test_a_table_without_the_ressorten_raises() -> None:
    properties = [p for p in PROPERTIES if p.get("ID") != "G3"]
    with pytest.raises(ValueError, match="Ressorten"):
        cd.read_table({"properties": properties, "rows": []})


def test_the_law_draws_provinces_municipalities_and_ressorten() -> None:
    law = cd.read_law(ARTICLES)
    assert set(law.districts) == {
        "Noord-Holland",
        "Midden-Nederland",
        "Oost-Brabant",
        "Limburg",
    }
    assert law.districts["Midden-Nederland"] == cd.LawDistrict(
        article="7",
        provinces=("Flevoland", "Utrecht"),
        municipalities="Blaricum en Huizen",
    )
    assert law.districts["Limburg"].provinces == ("Limburg",)
    assert law.circuits["'s-Hertogenbosch"] == ("16", ("Limburg", "Oost-Brabant"))


# ── comparing ──────────────────────────────────────────────────────────────


def test_a_name_with_a_comma_is_found_whole() -> None:
    row = _checked()["GM0820"]
    assert row["law_district"] == "Oost-Brabant"
    assert row["district_check"] == "agrees" and row["circuit_check"] == "agrees"
    assert row["district_article"] == "9" and row["circuit_article"] == "16"


def test_a_shared_name_goes_by_the_province_first() -> None:
    rows = _checked()
    assert rows["GM0373"]["law_district"] == "Noord-Holland"
    assert rows["GM0893"]["law_district"] == "Limburg"
    assert {rows[c]["district_check"] for c in ("GM0373", "GM0893")} == {"agrees"}


def test_a_municipality_by_its_province() -> None:
    assert _checked()["GM0344"]["law_district"] == "Midden-Nederland"


def test_the_gaps_are_shown_not_filled() -> None:
    rows = _checked()
    assert rows["GM0400"]["law_district"] is None
    assert rows["GM0400"]["district_check"] == "not_in_text"
    assert rows["GM0400"]["district_article"] == "4"  # the article of the CBS district
    assert rows["GM0406"]["law_district"] == "Midden-Nederland"
    assert rows["GM0406"]["district_check"] == "differs"


def test_an_unchecked_year_has_the_articles_and_no_checks() -> None:
    municipalities = cd.read_table(_payload(2020))
    rows = cd.rows(2020, municipalities, cd.read_law(ARTICLES), checked=False)
    checked = [r for r in rows if r["law_district"] or r["district_check"]]
    assert not checked, show_items(checked)
    assert rows[0]["district_article"] == "4" and rows[0]["circuit_article"] == "14"


# ── retrieve ───────────────────────────────────────────────────────────────

CATALOG = {
    "value": [
        {
            "Identifier": "70000NED",
            "Title": "Gebieden in Nederland 2012",
            "Modified": "",
        },
        {
            "Identifier": "86247NED",
            "Title": "Gebieden in Nederland 2026",
            "Modified": "2026-03-02T02:00:00",
        },
        {
            "Identifier": "85385NED",
            "Title": "Gebieden in Nederland 2025",
            "Modified": "2025-06-01T02:00:00",
        },
        {"Identifier": "99999NED", "Title": "Gebieden in Nederland; wijzigingen"},
    ]
}


def _client() -> CbsClient:
    table = f"{CBS.base_url}ODataApi/odata/86247NED"
    rows = [_row(*p) for p in PLACES]
    answers = {
        f"{CBS.base_url}ODataCatalog/Tables": CATALOG,
        f"{table}/DataProperties": {"value": PROPERTIES},
        f"{table}/TypedDataSet": {
            "value": rows[:3],
            "odata.nextLink": f"{table}/TypedDataSet?$skip=3",
        },
        f"{table}/TypedDataSet?$skip=3": {"value": rows[3:]},
    }

    def route(sent: Sent) -> Any:
        return answers[sent.url]

    return CbsClient(session=ScriptedSession(*[route] * len(answers)))


@pytest.mark.usefixtures("raw_reads")
def test_the_retrieve_stores_the_tables_that_changed_since_2013() -> None:
    store = InMemoryStore()
    store.insert_raw_sources(
        [raw_record(SOURCE_CBS, RAW_KIND_CBS_REGIONS, "85385NED")]  # stored after
    )
    records = list(CbsRetrievePipeline(store, client=_client()).fetch())

    assert [r.external_id for r in records] == ["86247NED"]
    (record,) = records
    assert record.payload_json["year"] == 2026
    assert len(record.payload_json["rows"]) == len(PLACES)  # both pages
    assert record.meta is not None and record.meta["modified"] == "2026-03-02"


# ── normalize ──────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("raw_reads")
def test_the_normalize_checks_this_year_and_fails_a_changed_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(queries, "article_texts", lambda store, bwb_id: ARTICLES)
    monkeypatch.setattr(queries, "write", lambda store, rows: written.append(rows))
    monkeypatch.setattr(normalize_cbs, "dutch_today", lambda: dt.date(2026, 11, 21))
    store = InMemoryStore()
    broken = {"year": 2024, "properties": PROPERTIES[:4], "rows": []}
    store.insert_raw_sources(
        [
            raw_record(SOURCE_CBS, RAW_KIND_CBS_REGIONS, e, payload_json=p)
            for e, p in (
                ("85385NED", _payload(2025)),
                ("86247NED", _payload(2026)),
                ("84000NED", broken),
            )
        ]
    )
    pipeline = CbsNormalizePipeline(store=store)
    result = PipelineResult()
    pipeline.write(pipeline.fetch_raw(), result)
    pipeline.add_outcomes(result)

    (rows,) = written
    assert {r["year"] for r in rows} == {2025, 2026}
    assert {r["year"] for r in rows if r["district_check"]} == {2026}
    assert result.updated == 2 * len(PLACES)
    assert result.skipped == 1 and "84000NED" in str(result.errors)
