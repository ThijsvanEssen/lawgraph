"""The name a dossier goes by, one rule for the feed, the nodes and the server HTML (pure)."""

from __future__ import annotations

import pytest

from lawgraph.core.dossier_names import dossier_name, dossier_own_name
from lawgraph.core.names import title_of

BILL = "Wijziging van de Archiefwet 1995 in verband met de modernisering daarvan"


@pytest.mark.parametrize(
    ("dossier", "name", "own", "title"),
    [
        # its title: the parentheses that end a bill's title, a budget's chapter and year
        (
            {
                "label": "36496",
                "title": "Regels over huurprijzen (Wet betaalbare huur)",
            },
            ("Wet betaalbare huur", "title"),
            "Wet betaalbare huur",
            "36496 Wet betaalbare huur",
        ),
        # the name its bill gives itself, its case, the law it changes
        (
            {
                "label": "36889",
                "title": BILL,
                "official_short": {"title": "Archiefwet", "basis": "citation"},
            },
            ("Archiefwet", "citation"),
            "Archiefwet",
            "36889 Archiefwet",
        ),
        (
            {
                "label": "36890",
                "title": BILL,
                "official_short": {"title": "Wet open overheid", "basis": "case"},
            },
            ("Wet open overheid", "case"),
            "Wet open overheid",
            "36890 Wet open overheid",
        ),
        (
            {
                "label": "36891",
                "title": BILL,
                "official_short": {"title": "Archiefwet 1995", "basis": "amended_law"},
            },
            ("Archiefwet 1995", "amended_law"),
            "wijziging van Archiefwet 1995",
            "36891 wijziging van Archiefwet 1995",
        ),
        # no name: the number first, then its title
        ({"label": "36892", "title": BILL}, (None, None), None, f"36892 {BILL}"),
        ({"label": "36600-VII"}, (None, None), None, "Dossier 36600 VII"),
    ],
)
def test_a_dossier_is_named_by_one_rule(
    dossier: dict[str, object],
    name: tuple[str | None, str | None],
    own: str | None,
    title: str,
) -> None:
    assert dossier_name(dossier) == name
    assert dossier_own_name(dossier) == own
    key = str(dossier["label"]).lower().replace("-", "_")
    assert title_of(f"dossiers/{key}", dossier) == title
