"""Who issued a publication, from retrieve to edge on a real PostgreSQL: ``retrieve
staatscourant-creators`` writes what the SRU says into the meta of the stored record (its
payload stays, a second run asks nothing), ``normalize staatscourant`` reads the ministry on
the day of publication, and ``semantic tooi-ministries`` makes the paper ``LED_BY`` it."""

from __future__ import annotations

from typing import Any, cast

from lawgraph.clients.koop_publications import KoopPublicationClient
from lawgraph.config.constants import (
    RAW_KIND_STAATSCOURANT_REGELING,
    RELATION_LED_BY,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline
from lawgraph.pipelines.retrieve.staatscourant_creators import (
    StaatscourantCreatorsRetrievePipeline,
)
from lawgraph.pipelines.semantic.tooi_ministries import TooiMinistriesSemanticPipeline

_XML = (
    "<officiele-publicatie><staatscourant><regeling>Regeling</regeling></staatscourant>"
    "</officiele-publicatie>"
)


class _Client:
    """The SRU holds stcrt-2011-1 (by Justitie, a name its successor had then) and
    stcrt-2011-2 (by a municipality), not stcrt-2011-3."""

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def creators_of(self, identifiers: list[str]) -> dict[str, dict[str, Any]]:
        self.asked.append(identifiers)
        held = {
            "stcrt-2011-1": "Ministerie van Justitie",
            "stcrt-2011-2": "Oost Gelre",
        }
        return {
            i: {
                "creators": [{"name": held[i], "scheme": "x"}],
                "published": "2011-06-01",
            }
            for i in identifiers
            if i in held
        }


def _store_records(store: GraphStore) -> None:
    with RawSourceWriter(store) as writer:
        for n in (1, 2, 3):
            identifier = f"stcrt-2011-{n}"
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSCOURANT,
                    kind=RAW_KIND_STAATSCOURANT_REGELING,
                    external_id=identifier,
                    payload_text=_XML,
                    meta={"identifier": identifier},
                )
            )


def _documents(store: GraphStore) -> dict[str, dict[str, Any]]:
    rows = store.query(
        "SELECT key, props FROM documents WHERE source = %(source)s",
        {"source": SOURCE_STAATSCOURANT},
    )
    return {row["key"]: row["props"] for row in rows}


def test_creators_from_retrieve_to_led_by(store: GraphStore) -> None:
    _store_records(store)
    client = _Client()
    result = StaatscourantCreatorsRetrievePipeline(
        store, cast(KoopPublicationClient, client)
    ).run()
    assert (result.created, result.errors) == (3, [])
    # one query, in the order of the record keys
    assert [sorted(ids) for ids in client.asked] == [
        ["stcrt-2011-1", "stcrt-2011-2", "stcrt-2011-3"]
    ]

    records = {
        r["external_id"]: r
        for r in raw_queries.iter_raw_records(
            store,
            source=SOURCE_STAATSCOURANT,
            kinds=[RAW_KIND_STAATSCOURANT_REGELING],
            since_iso=None,
            batch_size=10,
        )
    }
    assert records["stcrt-2011-3"]["meta"]["creators"] == []
    (read,) = store.with_payloads([records["stcrt-2011-1"]])
    assert read["payload_text"] == _XML

    again = _Client()
    StaatscourantCreatorsRetrievePipeline(
        store, cast(KoopPublicationClient, again)
    ).run()
    assert again.asked == []

    assert not StaatscourantNormalizePipeline(store=store).run().errors
    documents = _documents(store)
    assert {
        k: (p["ministries"], p["ministry_missing"]) for k, p in documents.items()
    } == {
        "stcrt_stcrt_2011_1": (["venj"], None),
        "stcrt_stcrt_2011_2": ([], "unlinked"),
        "stcrt_stcrt_2011_3": ([], "no_creator"),
    }

    assert not TooiMinistriesSemanticPipeline(store=store).run().errors
    led = store.query(
        "SELECT from_id, to_id FROM edges WHERE relation = %(relation)s "
        "AND from_collection = 'documents'",
        {"relation": RELATION_LED_BY},
    )
    assert [(r["from_id"], r["to_id"]) for r in led] == [
        ("documents/stcrt_stcrt_2011_1", "ministries/venj")
    ]
