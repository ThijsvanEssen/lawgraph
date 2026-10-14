"""A dossier number a reader sees in the server HTML is in its official notation
(``36600 VIII``, ``core.dossier_numbers.official_number``); its address keeps the label
(``/dossiers/36600-VIII``), and a paper its own number (``36600-VIII-5``). Every page that
names a dossier, rendered with one that has a suffix."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

from lawgraph.api.seo import pages
from lawgraph.api.seo.pages import Page

LABEL = "36600-VIII"
# the label on its own, not as the head of a paper's number
_BARE_LABEL = re.compile(rf"{LABEL}(?!-\d)")
DOSSIER = {"id": "dossiers/36600_viii", "key": "36600_viii", "label": LABEL}
NUMBERS = {"dossier_numbers": [LABEL]}

ROWS: dict[str, tuple[Callable[[dict[str, Any]], Page], dict[str, Any]]] = {
    "dossier": (pages.dossier_page, {**DOSSIER, "props": {"label": LABEL}}),
    "paper": (
        pages.paper_page,
        {"id": "documents/x", "date": None, "light": {"dossier_number": "36600",
         "dossier_suffix": "VIII", "number": 5, "kind": "Brief"}},
    ),
    "case": (
        pages.case_page,
        {"id": "cases/x", "key": "x", "props": {"number": "2025Z1"},
         "dossier": {"id": DOSSIER["id"], "label": LABEL}},
    ),
    "activity": (pages.activity_page, {"id": "activities/x", "key": "x",
                                       "props": NUMBERS}),
    "publication": (pages.publication_page, {"id": "publications/kst-1",
                                             "props": NUMBERS}),
    "commitment": (
        pages.commitment_page,
        {"id": "commitments/x", "key": "x", "props": {},
         "dossiers": [{"id": DOSSIER["id"], "key": DOSSIER["key"],
                       "props": {"label": LABEL}}]},
    ),
    "decision": (pages.decision_page, {"id": "decisions/x", "props": NUMBERS}),
}  # fmt: skip


def _seen(page: Page) -> str:
    """What a reader sees of *page*: its texts, without the addresses."""
    crumbs = " ".join(label for label, _ in page.crumbs)
    html = re.sub(r'href="[^"]*"', "", page.body)
    return " ".join((page.title, page.description, crumbs, html))


@pytest.mark.parametrize("kind", ROWS)
def test_a_dossier_number_in_a_page_is_written_officially(kind: str) -> None:
    build, row = ROWS[kind]
    page = build(row)
    assert "36600 VIII" in _seen(page)
    assert not _BARE_LABEL.search(_seen(page))
