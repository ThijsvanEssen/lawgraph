"""The parties of a judgment, read from its kop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.judgment_parties import read_parties
from lawgraph.core.judgments import extract_rdf_metadata, kop_lines, parse_judgment
from lawgraph.core.props import JudgmentProps

FIXTURES = Path(__file__).parent / "fixtures"


def _parties(name: str) -> list[dict[str, Any]]:
    root = parse_judgment((FIXTURES / name).read_text())
    _, subjects = extract_rdf_metadata(root)
    return read_parties(kop_lines(root), subjects)


def _brief(parties: list[dict[str, Any]]) -> list[str]:
    return [f"{p['role']}: {p['name']}" for p in parties]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "rechtspraak_hr_2019_1278.xml",
            [
                "Eiser: [eiseres 1]",
                "Eiser: [eiser 2]",
                "Verweerder: MAATSCHAP GRONINGEN",
                "Verweerder: NEDERLANDSE AARDOLIE MAATSCHAPPIJ B.V.",
                "Verweerder: EBN B.V.",
                "Verweerder: DE STAAT DER NEDERLANDEN",
            ],
        ),
        ("rechtspraak_hr_2026_1504.xml", ["Betrokkene: [betrokkene]"]),
        ("rechtspraak_hr_2026_1434.xml", ["Klager: [klager]"]),
        ("rechtspraak_gharl_2026_6060.xml", ["Verdachte: [verdachte]"]),
        ("rechtspraak_ghdha_2026_2908.xml", ["Verdachte: [verdachte]"]),
        (
            "rechtspraak_rvs_2026_5668.xml",
            ["Appellant: [appellant]", "Verweerder: de burgemeester van Rijswijk"],
        ),
        (
            "rechtspraak_rvs_2026_5642.xml",
            [
                "Appellant: de minister van Sociale Zaken en Werkgelegenheid",
                "Appellant: [appellant]",
            ],
        ),
        (
            "rechtspraak_rvs_2026_5659.xml",
            ["Appellant: de minister van Financiën", "Wederpartij: [wederpartij]"],
        ),
        (
            "rechtspraak_crvb_2025_1295.xml",
            [
                "Appellant: [Appellante]",
                "Verweerder: de Raad van bestuur van het Uitvoeringsinstituut "
                "werknemersverzekeringen",
            ],
        ),
        (
            "rechtspraak_rbams_2025_3600.xml",
            [
                "Eiser: Moonflower B.V.",
                "Verweerder: de minister van Infrastructuur en Waterstaat",
            ],
        ),
        (
            "rechtspraak_rbams_2025_8258.xml",
            [
                "Eiser: C MANAGEMENT B.V.",
                "Eiser: C TELEPORT B.V.",
                "Gedaagde: LETA CAPITAL FUND III LP",
            ],
        ),
        (
            "rechtspraak_ghams_2026_2707.xml",
            [
                "Verzoeker: [Aandeelhouder 1]",
                "Verzoeker: [Aandeelhouder 2]",
                "Verweerder: [Aandeelhouder 3]",
                "Belanghebbende: [de Vennootschap]",
            ],
        ),
        (
            "rechtspraak_gharl_2026_6033.xml",
            [
                "Appellant: [appellant1]",
                "Appellant: [appellant2]",
                "Appellant: [appellant3]",
                "Appellant: [appellant4]",
                "Appellant: [appellant5]",
                "Geïntimeerde: De Fontein B.V.",
                "Geïntimeerde: HUB de Fontein Exploitatie B.V.",
            ],
        ),
        (
            "rechtspraak_rbdha_2026_12077.xml",
            ["Verzoeker: [naam 1]", "Belanghebbende: [naam 2]"],
        ),
    ],
)
def test_the_parties_and_their_roles(name: str, expected: list[str]) -> None:
    assert _brief(_parties(name)) == expected


def test_joined_cases_are_read_each_and_a_party_named_twice_is_one() -> None:
    """RBAMS 2024:81: KLM and VNV stand against the claimants of both cases."""
    brief = _brief(_parties("rechtspraak_rbams_2024_81.xml"))

    assert brief[:5] == [
        "Eiser: [eiser in conventie 1]",
        "Eiser: [eiser in conventie 2]",
        "Eiser: [eiser in conventie 3]",
        "Gedaagde: Koninklijke Luchtvaart Maatschappij N.V.",
        "Gedaagde: Vereniging Nederlandse Verkeersvliegers",
    ]
    assert "Eiser: [eiser 248]" in brief
    assert len(brief) == len(set(brief))
    assert brief.count("Gedaagde: Koninklijke Luchtvaart Maatschappij N.V.") == 1


def test_sides_aliases_and_representatives() -> None:
    parties = {p["name"]: p for p in _parties("rechtspraak_hr_2019_1278.xml")}

    assert parties["[eiseres 1]"] == {
        "name": "[eiseres 1]",
        "role": "Eiser",
        "role_stated": True,  # "EISERS in eerste aanleg,"
        "side": "first",
        "alias": "[eisers]",  # "hierna gezamenlijk: [eisers] ,"
        "representatives": [{"name": "mr. H.J.W. Alt", "role": "advocaat"}],
    }
    # "hierna respectievelijk: de Maatschap en NAM"
    assert parties["MAATSCHAP GRONINGEN"]["alias"] == "de Maatschap"
    assert parties["NEDERLANDSE AARDOLIE MAATSCHAPPIJ B.V."]["alias"] == "NAM"
    assert parties["EBN B.V."]["side"] == "second"
    # "advocaten in de prejudiciële procedure: mr. K. Teuben en M.H.K. Jansen."
    assert [
        r["name"] for r in parties["DE STAAT DER NEDERLANDEN"]["representatives"]
    ] == [
        "mr. K. Teuben",
        "M.H.K. Jansen",
    ]


def test_a_role_derived_from_the_area_of_law_and_the_side_is_not_stated() -> None:
    parties = _parties("rechtspraak_rvs_2026_5668.xml")

    assert [(p["role"], p["role_stated"], p["side"]) for p in parties] == [
        ("Appellant", True, "first"),  # "appellant,"
        ("Verweerder", False, "second"),  # the burgemeester, of the case appealed
    ]


def test_an_interested_party_is_on_no_side() -> None:
    parties = _parties("rechtspraak_ghams_2026_2707.xml")

    assert [p["side"] for p in parties] == ["first", "first", "second", "other"]


def test_the_representative_of_a_party_in_parentheses() -> None:
    (eiser, verweerder) = _parties("rechtspraak_rbams_2025_3600.xml")

    assert eiser["representatives"] == [
        {"name": "mr. P.J. de Booij", "role": "gemachtigde"}
    ]
    assert [r["name"] for r in verweerder["representatives"]] == [
        "mr. S. Deaney",
        "mr. T.W. Franssen",
    ]


def _read(*lines: str, subjects: list[str] | None = None) -> list[str]:
    return _brief(read_parties(list(lines), subjects))


def test_a_role_line_holds_for_every_party_above_it() -> None:
    assert _read(
        "in de zaak van",
        "1. [A],",
        "2. [B],",
        "e i s e r s ,",
        "t e g e n",
        "de stichting",
        "STICHTING ICAM,",
        "gevestigd te Utrecht,",
        "gedaagde partij,",
    ) == ["Eiser: [A]", "Eiser: [B]", "Gedaagde: STICHTING ICAM"]


def test_what_names_no_party_is_left_out() -> None:
    assert _read(
        "in de strafzaak tegen",
        "[verdachte] ,",
        "geboren op [geboortedatum] 1987 in [geboorteplaats] ,",
        "BRP-adres: [BRP-adres] ,",
        "[V-nummer]",
        "wonende te [adres 1]",
        "advocaat: mr. X",
    ) == ["Verdachte: [verdachte]"]


@pytest.mark.parametrize(
    ("subjects", "lines", "expected"),
    [
        (
            ["Civiel recht"],
            ("tussen", "A B.V.", "en", "C B.V."),
            ["Eiser: A B.V.", "Verweerder: C B.V."],
        ),
        (
            ["Civiel recht"],
            ("beschikking", "inzake", "A B.V.", "tegen", "C B.V."),
            ["Verzoeker: A B.V.", "Verweerder: C B.V."],
        ),
        (
            ["Civiel recht"],
            ("in de zaak van", "A B.V.,", "appellante,", "tegen", "C B.V."),
            ["Appellant: A B.V.", "Geïntimeerde: C B.V."],
        ),
        (
            ["Bestuursrecht; Omgevingsrecht"],
            ("Uitspraak in het geding tussen:", "A B.V.", "en", "de raad van Epe"),
            ["Appellant: A B.V.", "Verweerder: de raad van Epe"],
        ),
        (
            ["Strafrecht"],
            ("in de strafzaak tegen", "Jan Jansen,"),
            ["Verdachte: Jan Jansen"],
        ),
        (
            None,
            ("tussen", "A B.V.", "en", "C B.V."),
            ["Partij: A B.V.", "Partij: C B.V."],
        ),
    ],
)
def test_a_role_the_judgment_does_not_state(
    subjects: list[str] | None, lines: tuple[str, ...], expected: list[str]
) -> None:
    assert _read(*lines, subjects=subjects) == expected


def test_a_kop_without_parties_has_none() -> None:
    assert read_parties(["HOGE RAAD DER NEDERLANDEN", "Datum 1 mei 2020"], None) == []


def test_the_parties_are_valid_judgment_props() -> None:
    JudgmentProps.model_validate({"parties": _parties("rechtspraak_hr_2019_1278.xml")})
