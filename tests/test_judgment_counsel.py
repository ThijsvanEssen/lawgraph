"""Who acts for the parties of a judgment, as its account of the procedure names them."""

from __future__ import annotations

from typing import Any

from lawgraph.core.judgment_counsel import read_counsel, same_person
from lawgraph.core.judgment_metadata import extract_rdf_metadata, parse_judgment
from lawgraph.core.judgment_paragraphs import judgment_text, kop_lines
from lawgraph.core.judgment_parties import read_parties
from lawgraph.core.props import JudgmentProps
from tests.paths import fixture_text

CRIMINAL = ["Strafrecht"]
ADMINISTRATIVE = ["Bestuursrecht; Omgevingsrecht"]


def _from_fixture(name: str) -> list[dict[str, Any]]:
    root = parse_judgment(fixture_text(name))
    _, subjects = extract_rdf_metadata(root)
    paragraphs, _ = judgment_text(root)
    return read_counsel(read_parties(kop_lines(root), subjects), paragraphs, subjects)


def _party(name: str, role: str, side: str = "first") -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "roles": [role],
        "role_stated": True,
        "side": side,
        "alias": None,
        "representatives": [],
    }


def _read(
    parties: list[dict[str, Any]], *texts: str, subjects: list[str] | None = None
) -> list[dict[str, Any]]:
    paragraphs = [{"kind": "subheading", "text": "KOP"}] + [
        {"kind": "body", "text": text} for text in texts
    ]
    return read_counsel(parties, paragraphs, subjects or ADMINISTRATIVE)


def _who(parties: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [
        (party["name"], r["name"], r["role"])
        for party in parties
        for r in party["representatives"]
    ]


def test_the_hearing_of_the_afdeling_names_who_acts_for_each_party() -> None:
    """ECLI:NL:RVS:2007:BB0782: "waar [directeur] van [appellanten], bijgestaan door mr.
    drs. R. van Gelder, advocaat te Voorschoten, en verweerder, vertegenwoordigd door mr.
    I.T.F. Vermeulen, ambtenaar in dienst van de provincie, zijn verschenen. Voorts is de
    gemeenteraad, vertegenwoordigd door mr. R. van der Meulen MPM, als partij gehoord.\""""
    parties = _from_fixture("rechtspraak_rvs_2007_bb0782.xml")

    assert [(p["name"], p["role"], p["side"], p["alias"]) for p in parties] == [
        ("[appellanten]", "Appellant", "first", None),
        (
            "het college van gedeputeerde staten van Zuid-Holland",
            "Verweerder",
            "second",
            None,
        ),
        # heard as a party, not in the kop: its fuller name from the procedure
        (
            "de gemeenteraad van Nieuwerkerk aan den IJssel",
            "Partij",
            "other",
            "de gemeenteraad",
        ),
    ]
    assert [p["representatives"] for p in parties] == [
        [
            {
                "name": "mr. drs. R. van Gelder",
                "role": "advocaat",
                "place": "Voorschoten",
                "capacity": None,
            }
        ],
        [
            {
                "name": "mr. I.T.F. Vermeulen",
                "role": "gemachtigde",
                "place": None,
                "capacity": "ambtenaar in dienst van de provincie",
            }
        ],
        [
            {
                "name": "mr. R. van der Meulen MPM",
                "role": "gemachtigde",
                "place": None,
                "capacity": None,
            }
        ],
    ]
    JudgmentProps.model_validate({"parties": parties})


def test_several_persons_with_one_capacity_and_a_party_by_its_head() -> None:
    parties = _read(
        [
            _party("[appellante sub 1]", "Appellant"),
            _party("de minister van Landbouw", "Verweerder", "second"),
        ],
        "De Afdeling heeft de zaak ter zitting behandeld op 20 juni 2025, waar "
        "[appellante sub 1], bijgestaan door mr. R.S. Wijling en mr. L.S.E. Hinrichs, "
        "advocaten in Rotterdam, en de minister, vertegenwoordigd door mr. M.M. de Vries "
        "en mr. J.S. Geurtjens, beiden werkzaam bij het ministerie, zijn verschenen.",
    )

    assert [
        (r["name"], r["role"], r["place"], r["capacity"])
        for p in parties
        for r in p["representatives"]
    ] == [
        ("mr. R.S. Wijling", "advocaat", "Rotterdam", None),
        ("mr. L.S.E. Hinrichs", "advocaat", "Rotterdam", None),
        ("mr. M.M. de Vries", "gemachtigde", None, "werkzaam bij het ministerie"),
        ("mr. J.S. Geurtjens", "gemachtigde", None, "werkzaam bij het ministerie"),
    ]


def test_the_counsel_of_a_suspect_is_his_raadsman() -> None:
    parties = _read(
        [_party("[verdachte]", "Verdachte", "second")],
        "Het hof heeft kennisgenomen van wat verdachte en zijn raadsvrouw, "
        "mr. N.E. Renders, hebben aangevoerd.",
        subjects=CRIMINAL,
    )

    assert _who(parties) == [("[verdachte]", "mr. N.E. Renders", "raadsman")]


def test_the_lawyer_who_proposed_the_grounds_of_cassation() -> None:
    parties = _read(
        [_party("[verdachte]", "Verdachte", "second")],
        "Het cassatieberoep is ingesteld namens de verdachte en mr. N. van Schaik, "
        "advocaat te Utrecht, heeft twee middelen van cassatie voorgesteld.",
        subjects=CRIMINAL,
    )

    assert _who(parties) == [("[verdachte]", "mr. N. van Schaik", "advocaat")]
    # "heeft mr. X" without the grounds after it names no one's lawyer
    assert (
        _who(
            _read(
                [_party("[verdachte]", "Verdachte", "second")],
                "Ter zitting heeft mr. A. Jansen, officier van justitie, gerequireerd.",
                subjects=CRIMINAL,
            )
        )
        == []
    )


def test_no_raadsman_outside_a_criminal_case() -> None:
    parties = _read(
        [_party("[appellant]", "Appellant")],
        "Appellant is verschenen, bijgestaan door zijn raadsman mr. P. de Wit.",
    )

    assert _who(parties) == [("[appellant]", "mr. P. de Wit", "gemachtigde")]


def test_a_party_on_behalf_of_whom() -> None:
    parties = _read(
        [
            _party("[belanghebbende]", "Belanghebbende"),
            _party("de inspecteur", "Verweerder"),
        ],
        "Namens belanghebbende heeft mr. K. de Haan, advocaat te Amsterdam, beroep in "
        "cassatie ingesteld.",
    )

    assert _who(parties) == [("[belanghebbende]", "mr. K. de Haan", "advocaat")]


def test_who_is_named_twice_is_one_person_and_an_expert_none() -> None:
    parties = _read(
        [_party("[appellant]", "Appellant")],
        "Appellant, bijgestaan door mr. B. van Dijk, advocaat, en ir. F. Smit, "
        "deskundige, is verschenen.",
        "Appellant, bijgestaan door mr. Van Dijk, heeft een nader stuk ingediend.",
    )

    assert _who(parties) == [("[appellant]", "mr. B. van Dijk", "advocaat")]


def test_who_represents_a_party_is_no_party_heard() -> None:
    parties = _read(
        [_party("[appellant]", "Appellant")],
        "Voorts is [partij], vertegenwoordigd door [gemachtigde], bijgestaan door "
        "mr. A. Bakker, advocaat te Arnhem, als partij gehoord.",
    )

    assert [p["name"] for p in parties] == ["[appellant]", "[partij]"]
    assert _who(parties) == [("[partij]", "mr. A. Bakker", "advocaat")]


def test_an_ambiguous_party_gets_no_one() -> None:
    parties = _read(
        [_party("[appellant A]", "Appellant"), _party("[appellant B]", "Appellant")],
        "Ter zitting is appellant, bijgestaan door mr. C. Vos, verschenen.",
    )

    assert _who(parties) == []


def test_the_considerations_are_not_read() -> None:
    parties = read_counsel(
        [_party("[appellant]", "Appellant")],
        [
            {"kind": "heading", "text": "Procesverloop"},
            {"kind": "body", "text": "Appellant heeft beroep ingesteld."},
            {"kind": "heading", "text": "Overwegingen"},
            {
                "kind": "body",
                "text": "Appellant, bijgestaan door mr. D. Kok, advocaat te Ede, stelt dat.",
            },
        ],
        ADMINISTRATIVE,
    )

    assert _who(parties) == []


def test_one_person_by_two_names() -> None:
    assert same_person("mr. B. van Dijk", "mr. Van Dijk")
    assert same_person("R. van Gelder", "mr. drs. R. van Gelder")
    assert not same_person("mr. B. van Dijk", "mr. C. van Dijk")
    assert not same_person("mr. B. van Dijk", "mr. B. van Dijken")


def test_each_party_of_the_hearing_keeps_its_own_lawyers() -> None:
    """ECLI:NL:RVS:2026:6099: "waar Trusthave Management, vertegenwoordigd door mr. J.
    Geelhoed, advocaat in Delft, en de raad, vertegenwoordigd door D. den Hamer BSc en
    L.E.G. de Rooij en bijgestaan door mr. A.P.C. Kester, advocaat in Rotterdam, zijn
    verschenen." The kop calls the appellant "(tezamen en in enkelvoud: Trusthave
    Management)"."""
    parties = _from_fixture("rechtspraak_rvs_2026_6099.xml")

    assert [(p["name"], p["alias"]) for p in parties] == [
        ("Trusthave Management B.V.", "Trusthave Management"),
        ("de raad van de gemeente Sluis", None),
    ]
    assert [
        (p["name"], r["name"], r["role"], r["place"])
        for p in parties
        for r in p["representatives"]
    ] == [
        ("Trusthave Management B.V.", "mr. J. Geelhoed", "advocaat", "Delft"),
        ("de raad van de gemeente Sluis", "D. den Hamer BSc", "gemachtigde", None),
        ("de raad van de gemeente Sluis", "L.E.G. de Rooij", "gemachtigde", None),
        ("de raad van de gemeente Sluis", "mr. A.P.C. Kester", "advocaat", "Rotterdam"),
    ]


def test_who_assists_after_who_represents_acts_for_the_same_party() -> None:
    parties = _read(
        [
            _party("[appellant]", "Appellant"),
            _party("het college van burgemeester en wethouders van Ede", "Verweerder"),
        ],
        "waar [appellant], bijgestaan door mr. P. Smit, en het college, vertegenwoordigd "
        "door A. de Boer, en bijgestaan door mr. K. Visser, advocaat te Utrecht, zijn "
        "verschenen.",
    )

    assert _who(parties) == [
        ("[appellant]", "mr. P. Smit", "gemachtigde"),
        (
            "het college van burgemeester en wethouders van Ede",
            "A. de Boer",
            "gemachtigde",
        ),
        (
            "het college van burgemeester en wethouders van Ede",
            "mr. K. Visser",
            "advocaat",
        ),
    ]


def test_no_party_from_a_sentence_before() -> None:
    parties = _read(
        [_party("[appellant]", "Appellant"), _party("de raad van Sluis", "Verweerder")],
        "[appellant] en de raad hebben nadere stukken ingediend. De Afdeling heeft de "
        "zaak behandeld, waar Bouwbedrijf Noord, vertegenwoordigd door mr. J. Jansen, "
        "is verschenen.",
    )

    assert _who(parties) == []


def test_a_company_by_its_first_word_and_two_by_their_shared_alias() -> None:
    """ECLI:NL:RVS:2026:3507: "waar Huisman, vertegenwoordigd door [gemachtigden],
    bijgestaan door mr. drs. W.J.W. van Eijk, advocaat te Den Bosch, en het college, ..."."""
    huisman = _read(
        [
            _party("Huisman Equipment B.V.", "Appellant"),
            _party(
                "het college van burgemeester en wethouders van Schiedam", "Verweerder"
            ),
        ],
        "Het college heeft nadere stukken ingediend. De Afdeling heeft de zaak behandeld, "
        "waar Huisman, vertegenwoordigd door [gemachtigde A] en [gemachtigde B], "
        "bijgestaan door mr. drs. W.J.W. van Eijk, advocaat te Den Bosch, is verschenen.",
    )
    assert _who(huisman) == [
        ("Huisman Equipment B.V.", "mr. drs. W.J.W. van Eijk", "advocaat")
    ]

    ls = [
        {**_party("Life Scientific Ltd", "Appellant"), "alias": "LS"},
        {**_party("Life Scientific Germany GmbH", "Appellant"), "alias": "LS"},
    ]
    assert _who(
        _read(ls, "Ter zitting is LS, bijgestaan door mr. P. Smit, verschenen.")
    ) == [
        ("Life Scientific Ltd", "mr. P. Smit", "gemachtigde"),
        ("Life Scientific Germany GmbH", "mr. P. Smit", "gemachtigde"),
    ]


def test_an_office_of_two_by_either_head() -> None:
    """ECLI:NL:RVS:2026:5174: the party "de burgemeester van Dinkelland en het college van
    burgemeester en wethouders van Dinkelland", "waar het college, vertegenwoordigd door
    ..."."""
    party = (
        "de burgemeester van Dinkelland en het college van burgemeester en wethouders "
        "van Dinkelland"
    )
    parties = _read(
        [_party("[appellante]", "Appellant"), _party(party, "Verweerder", "second")],
        "De Afdeling heeft de zaak behandeld, waar het college, vertegenwoordigd door "
        "K. Lammers, is verschenen.",
    )
    assert _who(parties) == [(party, "K. Lammers", "gemachtigde")]
