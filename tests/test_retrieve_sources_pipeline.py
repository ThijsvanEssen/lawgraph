from __future__ import annotations

import datetime as dt
from typing import Sequence

from lawgraph.config.settings import (
    RAW_KIND_EU_CELEX,
    RAW_KIND_RS_INDEX,
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
    SOURCE_EURLEx,
)
from lawgraph.pipelines.retrieve import RetrieveSourcesPipeline


class FakeStore:
    """Minimal store that records raw documents instead of writing to Arango."""

    def __init__(self) -> None:
        self.inserted: list[dict[str, object | None]] = []

    def insert_raw_source(
        self,
        *,
        source: str,
        kind: str,
        external_id: str | None,
        payload_json: dict | list | None = None,
        payload_text: str | None = None,
        meta: dict | None = None,
    ) -> dict:
        doc: dict[str, object | None] = {
            "_key": f"fake-{len(self.inserted)+1}",
            "source": source,
            "kind": kind,
            "external_id": external_id,
            "fetched_at": "1970-01-01T00:00:00Z",
            "payload_json": payload_json,
            "payload_text": payload_text,
            "meta": meta or {},
        }
        self.inserted.append(doc)
        return doc


class FakeTKClient:
    def zaken_modified_since(self, since: dt.datetime, top: int = 100) -> list[dict]:
        return [
            {"Id": "Z1", "Titel": "Zaak 1"},
            {"Id": "Z2", "Titel": "Zaak 2"},
        ]

    def documentversies_modified_since(
        self, since: dt.datetime, top: int = 100
    ) -> list[dict]:
        return [{"Id": "D1", "Naam": "Document"}]


class FakeRechtspraakClient:
    def search_ecli_index(
        self,
        modified_since: dt.datetime | None = None,
        extra_params: dict | None = None,
    ) -> str:
        return "<index>ok</index>"

    def fetch_ecli_content(self, ecli: str) -> str:
        return f"<content>{ecli}</content>"


class FakeEUClient:
    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        return f"<html>CELEX {celex} ({lang})</html>"


def test_dump_tk_writes_expected_raw_documents() -> None:
    store = FakeStore()
    pipeline = RetrieveSourcesPipeline(
        store=store,
        tk_client=FakeTKClient(),
        rs_client=FakeRechtspraakClient(),
        eu_client=FakeEUClient(),
    )

    since = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    pipeline.dump_tk(since=since, limit=10)

    assert len(store.inserted) == 3
    for doc in store.inserted:
        assert doc["source"] == SOURCE_TK
        assert doc["payload_json"] is not None
        assert doc["payload_text"] is None
        assert doc["kind"] in {RAW_KIND_TK_ZAAK, RAW_KIND_TK_DOCUMENTVERSIE}


def test_dump_rechtspraak_index_writes_single_raw_document() -> None:
    store = FakeStore()
    pipeline = RetrieveSourcesPipeline(
        store=store,
        tk_client=FakeTKClient(),
        rs_client=FakeRechtspraakClient(),
        eu_client=FakeEUClient(),
    )

    since = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    pipeline.dump_rechtspraak_index(since=since)

    assert len(store.inserted) == 1
    doc = store.inserted[0]
    assert doc["source"] == SOURCE_RECHTSPRAAK
    assert doc["kind"] == RAW_KIND_RS_INDEX
    assert doc["payload_text"] == "<index>ok</index>"
    assert doc["payload_json"] is None


def test_dump_eurlex_celex_list_writes_one_document_per_celex() -> None:
    store = FakeStore()
    pipeline = RetrieveSourcesPipeline(
        store=store,
        tk_client=FakeTKClient(),
        rs_client=FakeRechtspraakClient(),
        eu_client=FakeEUClient(),
    )

    celex_ids: Sequence[str] = ["C1", "C2"]
    pipeline.dump_eurlex_celex_list(celex_ids, lang="NL")

    assert len(store.inserted) == 2
    seen_ids: set[str] = set()
    for doc in store.inserted:
        assert doc["source"] == SOURCE_EURLEx
        assert doc["kind"] == RAW_KIND_EU_CELEX
        assert doc["external_id"] in celex_ids
        assert doc["payload_json"] is None
        payload_text = doc["payload_text"]
        assert isinstance(payload_text, str)
        assert doc["external_id"] in payload_text
        seen_ids.add(str(doc["external_id"]))
    assert seen_ids == set(celex_ids)
