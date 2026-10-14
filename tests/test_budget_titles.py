"""The titles of the budget laws: what they say, and the short title a dossier goes by.
Titles are those of the Kamer."""

from __future__ import annotations

import pytest

from lawgraph.core.budget_titles import parse_budget_title
from lawgraph.core.dossier_numbers import short_title


@pytest.mark.parametrize(
    ("title", "short"),
    [
        (
            "Vaststelling van de begrotingsstaten van het Ministerie van Defensie (X) voor "
            "het jaar 2027",
            "Begroting Defensie 2027",
        ),
        (
            "Vaststelling van de begrotingsstaat van het Ministerie van Financiën (IXB) en de "
            "begrotingsstaat van Nationale Schuld (IXA) voor het jaar 2027",
            "Begroting Financiën 2027",
        ),
        (
            "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar 2026 "
            "(wijziging samenhangende met de Miljoenennota)",
            "Suppletoire begroting gemeentefonds 2026 (Miljoenennota)",
        ),
        # without "de", and with a double space: the same form
        (
            "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar  2023 "
            "(wijziging samenhangende met Miljoenennota)",
            "Suppletoire begroting gemeentefonds 2023 (Miljoenennota)",
        ),
        # the occasion as written, also when it is no nota
        (
            "Wijziging van de begrotingsstaten van het Ministerie van Onderwijs, Cultuur en "
            "Wetenschap (VIII) voor het jaar 2011 (wijziging samenhangende met de incidentele "
            "suppletoire begrotingen)",
            "Suppletoire begroting Onderwijs, Cultuur en Wetenschap 2011 (incidentele "
            "suppletoire begrotingen)",
        ),
        # a second budget of the same year
        (
            "Wijziging van de begrotingsstaten van het Ministerie van Volkshuisvesting, "
            "Ruimtelijke Ordening en Milieubeheer (XI) voor het jaar 2010 en van de "
            "begrotingsstaat van het Waddenfonds voor het jaar 2010 (Wijziging samenhangende "
            "met de Najaarsnota)",
            "Suppletoire begroting Volkshuisvesting, Ruimtelijke Ordening en Milieubeheer "
            "2010 (Najaarsnota)",
        ),
        (
            "Jaarverslag en slotwet Ministerie van Defensie 2025",
            "Slotwet Defensie 2025",
        ),
        ("Jaarverslag en slotwet van de Koning 2022", "Slotwet van de Koning 2022"),
        # not of the plain form: the parentheses that end it
        (
            "Wijziging van de begrotingsstaat van het Ministerie van Financiën (IXB) voor het "
            "jaar 2020 (Incidentele suppletoire begroting inzake Noodpakket banen en economie)",
            "Incidentele suppletoire begroting inzake Noodpakket banen en economie",
        ),
        (
            "Wijziging van de begrotingsstaat behorende bij de begroting van de Koning (I) "
            "voor het jaar 2010 (wijziging samenhangende met de Voorjaarsnota)",
            "wijziging samenhangende met de Voorjaarsnota",
        ),
        ("Slotwet en jaarverslag Ministerie van Buitenlandse Zaken 2008", None),
    ],
)
def test_a_budget_law_goes_by_its_chapter_and_year(
    title: str, short: str | None
) -> None:
    assert short_title(title) == short


def test_a_budget_change_says_its_year_chapter_and_nota() -> None:
    change = parse_budget_title(
        "Wijziging van de begrotingsstaten van het Ministerie van Justitie (VI) voor het "
        "jaar 2008 wijziging samenhangende met de Najaarsnota)"
    )
    assert change is not None
    assert (change.act, change.year, change.chapter, change.nota) == (
        "change",
        2008,
        "VI",
        "najaarsnota",
    )
    assert change.subject == "het ministerie van justitie"
    assert change.short_title is None


def test_a_slotwet_is_dated_by_its_last_year() -> None:
    slotwet = parse_budget_title(
        "Slotwet en jaarverslag Ministerie van Landbouw, Natuur en Voedselkwaliteit 2008"
    )
    assert slotwet is not None
    assert (slotwet.act, slotwet.year) == ("slotwet", 2008)


def test_another_title_is_no_budget_law() -> None:
    assert parse_budget_title("Wijziging van de Woningwet") is None
    assert parse_budget_title(None) is None
