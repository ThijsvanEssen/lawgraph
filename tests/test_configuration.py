"""Configuration has one home, so nothing in ``.env`` is ever ignored.

1. Only ``config/settings.py`` reads the environment (and loads ``.env`` on import).
2. Collection names are written once, in ``config/constants.py``; AQL uses the constants.
3. ``.env.example`` lists only variables that are actually read.
"""

from __future__ import annotations

import pathlib
import re

from lawgraph.config.constants import COLLECTION_EDGES, DOCUMENT_COLLECTIONS

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lawgraph"
SETTINGS = SRC / "config" / "settings.py"
CONSTANTS = SRC / "config" / "constants.py"

_ENVIRONMENT_ACCESS = re.compile(r"\bos\.(getenv|environ)\b|\bload_dotenv\b")
_AQL_COLLECTION_LITERAL = re.compile(
    r"\b(?:IN|INTO|OUTBOUND|INBOUND|ANY)\s+(%s)\b(?![_.\[(])"
    % "|".join(sorted((*DOCUMENT_COLLECTIONS, COLLECTION_EDGES), key=len, reverse=True))
)


def _modules() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def test_only_settings_reads_the_environment() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in _modules()
        if path != SETTINGS and _ENVIRONMENT_ACCESS.search(path.read_text())
    ]
    assert offenders == []


def test_aql_names_collections_through_constants() -> None:
    offenders = [
        (str(path.relative_to(SRC)), match.group(1))
        for path in _modules()
        if path != CONSTANTS
        for match in _AQL_COLLECTION_LITERAL.finditer(path.read_text())
    ]
    assert offenders == []


def test_env_example_lists_only_variables_that_are_read() -> None:
    readers = SETTINGS.read_text() + (ROOT / "docker-compose.yml").read_text()
    listed = re.findall(
        r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M
    )
    assert listed

    def is_read(variable: str) -> bool:
        if variable.startswith("LAWGRAPH_CONFIDENCE_"):
            return "LAWGRAPH_CONFIDENCE_" in readers
        if re.fullmatch(r"LAWGRAPH_(RETRIEVE|NORMALIZE|SEMANTIC)_SKIP_\w+", variable):
            return "_SKIP_" in readers
        return (
            f'"{variable}"' in readers
            or re.search(rf"\${{{variable}(:-[^}}]*)?}}", readers) is not None
        )

    assert [v for v in listed if not is_read(v)] == []


def test_view_comparison_ignores_server_defaults_and_analyzer_order() -> None:
    from lawgraph.db.schema import _indexed_fields

    def link(analyzers: list[str], **server_defaults: object) -> dict:
        fields = {"props": {"fields": {"name": {"analyzers": analyzers}}}}
        return {"committees": {"fields": fields, **server_defaults}}

    specified = link(["text_en", "identity"])
    stored = link(["identity", "text_en"], trackListPositions=False)

    assert _indexed_fields(specified) == _indexed_fields(stored)
    assert _indexed_fields(specified) != _indexed_fields(link(["text_en"]))


def test_a_dotted_view_field_indexes_a_field_of_every_element_of_an_array() -> None:
    from lawgraph.db.schema import _indexed_fields, _nested_fields

    spec = {"heading": ["text_nl"], "breadcrumb.title": ["text_nl"]}
    nested = _nested_fields(spec)
    assert nested == {
        "heading": {"analyzers": ["text_nl"]},
        "breadcrumb": {"fields": {"title": {"analyzers": ["text_nl"]}}},
    }
    link = {"articles": {"fields": {"props": {"fields": nested}}}}
    assert _indexed_fields(link) == {
        "articles": {k: frozenset(v) for k, v in spec.items()}
    }
