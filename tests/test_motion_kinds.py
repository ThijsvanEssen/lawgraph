"""The kind of a motion that judges the government, from its subject as the Kamer writes it
(``Zaak.Onderwerp`` of the OData, verbatim)."""

from __future__ import annotations

import pytest

from lawgraph.core.motion_kinds import CENSURE, NO_CONFIDENCE, MotionKind, motion_kind


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        # Kamerstuk 37020-XVI, nr. 60 (2026Z22489, SGP, 15 October 2026)
        (
            "Motie van het lid Diederik van Dijk over afkeuring uitspreken over het beleid "
            "van de regering inzake de pilot die abortussen vanaf 22 weken zwangerschap bij "
            "gezonde kindjes toegankelijker maakt ",
            CENSURE,
        ),
        (
            "Motie van de leden Azarkan over het uitspreken van afkeuring over de voortgang "
            "van het herstelproces",
            CENSURE,
        ),
        (
            "Motie Gesthuizen over afkeuring van de handelswijze van de staatssecretaris van "
            "Veiligheid en Justitie",
            CENSURE,
        ),
        (
            "Motie van het lid Van Brenk over afkeuring inzake de chaos bij het CBR ",
            CENSURE,
        ),
        (
            "Motie van het lid Wilders over het opzeggen van het vertrouwen in het kabinet",
            NO_CONFIDENCE,
        ),
        (
            "Motie-Madlener over het opzeggen van het vertrouwen in de minister",
            NO_CONFIDENCE,
        ),
        (
            "Motie van het lid Beertema over opzeggen van het vertrouwen in het bestuur ",
            NO_CONFIDENCE,
        ),
        (
            "Motie van het lid Van Haga over het vertrouwen opzeggen in de minister voor "
            "Rechtsbescherming",
            NO_CONFIDENCE,
        ),
        (
            "Motie van het lid Van Houwelingen over het vertrouwen in de minister van VWS "
            "opzeggen",
            NO_CONFIDENCE,
        ),
        (
            "Motie van het lid Ergin over uitspreken dat het vertrouwen in staatssecretaris "
            "Nobel wordt opgezegd",
            NO_CONFIDENCE,
        ),
        (
            "Gewijzigde motie van de leden Wilders en Baudet over het opzeggen van het "
            "vertrouwen in de minister-president t.v.v. 35788-10",
            NO_CONFIDENCE,
        ),
        (
            "MOTIE VAN HET LID WILDERS  OVER HET OPZEGGEN VAN HET VERTROUWEN",
            NO_CONFIDENCE,
        ),
    ],
)
def test_the_fixed_wording_gives_the_kind(subject: str, kind: MotionKind) -> None:
    assert motion_kind(subject) == kind


@pytest.mark.parametrize(
    "subject",
    [
        # the word, but not what the motion does
        "Motie van de leden Aptroot en Roefs over toepassing van de hardheidsclausule vóór "
        "afkeuring van een schip",
        "Motie van de leden Piri en Paternotte over afkeuring over de arrestatie van "
        "Imamoglu actief uitdragen ",
        "Motie van het lid Koorevaar c.s. over beschikkingen die hebben geleid tot "
        "substantiële verlagingen of afkeuringen van vergoedingen binnen de ecoregeling met "
        "prioriteit opnieuw beoordelen",
        "Motie van de leden Bushoff en Vliegenthart over het vertrouwen in het "
        "bevolkingsonderzoek baarmoederhalskanker herstellen ",
        "Motie Thieme over het uitspreken van het volledige vertrouwen in de staatssecretaris "
        "van Veiligheid en Justitie",
        "Motie van het lid Dekker over het VN-vluchtelingenverdrag opzeggen en stoppen met "
        "het opnemen van asielzoekers",
        "Motie van het lid Van Meijeren over uitdragen dat wantrouwen jegens de overheid of "
        "democratische instituties niet ondermijnend of extremistisch is",
        # no "over": no form to read
        "Motie afkeuring uitspreken",
        "",
        None,
    ],
)
def test_a_near_miss_is_no_kind(subject: str | None) -> None:
    assert motion_kind(subject) is None
