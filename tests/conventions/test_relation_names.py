"""Relation names are written once, in ``config.constants`` (and ``core.relations``).

Everywhere else they are referenced through a ``RELATION_*`` constant, SQL included,
which is built with f-strings from those constants.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from lawgraph.core.relations import RELATION_NAMES
from tests.paths import SRC
from tests.source_scan import RELATION_NAME_HOMES, python_files


def _quoted_relation_names(source: str) -> set[str]:
    """Relation names that appear as a quoted string anywhere in *source*.

    Covers plain string literals and the relation names baked into a SQL
    string, which is why the scan is textual rather than AST-based: a name
    interpolated from a constant (``f"... '{RELATION_PART_OF}' ..."``) never
    appears literally, while a hand-written ``'PART_OF'`` does.
    """
    found: set[str] = set()
    for name in RELATION_NAMES:
        # A quote, then the bare name, then a quote — no surrounding word
        # characters, so ``PART_OF`` does not match inside ``PART_OF_X``.
        if re.search(rf"""['"]{name}['"]""", source):
            found.add(name)
    return found


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_relation_names_are_only_written_in_the_constants(path: pathlib.Path) -> None:
    if path in RELATION_NAME_HOMES:
        return
    written = _quoted_relation_names(path.read_text())
    assert not written, (
        f"{path.relative_to(SRC)} spells out {sorted(written)}; use the "
        f"RELATION_* constant (in SQL: an f-string from the constant)."
    )


def test_the_scan_would_catch_a_literal() -> None:
    """The guard above is only worth having if it actually matches."""
    assert _quoted_relation_names("FILTER e.relation == 'PART_OF'") == {"PART_OF"}
    assert _quoted_relation_names('relation="REFERS_TO"') == {"REFERS_TO"}
    assert _quoted_relation_names("relation == '{RELATION_PART_OF}'") == set()
    assert _quoted_relation_names("PART_OF_SOMETHING_ELSE") == set()
