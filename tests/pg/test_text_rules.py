"""The words of a ``q`` as the database matches them (``_words.word_pattern``), against the
cases of ``tests/data/text-rules.json`` that the explorer's ``treffer.ts`` is tested on too."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from lawgraph.db.queries import _words
from tests.paths import TESTS

WORDS: list[dict[str, Any]] = json.loads(
    (TESTS / "data" / "text-rules.json").read_text()
)["words"]


def test_the_words_are_found_as_the_explorer_marks_them(
    conn: psycopg.Connection,
) -> None:
    found = [
        conn.execute(
            "SELECT lower(%s) ~ %s",
            (case["text"], _words.word_pattern(_words.words(case["q"]))),
        ).fetchone()[0]  # type: ignore[index]
        for case in WORDS
    ]
    assert found == [case["found"] for case in WORDS]
