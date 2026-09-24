"""Relations between dossiers: the budget a change revises, the nota it accompanies, and the
dossiers of two cases the Kamer relates. Titles are those of the Kamer."""

from __future__ import annotations

from lawgraph.core.dossier_relations import (
    DossierRef,
    accompanied_notas,
    budget_amendments,
    related_dossiers,
)


def _dossier(label: str, title: str) -> DossierRef:
    number, _, suffix = label.partition("-")
    return DossierRef.of(
        {"label": label, "number": number, "suffix": suffix, "title": title}
    )


_BUDGETS_2026 = [
    _dossier("36800", "Nota over de toestand van ’s Rijks Financiën"),
    _dossier(
        "36800-XXII",
        "Vaststelling van de begrotingsstaten van het Ministerie van Volkshuisvesting en "
        "Ruimtelijke Ordening (XXII) voor het jaar 2026",
    ),
    _dossier(
        "36800-IX",
        "Vaststelling van de begrotingsstaat van het Ministerie van Financiën (IXB) en de "
        "begrotingsstaat van Nationale Schuld (IXA) voor het jaar 2026",
    ),
    _dossier(
        "36800-B",
        "Vaststelling van de begrotingsstaat van het gemeentefonds voor het jaar 2026",
    ),
    _dossier(
        "36800-XIII",
        "Vaststelling van de begrotingsstaten van het Ministerie van Economische Zaken "
        "(XIII) voor het jaar 2026",
    ),
]
_BUDGETS_2027 = [
    _dossier("37020", "Nota over de toestand van ’s Rijks Financiën"),
    _dossier(
        "37020-XXII",
        "Vaststelling van de begrotingsstaten van Volkshuisvesting en Ruimtelijke Ordening "
        "(XXII) voor het jaar 2027",
    ),
]


def _links(found) -> set[tuple[str, str]]:
    return {(link.from_label, link.to_label) for link in found}


def test_a_budget_change_revises_the_budget_of_its_chapter_and_year() -> None:
    changes = [
        _dossier(
            "37035-XXII",
            "Wijziging van de begrotingsstaten van het Ministerie van Volkshuisvesting en "
            "Ruimtelijke Ordening (XXII) voor het jaar 2026 (wijziging samenhangende met de "
            "Miljoenennota)",
        ),
        _dossier(
            "36915-B",
            "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar 2026 "
            "(wijziging samenhangende met de Voorjaarsnota)",
        ),
        # an incidental one has a number of its own and names its chapter in its title
        _dossier(
            "36999",
            "Wijziging van de begrotingsstaat van het Ministerie van Financiën (IXB) voor het "
            "jaar 2026 (Incidentele suppletoire begroting inzake Oekraïne Facility)",
        ),
        # or only its budget
        _dossier(
            "36998",
            "Wijziging van de begrotingsstaten van het Ministerie van Economische Zaken voor "
            "het jaar 2026 (Incidentele suppletoire begroting inzake maatregelen)",
        ),
        # a slotwet settles the budget of its year
        _dossier(
            "37005-XXII",
            "Jaarverslag en slotwet Ministerie van Volkshuisvesting en Ruimtelijke Ordening "
            "2026",
        ),
    ]
    found = list(budget_amendments(_BUDGETS_2026 + _BUDGETS_2027 + changes))
    assert _links(found) == {
        ("37035-XXII", "36800-XXII"),  # 2026, not the 2027 budget of the same chapter
        ("36915-B", "36800-B"),
        ("36999", "36800-IX"),
        ("36998", "36800-XIII"),
        ("37005-XXII", "36800-XXII"),
    }
    rules = {link.from_label: link.meta["rule"] for link in found}
    assert rules["37005-XXII"] == "slotwet"
    assert rules["37035-XXII"] == "begrotingswijziging"


def test_a_change_without_its_budget_in_the_graph_revises_nothing() -> None:
    change = _dossier(
        "31792-G",
        "Wijziging van de begrotingsstaat van het BTW-compensatiefonds voor het jaar 2008 "
        "(wijziging samenhangende met de Najaarsnota)",
    )
    assert list(budget_amendments([*_BUDGETS_2026, change])) == []


def test_a_budget_change_accompanies_the_nota_it_names() -> None:
    notas = [
        _dossier("36915", "Voorjaarsnota 2026"),
        _dossier("36850", "Najaarsnota 2025"),
    ]
    changes = [
        # presented on Prinsjesdag 2026 with the budgets of 2027: goes with 37020
        _dossier(
            "37035-XXII",
            "Wijziging van de begrotingsstaten van het Ministerie van Volkshuisvesting en "
            "Ruimtelijke Ordening (XXII) voor het jaar 2026 (wijziging samenhangende met de "
            "Miljoenennota)",
        ),
        _dossier(
            "36915-B",
            "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar 2026 "
            "(wijziging samenhangende met de Voorjaarsnota)",
        ),
        _dossier(
            "36850-XVI",
            "Wijziging van de begrotingsstaten van het Ministerie van Volksgezondheid, "
            "Welzijn en Sport (XVI) voor het jaar 2025 (wijziging samenhangende met "
            "Najaarsnota)",
        ),
        # an incidental change names no nota
        _dossier(
            "36999",
            "Wijziging van de begrotingsstaat van het Ministerie van Financiën (IXB) voor het "
            "jaar 2026 (Incidentele suppletoire begroting inzake Oekraïne Facility)",
        ),
    ]
    found = list(accompanied_notas(_BUDGETS_2026 + _BUDGETS_2027 + notas + changes))
    assert _links(found) == {
        ("37035-XXII", "37020"),
        ("36915-B", "36915"),
        ("36850-XVI", "36850"),
    }
    assert {link.meta["nota"] for link in found} == {
        "miljoenennota",
        "voorjaarsnota",
        "najaarsnota",
    }


def test_the_cases_the_kamer_relates_relate_their_dossiers() -> None:
    letter = {
        "id": "brief-1",
        "kind": "Brief regering",
        "dossier_numbers": ["21501-02"],
        "related_cases": [
            {"id": "motie-1", "kind": "Motie", "dossier_numbers": ["36800-V"]},
            {"id": "motie-2", "kind": "Motie", "dossier_numbers": ["36800-V"]},
            # a case of the same dossier relates no dossiers
            {
                "id": "brief-0",
                "kind": "Brief commissie",
                "dossier_numbers": ["21501-02"],
            },
            {"id": "zonder", "kind": "Motie", "dossier_numbers": []},
        ],
    }
    other = {
        "id": "brief-2",
        "kind": "Brief regering",
        "dossier_numbers": ["21501-02"],
        "related_cases": [
            {"id": "begroting", "kind": "Begroting", "dossier_numbers": ["36800-V"]}
        ],
    }
    found = list(related_dossiers([letter, other]))
    assert [(link.from_label, link.to_label) for link in found] == [
        ("21501-02", "36800-V")
    ]
    assert found[0].meta == {
        "cases": 3,
        "case_kinds": ["Brief regering → Begroting", "Brief regering → Motie"],
    }
