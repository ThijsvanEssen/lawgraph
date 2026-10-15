"""The text payloads of raw records live in the payload store, run for real on the test server.

`raw_sources` keeps the metadata of a record and the name of its object; the XML itself is an
object in the payload store (a directory of the test here). JSON payloads stay in the
database, where queries filter on them.
"""

from __future__ import annotations

import os
import subprocess
import sys
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
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.payloads import S3PayloadStore, decode
from tests.integration.conftest import ROOT
from tests.integration.seed import seed

XML = "<open-rechtspraak><uitspraak>Tekst</uitspraak></open-rechtspraak>"


def _raw(store: GraphStore, key: str) -> dict[str, Any]:
    return next(
        store.query(
            f"SELECT doc FROM {COLLECTION_RAW_SOURCES} WHERE key = %(key)s",
            {"key": key},
        )
    )


def test_a_text_payload_is_an_object_and_not_in_the_database(database: str) -> None:
    store = GraphStore()
    doc = raw_source_doc(
        source=SOURCE_RECHTSPRAAK,
        kind=RAW_KIND_RS_CONTENT,
        external_id="ECLI:NL:HR:2024:1",
        payload_text=XML,
    )
    with RawSourceWriter(store) as writer:
        writer.add(doc)
    stored = _raw(store, doc["key"])
    assert "payload_text" not in stored
    assert stored["payload_ref"].startswith(f"{database}/rechtspraak/rs-content/")
    assert stored["payload_chars"] == len(XML)
    assert decode(store.payloads.get(stored["payload_ref"])) == XML
    (read,) = store.with_payloads([stored])
    assert read["payload_text"] == XML


def test_a_json_payload_stays_in_the_database(database: str) -> None:
    store = GraphStore()
    doc = raw_source_doc(
        source=SOURCE_TK,
        kind=RAW_KIND_TK_ZAAK,
        external_id="z1",
        payload_json={"Id": "z1", "Soort": "Motie"},
    )
    with RawSourceWriter(store) as writer:
        writer.add(doc)
    stored = _raw(store, doc["key"])
    assert stored["payload_json"] == {"Id": "z1", "Soort": "Motie"}
    assert "payload_ref" not in stored


def test_the_whole_chain_reads_its_payloads_from_the_store(
    database: str, cli: Callable[..., CompletedProcess[str]]
) -> None:
    """Seeded through the real writer, normalized and linked by the real CLI."""
    store = GraphStore()
    seed(store, documents=0, judgments=5, regulations=0)
    in_database = store.query(
        f"SELECT 1 FROM {COLLECTION_RAW_SOURCES} WHERE doc ->> 'payload_text' IS NOT NULL"
    )
    assert list(in_database) == []
    cli("normalize", "rechtspraak")
    judgments = store.query(
        f"SELECT 1 FROM {COLLECTION_JUDGMENTS} WHERE props ->> 'text' IS NOT NULL"
    )
    assert len(list(judgments)) == 5
    assert check(
        store, edges=False
    ).notes  # and the payloads are found where they were put
    assert not [p for p in check(store, edges=False).problems if "payloads" in p]


def test_a_payload_that_is_lost_is_skipped_and_reported(
    database: str, cli: Callable[..., CompletedProcess[str]]
) -> None:
    store = GraphStore()
    seed(store, documents=0, judgments=3, regulations=0)
    first = next(
        iter(
            store.query(
                f"SELECT doc ->> 'payload_ref' FROM {COLLECTION_RAW_SOURCES} "
                "WHERE doc ->> 'payload_ref' IS NOT NULL ORDER BY external_id LIMIT 1"
            )
        )
    )
    (store.payloads.root / first).unlink()  # type: ignore[attr-defined]
    done = cli("normalize", "rechtspraak", check=False)
    assert "is missing in" in done.stderr
    judgments = store.query(
        f"SELECT 1 FROM {COLLECTION_JUDGMENTS} WHERE props ->> 'text' IS NOT NULL"
    )
    assert len(list(judgments)) == 2
    problems = check(store, edges=False).problems
    assert any(p.startswith("payloads: 1 of 3") for p in problems)


# ── the same in an S3 bucket ─────────────────────────────────────────────────

S3_URL = os.environ.get("LAWGRAPH_TEST_S3_URL", "http://localhost:8531")


@pytest.fixture()
def bucket() -> str:
    """A fresh bucket on the S3 test server, when ``ALLOW_S3_TESTS=1`` asks for these tests;
    asked for, a server that does not answer fails them."""
    if os.environ.get("ALLOW_S3_TESTS") != "1":
        pytest.skip("S3 tests disabled (set ALLOW_S3_TESTS=1 to enable).")
    try:
        requests.get(S3_URL, timeout=2)
    except requests.RequestException as error:
        pytest.fail(
            f"ALLOW_S3_TESTS=1, but no S3 server answers at {S3_URL} "
            f"(docker compose -f docker-compose.test.yml up -d s3-test): {error}"
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
    store = GraphStore()
    seed(store, documents=0, judgments=4, regulations=0)
    rows = list(
        store.with_payloads(
            store.query(
                f"SELECT doc FROM {COLLECTION_RAW_SOURCES} "
                "WHERE doc ->> 'payload_ref' IS NOT NULL"
            )
        )
    )
    assert len(rows) >= 4 and all(row["payload_text"].startswith("<") for row in rows)
    assert not [p for p in check(store, edges=False).problems if "payloads" in p]


def _s3_tests(**switches: str) -> subprocess.CompletedProcess[str]:
    """``pytest`` over the S3 tests of this file, against no S3 server at all."""
    env = {key: value for key, value in os.environ.items() if key != "ALLOW_S3_TESTS"}
    env.update(LAWGRAPH_TEST_S3_URL="http://127.0.0.1:1", **switches)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            f"{__file__}::test_an_s3_store_gives_back_what_it_was_given",
            f"{__file__}::test_the_chain_runs_on_an_s3_store",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_a_requested_s3_server_that_does_not_answer_fails_the_s3_tests() -> None:
    done = _s3_tests(ALLOW_S3_TESTS="1")
    assert done.returncode != 0, done.stdout
    assert "no S3 server answers at http://127.0.0.1:1" in done.stdout


def test_without_the_switch_the_s3_tests_are_skipped() -> None:
    done = _s3_tests()
    assert done.returncode == 0, done.stdout
    assert "2 skipped" in done.stdout


def test_a_payload_store_that_fails_stops_the_step_and_keeps_the_buffer(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like a database that cannot be reached: fetching on would store nothing."""
    from lawgraph.db.raw import StoreUnavailable

    store = GraphStore()

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
    assert list(store.query(f"SELECT 1 FROM {COLLECTION_RAW_SOURCES}")) == []
