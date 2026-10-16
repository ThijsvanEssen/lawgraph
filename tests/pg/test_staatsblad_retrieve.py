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
