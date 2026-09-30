"""The composition of the Eerste Kamer, read from pages of eerstekamer.nl as they were served
on 2026-09-30 (``<h1>`` and ``<main>`` only)."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core import eerstekamer_composition as ec

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_the_factions_are_listed_with_their_seats() -> None:
    factions = ec.factions(_read("ek_factions.html"))
    assert len(factions) == 20
    assert sum(f.seats or 0 for f in factions) == 75
    assert factions[0] == ec.Listed(
        path="/fractie/progressief_nederland_pro",
        name="PRO",
        abbreviation="PRO",
        seats=14,
    )
    one = {f.name: f.seats for f in factions}
    assert one["Fractie-Van Gasteren"] == 1


def test_the_committees_are_listed_with_their_abbreviation() -> None:
    committees = {c.path: c for c in ec.committees(_read("ek_committees.html"))}
    assert len(committees) == 16
    assert committees["/commissies/fin"].name == "Financiën"
    assert committees["/commissies/fin"].abbreviation == "FIN"
    # a committee without an abbreviation keeps its name as the list writes it
    assert committees["/commissies/verzoekschriften"].abbreviation is None


def test_a_faction_page_gives_its_board_and_members() -> None:
    page = ec.page(_read("ek_faction_d66.html"))
    assert page.title == "D66-fractie"
    assert [(b.function, b.name, b.since) for b in page.board] == [
        ("fractievoorzitter", "Paul van Meenen", "2023-06-13"),
        ("vice-fractievoorzitter", "Carla Moonen", "2026-02-24"),
        ("penningmeester", "Antoon Kanis", "2025-11-11"),
    ]
    members = {m.path: m for m in page.members}
    assert len(members) == 7
    dittrich = members["/persoon/mr_b_o_dittrich_d66"]
    assert (dittrich.name, dittrich.seniority_days, dittrich.birth_date) == (
        "mr. B.O. Dittrich",
        2668,
        "1955-07-21",
    )
    assert dittrich.residence == "Amsterdam, Noord-Holland"
    # a member without a place of residence on the page has none
    assert members["/persoon/mr_r_s_croll_d66"].residence is None


def test_a_committee_page_gives_its_members_with_faction_and_role() -> None:
    page = ec.page(_read("ek_committee_fin.html"))
    assert page.title == "Commissie voor Financiën (FIN)"
    assert len(page.members) == 29
    roles = [(m.name, m.faction, m.role) for m in page.members if m.role]
    assert roles == [
        ("W.T. van Ballekom", "VVD", "voorzitter"),
        ("drs. ing. B. Kroon", "BBB", "ondervoorzitter"),
    ]
    assert page.members[0].faction == "SP" and page.members[0].role is None
    assert page.board == []
