"""The seats of the Eerste Kamer per term and stretch (``normalize eerstekamer-mutations``) on
a real PostgreSQL, from the real pages: the Kiesraad's result of 2023, the changes of the
current term and the composition of today."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EK_COMPOSITION,
    RAW_KIND_EK_MUTATION,
    RAW_KIND_EK_MUTATIONS,
    RAW_KIND_KIESRAAD_EK_RESULT,
    SOURCE_EERSTEKAMER,
    SOURCE_KIESRAAD,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import ek_seats
from lawgraph.db.store import raw_source_doc
from lawgraph.pipelines.normalize.eerstekamer_mutations import (
    EerstekamerMutationsNormalizePipeline,
    installed_on,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EK = FIXTURES / "eerstekamer"


def _store_pages(store: GraphStore) -> None:
    docs = [
        raw_source_doc(
            source=SOURCE_KIESRAAD,
            kind=RAW_KIND_KIESRAAD_EK_RESULT,
            external_id="EK20230530",
            payload_text=(FIXTURES / "kiesraad" / "EK20230530.html").read_text("utf-8"),
            meta={"url": "https://www.verkiezingsuitslagen.nl/verkiezingen/detail/EK20230530",
                  "read_on": "2026-10-10"},
        ),
        raw_source_doc(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EK_MUTATIONS,
            external_id="/personele_mutaties",
            payload_text=(EK / "personele_mutaties_2023.html").read_text("utf-8"),
        ),
        raw_source_doc(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EK_COMPOSITION,
            external_id="/fracties",
            payload_text=(EK / "fracties_2026.html").read_text("utf-8"),
        ),
        raw_source_doc(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EK_COMPOSITION,
            external_id="/fractie/progressief_nederland_pro",
            payload_text=(EK / "fractie_progressief_nederland_pro.html").read_text("utf-8"),
        ),
    ]  # fmt: skip
    for item in json.loads((EK / "articles_2023.json").read_text("utf-8")):
        page = (
            f"<html><body>Nieuwsoverzicht {item['text']} Terug naar boven</body></html>"
        )
        docs.append(
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_MUTATION,
                external_id=item["path"],
                payload_text=page,
                meta={"date": item["date"], "headline": item["headline"]},
            )
        )
    store.insert_raw_sources(docs)


def test_installed_two_weeks_after_the_week_of_the_election() -> None:
    assert [
        installed_on(day)
        for day in (
            "2003-05-26",
            "2007-05-29",
            "2011-05-23",
            "2015-05-26",
            "2019-05-27",
            "2023-05-30",
        )
    ] == [
        "2003-06-10",
        "2007-06-12",
        "2011-06-07",
        "2015-06-09",
        "2019-06-11",
        "2023-06-13",
    ]


@pytest.fixture()
def walked(store: GraphStore) -> GraphStore:
    _store_pages(store)
    EerstekamerMutationsNormalizePipeline(store=store).run()
    return store


def test_the_term_from_the_kiesraad_is_checked_against_today(
    walked: GraphStore,
) -> None:
    (term,) = list(walked.query("SELECT * FROM lg_ek_terms"))
    assert term["start"] == "2023-06-13"
    assert term["election"] == "EK20230530"
    assert term["checked"] is True, term["mismatches"]
    assert term["source"]["kiesraad"]["url"].endswith("EK20230530")
    assert term["source"]["kiesraad"]["read_on"] == "2026-10-10"


def test_a_stretch_per_day_the_seats_changed(walked: GraphStore) -> None:
    stretches = ek_seats.stretches_between(walked, "2023-01-01", "2030-12-31")
    assert len(stretches) == 24
    first, last = stretches[0], stretches[-1]
    assert first["from_date"] == "2023-06-13"
    assert first["seats"]["BBB"] == 16
    assert first["seats"]["GroenLinks-PvdA"] == 14  # the two lists, one faction
    assert last["to_date"] is None
    assert last["seats"]["PRO"] == 14
    assert sum(last["seats"].values()) == 75
    assert all(s["checked"] for s in stretches)
    # Klopman gone on 5 July, his successor sworn in on 11 July: BBB one short between
    klopman = next(s for s in stretches if s["from_date"] == "2023-07-05")
    assert klopman["seats"]["BBB"] == 15 and klopman["to_date"] == "2023-07-10"
    (event,) = klopman["events"]
    assert (event["kind"], event["basis"], event["words"]) == (
        "vertrek",
        "tekst",
        "Jan Klopman vertrekt uit de Eerste Kamer",
    )


def test_the_stretches_of_a_period(walked: GraphStore) -> None:
    inside = ek_seats.stretches_between(walked, "2025-06-01", "2025-06-30")
    assert [s["from_date"] for s in inside] == ["2025-05-20", "2025-06-03"]


def test_the_seats_of_the_eerste_kamer_on_a_day(walked: GraphStore) -> None:
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    app.dependency_overrides[get_store] = lambda: walked
    try:
        client = TestClient(app)
        july = client.get(
            "/api/parliament/seats", params={"chamber": "EK", "date": "2023-07-06"}
        ).json()
        before = client.get(
            "/api/parliament/seats", params={"chamber": "EK", "date": "2020-01-01"}
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    seats = {f["abbreviation"]: f["seats"] for f in july["factions"]}
    # Klopman gone on 5 July, Van Gasteren not yet sworn in
    assert seats["BBB"] == 15 and seats["GroenLinks-PvdA"] == 14
    assert july["assigned_seats"] == 74
    assert july["checked"] is True
    assert july["source"]["composition_date"] == "2023-07-05"
    # a faction of the past has no node: no key
    assert (
        next(f for f in july["factions"] if f["abbreviation"] == "GroenLinks-PvdA")[
            "key"
        ]
        is None
    )
    assert before.status_code == 404


def test_the_counts_of_the_ops_script_read(walked: GraphStore) -> None:
    """``ops/ek-seats-counts.sql`` runs on the tables it counts (its psql lines aside)."""
    sql = (
        Path(__file__).resolve().parents[2] / "ops" / "ek-seats-counts.sql"
    ).read_text()
    queries = [
        q.strip()
        for q in "\n".join(
            line
            for line in sql.splitlines()
            if not line.startswith(("\\", "--", "SET"))
        ).split(";")
        if q.strip()
    ]
    terms, mismatches, cabinets = (list(walked.query(q)) for q in queries)
    assert [(t["start"], t["checked"], t["stretches"]) for t in terms] == [
        ("2023-06-13", True, 24)
    ]
    assert mismatches == [] and cabinets == []
