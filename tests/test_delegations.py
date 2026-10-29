"""Delegation formulas in the text of an article, and which regulations fill them."""

from __future__ import annotations

import json

from lawgraph.core.delegations import (
    DelegationClause,
    DelegationKind,
    basis_kind,
    basis_qualifier,
    basis_range_end,
    basis_text,
    delegation_clauses,
    fills,
    kind_rank,
)
from tests.asserts import show_items
from tests.paths import fixture_text

_TEXT = (
    "1. Bij of krachtens algemene maatregel van bestuur wordt het CSIRT aangewezen.\n"
    "2. Bij ministeriële regeling kunnen regels worden gesteld over:\n"
    "a. de melding.\n"
    "3. Het handelen in strijd met de bij algemene maatregel van bestuur gestelde regels "
    "is verboden."
)


def _parts(text: str) -> list[dict[str, object]]:
    first = text.index("1.") + 3
    second = text.index("2.")
    onder = text.index("a. de")
    third = text.index("3.")
    return [
        {
            "id": "lid-1",
            "kind": "lid",
            "number": "1.",
            "start": first,
            "end": second - 1,
        },
        {
            "id": "lid-2",
            "kind": "lid",
            "number": "2.",
            "start": second + 3,
            "end": third - 1,
        },
        {
            "id": "lid-2-onder-a",
            "kind": "onderdeel",
            "number": "a.",
            "start": onder + 3,
            "end": third - 1,
        },
        {
            "id": "lid-3",
            "kind": "lid",
            "number": "3.",
            "start": third + 3,
            "end": len(text),
        },
    ]


def test_the_formulas_of_an_article_with_their_lid() -> None:
    clauses = delegation_clauses(_TEXT, _parts(_TEXT))

    assert [(c.text, c.kind, c.krachtens, c.part, c.lid) for c in clauses] == [
        (
            "Bij of krachtens algemene maatregel van bestuur",
            "amvb",
            True,
            "lid-1",
            "1",
        ),
        ("Bij ministeriële regeling", "ministeriele_regeling", False, "lid-2", "2"),
    ]
    failing = [c for c in clauses if _TEXT[c.start : c.end] != c.text]
    assert not failing, show_items(failing)


def test_rules_already_made_delegate_nothing() -> None:
    assert (
        delegation_clauses(
            "de bij of krachtens algemene maatregel van bestuur vastgestelde eisen"
        )
        == []
    )
    assert (
        delegation_clauses("de bij regeling van Onze Minister gegeven voorschriften")
        == []
    )
    assert [
        c.kind
        for c in delegation_clauses("bij regeling van Onze Minister te stellen regels")
    ] == ["ministeriele_regeling"]


def test_variants_of_the_formula() -> None:
    text = (
        "Bij algemene maatregel van rijksbestuur, bij een algemene maatregel van bestuur "
        "en bij ministeriele regeling; niet bij koninklijk besluit."
    )
    assert [c.kind for c in delegation_clauses(text)] == [
        "amvb",
        "amvb",
        "ministeriele_regeling",
    ]
    # without parts: no part, no lid
    assert delegation_clauses(text)[0].part is None
    assert delegation_clauses(None) == []


def _clause(
    kind: DelegationKind, *, krachtens: bool = False, lid: str | None = "1"
) -> DelegationClause:
    return DelegationClause(0, 1, "x", kind, krachtens, "lid-1", lid)


def test_a_regulation_fills_a_clause_of_its_type_and_lid() -> None:
    amvb = _clause("amvb")
    assert fills(amvb, "AMvB", ["1", "7"])
    assert fills(amvb, "AMvB", [])  # the whole article
    assert not fills(amvb, "AMvB", ["2"])
    assert not fills(amvb, "ministeriele-regeling", [])
    assert fills(_clause("amvb", krachtens=True), "ministeriele-regeling", ["1"])
    assert not fills(_clause("ministeriele_regeling"), "AMvB", [])
    assert fills(
        _clause("ministeriele_regeling", lid=None), "ministeriele-regeling", ["3"]
    )
    assert not fills(amvb, "KB", [])
    # the stored type in either case: the source writes ``amvb`` and ``AMvB``
    assert fills(amvb, "amvb", [])
    assert fills(_clause("amvb", lid=None), "rijksamvb", [])
    assert fills(_clause("ministeriele_regeling"), "ministeriele-regeling-bes", [])
    assert not fills(amvb, "kb", [])


def test_amvbs_come_first() -> None:
    assert sorted(
        ["kb", "ministeriele-regeling", "amvb", None, "AMvB-BES"], key=kind_rank
    ) == ["amvb", "AMvB-BES", "ministeriele-regeling", "kb", None]


def test_an_article_delegates_in_the_leden_a_preamble_names() -> None:
    parts = _parts(_TEXT)
    # a formula in lid 1 and in lid 2; lid 3 names rules already made
    assert basis_kind(_TEXT, parts, ["1"]) == "delegates"
    assert basis_kind(_TEXT, parts, ["2"]) == "delegates"
    assert basis_kind(_TEXT, parts, ["3"]) == "mentioned"
    assert basis_kind(_TEXT, parts, []) == "delegates"  # the whole article
    # a lid the article does not have: the whole article
    assert basis_kind(_TEXT, parts, ["9"]) == "delegates"
    assert basis_kind(None, None, []) is None


def test_other_wordings_of_a_power_delegate_too() -> None:
    for text in (
        "Met het toezicht zijn belast de bij besluit van de bevoegde autoriteit "
        "aangewezen ambtenaren.",
        "Onze Minister kan nadere regels stellen over de melding.",
        "Een bestuursorgaan kan beleidsregels vaststellen.",
        "Deze wet treedt in werking op een bij koninklijk besluit te bepalen tijdstip.",
        "Onze Minister kan bij regeling een sector aanwijzen.",
    ):
        assert basis_kind(text, None, []) == "delegates", text


def test_an_article_only_named_in_a_preamble_is_mentioned() -> None:
    # Awb 3:4: no formula, no power to make rules
    awb_3_4 = (
        "1. Het bestuursorgaan weegt de rechtstreeks bij het besluit betrokken belangen "
        "af.\n2. De voor een of meer belanghebbenden nadelige gevolgen van een besluit "
        "mogen niet onevenredig zijn."
    )
    assert basis_kind(awb_3_4, None, []) == "mentioned"
    for text in (
        "met inachtneming van de regels gesteld bij de wet",
        "de bij besluit van 12 juli 2020 aangewezen gebieden",
        "gewijzigd bij koninklijk besluit van 3 maart 2001",
        "zoals vastgesteld bij regeling van 1 juli 2019",
        "met inachtneming van de bij regeling van Onze Minister gestelde eisen",
        "Bij de voorbereiding van een besluit vergaart het bestuursorgaan kennis.",
    ):
        assert basis_kind(text, None, []) == "mentioned", text


def test_the_reference_of_a_preamble_without_list_word_and_law() -> None:
    assert basis_text("artikelen 3") == "3"
    assert basis_text("artikel 54a van de Drinkwaterwet") == "54a"
    assert basis_text("16, eerste en zevende lid") == "16, eerste en zevende lid"
    assert (
        basis_text(
            "1:25, derde lid, onderdeel b, van de Wet op het financieel toezicht"
        )
        == "1:25, derde lid, onderdeel b"
    )
    assert basis_text("107 van de Cyberbeveiligingswet") == "107"
    assert basis_text("Artikelen 26 tot en met 30") == "26 tot en met 30"


def test_a_range_of_articles_and_not_of_leden() -> None:
    assert basis_range_end("artikelen 26 tot en met 30", "26") == "30"
    assert basis_range_end("artikelen 3:41 tot en met 3:45 van de wet", "3:41") == (
        "3:45"
    )
    assert basis_range_end("2.1 tot en met artikel 2.5", "2.1") == "2.5"
    # leden, one article, or a range that does not start at the linked article
    assert basis_range_end("artikel 3:11, tweede tot en met derde lid", "3:11") is None
    assert basis_range_end("artikel 16, eerste lid", "16") is None
    assert basis_range_end("artikelen 6 tot en met 18", "7") is None


def test_the_number_of_the_article_is_no_lid() -> None:
    # "673e" reads as an ordinal ("673ste"): the article number is left out first
    text = (
        "artikel 673e, eerste lid, aanhef en onderdeel b, en vierde lid, van Boek 7 van "
        "het Burgerlijk Wetboek"
    )
    qualifier = basis_qualifier(text)
    assert (qualifier.leden, qualifier.onderdelen, qualifier.aanhef) == (
        ("1", "4"),
        ("b",),
        True,
    )
    assert basis_qualifier("16, eerste en zevende lid").leden == ("1", "7")
    assert basis_qualifier("26 tot en met 30").leden == ()
    assert basis_qualifier("3e, tweede lid").leden == ("2",)
    assert basis_text(text) == "673e, eerste lid, aanhef en onderdeel b, en vierde lid"


def test_the_formulas_of_the_law_delegate() -> None:
    for text in (
        "De wet regelt wie Nederlander is.",
        "De wet stelt regels ter bescherming van de persoonlijke levenssfeer.",
        "De wet kan regels stellen ter bescherming van de gezondheid.",
        "Regels omtrent de bijzondere zorg worden bij de wet gegeven.",
        "behoudens bij of krachtens de wet te stellen beperkingen",
        "Bij of krachtens de wet worden regels gesteld over de kosten.",
        "Bij de wet kunnen provincies en gemeenten worden opgeheven.",
        "kunnen bij een wet een of meer personen van de erfopvolging worden uitgesloten",
        "Krachtens de wet kunnen nadere regels worden gesteld.",
        "Belastingen van het Rijk worden geheven uit kracht van een wet.",
        "binnen door de wet te stellen grenzen",
        "Voor het oorlogsstrafrecht kan de wet afwijkende regels stellen.",
        "Dit additionele artikel vervalt op een bij wet te bepalen tijdstip.",
    ):
        assert basis_kind(text, None, []) == "delegates", text


def test_a_law_named_is_no_formula_of_the_law() -> None:
    for text in (
        "gewijzigd bij wet van 3 maart 2001",
        "met inachtneming van de bij de wet gestelde voorwaarden",
        "onverminderd het bij of krachtens de wet bepaalde",
        "In afwijking van artikel 5 van de wet kan het college besluiten.",
        "Niemand kan worden afgehouden van de rechter die de wet hem toekent.",
        "behoudens ieders verantwoordelijkheid volgens de wet",
    ):
        assert basis_kind(text, None, []) == "mentioned", text


def test_the_articles_of_the_grondwet_that_leave_a_matter_to_the_law() -> None:
    """The articles of the Grondwet in force (toestand 2023-02-22): every article with a
    formula of the law delegates; only those about the King, the procedure of the Staten-
    Generaal, the government and the revision, without one, are mentioned."""
    articles = json.loads(fixture_text("bwb_grondwet_articles.json"))
    mentioned = [
        a["number"]
        for a in articles
        if basis_kind(a["text"], a["parts"], []) == "mentioned"
    ]
    assert len(articles) == 146
    # art. 4, "behoudens bij de wet gestelde beperkingen", reads as rules already made
    assert mentioned == [
        *("1", "3", "4", "5", "16", "17", "21", "22", "24", "25", "26", "27", "31"),
        *("33", "38", "41", "42", "45", "47", "48", "50", "51", "55", "56", "61"),
        *("62", "66", "67", "68", "69", "71", "72", "76", "81", "82", "83", "84"),
        *("85", "86", "87", "90", "92", "93", "94", "96", "97", "100", "101", "102"),
        *("108", "114", "115", "120", "128", "139", "140"),
    ]
    # a lid: art. 10 lid 2 and 3 ("De wet stelt regels"), art. 46 lid 2 (no formula)
    by_number = {a["number"]: a for a in articles}
    art_10, art_46 = by_number["10"], by_number["46"]
    assert basis_kind(art_10["text"], art_10["parts"], ["2", "3"]) == "delegates"
    assert basis_kind(art_46["text"], art_46["parts"], ["2"]) == "mentioned"
