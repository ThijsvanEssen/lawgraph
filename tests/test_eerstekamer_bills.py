"""The bills of the Eerste Kamer, read from pages of eerstekamer.nl as they were served on
2026-10-03 (``<title>`` and ``<main>`` only)."""

from __future__ import annotations

import pytest

from lawgraph.core import ek_bills as eb
from tests.asserts import show_items
from tests.paths import fixture_text


@pytest.mark.parametrize(
    ("number", "label"),
    [
        ("36.791", "36791"),
        ("36.600 VII", "36600-VII"),
        ("36.600  VII", "36600-VII"),
        ("36.600 B", "36600-B"),
        ("36.455 (R2188)", "36455-(R2188)"),
        ("36.647\n\t (R2204)", "36647-(R2204)"),
        ("6.791", "6791"),
        ("Wet 36791", None),
        ("CXLIV", None),
        ("nr. 12", None),
        ("Brief regering", None),
        ("E260009", None),
    ],
)
def test_the_number_of_the_eerste_kamer_is_the_label_of_the_tweede_kamer(
    number: str, label: str | None
) -> None:
    assert eb.ek_dossier_label(number) == label


def test_a_committee_lists_its_bills_under_the_kamers_headings() -> None:
    bills, older = eb.listed_bills(fixture_text("ek_committee_bills_iw_vro.html"))
    assert len(bills) == 54
    assert bills[0] == eb.ListedBill(
        "/wetsvoorstel/36879_implementatie_herziening",
        "36879",
        "In schriftelijke voorbereiding",
        "Implementatie herziening richtlijn luchtkwaliteit",
    )
    # an abbreviation in its name, without the markup
    assert bills[1].name == (
        "Implementatie herziening Richtlijn industriële emissies en de uitvoering van de "
        "PIE-verordening"
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
    bill = eb.bill(fixture_text("ek_bill_36791.html"))
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
    failing = [
        (s, p) for s in bill.progress for p in s.papers if p.kind == "Van plan tot ..."
    ]
    assert not failing, show_items(failing)


def test_a_pending_bill_and_a_budget_chapter() -> None:
    pending = eb.bill(fixture_text("ek_bill_36879.html"))
    assert [s.state for s in pending.progress] == ["vol", "geblokt", "leeg", "leeg"]
    assert pending.progress[1].papers == []
    budget = eb.bill(fixture_text("ek_bill_36945_xxii.html"))
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


def test_the_list_of_every_bill_is_asked_with_the_id_of_its_form() -> None:
    form = '<input type="hidden" name="dlgid" value="n29okkelj2o1f" />'
    assert eb.index_path(form) == (
        "/wetsvoorstellen_2?dlgid=n29okkelj2o1f&modus=selecteer"
    )
    assert eb.index_path("<p>geen formulier</p>") is None


def test_the_list_of_every_bill_names_them_with_the_newest_numbers_first() -> None:
    bills, older = eb.listed_bills(fixture_text("ek_bill_index.html"))
    # 8310 (R 498) and 8603 (R 530) are no numbers it reads: passed over, and no other bill
    # takes their address
    assert len(bills) == 18
    assert "/wetsvoorstel/8310_toestemming_tot_het_aangaan" not in [
        b.path for b in bills
    ]
    # an old bill without a dossier number of today, then the highest numbers
    assert bills[0].label is None
    assert bills[0].path == "/wetsvoorstel/9_toestemmingswet_huwelijk_prins"
    newest = next(b for b in bills if b.label == "37048")
    assert newest.name and newest.name.startswith("Wijziging van de Wet milieubeheer")
    assert older is not None and older.endswith("start_00k=20#p1")
