"""The grammar of a budget title is read in ``core/budget_titles.py``, a publication is cited
and its KOOP id read in ``core/publications.py``, and the kinds of EU act are named in
``core/identifiers.py`` (``EU_ACT_KINDS``).
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from tests.conventions._scan import SRC, _python_files

BUDGET_TITLES_HOME = SRC / "core" / "budget_titles.py"
PUBLICATIONS_HOME = SRC / "core" / "publications.py"
EU_ACT_KINDS_HOME = SRC / "core" / "identifiers.py"

# The grammar of a budget title: "Vaststelling van de begrotingsstaten … voor het jaar 2027".
_BUDGET_GRAMMAR = re.compile(r"van de begrotingssta|voor het jaar", re.IGNORECASE)
# A citation made by hand ("Stb.", f"{kind}. {year}, {number}") or a KOOP id read by a
# pattern of its own ("(stb|stcrt)-(\d{4})").
_PUBLICATION_FORMS = re.compile(
    r"^(?:Stb|Stcrt|Trb)\.$|\. \{[^{}]*\}, \{|\((?:\?P<\w+>)?(?:stb|stcrt|trb)\|",
    re.IGNORECASE,
)
# ("Besluit" is also a record of the Tweede Kamer.)
_EU_ACT_NOUNS = {"Richtlijn", "Verordening", "Kaderbesluit", "Beschikking"}


def _code_strings(source: str) -> list[str]:
    """The string literals of *source* (also the text of f-strings, ``{name}`` for each
    value), docstrings left out."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            found.append(
                "".join(
                    v.value
                    if isinstance(v, ast.Constant)
                    else "{" + ast.unparse(v.value) + "}"
                    for v in node.values
                )
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.append(node.value)
    return found


def _copies(source: str, home: pathlib.Path, path: pathlib.Path) -> list[str]:
    if path == home:
        return []
    strings = _code_strings(source)
    if home == BUDGET_TITLES_HOME:
        return [s for s in strings if _BUDGET_GRAMMAR.search(s)]
    if home == PUBLICATIONS_HOME:
        return [s for s in strings if _PUBLICATION_FORMS.search(s)]
    return [s for s in strings if s in _EU_ACT_NOUNS]


def test_the_scan_for_copies_would_catch_one() -> None:
    other = SRC / "core" / "other.py"
    budget = 'X = re.compile(r"^wijziging van de begrotingssta")'
    assert _copies(budget, BUDGET_TITLES_HOME, other)
    assert not _copies(
        '"""Vaststelling van de begrotingsstaten."""', BUDGET_TITLES_HOME, other
    )
    assert _copies('name = f"{kind}. {year}, {number}"', PUBLICATIONS_HOME, other)
    assert _copies('SERIES = {"stb": "Stb."}', PUBLICATIONS_HOME, other)
    assert _copies(r'X = re.compile(r"^(stb|stcrt)-(\d{4})")', PUBLICATIONS_HOME, other)
    assert not _copies('detail = "series stb|stcrt|trb"', PUBLICATIONS_HOME, other)
    assert _copies('LABELS = {"directive": "Richtlijn"}', EU_ACT_KINDS_HOME, other)


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
@pytest.mark.parametrize(
    "home",
    [BUDGET_TITLES_HOME, PUBLICATIONS_HOME, EU_ACT_KINDS_HOME],
    ids=lambda p: p.name,
)
def test_budget_titles_publications_and_eu_acts_are_read_in_one_place(
    path: pathlib.Path, home: pathlib.Path
) -> None:
    found = _copies(path.read_text(), home, path)
    assert not found, (
        f"{path.relative_to(SRC)} has its own copy of what {home.relative_to(SRC)} "
        f"holds: {found}"
    )
