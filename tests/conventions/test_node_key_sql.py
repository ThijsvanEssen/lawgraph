"""A query makes a node key of an identifier with ``lg_node_key`` (``db/schema.py``), the
SQL twin of ``core.models.make_node_key``; it does not imitate it with ``lower`` and
``replace``, which hold for one kind of identifier only and break silently when the key
changes. ``tests/pg/test_node_key_sql.py`` keeps the two the same."""

from __future__ import annotations

import re

from tests.conventions._scan import DB

_QUERIES = DB / "queries"

# a key made of an identifier by hand: lower case with '-' (or every character but a letter
# or a digit) as '_', or an id or key of an identifier (a BWB id) in lower case
_IMITATED = re.compile(
    r"replace\(lower\([^;]*?'-', '_'\)"
    r"|\[\^a-z0-9_?\]\+"
    r"|/' \|\| lower\("
    r"|\.key = lower\("
    r"|lower\(coalesce\(\w+\.bwb_id"
)


# Where the feed keeps the cheap spelling of a GUID's key (``feed_relations.bwb_key`` that
# of a BWB id): ``lg_node_key`` in its place turns the plan of the feed's page.
_KEPT = {"feed.py": ("_PERSON_KEY = ",)}


def test_a_query_makes_a_node_key_with_lg_node_key() -> None:
    offenders = [
        f"{path.relative_to(_QUERIES)}:{line}"
        for path in sorted(_QUERIES.rglob("*.py"))
        for text in [path.read_text()]
        for match in _IMITATED.finditer(text)
        for line in [text[: match.start()].count(chr(10)) + 1]
        if not text.splitlines()[line - 1].startswith(
            _KEPT.get(path.relative_to(_QUERIES).as_posix(), ("\0",))
        )
    ]
    assert not offenders, offenders
