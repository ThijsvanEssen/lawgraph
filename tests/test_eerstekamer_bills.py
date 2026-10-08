"""The bills of the Eerste Kamer, read from pages of eerstekamer.nl as they were served on
2026-10-03 (``<title>`` and ``<main>`` only)."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core import eerstekamer_bills as eb

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_a_committee_lists_its_bills_under_the_kamers_headings() -> None:
    bills, older = eb.listed_bills(_read("ek_committee_bills_iw_vro.html"))
    assert len(bills) == 54
    assert bills[0] == eb.ListedBill(
        "/wetsvoorstel/36879_implementatie_herziening",
        "36879",
        "In schriftelijke voorbereiding",
    )
    budget = next(b for b in bills if b.path.startswith("/wetsvoorstel/36945_xxii"))
    assert (budget.label, budget.status) == (
        "36945-XXII",
        "Plenaire behandeling Eerste Kamer afgerond",
    )
    # the page of the older bills, its entity unescaped
    assert older is not None and older.endswith("?key=vmgxjiftqbyo&start_pag=50")


def test_a_committee_page_links_its_list() -> None:
    page = '<a href="/wetsvoorstellen_bij_commissie?key=vmgxjiftqbyo&#38;k=tk">x</a>'
    assert eb.bill_lists(page) == ["/wetsvoorstellen_bij_commissie?key=vmgxjiftqbyo"]


def test_a_bill_gives_its_label_submission_and_progress() -> None:
    bill = eb.bill(_read("ek_bill_36791.html"))
    assert (bill.label, bill.submitted_on) == ("36791", "2025-08-15")
    assert [(s.phase, s.house, s.state) for s in bill.progress] == [
        (None, "Tweede Kamer", "vol"),
        ("Schriftelijke voorbereiding", "Eerste Kamer", "vol"),
        ("Plenair", None, "vol"),
        ("Afkondiging", "Staatsblad(en)", "geblokt"),
    ]
    written = bill.progress[1].papers
    assert [(p.kind, p.date, p.number) for p in written[:2]] == [
        ("gewijzigd voorstel van wet", "2026-04-21", "EK, A"),
        ("verslag", "2026-06-16", "EK, B"),
    ]
    # the "i" of a phase explains it and is no paper
    assert all(p.kind != "Van plan tot ..." for s in bill.progress for p in s.papers)


def test_a_pending_bill_and_a_budget_chapter() -> None:
    pending = eb.bill(_read("ek_bill_36879.html"))
    assert [s.state for s in pending.progress] == ["vol", "geblokt", "leeg", "leeg"]
    assert pending.progress[1].papers == []
    budget = eb.bill(_read("ek_bill_36945_xxii.html"))
    assert (budget.label, budget.submitted_on) == ("36945-XXII", "2026-05-20")
    assert budget.progress[2].papers[0].kind == "stemming (hamerstuk)"


def test_a_page_without_a_bill_has_nothing() -> None:
    assert eb.bill("<html></html>") == eb.Bill(label=None, submitted_on=None)


def test_a_rijkswet_is_numbered_with_its_r_number() -> None:
    # the title of a Rijkswet names its R-number in parentheses inside its number's
    page = (
        "<html><title>Rijkswet Caribisch orgaan (36.455 (R2188)) - Eerste Kamer</title>"
    )
    assert eb.bill(page).label == "36455-(R2188)"
