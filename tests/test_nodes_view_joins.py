"""No query joins the view ``nodes`` on an id alone: the view is every table of the graph,
and such a join looked the id up in each of them, an index probe per table per row (a page of
200 neighbours: 6,600 buffers of 8,256). A join names the node's table as a literal, or reads
the node through ``schema.node_of``, which looks in its own table only."""

from __future__ import annotations

import re

from tests.paths import SRC

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


# "FROM nodes [n] WHERE ..." up to the end of its WHERE clause: an id looked up in the view
_FROM = re.compile(
    r"FROM\s+nodes(?:\s+(?P<alias>(?!WHERE\b)\w+))?\s+WHERE\s+(?P<where>.*?)"
    r"(?=\bORDER\b|\bLIMIT\b|\bGROUP\b|\)\s*(?:\w+\s*)?(?:ON\b|$)|\"\"\"|$)",
    re.DOTALL,
)
# Read through the view on an id, still to be gated on the collection (E20).
_NOT_GATED_YET = {
    "db/queries/_helpers.py",
    "db/queries/dossier_changes.py",
    "db/queries/instruments.py",
    "db/queries/relationships.py",
}


def test_no_read_of_the_view_on_an_id_alone() -> None:
    """``FROM nodes WHERE nodes.id = e.to_id`` looks in every table too: a read of the view
    by id names its collection (``n.collection = ...``, ``nodes_of_ids_sql``), or reads the
    node through ``schema.node_of`` or ``schema.node_exists``."""
    found = []
    for path in sorted((SRC / "db").rglob("*.py")):
        name = str(path.relative_to(SRC))
        text = path.read_text()
        for match in _FROM.finditer(text):
            where = match["where"]
            if not re.search(r"\bid\s*=", where):
                continue
            if re.search(r"\bcollection\b|nodes_of_ids_sql", where):
                continue
            if name not in _NOT_GATED_YET:
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{name}:{line}: {match.group(0)[:80]}")
    assert not found, "\n".join(found)


def test_the_view_read_by_id_alone_is_found() -> None:
    for text in (
        "SELECT 1 FROM nodes WHERE nodes.id = e.from_id)",
        "SELECT n.key FROM nodes n WHERE n.id = c.source_id LIMIT 1",
    ):
        match = _FROM.search(text)
        assert match and re.search(r"\bid\s*=", match["where"])
