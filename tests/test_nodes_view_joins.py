"""No query joins the view ``nodes`` on an id alone: the view is every table of the graph,
and such a join looked the id up in each of them, an index probe per table per row (a page of
200 neighbours: 6,600 buffers of 8,256). A join names the node's table as a literal, or reads
the node through ``schema.node_of``, which looks in its own table only."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "lawgraph"
# "JOIN nodes n ON n.id = ..." up to the end of its ON clause (the next JOIN, WHERE, ...)
_JOIN = re.compile(
    r"JOIN\s+nodes\s+(?P<alias>\w+)\s+ON\s+(?P<on>.*?)(?=\bJOIN\b|\bWHERE\b|\bGROUP\b|"
    r"\bORDER\b|\bUNION\b|\)|\"\"\"|$)",
    re.DOTALL,
)


def test_no_join_of_the_view_on_an_id_alone() -> None:
    found = []
    for path in sorted((SRC / "db").rglob("*.py")):
        text = path.read_text()
        for match in _JOIN.finditer(text):
            alias = match["alias"]
            literal = re.search(rf"\b{alias}\.collection\s*=\s*'", match["on"])
            if not literal:
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{path.relative_to(SRC)}:{line}: {match.group(0)[:80]}")
    assert not found, "\n".join(found)
