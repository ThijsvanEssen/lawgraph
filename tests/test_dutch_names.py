"""How a Dutch text writes a name: titles, initials, particles, surnames and places, in one
module."""

from __future__ import annotations

import re

import pytest

from lawgraph.core.dutch_names import (
    INITIALS,
    LONG_WORD,
    PARTICLES,
    PLACE,
    TITLE,
    surname,
)
from tests.optional import present
from tests.paths import SRC


@pytest.mark.parametrize(
    "place",
    [
        "Utrecht",
        "Den Haag",
        "'s-Gravenhage",
        "‘s-Hertogenbosch",
        "'s Gravenhage",
        "'t Zandt",
        "Bergen op Zoom",
        "Nieuwerkerk aan den IJssel",
        "Wijk bij Duurstede",
        "Alphen a/d Rijn",
    ],
)
def test_a_place(place: str) -> None:
    assert re.fullmatch(PLACE, place)


@pytest.mark.parametrize(
    "initials", ["A.", "P.J. ", "IJ.", "Th.", "Chr.", "Joh.", "Jac.", "Fr.-J.", "Wm."]
)
def test_initials(initials: str) -> None:
    assert re.fullmatch(INITIALS, initials)


@pytest.mark.parametrize(
    "name",
    [
        "Hartlief",
        "van der Meulen",
        "Witteveen-van den Berg",
        "in 't Veld",
        "uit den Bogaard",
        "op de Beek",
        "du Pré",
        "de la Court",
        "Bij de Vaate",
        "vander Laan",
    ],
)
def test_a_surname(name: str) -> None:
    assert re.fullmatch(surname(), name)


def test_a_surname_ends_before_a_stop_word() -> None:
    assert present(re.match(surname(stop="te"), "de Jong te Amsterdam"))[0] == "de Jong"


def test_a_long_word_is_no_initial() -> None:
    assert not re.fullmatch(surname(LONG_WORD), "V")
    assert re.fullmatch(surname(), "X")


@pytest.mark.parametrize(
    "text", ["mr. ", "Mr ", "mr.", "prof. ", "drs ", "ing. ", "IR. "]
)
def test_a_title(text: str) -> None:
    assert re.fullmatch(TITLE, text)


def test_ing_without_its_dot_is_no_title() -> None:
    assert not re.match(TITLE, "ING Bank")


def test_the_particles_are_words() -> None:
    assert {"van", "der", "t", "d", "vander"} <= PARTICLES
    assert all(re.fullmatch("[a-z]+", p) for p in PARTICLES)


# What a copy of the vocabulary looks like: a list of particles, of initials, the start of
# "'s-Gravenhage", a list of titles.
_COPIES = re.compile(
    r"ten\|ter|ter\|ten|\"ten\", \"ter\"|\"ter\", \"ten\"|in\\\\s\+'t"
    r"|IJ\|Th|\[st\]\[-|'s\[-|mr\|dr|\"mr\", \"dr\"|aan\|den\|de"
)


def test_the_vocabulary_of_names_is_in_one_module() -> None:
    copies = [
        f"{path.relative_to(SRC)}:{n}"
        for path in SRC.rglob("*.py")
        if path.name != "dutch_names.py"
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if _COPIES.search(line)
    ]
    assert copies == []
