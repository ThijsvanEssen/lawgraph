"""What ``normalize rechtspraak`` writes for every judgment fixture, as written before: each
prop of each judgment node (the paragraphs with their ids, kinds and kop among them), the
order of the props, and how a translation is linked to the judgment it translates.

The golden file of a fixture holds each short value as it is and a long text as its digest
and its start, so a change shows as the fixture, the field and what it was and is. After a
change meant to alter what is written, write the golden files anew with
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

GOLDEN = FIXTURES / "rechtspraak_normalize_golden"  # a file per fixture
_NOT_JUDGMENTS = ("rechtspraak_index_page.xml", "rechtspraak_instanties.xml")
_ECLI = re.compile(r"ECLI:NL:[A-Z]+:\d{4}:[A-Z0-9]+")
_SHORT = 120  # characters of JSON a value is kept as it is up to
_START = 60  # characters of a long text kept beside its digest
_SHOWN = 20  # differences a failure lists
_TRANSLATION = "translation"
_JUDGMENTS = [
    path
    for path in sorted(FIXTURES.glob("rechtspraak_*.xml"))
    if path.name not in _NOT_JUDGMENTS
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)  # in the order written


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()[:16]


def _kept(value: Any) -> Any:
    """*value* as the golden file keeps it: as it is when short, a list or object item by
    item, a long text as its digest and its start."""
    text = value if isinstance(value, str) else _json(value)
    if len(text) <= _SHORT:
        return value
    if isinstance(value, list):
        return [_kept(item) for item in value]
    if isinstance(value, dict):
        return {key: _kept(item) for key, item in value.items()}
    return f"{_digest(value)} {text[:_START]}…"


def _differences(was: Any, now: Any, where: str) -> list[str]:
    """What differs between *was* and *now*, a line per field (order counts)."""
    if _json(was) == _json(now):
        return []
    if isinstance(was, dict) and isinstance(now, dict):
        found = [
            f"{where}.{key}: gone (was {was[key]!r})" for key in was if key not in now
        ]
        found += [f"{where}.{key}: new, {now[key]!r}" for key in now if key not in was]
        shared = [key for key in was if key in now]
        if shared != [key for key in now if key in was]:
            found.append(f"{where}: keys in another order, {list(now)}")
        for key in shared:
            found += _differences(was[key], now[key], f"{where}.{key}")
        return found
    if isinstance(was, list) and isinstance(now, list):
        found = []
        if len(was) != len(now):
            found.append(f"{where}: {len(was)} items, now {len(now)}")
        for index, (old, new) in enumerate(zip(was, now, strict=False)):
            found += _differences(old, new, f"{where}[{index}]")
        return found
    return [f"{where}: was {was!r}\n  now {now!r}"]


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
    if path.name == _TRANSLATION:
        _, linked = _normalize(
            [
                FIXTURES / "rechtspraak_hr_2019_2006.xml",
                FIXTURES / "rechtspraak_hr_2019_2007.xml",
            ],
            monkeypatch,
        )
        return {"lookup": _kept(linked["lookup"]), "updates": _kept(linked["updates"])}
    (document,), _ = _normalize([path], monkeypatch)
    return {"document": _digest(document), "props": _kept(document["props"])}


@pytest.mark.parametrize(
    "path", [*_JUDGMENTS, Path(_TRANSLATION)], ids=lambda path: path.stem
)
def test_a_judgment_fixture_normalizes_as_before(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _read(path, monkeypatch)
    golden = GOLDEN / f"{path.stem}.json"
    if os.environ.get("LAWGRAPH_WRITE_GOLDEN"):
        golden.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n")
    was = json.loads(golden.read_text())
    differences = _differences(was, found, path.stem)
    if len(differences) > _SHOWN:
        differences[_SHOWN:] = [f"… {len(differences) - _SHOWN} more"]
    same = _json(found) == _json(was)  # not the texts themselves: their diff is long
    assert same, "\n".join(
        [
            *differences,
            "Meant? Write the golden files anew: LAWGRAPH_WRITE_GOLDEN=1 "
            "pytest tests/normalize/test_rechtspraak_golden.py",
        ]
    )


def test_every_golden_file_has_its_fixture() -> None:
    assert sorted(path.stem for path in GOLDEN.glob("*.json")) == sorted(
        [*(path.stem for path in _JUDGMENTS), _TRANSLATION]
    )
