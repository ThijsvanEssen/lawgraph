"""The Kamerstukken a subject names (``core.kamerstuk_refs``), and the relation each gets."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import RELATION_ANSWERS, RELATION_REFERS_TO
from lawgraph.core.kamerstuk_refs import cited_papers
from lawgraph.pipelines.semantic.tk_cited_papers import relation_of

DOSSIERS = {"21501-02", "21501-32", "36945-XIV", "36600-XV", "36200-XVI"}


def _papers(text: str) -> list[tuple[str, str | None, int]]:
    found = cited_papers(text, lambda n, s: f"{n}-{s}" in DOSSIERS)
    return [(p.number, p.suffix, p.sequence) for p in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Uitvoering van de motie van het lid Vliegenthart c.s. over een plan "
            "(Kamerstuk 25424-795) en de motie van het lid Diederik van Dijk c.s. over "
            "steun (Kamerstuk 29282-638)",
            [("25424", None, 795), ("29282", None, 638)],
        ),
        (
            "Lijst van vragen over het jaarverslag (Kamerstuk 36945-XIV-1)",
            [("36945", "XIV", 1)],
        ),
        ("Geannoteerde agenda (Kamerstuk 21501-02-3465)", [("21501", "02", 3465)]),
        # 35261-13 is no dossier: three papers of 35261
        (
            "Amendementen (Kamerstuk 35261-13-15-16)",
            [("35261", None, n) for n in (13, 15, 16)],
        ),
        ("Brief (Kamerstuk 29 507, nr. 146)", [("29507", None, 146)]),
        ("Brief (Kamerstuk 33161, nr. 9)", [("33161", None, 9)]),
        ("Brief (Kamerstuk 34348 nr. 104)", [("34348", None, 104)]),
        ("Brief (Kamerstuk 36 200 XVI, nr. 12)", [("36200", "XVI", 12)]),
        ("Brief (Kamerstukken 25424, nr. 795)", [("25424", None, 795)]),
        (
            "Moties (Kamerstuk 36441, nrs. 38 en 39)",
            [("36441", None, 38), ("36441", None, 39)],
        ),
        ("Brief (Kamerstukken II 2025/26, 36600-XV, nr. 5)", [("36600", "XV", 5)]),
        ("Brief (Kamerstuk 32 279-292)", [("32279", None, 292)]),
        (
            "Moties (Kamerstuk 36222-8, 9 en 10)",
            [("36222", None, n) for n in (8, 9, 10)],
        ),
        (
            "Moties (Kamerstuk 36222-8 en Kamerstuk 36600-XV-9)",
            [("36222", None, 8), ("36600", "XV", 9)],
        ),
        ("Brief (kamerstuknummer 32043, nr. 710)", [("32043", None, 710)]),
    ],
)
def test_the_forms_the_kamer_writes(
    text: str, expected: list[tuple[str, str | None, int]]
) -> None:
    assert _papers(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Jaarverslag (Kamerstuk 37020-XIV)",  # a dossier, no paper
        "Brief (Kamerstuk 36945)",
        "Voorstel (Kamerstuk 37035-M)",  # a paper of the Eerste Kamer by its letter
        "Geannoteerde agenda (Kamerstuk 21501-02)",  # the dossier 21501-02, not paper 2
        "Rijkswet (Kamerstuk 36956-(R2220))",
        "Gewijzigde motie ... (ter vervanging van Kamerstuk 29826-322)",
        "Motie 25424-795 zonder het woord",
    ],
)
def test_no_paper(text: str) -> None:
    assert _papers(text) == []


def test_the_text_as_written() -> None:
    (paper,) = cited_papers("Brief (Kamerstuk 29 507, nr. 146)", lambda n, s: False)
    assert paper.text == "29 507, nr. 146"


def test_a_letter_of_the_government_answers_a_motion() -> None:
    assert relation_of("Brief regering", "Motie") == RELATION_ANSWERS
    assert relation_of("Brief regering", "Motie (gewijzigd/nader)") == RELATION_ANSWERS
    assert relation_of("Brief regering", "Amendement") == RELATION_REFERS_TO
    assert relation_of("Bijlage", "Motie") == RELATION_REFERS_TO
    assert relation_of("Lijst van vragen", "Brief regering") == RELATION_REFERS_TO
    assert relation_of(None, None) == RELATION_REFERS_TO
