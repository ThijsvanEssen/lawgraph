"""The names lawyers call landmark judgments by ("Haviltex", "Urgenda", "Lindenbaum/Cohen").

CURATED DATA: the table below is kept by hand. The open data of the Rechtspraak carries no
name for a judgment: its metadata has no ``dcterms:alternative``, its vindplaatsen
(``dcterms:hasVersion``) are citations ("NJ 1981/635 met annotatie van C.J.H. Brunner"), and
the inhoudsindicatie of a later judgment names the precedent it applies as readily as its
own ("Uitleg. Haviltex."). A name is added here only for an ECLI checked against the
judgment itself (its court, date and inhoudsindicatie); an English translation the
Rechtspraak publishes under an ECLI of its own carries the name of the judgment it
translates.

``normalize rechtspraak`` writes ``props.names`` from this table on every judgment it
reads; ``semantic graph-list-stats`` writes it on a stub (a judgment cited but not loaded).
"""

from __future__ import annotations

CURATED_NAMES: dict[str, tuple[str, ...]] = {
    # onrechtmatige daad (HR 31 januari 1919)
    "ECLI:NL:HR:1919:AG1776": ("Lindenbaum/Cohen",),
    # afwezigheid van alle schuld (HR 14 februari 1916)
    "ECLI:NL:HR:1916:BG9431": ("Melk en water",),
    # wederrechtelijke toe-eigening van elektriciteit (HR 23 mei 1921)
    "ECLI:NL:HR:1921:186": ("Elektriciteitsarrest",),
    # functioneel daderschap (HR 23 februari 1954)
    "ECLI:NL:HR:1954:3": ("IJzerdraad",),
    # gevaarzetting (HR 5 november 1965)
    "ECLI:NL:HR:1965:AB7079": ("Kelderluik",),
    # uitleg van overeenkomsten (HR 13 maart 1981)
    "ECLI:NL:HR:1981:AG4158": ("Haviltex",),
    # HR 16 juni 1981
    "ECLI:NL:HR:1981:AC7243": ("Papa Blanca",),
    # schade door de geboorte van een kind (HR 18 maart 2005)
    "ECLI:NL:HR:2005:AR5213": ("Baby Kelly",),
    # slapend dienstverband (HR 8 november 2019)
    "ECLI:NL:HR:2019:1734": ("Xella",),
    # the climate case: the Hoge Raad (20 december 2019), the gerechtshof Den Haag
    # (9 oktober 2018) and the rechtbank Den Haag (24 juni 2015), each also in English
    "ECLI:NL:HR:2019:2006": ("Urgenda",),
    "ECLI:NL:HR:2019:2007": ("Urgenda",),
    "ECLI:NL:GHDHA:2018:2591": ("Urgenda",),
    "ECLI:NL:GHDHA:2018:2610": ("Urgenda",),
    "ECLI:NL:RBDHA:2015:7145": ("Urgenda",),
    "ECLI:NL:RBDHA:2015:7196": ("Urgenda",),
    # verkoop van onroerende zaken door de overheid (HR 26 november 2021)
    "ECLI:NL:HR:2021:1778": ("Didam",),
    # de arbeidsovereenkomst van maaltijdbezorgers (HR 24 maart 2023)
    "ECLI:NL:HR:2023:443": ("Deliveroo",),
}


def judgment_names(ecli: str | None) -> list[str]:
    """The names of the judgment *ecli* (``CURATED_NAMES``); empty when it has none."""
    return list(CURATED_NAMES.get((ecli or "").upper(), ()))
