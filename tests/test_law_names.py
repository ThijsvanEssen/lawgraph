"""The laws a dossier title names."""

from __future__ import annotations

import pytest

from lawgraph.core.law_names import laws_in_title


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Wijziging van het Wetboek van Strafrecht en het Wetboek van Strafvordering "
            "in verband met de herziening",
            ["Wetboek van Strafrecht", "Wetboek van Strafvordering"],
        ),
        ("Wijziging van de Vreemdelingenwet 2000", ["Vreemdelingenwet 2000"]),
        (
            "Wijziging van de Algemene wet bestuursrecht in verband met ...",
            ["Algemene wet bestuursrecht"],
        ),
        (
            "Wijziging van de Wet op de rechterlijke organisatie en de Opiumwet",
            ["Wet op de rechterlijke organisatie", "Opiumwet"],
        ),
        ("Vaststelling van de begrotingsstaten voor het jaar 2026", []),
        # a kind of law is no name
        ("Verzamelwet Justitie en een Uitvoeringswet", ["Verzamelwet Justitie"]),
        (None, []),
    ],
)
def test_the_laws_a_title_names(title: str | None, expected: list[str]) -> None:
    assert laws_in_title(title) == expected
