"""A json shape the API shows in several places is built in SQL once: what the coalition did
on a vote (``coalition_sql.coalition_object``), a judgment as a link or as a row of a list
(``judgment_sql``), the lead committee of an activity (``activities.lead_committee``); the
name a member goes by is the column ``members.list_name``."""

from __future__ import annotations

import re

import pytest

from tests.conventions._scan import DB

_QUERIES = DB / "queries"

# shape -> (how it looks written out, the one module that builds it)
_SHAPES = {
    "coalition_object": (re.compile(r"'coalition_for',"), "coalition_sql.py"),
    "judgment_sql": (
        re.compile(
            r"'_key', [\w{}]+\.key,\s*'props', json_build_object\(\s*"
            r"'(?:display_name|ecli)', [\w{}]+\.pj_"
        ),
        "judgment_sql.py",
    ),
    "lead_committee": (
        re.compile(r"ON c\.id = \w+\.to_id\s+WHERE \w+\.from_id = [^;]*?LIMIT 1"),
        "activities.py",
    ),
    "members.list_name": (re.compile(r"props -> 'known_as'"), "../schema.py"),
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_shape_is_built_in_one_place(shape: str) -> None:
    spelled, home = _SHAPES[shape]
    offenders = [
        f"{path.relative_to(_QUERIES)}:{text[: match.start()].count(chr(10)) + 1}"
        for path in sorted(_QUERIES.rglob("*.py"))
        if path != (_QUERIES / home).resolve()
        for text in [path.read_text()]
        for match in spelled.finditer(text)
    ]
    assert not offenders, offenders
