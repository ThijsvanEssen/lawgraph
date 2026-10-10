"""Which articles each onderdeel of a bill changes, read from the text of the bill (pure)."""

from __future__ import annotations

from lawgraph.core.bill_parts import (
    BillPart,
    amendment_changes,
    bill_parts,
    heading_law,
    heading_parts,
)

# The text of Kamerstukken II 2008/09, 31810, nr. 2 (Lanzarote), shortened.
BILL_31810 = """VOORSTEL VAN WET
Wij Beatrix, bij de gratie Gods, Koningin der Nederlanden, enz. enz. enz.
Zo is het, dat Wij, de Raad van State gehoord, hebben goedgevonden en verstaan:
ARTIKEL I
Het Wetboek van Strafrecht wordt als volgt gewijzigd:
A
In artikel 240b, eerste lid, wordt de zinsnede «verspreidt» vervangen door: aanbiedt.
B
Na artikel 248c worden twee artikelen ingevoegd, luidende:
Artikel 248d
Hij die een persoon ertoe beweegt getuige te zijn van seksuele handelingen, wordt gestraft.
Artikel 248e
Hij die een persoon een ontmoeting voorstelt, wordt gestraft.
ARTIKEL II
Het Wetboek van Strafvordering wordt als volgt gewijzigd:
A
In artikel 67, eerste lid, onderdeel b, wordt na «137g, tweede lid,» ingevoegd: 248d, 248e,.
B
In artikel 167a wordt «artikel 245, 247 of 248a» vervangen door: artikel 245, 248d of 248e.
ARTIKEL III
In artikel 51a, tweede lid, van de Uitleveringswet wordt een onderdeel toegevoegd:
– de misdrijven van de artikelen 240b, 242 tot en met 250 van het Wetboek van Strafrecht.
ARTIKEL IV
Deze wet treedt in werking op een bij koninklijk besluit te bepalen tijdstip.
Lasten en bevelen dat deze in het Staatsblad zal worden geplaatst."""

# Kamerstukken II 2015/16, 34372, nr. 2, shortened: an onderdeel that adds a lid, one that
# inserts a division, two letters after U, a code that runs out of single letters.
BILL_34372 = """ARTIKEL II
Het Wetboek van Strafvordering wordt als volgt gewijzigd:
C
Aan artikel 125m wordt een lid toegevoegd, luidende:
5.
Degene tot wie een bevel is gericht neemt geheimhouding in acht.
D
Na artikel 125o wordt een artikel ingevoegd, luidende:
Artikel 125p
1.
In geval van verdenking van een misdrijf kan de officier van justitie een bevel richten.
Ua
In titel VD wordt na de vijfde afdeling een afdeling ingevoegd, luidende:
ZESDE AFDELING UITSTEL MELDING ONBEKENDE KWETSBAARHEDEN
Artikel 126ffa
1.
De officier van justitie kan bevelen dat het bekend maken wordt uitgesteld.
AA
De artikelen 138e en 138f vervallen.
BB
Artikel 552a komt te luiden:
Artikel 552a
De belanghebbende kan zich beklagen."""


def _part(bill: str, article: str, part: str) -> BillPart:
    return bill_parts(bill)[(article, part)]


def test_each_onderdeel_names_the_articles_it_changes() -> None:
    parts = bill_parts(BILL_31810)

    assert sorted(parts) == [
        ("I", "A"),
        ("I", "B"),
        ("II", "A"),
        ("II", "B"),
        ("III", ""),
        ("IV", ""),
    ]
    assert parts[("I", "A")] == BillPart(
        article="I",
        part="A",
        law="Wetboek van Strafrecht",
        numbers=("240b",),
        instruction="In artikel 240b, eerste lid, wordt de zinsnede",
    )
    # inserted articles are those of their headings, not the one they follow
    assert _part(BILL_31810, "I", "B").numbers == ("248d", "248e")
    # what a quotation or the new text names is not changed
    assert _part(BILL_31810, "II", "A").numbers == ("67",)
    assert _part(BILL_31810, "II", "B").numbers == ("167a",)
    assert _part(BILL_31810, "II", "B").law == "Wetboek van Strafvordering"


def test_an_article_without_onderdelen_names_its_law_in_its_instruction() -> None:
    part = _part(BILL_31810, "III", "")

    assert part.law is None
    assert part.numbers == ("51a",)
    assert part.instruction.startswith(
        "In artikel 51a, tweede lid, van de Uitleveringswet"
    )
    # an article that changes nothing names no article
    assert _part(BILL_31810, "IV", "").numbers == ()


def test_lids_divisions_letters_after_u_and_repeals() -> None:
    assert _part(BILL_34372, "II", "C").numbers == ("125m",)
    assert _part(BILL_34372, "II", "D").numbers == ("125p",)
    assert _part(BILL_34372, "II", "Ua").numbers == ("126ffa",)
    assert _part(BILL_34372, "II", "AA").numbers == ("138e", "138f")
    assert _part(BILL_34372, "II", "BB").numbers == ("552a",)


def test_a_code_numbered_by_chapter() -> None:
    """Wft, Wazo, BW: "3:57" is one number, not article 3 and a quotation."""
    bill = """ARTIKEL I
De Wet op het financieel toezicht wordt als volgt gewijzigd:
M
In artikel 3:57, derde lid, wordt «twee» vervangen door: drie.
N
Artikel 4:3 komt te luiden: de melding.
O
Na artikel 4:2 wordt een artikel ingevoegd, luidende:
Artikel 4:2a
De melding geschiedt schriftelijk."""

    parts = bill_parts(bill)

    assert parts[("I", "M")].law == "Wet op het financieel toezicht"
    assert parts[("I", "M")].numbers == ("3:57",)
    assert parts[("I", "N")].numbers == ("4:3",)
    assert parts[("I", "O")].numbers == ("4:2a",)


def test_a_text_that_is_no_bill_has_no_parts() -> None:
    assert bill_parts("") == {}
    assert bill_parts("Memorie van toelichting\nArtikel 5\nToelichting.") == {}


def test_the_onderdelen_a_heading_of_a_memorandum_names() -> None:
    assert heading_parts("Artikel I, onderdeel B") == ("I", ("B",))
    assert heading_parts("Artikel II onderdeel Q") == ("II", ("Q",))
    assert heading_parts("Artikel II, onderdelen H en I") == ("II", ("H", "I"))
    assert heading_parts("Artikel I onderdelen C, D en E") == ("I", ("C", "D", "E"))
    assert heading_parts("Artikel II, onderdeel Ua") == ("II", ("Ua",))
    assert heading_parts("ARTIKEL III") == ("III", ("",))
    assert heading_parts("Artikel III Algemene wet inzake rijksbelastingen") == (
        "III",
        ("",),
    )
    # a range of letters, past Z on to AA
    assert heading_parts(
        "Artikel I, onderdeel CS tot en met CV (artikel 4:38 Wft)"
    ) == (
        "I",
        ("CS", "CT", "CU", "CV"),
    )
    assert heading_parts("Artikel I, onderdelen Y t/m AB") == (
        "I",
        ("Y", "Z", "AA", "AB"),
    )
    # what is no heading of an onderdeel of the bill
    assert heading_parts("Artikel 5") is None
    assert heading_parts("Artikel I, onderdeel B (artikel 1a)") == ("I", ("B",))
    assert heading_parts("Algemeen") is None


def test_the_law_a_heading_of_an_article_of_the_bill_names() -> None:
    assert (
        heading_law("ARTIKEL II – WETBOEK VAN STRAFRECHT") == "WETBOEK VAN STRAFRECHT"
    )
    assert heading_law("Artikel III (Woningwet)") == "Woningwet"
    assert heading_law("Artikel I, onderdeel B (artikel 1a)") == "artikel 1a"
    assert heading_law("ARTIKEL II") is None
    assert heading_law("Artikel 5 Sr") is None  # no article of a bill


# Kamerstukken II 2016/17, 34372, nrs. 14 and 13, shortened.
AMENDMENT_14 = """AMENDEMENT VAN DE LEDEN RECOURT EN TELLEGEN
De ondergetekenden stellen het volgende amendement voor:
In artikel II wordt na onderdeel U een onderdeel ingevoegd, luidende:
Ua
In titel VD wordt na de vijfde afdeling een afdeling ingevoegd, luidende:
ZESDE AFDELING UITSTEL MELDING ONBEKENDE KWETSBAARHEDEN
Artikel 126ffa
1.
De officier van justitie kan bevelen dat het bekend maken wordt uitgesteld."""
AMENDMENT_13 = """GEWIJZIGD AMENDEMENT VAN HET LID VERHOEVEN C.S.
De ondergetekenden stellen het volgende amendement voor:
I
In artikel II, onderdeel G, wordt in artikel 126nba «binnendringt» vervangen door: zonder.
II
In artikel II, onderdeel L, wordt in artikel 126uba «binnendringt» vervangen door: zonder."""


def test_what_an_amendment_changes() -> None:
    inserted = amendment_changes(AMENDMENT_14)
    assert inserted.numbers == ("126ffa",)
    assert inserted.bill_articles == ("II",)

    two = amendment_changes(AMENDMENT_13)
    # the articles it changes, not what it quotes or puts in their place
    assert two.numbers == ("126nba", "126uba")
    assert two.bill_articles == ("II",)


def test_an_amendment_that_names_the_law_it_changes() -> None:
    changes = amendment_changes(
        "De ondergetekende stelt het volgende amendement voor:\n"
        "In artikel 51a, tweede lid, van de Uitleveringswet wordt «a» vervangen door: b."
    )

    assert changes.numbers == ("51a",)
    assert changes.bill_articles == ()
    assert changes.instructions == (
        "In artikel 51a, tweede lid, van de Uitleveringswet wordt",
    )
