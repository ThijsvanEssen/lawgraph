"""The triggers, functions and indexes the schema creates, pinned by name and definition.

A trigger renamed in the code is a second trigger on an existing database (``CREATE OR
REPLACE`` keeps the old one), and an index whose definition changed is not built again
(``IF NOT EXISTS``). ``tests/fixtures/schema_objects.json`` holds what ``statements()``
creates.

A change of the schema meant (a new function, trigger or index) changes it too: write it
anew with ``PYTHONPATH=src:. python tests/test_schema_objects.py`` and check in ``git diff``
that every changed line is the change meant, and nothing else, before committing it."""

from __future__ import annotations

import json
import re

from lawgraph.db._rows import CANVAS_PROPS, CANVAS_PROPS_EVERY
from lawgraph.db.schema import JUDGMENT_LIGHT_PROPS, statements
from tests.paths import FIXTURES

GOLDEN = FIXTURES / "schema_objects.json"

_TRIGGER = re.compile(r"CREATE OR REPLACE TRIGGER (\w+ [^\n]*?EXECUTE FUNCTION [\w.]+)")
_FUNCTION = re.compile(r"CREATE OR REPLACE FUNCTION (?:public\.)?(\w+)\(")
_COMMENT = re.compile(r"--[^\n]*")
_INDEX = re.compile(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS ")


def schema_objects() -> dict[str, list[str]]:
    """Per kind of object: what the schema creates, a line each."""
    parts = [
        _COMMENT.sub("", part).strip()
        for statement in statements()
        for part in statement.split(";\n")
    ]
    text = "\n".join(parts)
    return {
        "triggers": sorted(_TRIGGER.findall(text)),
        "functions": sorted(set(_FUNCTION.findall(text))),
        "indexes": sorted(" ".join(p.split()) for p in parts if _INDEX.match(p)),
    }


def test_the_schema_creates_the_same_objects() -> None:
    assert schema_objects() == json.loads(GOLDEN.read_text("utf-8"))


def test_a_judgment_on_the_canvas_reads_only_light_props() -> None:
    """``light_props`` reads a judgment from ``lg_judgment_light``: every prop the canvas
    shows of it is kept there."""
    canvas = {*CANVAS_PROPS["judgments"], *CANVAS_PROPS_EVERY}
    assert canvas <= set(JUDGMENT_LIGHT_PROPS)


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(schema_objects(), indent=1) + "\n", "utf-8")
