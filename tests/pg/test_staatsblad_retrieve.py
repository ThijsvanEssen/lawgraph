"""``retrieve staatsblad`` on a real PostgreSQL: a publication the source answered HTTP 404
for is remembered (``missing_record``, asked again after ``MISSING_FOR_DAYS``), so the next
run does not ask for it; one it could not serve (HTTP 500) is asked again."""

from __future__ import annotations

from typing import cast

from lawgraph.clients.koop_publications import KoopPublicationClient
from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.fakes import http_error


class _Client:
    """The SRU lists three AMvBs: one without XML, one the source cannot serve, one."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def search(self) -> list[dict[str, str]]:
        return [
            {"identifier": i, "modified": "2020-01-01"}
            for i in ("stb-2020-404", "stb-2015-29246", "stb-2020-1")
        ]

    def fetch_publication_xml(self, identifier: str) -> str:
        self.asked.append(identifier)
        if identifier == "stb-2015-29246":
            raise http_error(500)
        if identifier.endswith("404"):
            raise http_error(404)
        return f"<xml>{identifier}</xml>"


def test_a_known_404_is_not_asked_again_and_a_500_is(store: GraphStore) -> None:
    client = _Client()
    first = StaatsbladRetrievePipeline(
        store, cast(KoopPublicationClient, client)
    ).run_full()
    assert first.errors == [] and first.created == 1
    client.asked.clear()
    second = StaatsbladRetrievePipeline(
        store, cast(KoopPublicationClient, client)
    ).run_full()
    assert second.errors == []
    assert client.asked == ["stb-2015-29246"]


def test_a_toestand_without_the_ref_gets_it_in_its_meta_once(store: GraphStore) -> None:
    """Read from its XML the first run and written into its meta through the raw writer:
    its payload and its fetched_at stay, and the next run finds it there."""
    xml = (
        "<toestand><wetgeving><publicatie soort='Stb'><publicatiejaar>2012"
        "</publicatiejaar><publicatienr>79</publicatienr></publicatie></wetgeving>"
        "</toestand>"
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id="BWBR0000002",
                payload_text=xml,
                meta={"bwb_id": "BWBR0000002"},
            )
        )
    (before,) = raw_queries.toestanden_without_staatsblad_ref(store)
    client = _Client()
    StaatsbladRetrievePipeline(
        store, cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)

    assert client.asked == ["stb-2012-79"]
    assert list(raw_queries.toestanden_without_staatsblad_ref(store)) == []
    assert list(raw_queries.toestand_staatsblad_refs(store)) == [
        {"bwb_id": "BWBR0000002", "ref": "stb-2012-79"}
    ]
    (after,) = raw_queries.iter_raw_records(
        store,
        source=SOURCE_BWB,
        kinds=[RAW_KIND_BWB_TOESTAND],
        since_iso=None,
        batch_size=10,
    )
    assert after["meta"] == {"bwb_id": "BWBR0000002", "staatsblad_ref": "stb-2012-79"}
    assert {k: v for k, v in after.items() if k != "meta"} == {
        k: v for k, v in before.items() if k != "meta"
    }
    (read,) = store.with_payloads([after])
    assert read["payload_text"] == xml


def test_a_treaty_published_in_the_tractatenblad_names_no_staatsblad(
    store: GraphStore,
) -> None:
    """Trb. 2018, 100 of a treaty is no Stb. 2018, 100: that decree is not fetched for it,
    and its explanation explains no treaty."""
    xml = (
        "<toestand><brondata><oorspronkelijk><publicatie soort='Trb'>"
        "<publicatiejaar>2018</publicatiejaar><publicatienr>100</publicatienr>"
        "</publicatie></oorspronkelijk></brondata></toestand>"
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id="BWBV0001911",
                payload_text=xml,
                meta={"bwb_id": "BWBV0001911"},
            )
        )
    client = _Client()
    StaatsbladRetrievePipeline(
        store, cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)

    assert client.asked == []
    assert list(raw_queries.toestand_staatsblad_refs(store)) == [
        {"bwb_id": "BWBV0001911", "ref": None}
    ]


class _Laws:
    """The laws the SRU lists per dossier: the Wetboek van Strafvordering of 36327 and the
    Verlengingswet of the same dossier, which changes the law of the BWB; the budget law of
    36600-VIII; the Rijkswet of 33440-(R1990), which it lists under 33440."""

    def __init__(self) -> None:
        self.dossiers: list[str | None] = []

    def search(self, *, dossier: str | None = None) -> list[dict[str, str]]:
        self.dossiers.append(dossier)
        found = {
            "36327": ("stb-2026-49", "stb-2026-56"),
            "36600-VIII": ("stb-2025-21",),
            "33440": ("stb-2014-10",),
        }.get(dossier or "", ())
        return [{"identifier": i, "modified": "2026-03-13"} for i in found]


def _dossier(key: str, **props: object) -> dict[str, object]:
    return {"key": key, "type": "dossier", "labels": ["TK"], "props": props}


def test_the_laws_of_the_dossiers_whose_bill_passed_without_a_law_are_stored(
    store: GraphStore,
) -> None:
    """A bill adopted, or passed by the Tweede Kamer (its phase ``Eindtekst``), a budget
    too, with no instrument LEGISLATED_IN its dossier: its laws are looked for, a Rijkswet's
    by its number alone; not those of a dossier whose bill did not pass, was rejected, or
    whose law the graph has."""
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _dossier("36327", label="36327", kind="Wetgeving", outcome="aangenomen"),
            _dossier("36600_viii", label="36600-VIII", kind="Begroting",
                     outcome="aangenomen"),
            _dossier("33440_r1990", label="33440-(R1990)", kind="Wetgeving",
                     current_phase="Eindtekst"),
            _dossier("36999", label="36999", kind="Wetgeving", current_phase="Verslag"),
            _dossier("36998", label="36998", kind="Wetgeving", outcome="verworpen",
                     current_phase="Eindtekst"),
            _dossier("34372", label="34372", kind="Wetgeving", outcome="aangenomen"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            {
                "key": "l1",
                "from_id": "instruments/stb_2018_322",
                "to_id": "dossiers/34372",
                "relation": "LEGISLATED_IN",
                "source": "test",
            }
        ]
    )
    client, laws = _Client(), _Laws()
    result = StaatsbladRetrievePipeline(
        store,
        cast(KoopPublicationClient, client),
        cast(KoopPublicationClient, laws),
    ).run_laws_of_adopted_dossiers(store)
    assert result.errors == [] and result.created == 4
    assert laws.dossiers == ["33440", "36327", "36600-VIII"]
    assert client.asked == ["stb-2014-10", "stb-2026-49", "stb-2026-56", "stb-2025-21"]
    stored = {
        row["external_id"]: row["kind"]
        for row in raw_queries.iter_raw_records(
            store,
            source="staatsblad",
            kinds=["stb-wet-xml"],
            since_iso=None,
            batch_size=10,
        )
    }
    assert stored == dict.fromkeys(
        ("stb-2014-10", "stb-2025-21", "stb-2026-49", "stb-2026-56"), "stb-wet-xml"
    )
    client.asked.clear()
    StaatsbladRetrievePipeline(
        store,
        cast(KoopPublicationClient, client),
        cast(KoopPublicationClient, laws),
    ).run_laws_of_adopted_dossiers(store)
    assert client.asked == []  # stored, and not changed since
