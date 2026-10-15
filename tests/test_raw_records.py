"""Reading a raw record (``core/raw_records.py``)."""

from __future__ import annotations

from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.pipelines.normalize.base import NormalizePipelineBase


def test_raw_record_accessors() -> None:
    assert payload_text({"payload_text": "x"}) == "x"
    assert payload_text({"payload_text": 1}) is None
    assert payload_text({}) is None
    assert payload_json({"payload_json": {"a": 1}}) == {"a": 1}
    assert payload_json({"payload_json": []}) == {}
    assert meta({"meta": {"a": 1}}) == {"a": 1}
    assert meta({"meta": None}) == {}


def test_normalize_base_delegates_to_raw_records() -> None:
    assert NormalizePipelineBase._payload_text is payload_text
    assert NormalizePipelineBase._payload_json is payload_json
    assert NormalizePipelineBase._meta is meta
