"""Stored property names are English. What a node carries is ours to name, so no props
field may be spelled in Dutch.
"""

from __future__ import annotations

import ast

from tests.paths import SRC
from tests.source_scan import DUTCH_STEMS

PROPS_MODULE = SRC / "core" / "props.py"

# Dutch words that must not be a token of a stored property name. Matching is
# per snake_case token, so ``title`` does not trip on ``titel`` and ``number``
# does not trip on ``nummer``.
DUTCH_PROP_TOKENS = frozenset(
    {
        *DUTCH_STEMS,
        "aangenomen",
        "actief",
        "afgedaan",
        "afkorting",
        "agendapunt",
        "besluit",
        "datum",
        "fase",
        "gedaan",
        "geopend",
        "gesloten",
        "kamerstuk",
        "kamerstuknummer",
        "lid",
        "naam",
        "nummer",
        "onderwerp",
        "partij",
        "persoon",
        "soort",
        "tekst",
        "titel",
        "toestand",
        "toevoeging",
        "traject",
        "verdrag",
        "verdragsnummer",
        "vergaderjaar",
        "vergadering",
        "volgnummer",
        "wet",
        "zetels",
    }
)


def _props_fields() -> list[tuple[str, str]]:
    """``(class name, field name)`` for every annotated field in props.py."""
    tree = ast.parse(PROPS_MODULE.read_text())
    return [
        (node.name, stmt.target.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]


def _dutch_tokens(field: str) -> frozenset[str]:
    return DUTCH_PROP_TOKENS & set(field.lower().split("_"))


def test_the_props_scan_finds_the_schemas() -> None:
    """The guard below is only worth having if it reads real fields."""
    fields = _props_fields()
    assert ("DossierProps", "current_phase") in fields
    assert len(fields) > 100


def test_the_props_scan_tells_dutch_from_english() -> None:
    """Whole-token matching, so the English word next to it stays clean."""
    assert _dutch_tokens("titel_source") == {"titel"}
    assert _dutch_tokens("dossier_nummer") == {"nummer"}
    assert _dutch_tokens("title_source") == set()
    assert _dutch_tokens("dossier_number") == set()
    assert _dutch_tokens("date") == set()


def test_props_field_names_are_english() -> None:
    offenders = sorted(
        f"{class_name}.{field}"
        for class_name, field in _props_fields()
        if _dutch_tokens(field)
    )
    assert not offenders, (
        f"{sorted(offenders)} are stored under a Dutch name; a property name "
        f"is ours to choose, so it is English."
    )
