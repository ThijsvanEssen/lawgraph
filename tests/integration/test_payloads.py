"""The text payloads of raw records live in the payload store, run for real on the test server.

`raw_sources` keeps the metadata of a record and the name of its object; the XML itself is an
object in the payload store (a directory of the test here). JSON payloads stay in the
database, where queries filter on them.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from subprocess import CompletedProcess
from typing import Any

import pytest
import requests

from lawgraph.commands.check import check
from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_TK_ZAAK,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.db.payloads import S3PayloadStore, decode
from tests.integration.seed import seed

XML = "<open-rechtspraak><uitspraak>Tekst</uitspraak></open-rechtspraak>"


def _raw(store: ArangoStore, key: str) -> dict[str, Any]:
    return store.raw_sources.get(key)


def test_a_text_payload_is_an_object_and_not_in_the_database(database: str) -> None:
    store = ArangoStore()
    doc = raw_source_doc(
        source=SOURCE_RECHTSPRAAK,
        kind=RAW_KIND_RS_CONTENT,
        external_id="ECLI:NL:HR:2024:1",
        payload_text=XML,
    )
    with RawSourceWriter(store) as writer:
        writer.add(doc)
    stored = _raw(store, doc["_key"])
    assert "payload_text" not in stored
    assert stored["payload_ref"].startswith(f"{database}/rechtspraak/rs-content/")
    assert stored["payload_chars"] == len(XML)
    assert decode(store.payloads.get(stored["payload_ref"])) == XML
    (read,) = store.with_payloads([stored])
    assert read["payload_text"] == XML


def test_a_json_payload_stays_in_the_database(database: str) -> None:
    store = ArangoStore()
    doc = raw_source_doc(
        source=SOURCE_TK,
        kind=RAW_KIND_TK_ZAAK,
        external_id="z1",
        payload_json={"Id": "z1", "Soort": "Motie"},
    )
    with RawSourceWriter(store) as writer:
        writer.add(doc)
    stored = _raw(store, doc["_key"])
    assert stored["payload_json"] == {"Id": "z1", "Soort": "Motie"}
    assert "payload_ref" not in stored


def test_the_whole_chain_reads_its_payloads_from_the_store(
    database: str, cli: Callable[..., CompletedProcess[str]]
) -> None:
    """Seeded through the real writer, normalized and linked by the real CLI."""
    store = ArangoStore()
    seed(store, documents=0, judgments=5, regulations=0)
    in_database = store.query(
        f"FOR r IN {COLLECTION_RAW_SOURCES} FILTER r.payload_text != null RETURN 1"
    )
    assert list(in_database) == []
    cli("normalize", "rechtspraak")
    judgments = store.query(
        f"FOR j IN {COLLECTION_JUDGMENTS} FILTER j.props.text != null RETURN 1"
    )
    assert len(list(judgments)) == 5
    assert check(
        store, edges=False
    ).notes  # and the payloads are found where they were put
    assert not [p for p in check(store, edges=False).problems if "payloads" in p]


def test_a_payload_that_is_lost_is_skipped_and_reported(
    database: str, cli: Callable[..., CompletedProcess[str]]
) -> None:
    store = ArangoStore()
    seed(store, documents=0, judgments=3, regulations=0)
    first = next(
        iter(
            store.query(
                f"FOR r IN {COLLECTION_RAW_SOURCES} FILTER r.payload_ref != null "
                "SORT r.external_id LIMIT 1 RETURN r.payload_ref"
            )
        )
    )
    (store.payloads.root / first).unlink()  # type: ignore[attr-defined]
    done = cli("normalize", "rechtspraak", check=False)
    assert "is missing in" in done.stderr
    judgments = store.query(
        f"FOR j IN {COLLECTION_JUDGMENTS} FILTER j.props.text != null RETURN 1"
    )
    assert len(list(judgments)) == 2
    problems = check(store, edges=False).problems
    assert any(p.startswith("payloads: 1 of 3") for p in problems)


# ── the same in an S3 bucket ─────────────────────────────────────────────────

S3_URL = os.environ.get("LAWGRAPH_TEST_S3_URL", "http://localhost:8531")


def _s3_reachable() -> bool:
    try:
        requests.get(S3_URL, timeout=2)
    except requests.RequestException:
        return False
    return True


@pytest.fixture()
def bucket() -> str:
    if not _s3_reachable():
        pytest.skip(
            f"No S3 test server at {S3_URL} (docker compose -f docker-compose.test.yml up -d)."
        )
    import boto3

    name = f"lawgraph-it-{uuid.uuid4().hex[:10]}"
    boto3.client(
        "s3",
        endpoint_url=S3_URL,
        region_name="us-east-1",
        aws_access_key_id="lawgraph",
        aws_secret_access_key="lawgraph-test-secret",
    ).create_bucket(Bucket=name)
    return name


def test_an_s3_store_gives_back_what_it_was_given(bucket: str) -> None:
    store = S3PayloadStore(
        bucket,
        "prefix",
        endpoint=S3_URL,
        region="us-east-1",
        access_key="lawgraph",
        secret_key="lawgraph-test-secret",
    )
    assert not store.exists("a/b.gz")
    store.put("a/b.gz", b"data")
    assert store.exists("a/b.gz") and store.get("a/b.gz") == b"data"


def test_the_chain_runs_on_an_s3_store(
    database: str, bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lawgraph.db import store as store_module

    monkeypatch.setattr(store_module, "PAYLOAD_STORE", f"s3://{bucket}/payloads")
    monkeypatch.setattr(store_module, "S3_ENDPOINT", S3_URL)
    monkeypatch.setattr(store_module, "S3_REGION", "us-east-1")
    monkeypatch.setattr(store_module, "S3_ACCESS_KEY", "lawgraph")
    monkeypatch.setattr(store_module, "S3_SECRET_KEY", "lawgraph-test-secret")
    store = ArangoStore()
    seed(store, documents=0, judgments=4, regulations=0)
    rows = list(
        store.with_payloads(
            store.query(
                f"FOR r IN {COLLECTION_RAW_SOURCES} FILTER r.payload_ref != null RETURN r"
            )
        )
    )
    assert len(rows) >= 4 and all(row["payload_text"].startswith("<") for row in rows)
    assert not [p for p in check(store, edges=False).problems if "payloads" in p]


def test_a_payload_store_that_fails_stops_the_step_and_keeps_the_buffer(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like a database that cannot be reached: fetching on would store nothing."""
    from lawgraph.db.raw import StoreUnavailable

    store = ArangoStore()

    def full(name: str, data: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store.payloads, "put", full)
    writer = RawSourceWriter(store)
    writer.add(
        raw_source_doc(
            source=SOURCE_RECHTSPRAAK,
            kind=RAW_KIND_RS_CONTENT,
            external_id="ECLI:NL:HR:2024:2",
            payload_text=XML,
        )
    )
    with pytest.raises(StoreUnavailable, match="No space left"):
        writer.flush()
    assert len(writer) == 1  # kept for a retry
    assert list(store.query(f"FOR r IN {COLLECTION_RAW_SOURCES} RETURN 1")) == []
