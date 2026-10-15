"""The paragraphs and footnotes of every judgment fixture, as read before: a change to the
reading shows here as the fixture it changes. The golden file holds a digest of the
paragraphs (id, number, kind, text) and the footnotes (paragraph_id, at) of each.

After a change meant to alter what is read, write the golden file anew with
``LAWGRAPH_WRITE_GOLDEN=1 pytest tests/test_judgment_text_golden.py``.
"""

from __future__ import annotations

import hashlib
import json
import os

from lawgraph.core.judgment_metadata import parse_judgment
from lawgraph.core.judgment_paragraphs import judgment_text
from tests.paths import FIXTURES

GOLDEN = FIXTURES / "judgment_text_golden.json"


def _digest(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def test_every_judgment_fixture_reads_its_text_as_before() -> None:
    found = {}
    for path in sorted(FIXTURES.glob("rechtspraak_*.xml")):
        if path.name in ("rechtspraak_index_page.xml", "rechtspraak_instanties.xml"):
            continue
        paragraphs, footnotes = judgment_text(parse_judgment(path.read_text()))
        found[path.name] = {
            "paragraphs": _digest(paragraphs),
            "footnotes": _digest(footnotes),
            "placed": sum("at" in note for note in footnotes),
        }
    if os.environ.get("LAWGRAPH_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    assert found == json.loads(GOLDEN.read_text())
