"""The legal basis a considerans states outside a "Gelet op" paragraph, and a "Gelet op" that
runs on over more paragraphs (the aanhef of official toestanden, ``fixtures/bwb_considerans``)."""

from __future__ import annotations

import pytest

from lawgraph.core.bwb_xml import PREAMBLE_GELET_OP, ToestandXml, parse_toestand
from tests.paths import fixture_text

GRONDWET = "BWBR0001840"


def _toestand(bwb_id: str) -> ToestandXml:
    return parse_toestand(fixture_text(f"{bwb_id}.xml", sub="bwb_considerans"))


def _gelet_op(toestand: ToestandXml) -> list[str]:
    preamble = toestand.preamble
    assert preamble is not None
    return [
        preamble.text[part.start : part.end]
        for part in preamble.parts
        if part.kind == PREAMBLE_GELET_OP
    ]


@pytest.mark.parametrize(
    ("bwb_id", "articles", "clause"),
    [
        # Woo: "dat het, mede gelet op artikel 110 van de Grondwet, het … Verdrag …"
        ("BWBR0045754", ["110"], "gelet op artikel 110 van de Grondwet"),
        # Waterschapswet: "dat ingevolge artikel 133 van de Grondwet regels moeten …"
        ("BWBR0005108", ["133"], "ingevolge artikel 133 van de Grondwet"),
        # Comptabiliteitswet 2016: "mede ter uitvoering van de artikelen 78 en 105 …"
        (
            "BWBR0039429",
            ["78", "105"],
            "ter uitvoering van de artikelen 78 en 105 van de Grondwet",
        ),
        # WOM: "dat het gelet op de artikelen 6 en 9 en de additionele artikelen III en V"
        (
            "BWBR0004318",
            ["6", "9", "III", "V"],
            "gelet op de artikelen 6 en 9 en de additionele artikelen III en V van de "
            "Grondwet",
        ),
        # Rijkswet goedkeuring verdragen: not "de in artikel 95 van de Grondwet bedoelde
        # wettelijke regeling", which is no basis word
        (
            "BWBR0006799",
            ["91"],
            "ingevolge artikel 91, eerste en tweede lid, van de Grondwet",
        ),
        # Staat en Kerk: not the article of 1972 after the list ("(additioneel artikel X
        # van de Grondwet naar de tekst van 1972)")
        ("BWBR0003640", ["IV"], "ingevolge additioneel artikel IV van de Grondwet"),
        # Uitvoeringswet ex artikel VI: not "de termijn waarna artikel 10 … in werking zal
        # treden"
        (
            "BWBR0004712",
            ["VI"],
            "met toepassing van additioneel artikel VI van de Grondwet",
        ),
    ],
)
def test_a_basis_word_in_the_considerans_of_a_law_opens_its_basis(
    bwb_id: str, articles: list[str], clause: str
) -> None:
    toestand = _toestand(bwb_id)

    assert [(b.bwb_id, b.article) for b in toestand.basis] == [
        (GRONDWET, article) for article in articles
    ]
    # one criterion: the text kept for a law named without a link, and the gelet_op part
    # of the aanhef (its spaces as the source writes them, a no-break space in the Woo)
    assert toestand.basis_preamble == clause
    assert [" ".join(line.split()) for line in _gelet_op(toestand)] == [clause]


def test_a_gelet_op_runs_on_over_the_paragraphs_the_source_marks() -> None:
    # Besluit gewasbeschermingsmiddelen en biociden: twelve paragraphs bevat="grondslag",
    # the first "Gelet op …", the others "artikel 44, eerste lid, van de Grondwet …,"
    toestand = _toestand("BWBR0022530")

    basis = {(b.bwb_id, b.article) for b in toestand.basis}
    assert (GRONDWET, "44") in basis
    assert ("BWBR0021670", "124") in basis  # Wet gewasbeschermingsmiddelen en biociden
    assert ("BWBR0010346", "16") in basis  # Arbeidsomstandighedenwet
    assert len(basis) == 23
    lines = _gelet_op(toestand)
    assert len(lines) == 12
    assert lines[0].startswith("Gelet op de artikelen 3, derde lid")
    assert (
        lines[-1]
        == "artikel 16, eerste en zevende lid, van de Arbeidsomstandighedenwet;"
    )
    assert toestand.basis_preamble == " ".join(lines)


def _considerans(*paragraphs: str) -> ToestandXml:
    body = "".join(f"<considerans.al>{p}</considerans.al>" for p in paragraphs)
    return parse_toestand(
        f'<toestand bwb-id="BWBR0000009"><wetgeving soort="AMvB"><wet-besluit><aanhef>'
        f"<considerans>{body}</considerans></aanhef></wet-besluit></wetgeving></toestand>"
    )


def _link(article: str, law: str = "BWBR0000001") -> str:
    return (
        f'<extref doc="jci1.3:c:{law}&amp;artikel={article}" bwb-id="{law}">'
        f"artikel {article} van de wet</extref>"
    )


def test_an_unmarked_gelet_op_runs_on_after_a_comma_and_not_after_a_semicolon() -> None:
    toestand = _considerans(
        f"Gelet op {_link('1')},",
        f"{_link('2')} en",
        f"{_link('3')};",
        f"De Raad van State gehoord, {_link('4')};",
    )

    assert [b.article for b in toestand.basis] == ["1", "2", "3"]
    assert len(_gelet_op(toestand)) == 3


def test_a_link_without_a_basis_word_in_its_clause_is_no_basis() -> None:
    toestand = _considerans(
        "Alzo Wij in overweging genomen hebben, dat het wenselijk is in verband met de "
        f"wijziging van {_link('5')} regels te stellen;",
        "dat ingevolge het verdrag nodig is dat " + _link("6") + " vervalt;",
    )

    assert toestand.basis == ()
    assert toestand.basis_preamble == ""
    assert _gelet_op(toestand) == []
