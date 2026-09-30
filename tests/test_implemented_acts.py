"""The EU acts a considerans says a regulation implements (real clauses from the BWB)."""

from __future__ import annotations

import pytest

from lawgraph.core.eu_citations import EU_ACT_PATTERN, eu_act_celex, implemented_acts


@pytest.mark.parametrize(
    ("cited", "celex"),
    [
        ("Richtlijn 95/46/EG", "31995L0046"),
        ("richtlijn nr. 2004/17/EG", "32004L0017"),
        ("Verordening (EEG) nr. 1408/71", "31971R1408"),
        ("Verordening (EG) nr. 1606/2002", "32002R1606"),
        ("Verordening (EU) nr. 575/2013", "32013R0575"),
        ("Verordening (EU) 2016/679", "32016R0679"),
        ("Gedelegeerde Verordening (EU) 2017/565", "32017R0565"),
        ("Richtlijn (EU) 2015/849", "32015L0849"),
        ("Kaderbesluit 2008/977/JBZ", "32008F0977"),
    ],
)
def test_an_eu_act_in_the_notation_of_its_era(cited: str, celex: str) -> None:
    match = EU_ACT_PATTERN.search(f"gelet op {cited} van de Raad")
    assert match is not None
    assert eu_act_celex(match) == celex


def test_the_act_a_uitvoeringswet_executes_not_the_one_its_title_repeals() -> None:
    clause = (
        "Alzo Wij in overweging genomen hebben, dat het noodzakelijk is te voorzien in "
        "wettelijke regels ter uitvoering van Verordening (EU) 2016/679 van het Europees "
        "Parlement en de Raad van 27 april 2016 betreffende de bescherming van natuurlijke "
        "personen in verband met de verwerking van persoonsgegevens en betreffende het vrije "
        "verkeer van die gegevens en tot intrekking van Richtlijn 95/46/EG (algemene "
        "verordening gegevensbescherming) (PbEU 2016, L 119);"
    )
    assert implemented_acts([clause]) == ["32016R0679"]


def test_every_act_a_clause_implements() -> None:
    clause = (
        "Alzo Wij in overweging genomen hebben, dat het wenselijk is richtlijn nr. "
        "2004/17/EG van het Europees Parlement en de Raad van de Europese Unie van 31 maart "
        "2004 houdende coördinatie van de procedures voor het plaatsen van opdrachten in de "
        "sectoren water- en energievoorziening, vervoer en postdiensten (PbEU L 134) en "
        "richtlijn nr. 2004/18/EG van het Europees Parlement en de Raad van de Europese Unie "
        "van 31 maart 2004 betreffende de coördinatie van de procedures voor het plaatsen van "
        "overheidsopdrachten voor werken, leveringen en diensten (PbEU L 134) opnieuw te "
        "implementeren;"
    )
    assert implemented_acts([clause]) == ["32004L0017", "32004L0018"]


def test_an_act_amended_by_the_implemented_one_is_not_implemented() -> None:
    clause = (
        "dat het noodzakelijk is om regels te stellen ter uitvoering van richtlijn nr. "
        "2013/50/EU van het Europees Parlement en de Raad van 22 oktober 2013 tot wijziging "
        "van Richtlijn 2004/109/EG van het Europees Parlement en de Raad betreffende de "
        "transparantievereisten, Richtlijn 2003/71/EG van het Europees Parlement en de Raad "
        "betreffende het prospectus en Richtlijn 2007/14/EG van de Commissie (PbEU 2013, L "
        "294);"
    )
    assert implemented_acts([clause]) == ["32013L0050"]


def test_without_a_journal_reference_an_amended_act_is_still_part_of_the_title() -> (
    None
):
    clause = (
        "dat het ter implementatie van Richtlijn (EU) 2019/2162 betreffende de uitgifte van "
        "gedekte obligaties en tot wijziging van Richtlijn 2009/65/EG noodzakelijk is regels "
        "te stellen;"
    )
    assert implemented_acts([clause]) == ["32019L2162"]


@pytest.mark.parametrize(
    "clause",
    [
        "dat richtlijn 2009/138/EG in Nederlandse regelgeving dient te worden "
        "geïmplementeerd;",
        "dat het noodzakelijk is Verordening (EU) 2019/881 uit te voeren;",
        "dat het noodzakelijk is de Richtlijn (EU) 2021/2118 om te zetten in bepalingen van "
        "nationaal recht;",
        "Gelet op Richtlijn (EU) 2019/520 van het Europees parlement en de Raad;",
    ],
)
def test_the_formulas_of_implementation(clause: str) -> None:
    assert len(implemented_acts([clause])) == 1


def test_a_clause_that_does_not_implement_names_no_implemented_act() -> None:
    clause = (
        "dat het in verband met Richtlijn 2006/123/EG wenselijk is de regels over "
        "vergunningen te vereenvoudigen;"
    )
    assert implemented_acts([clause]) == []
