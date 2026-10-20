"""A treaty in the BWB and in the Verdragenbank is one treaty by its number, for real.

The BWB text of a treaty names its Verdragenbank id (``wetgeving@verdragnummer``), and the
Verdragenbank record is that id: ``normalize bwb`` and ``normalize verdragenbank`` write it
as ``treaty_number``, and the instrument detail names the other instrument of the number.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.commands.check import check
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_VERDRAGENBANK_JSON,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden


def _toestand(bwb_id: str, number: str | None, title: str) -> str:
    attribute = f' verdragnummer="{number}"' if number else ""
    return (
        f'<toestand bwb-id="{bwb_id}" inwerkingtreding="1998-11-01">'
        f'<wetgeving soort="verdrag"{attribute}>'
        f"<intitule>{title}</intitule>"
        "<verdrag><artikel><kop><label>Artikel</label><nr>1</nr></kop>"
        "<al>De Hoge Verdragsluitende Partijen verzekeren een ieder.</al></artikel>"
        "</verdrag></wetgeving></toestand>"
    )


# BWB id, treaty number (None: the toestand names none), title
BWB_TREATIES = [
    ("BWBV0001000", "005132", "Verdrag tot bescherming van de rechten van de mens"),
    (
        "BWBV0002060",
        "000462",
        "Akkoord tussen de Nederlandse Minister van Sociale Zaken",
    ),
    ("BWBV0009999", None, "Een verdrag zonder nummer"),
]


def _verdrag(number: str, title: str) -> dict[str, Any]:
    return {
        "uri": f"https://verdragenbank.overheid.nl/nl/Verdrag/Details/{number}",
        "title": title,
        "title_nl": title,
        "title_en": None,
        "date_signed": "1950-11-04",
        "date_in_force": "1953-09-03",
        "treaty_type": "Multilateraal",
        "status": "Inwerkinggetreden",
        "verdragsnummer": number,
    }


# The tests read one database built for them all (``store``), on the worker that built it;
# the ones that write have a database of their own (``database``).
pytestmark = pytest.mark.xdist_group("treaty_numbers")


def _build(store: GraphStore, cli: Any) -> None:
    write_toestanden(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND,
                bwb_id,
                _toestand(bwb_id, number, title),
                {"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}.xml"},
            )
            for bwb_id, number, title in BWB_TREATIES
        ],
    )
    with RawSourceWriter(store) as writer:
        for number, title in (
            (
                "005132",
                "Verdrag tot bescherming van de rechten van de "
                "mens en de fundamentele vrijheden",
            ),
            ("001610", "Ander"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAGENBANK_JSON,
                    external_id=number,
                    payload_json=_verdrag(number, title),
                )
            )
    cli("normalize", "bwb")
    cli("normalize", "verdragenbank")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _build(store, cli)
        yield store


def test_a_bwb_treaty_and_its_verdragenbank_record_name_each_other(api: Api) -> None:
    bwb = api.get_json("/api/instruments/BWBV0001000")
    assert bwb["treaty_number"] == "005132"
    assert [other["key"] for other in bwb["same_treaty"]] == ["verdrag_005132"]

    record = api.get_json("/api/instruments/verdrag_005132")
    assert record["treaty_number"] == "005132"
    assert [other["bwb_id"] for other in record["same_treaty"]] == ["BWBV0001000"]


def test_a_treaty_without_a_counterpart_has_none(api: Api) -> None:
    assert api.get_json("/api/instruments/BWBV0002060")["same_treaty"] == []
    assert api.get_json("/api/instruments/verdrag_001610")["same_treaty"] == []
    unnumbered = api.get_json("/api/instruments/BWBV0009999")
    assert unnumbered["treaty_number"] is None and unnumbered["same_treaty"] == []


def test_the_check_counts_what_the_numbers_match(store: GraphStore) -> None:
    notes = check(store, edges=False).notes
    assert (
        "treaties: 1 of 3 BWB treaties have a Verdragenbank record, 1 name a number it "
        "does not have, 1 name none"
    ) in notes


def test_the_bwb_text_of_a_treaty_is_the_same_as_its_verdragenbank_record(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _build(store, cli)

    def same_as() -> set[tuple[str, str]]:
        return {
            (row["from_id"], row["to_id"])
            for row in store.query(
                "SELECT from_id, to_id FROM edges WHERE relation = 'SAME_AS'"
            )
        }

    cli("semantic", "verdragenbank")
    # the numbered text with a record; not the one whose number has none, nor the unnumbered
    assert same_as() == {("instruments/bwbv0001000", "instruments/verdrag_005132")}
    cli("semantic", "verdragenbank")
    assert len(same_as()) == 1

    # a number that no longer matches: the edge goes on the next run
    store.query(
        "UPDATE instruments SET treaty_number = '999999' WHERE key = 'bwbv0001000'"
    )
    cli("semantic", "verdragenbank")
    assert same_as() == set()
