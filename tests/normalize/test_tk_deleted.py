"""A record the Tweede Kamer deleted is set apart in one place, before any reader sees it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_CASES, COLLECTION_FACTIONS
from lawgraph.core.models import make_node_key
from lawgraph.pipelines.normalize._tk_deleted import DELETED, Deleted, kept, living
from lawgraph.pipelines.normalize.tk import TKNormalizePipeline
from tests.fakes import InMemoryStore

GONE = {"Id": "d-1", "Soort": None, "Titel": None, "Verwijderd": True, "Zaak": []}
LIVE = {"Id": "d-2", "Soort": "Motie", "Verwijderd": False}


def _raw(*payloads: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": str(p.get("Id")), "payload_json": p} for p in payloads]


def test_deleted_keeps_the_id_of_a_record_the_kamer_deleted() -> None:
    deleted = Deleted(COLLECTION_CASES)
    assert deleted(GONE)
    assert not deleted(LIVE)
    assert not deleted({"Id": "d-3"})
    assert deleted.ids == {"d-1"}
    assert deleted.key is not None and deleted.key("d-1") == make_node_key("d-1")
    assert Deleted(COLLECTION_FACTIONS, key=None).key is None


def test_kept_skips_a_deleted_record_with_its_reason() -> None:
    pipeline = TKNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]
    assert list(kept(pipeline, _raw(GONE, LIVE, {"Soort": "Motie"}))) == [LIVE]
    assert pipeline.progress.skips == {DELETED: 1, "no Id": 1}


def test_living_leaves_out_a_deleted_record_unreported() -> None:
    assert list(living(_raw(GONE, LIVE))) == [LIVE]
