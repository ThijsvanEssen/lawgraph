"""Conventions of the SQL of the code, read from its strings.

1. SQL is written in ``db/`` only: the rest of the code calls its query functions.
2. No ``jsonb_build_object`` or ``jsonb_agg``: ``jsonb`` orders the keys of an object by
   their length and bytes, and the API serves its objects with their keys in the order the
   statement writes them (``json`` keeps that order).
3. Every term of an ``ORDER BY`` says where its nulls go (``NULLS FIRST`` / ``LAST``):
   PostgreSQL puts null last in an ascending order and first in a descending one, so a
   list sorted newest first would open with what has no date. A term that cannot be null
   needs nothing: a key or an id, a test for null, a count, a ``coalesce``, a number. Any
   other term without it is named in ``_REVIEWED`` with why it cannot be null; adding
   ``NULLS`` there would only keep an index from serving the order.

The statements are the strings of the code (``string_literals``: constants and f-strings,
with ``{}`` for what is filled in at run time), docstrings left out.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from tests.paths import SRC
from tests.source_scan import is_sql, python_files, string_literals

_JSONB = re.compile(r"\bjsonb_(build_object|agg|object_agg)\b")
_END = re.compile(
    r"\b(LIMIT|OFFSET|FOR|FETCH|UNION|EXCEPT|INTERSECT|RETURNING|ON\s+CONFLICT)\b", re.I
)
# A term that cannot be null.
_SAFE = re.compile(
    r"^(\w+\.)?(id|key|\w+_id|\w+_key|n|ord|o|position|part|rank|count|total)"
    r'(\s+(ASC|DESC))?(\s+COLLATE\s+"C")?$'
    r"|\bIS\s+(NOT\s+)?(NULL|TRUE|FALSE)\)?(\s+(ASC|DESC))?$"
    r"|^(coalesce|count|length|char_length|array_position|row_number)\("
    r"|^\d+$",
    re.I,
)

# (file, term) -> why the term cannot be null.
_REVIEWED: dict[tuple[str, str], str] = {
    ("db/queries/_json_sql.py", 'k COLLATE "C"'): "a key of a json object",
    ("db/queries/checks.py", "match"): "a CASE of two strings",
    ("db/queries/checks.py", "named"): "a comparison of a coalesce",
    ("db/queries/nodes.py", "direction"): "a constant of each branch",
    ("db/queries/raw.py", "source"): "filtered on equality",
    ("db/queries/raw.py", "kind"): "filtered on equality",
    ("db/queries/raw.py", "decision"): "filtered on IS NOT NULL",
    ("db/queries/semantic/eu.py", "source"): "filtered on equality",
    ("db/queries/semantic/eu.py", "kind"): "filtered on equality",
    ("db/queries/semantic/eu.py", "publication"): (
        "a DISTINCT ON key; the result is ordered by part and n"
    ),
    ("db/queries/semantic/rechtspraak.py", "fingerprint"): (
        "the md5 of a summary that is there"
    ),
    ("db/queries/semantic/rechtspraak.py", "j.court_code"): "filtered on IS NOT NULL",
    ("db/queries/semantic/rechtspraak.py", "j.date_eff"): "filtered on IS NOT NULL",
    ("db/queries/stats.py", "source"): "filtered on IS NOT NULL",
    ("db/queries/stats.py", "r.source"): "filtered on IS NOT NULL",
    ("db/queries/stats.py", "date DESC"): "filtered on date <= today",
    ("db/queries/stats.py", "date_eff DESC"): "filtered on date_eff <= today",
    ("db/queries/stats.py", "date_published DESC"): "filtered on <= today",
    ("db/queries/stats.py", "valid_from DESC"): "filtered on valid_from <= today",
    ("db/queries/government.py", "date ASC"): "filtered on date IS NOT NULL",
    ("db/schema.py", "grp"): "a group number lg_update computes",
    ("db/schema.py", "first"): "the place of a value's first occurrence",
    ("db/schema.py", "m"): "an ordinality",
    ("db/queries/articles.py", "k"): "the key of a dossier from its id",
    ("db/queries/articles.py", "section_anchor"): (
        "a DISTINCT ON key; the page is ordered after it with NULLS"
    ),
    ("db/queries/articles.py", "ds.label"): "filtered on IS NOT NULL",
    ("db/queries/articles.py", "h.edge"): "the key of an edge",
    ("db/queries/instruments.py", "k.cited_count DESC"): "a count",
    ("db/queries/instruments.py", "r.outbound_count + r.inbound_count DESC"): (
        "a sum of counts"
    ),
    ("db/queries/instruments.py", "r.b"): "the identity that found the instrument",
    ("db/queries/feed.py", "u.fid"): "filtered on IS NOT NULL",
    ("db/queries/feed.py", "from_date"): "filtered on IS NOT NULL",
    ("db/queries/feed.py", "nums.number ASC"): "filtered on IS NOT NULL",
}

# file -> why a jsonb object built there is never served.
_JSONB_REVIEWED: dict[str, str] = {
    "db/queries/feed.py": "faction_map: a lookup in the statement, never served",
}


_ORDER_NAME = re.compile(r"order|sort", re.I)


def _named_orders(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """The order lists the code keeps under a name (``_ORDER = "r.date DESC NULLS LAST"``,
    ``_SORTS = {"date_desc": "..."}``, ``order = {...}[sort]``) and puts into an
    ``ORDER BY {...}`` at run time, each as an ORDER BY of its own."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(t, ast.Name) and _ORDER_NAME.search(t.id) for t in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Subscript):
            value = value.value
        values = value.values if isinstance(value, ast.Dict) else [value]
        for item in values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                text = item.value
                yield item.lineno, text if "ORDER BY" in text else f"ORDER BY {text}"


def _modules() -> Iterator[tuple[str, list[tuple[int, str]]]]:
    for path in python_files():
        relative = str(path.relative_to(SRC))
        tree = ast.parse(path.read_text())
        yield relative, [*string_literals(tree), *_named_orders(tree)]


def _order_terms(text: str) -> Iterator[str]:
    """The terms of every ORDER BY in *text*."""
    for match in re.finditer(r"\bORDER BY\s", text):
        depth, start, end = 0, match.end(), len(text)
        for i in range(match.end(), len(text)):
            char = text[i]
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    end = i
                    break
                depth -= 1
            elif depth == 0 and (
                char == ";" or (_END.match(text, i) and not text[i - 1].isalnum())
            ):
                end = i
                break
        depth, begin = 0, start
        for i in range(start, end + 1):
            char = text[i] if i < end else ","
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                term = " ".join(text[begin:i].split())
                begin = i + 1
                if term:
                    yield term


def test_sql_is_written_in_db_only() -> None:
    outside = [
        f"{module}:{line}"
        for module, strings in _modules()
        if not module.startswith("db/")
        for line, text in strings
        if is_sql(text)
    ]
    assert outside == []


def test_no_jsonb_object_is_built() -> None:
    built = [
        f"{module}:{line}"
        for module, strings in _modules()
        for line, text in strings
        if _JSONB.search(text) and module not in _JSONB_REVIEWED
    ]
    assert built == []


def test_every_order_says_where_its_nulls_go() -> None:
    open_ended = []
    seen: set[tuple[str, str]] = set()
    for module, strings in _modules():
        if not module.startswith("db/"):
            continue
        for line, text in strings:
            for term in _order_terms(text):
                if "{}" in term or "NULLS" in term.upper() or _SAFE.search(term):
                    continue
                seen.add((module, term))
                if (module, term) not in _REVIEWED:
                    open_ended.append(f"{module}:{line}: {term}")
    assert open_ended == []
    # an entry no term needs any more goes
    assert set(_REVIEWED) - seen == set()


def test_the_order_terms_are_read_whole() -> None:
    text = "SELECT a FROM t ORDER BY coalesce(a, 0) DESC, b NULLS FIRST, c LIMIT 3"
    assert list(_order_terms(text)) == ["coalesce(a, 0) DESC", "b NULLS FIRST", "c"]
    assert list(_order_terms("SELECT array_agg(x ORDER BY y) FROM t")) == ["y"]
