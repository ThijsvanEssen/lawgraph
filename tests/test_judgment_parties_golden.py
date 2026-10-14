"""The parties and their representatives of every judgment fixture, in every area of law,
as read before: a change to the reading shows here as the fixture and area it changes. The
golden file holds a digest of each reading (one kop names 253 parties).

After a change meant to alter what is read, write the golden file anew with
``LAWGRAPH_WRITE_GOLDEN=1 pytest tests/test_judgment_parties_golden.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from lawgraph.core.judgment_counsel import read_counsel
from lawgraph.core.judgment_parties import read_parties
from lawgraph.core.judgments import (
    AREA_ADMINISTRATIVE,
    AREA_CIVIL,
    AREA_CRIMINAL,
    extract_rdf_metadata,
    judgment_text,
    kop_lines,
    parse_judgment,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "judgment_parties_golden.json"
# Each judgment as its own subjects give it, and as if of every area of law.
AREAS: dict[str, list[str] | None] = {
    "own": None,
    "criminal": [AREA_CRIMINAL],
    "civil": [AREA_CIVIL],
    "administrative": [AREA_ADMINISTRATIVE],
    "none": [],
}


def _digest(parties: list[dict[str, Any]]) -> str:
    text = json.dumps(parties, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _read(path: Path) -> dict[str, str]:
    root = parse_judgment(path.read_text())
    _, own = extract_rdf_metadata(root)
    lines = kop_lines(root)
    paragraphs, _ = judgment_text(root)
    read = {}
    for area, subjects in AREAS.items():
        subjects = own if subjects is None else subjects
        parties = read_counsel(read_parties(lines, subjects), paragraphs, subjects)
        read[area] = _digest(parties)
    return read


def test_every_judgment_fixture_reads_as_before() -> None:
    found = {
        path.name: _read(path)
        for path in sorted(FIXTURES.glob("rechtspraak_*.xml"))
        if path.name not in ("rechtspraak_index_page.xml", "rechtspraak_instanties.xml")
    }
    if os.environ.get("LAWGRAPH_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    assert found == json.loads(GOLDEN.read_text())
