"""What ``normalize rechtspraak`` writes for every judgment fixture, as written before: each
prop of each judgment node (the paragraphs with their ids, kinds and kop among them), the
order of the props, and how a translation is linked to the judgment it translates. The
golden file holds a digest per prop; a change shows as the fixture and prop it changes.

After a change meant to alter what is written, write the golden file anew with
``LAWGRAPH_WRITE_GOLDEN=1 pytest tests/normalize/test_rechtspraak_golden.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from lawgraph.config.constants import COLLECTION_JUDGMENTS, RAW_KIND_RECHTSPRAAK_CONTENT
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries.normalize import rechtspraak as normalize_queries
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from tests.fakes import InMemoryStore
from tests.paths import FIXTURES

GOLDEN = FIXTURES / "rechtspraak_normalize_golden.json"
_NOT_JUDGMENTS = ("rechtspraak_index_page.xml", "rechtspraak_instanties.xml")
_ECLI = re.compile(r"ECLI:NL:[A-Z]+:\d{4}:[A-Z0-9]+")


def _digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)  # in the order written
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _record(path: Path) -> dict[str, Any]:
    xml = path.read_text(encoding="utf-8")
    ecli = _ECLI.search(xml)
    assert ecli is not None
    return {
        "key": path.stem,
        "kind": RAW_KIND_RECHTSPRAAK_CONTENT,
        "payload_text": xml,
        "meta": {"ecli": ecli[0]},
    }


def _normalize(
    paths: list[Path], monkeypatch: pytest.MonkeyPatch
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The judgment documents one run over *paths* writes, in order, and what it asks and
    writes to link translations (every translation finds one made-up original)."""
    linked: dict[str, Any] = {}

    def translated(_store: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        linked["lookup"] = rows
        original = {
            "key": "original",
            "ecli": "ECLI:NL:X:1:1",
            "summary": "Samenvatting",
        }
        return [{"key": row["key"], "original": original} for row in rows]

    def update(_store: Any, rows: list[dict[str, Any]]) -> int:
        linked["updates"] = rows
        return len(rows)

    monkeypatch.setattr(normalize_queries, "translated_judgments", translated)
    monkeypatch.setattr(normalize_queries, "update_judgment_props", update)
    store = InMemoryStore()
    pipeline = RechtspraakNormalizePipeline(store=store)
    pipeline.write(iter([_record(path) for path in paths]), PipelineResult())
    return list(store.nodes.get(COLLECTION_JUDGMENTS, {}).values()), linked


def _read(path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    (document,), _ = _normalize([path], monkeypatch)
    props = document["props"]
    return {
        "document": _digest(document),
        "keys": list(props),
        "props": {key: _digest(value) for key, value in props.items()},
    }


def test_every_judgment_fixture_normalizes_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [
        path
        for path in sorted(FIXTURES.glob("rechtspraak_*.xml"))
        if path.name not in _NOT_JUDGMENTS
    ]
    found: dict[str, Any] = {path.name: _read(path, monkeypatch) for path in paths}
    _, linked = _normalize(
        [
            FIXTURES / "rechtspraak_hr_2019_2006.xml",
            FIXTURES / "rechtspraak_hr_2019_2007.xml",
        ],
        monkeypatch,
    )
    found["translation"] = {
        "lookup": linked["lookup"],
        "updates": _digest(linked["updates"]),
    }
    if os.environ.get("LAWGRAPH_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n")
    assert found == json.loads(GOLDEN.read_text())
