"""The dictum of a motion (``core/motion_dictum.py``)."""

from __future__ import annotations

from lawgraph.core.motion_dictum import read_dictum

MOTION = """MOTIE VAN HET LID TEUNISSEN
De Kamer,
gehoord de beraadslaging,
constaterende dat het kabinet de CO2-heffing afschaft onder het mom van «weglek»;
overwegende dat de klimaatschade op de toekomstige generaties wordt afgewenteld;
verzoekt de regering om te onderzoeken en inzichtelijk te maken wat de kosten van deze
klimaatschade zijn,
en gaat over tot de orde van de dag.
Teunissen"""


def test_the_dictum_is_what_the_kamer_asks_up_to_the_closing_formula() -> None:
    assert read_dictum(MOTION) == (
        "verzoekt de regering om te onderzoeken en inzichtelijk te maken wat de kosten"
        " van deze klimaatschade zijn"
    )


def test_every_line_of_what_the_kamer_does_is_in_it() -> None:
    text = """De Kamer,
gehoord de beraadslaging,
overwegende dat …;
spreekt uit dat de asielwetgeving niet verder wordt aangescherpt;
roept de regering op niet akkoord te gaan met de Europese noodwetgeving,
en gaat over tot de orde van de dag."""
    assert read_dictum(text) == (
        "spreekt uit dat de asielwetgeving niet verder wordt aangescherpt;"
        " roept de regering op niet akkoord te gaan met de Europese noodwetgeving"
    )


def test_without_the_form_of_a_motion_there_is_none() -> None:
    # a letter: no closing formula
    assert read_dictum("Geachte voorzitter,\nverzoekt u …\nHoogachtend,") is None
    # the closing formula without a line of what the Kamer does
    assert (
        read_dictum("De Kamer,\noverwegende …,\nen gaat over tot de orde van de dag.")
        is None
    )
    assert read_dictum(None) is None and read_dictum("") is None
