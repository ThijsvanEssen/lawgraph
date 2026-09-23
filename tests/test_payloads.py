"""The payload store: where the text payloads of raw records are kept (``db/payloads.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lawgraph.db.payloads import (
    FilePayloadStore,
    PayloadMissing,
    S3PayloadStore,
    decode,
    encode,
    open_payload_store,
)
from lawgraph.db.store import payload_name


def test_a_text_is_what_it_was_after_it_was_compressed() -> None:
    text = "<toestand>Artikel 1 — één ‘citaat’</toestand>" * 100
    assert decode(encode(text)) == text
    assert len(encode(text)) < len(text.encode()) / 10


def test_a_file_store_gives_back_what_it_was_given(tmp_path: Path) -> None:
    store = FilePayloadStore(tmp_path)
    store.put("lawgraph/bwb/bwb-toestand-xml/abc.gz", b"data")
    assert store.exists("lawgraph/bwb/bwb-toestand-xml/abc.gz")
    assert store.get("lawgraph/bwb/bwb-toestand-xml/abc.gz") == b"data"
    store.put("lawgraph/bwb/bwb-toestand-xml/abc.gz", b"newer")
    assert store.get("lawgraph/bwb/bwb-toestand-xml/abc.gz") == b"newer"
    assert not list(tmp_path.rglob(".tmp-*"))  # written aside and renamed


def test_a_missing_object_is_said_to_be_missing(tmp_path: Path) -> None:
    store = FilePayloadStore(tmp_path)
    assert not store.exists("nothing.gz")
    with pytest.raises(PayloadMissing):
        store.get("nothing.gz")


def test_a_name_cannot_reach_outside_the_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        FilePayloadStore(tmp_path / "store").put("../elsewhere.gz", b"x")


def test_the_url_says_which_store(tmp_path: Path) -> None:
    store = open_payload_store(f"file://{tmp_path}")
    assert isinstance(store, FilePayloadStore) and store.root == tmp_path
    home = open_payload_store("file://~/payloads")
    assert isinstance(home, FilePayloadStore) and home.root == Path.home() / "payloads"
    s3 = open_payload_store(
        "s3://lawgraph-payloads/prod",
        s3_endpoint="https://leafcloud.store",
        s3_region="europe-nl-ams1",
        s3_access_key="key",
        s3_secret_key="secret",
    )
    assert isinstance(s3, S3PayloadStore)
    assert (s3.bucket, s3.prefix) == ("lawgraph-payloads", "prod")
    with pytest.raises(ValueError, match="LAWGRAPH_PAYLOAD_STORE"):
        open_payload_store("/just/a/path")


def test_an_object_is_named_by_its_database_source_kind_and_key() -> None:
    doc = {"_key": "abc", "source": "bwb", "kind": "bwb-toestand-xml"}
    assert payload_name(doc).endswith("/bwb/bwb-toestand-xml/abc.gz")
