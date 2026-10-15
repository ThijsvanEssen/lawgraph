"""What the readers of names, particles, initials and places give, pinned: the
advocate-general of a conclusion, the parties of a kop and who acts for them, the members of
the Eerste Kamer, the holders of a post and the words a person search looks up by.

``tests/fixtures/dutch_names_golden.json`` holds the expected output. A change in it is a
change in what is read: check every line of the diff before writing the file anew with
``python tests/test_dutch_names_golden.py``.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from lawgraph.core import ek_change_patterns, ek_pages
from lawgraph.core.government import match_holder
from lawgraph.core.judgment_advocate_general import advocate_general
from lawgraph.core.judgment_counsel import read_counsel, same_person
from lawgraph.core.judgment_metadata import extract_rdf_metadata, parse_judgment
from lawgraph.core.judgment_paragraphs import judgment_text, kop_lines
from lawgraph.core.judgment_parties import read_parties
from lawgraph.db.queries.search.persons import _telling
from tests.paths import FIXTURES, fixture_text

GOLDEN = FIXTURES / "dutch_names_golden.json"

# The opening lines of a conclusion, one per case.
AG_LINES = [
    "T. Hartlief",
    "mr. P.J. Wattel",
    "Mr. Wattel",
    "mr Wattel.",
    "Zaaknr: 18/04298 (Prejudicieel) mr. Wattel",
    "Conclusie van den Advocaat-Generaal Mr. Besier.",
    "Zaaknr :26/00083 R.H. de Bock",
    "F.F. Langemeijer en M.H. Wissink",
    "Mr. T.N.B.M. Spronken Conclusie inzake:",
    "D.J.C. Aben Vordering tot cassatie",
    "mr. A.E. Harteveld",
    "Th. Bierens",
    "Chr. van Dijk",
    "Joh. van der Linden",
    "Jac. ten Brink",
    "Fr. de Wit",
    "Wm. Tak",
    "IJ. van Oven",
    "mr. E.M. Witteveen-van den Berg",
    "mr. G.R.B. van Peursem",
    "mr. J. in 't Veld",
    "mr. J. uit den Bogaard",
    "mr. D. du Pré",
    "mr. A. ter Horst",
    "mr. A. Jansen te Amsterdam",
    "mr. B. op de Beek",
    "prof. mr. A. Hammerstein",
    "dr. P. Vlas",
    "drs. K. Teuben",
    "ING Bank N.V.",
    "mr. R.J.B. Boonekamp en",
    "De Hoge Raad",
]

# Who acts for whom, as the account of the procedure says it: one sentence per case, for
# the same two parties.
COUNSEL_PARTIES = [
    {"name": "[appellant]", "role": "Appellant", "side": "first"},
    {"name": "het college", "role": "Verweerder", "side": "other"},
]
COUNSEL_SENTENCES = [
    "[appellant], bijgestaan door mr. drs. R. van Gelder, advocaat te Voorschoten, en het "
    "college, vertegenwoordigd door mr. I.T.F. Vermeulen, zijn verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te 's-Gravenhage, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te ‘s-Hertogenbosch, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te Den Haag, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat in Bergen op Zoom, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te Nieuwerkerk aan den IJssel, "
    "is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te Alphen a/d Rijn, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te Wijk bij Duurstede, is "
    "verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen, advocaat te 't Zandt, is verschenen.",
    "[appellant], bijgestaan door Joh. van der Linden, advocaat te Utrecht, is verschenen.",
    "[appellant], bijgestaan door mr. Th. in 't Veld en mr. Chr. uit den Bogaard, beiden "
    "advocaat te Amsterdam, is verschenen.",
    "[appellant], bijgestaan door mr. D. du Pré, advocaat te Rotterdam, is verschenen.",
    "[appellant], bijgestaan door mr. P. de la Court, advocaat te Leiden, is verschenen.",
    "[appellant], bijgestaan door ir. B. Bij de Vaate, is verschenen.",
    "[appellant], bijgestaan door ing. C. Aan de Stegge, is verschenen.",
    "[appellant], bijgestaan door ING Bank, is verschenen.",
    "[appellant], bijgestaan door mr. A. Jansen te Amsterdam, is verschenen.",
    "[appellant], bijgestaan door mr. Fr.-J. de Graaf, is verschenen.",
    "Het college, vertegenwoordigd door mr. A. de Boer, is verschenen. Voorts is de "
    "gemeenteraad, vertegenwoordigd door mr. X. Pietersen, als partij gehoord. De "
    "gemeenteraad van Nieuwerkerk aan den IJssel heeft een zienswijze gegeven.",
    "Het college, vertegenwoordigd door mr. A. de Boer, is verschenen. Voorts is de "
    "gemeenteraad, vertegenwoordigd door mr. X. Pietersen, als partij gehoord. De "
    "gemeenteraad van 's-Gravenhage heeft een zienswijze gegeven.",
    "Het college, vertegenwoordigd door mr. A. de Boer, is verschenen. Voorts is de "
    "gemeenteraad, vertegenwoordigd door mr. X. Pietersen, als partij gehoord. De "
    "gemeenteraad van ‘s-Hertogenbosch heeft een zienswijze gegeven.",
]
SAME_PERSON = [
    ("mr. B. van Dijk", "mr. Van Dijk"),
    ("mr. drs. R. van Gelder", "R. van Gelder"),
    ("mr. J. in 't Veld", "mr. J. In 't Veld"),
    ("ir. A. Bos", "ing. A. Bos"),
    ("mr. A.B. Jansen", "mr. A.C. Jansen"),
]

# The parties of a kop: one kop per case.
KOPS = [
    [
        "uitspraak in het geding tussen:",
        "[appellant], wonend te [woonplaats],",
        "appellant,",
        "(gemachtigde: mr. A. Jansen te 's-Gravenhage),",
        "en",
        "het college van burgemeester en wethouders van Den Haag,",
        "verweerder,",
        "(gemachtigde: mr. B. de Vries te Den Haag).",
    ],
    [
        "inzake",
        "ING BANK N.V.,",
        "gevestigd te Amsterdam,",
        "eiseres,",
        "advocaat: mr. C. van der Meer te Bergen op Zoom,",
        "tegen",
        "[gedaagde],",
        "wonende te [woonplaats],",
        "gedaagde,",
        "advocaat: mr. D. du Pré te Nieuwerkerk aan den IJssel.",
    ],
    [
        "in de zaak van",
        "[eiser],",
        "eiser,",
        "advocaten: mr. E. in 't Veld en",
        "mr. F. uit den Bogaard, kantoorhoudende te ‘s-Hertogenbosch,",
        "tegen",
        "de Staat der Nederlanden (Ministerie van Financiën),",
        "zetelende te 's-Gravenhage,",
        "gedaagde,",
        "advocaat: drs. G. ter Horst te 't Zandt.",
    ],
    [
        "in de zaak van",
        "[eiser],",
        "eiser,",
        "gemachtigde: Joh. van den Berg te Alphen a/d Rijn,",
        "tegen",
        "de vereniging Vereniging Eigen Huis,",
        "gevestigd te Amersfoort,",
        "gedaagde,",
        "advocaat: ir. H. Bij de Vaate te Wijk bij Duurstede.",
    ],
]

# Members of the Eerste Kamer as its texts name them.
EK_NAMES = [
    "Robert van Gasteren",
    "Marjolein Faber-van de Klashorst",
    "Annabel Nanninga",
    "Cees van de Sanden",
    "Senator Kemperman",
    "Kemperman",
    "Van Gasteren",
    "Ten Hoeve",
    "Het Kamerlid Bert ten Hoeve",
    "Eerste Kamerlid Theo van den Berg",
    "Paul van Meenen",
    "Tineke in 't Veld",
    "Ruud op de Beek",
    "Laura la Rivière",
    "Te Velde",
    "Op de Beek",
    "Al Jansen",
    "Dick de la Court",
]
EK_TEXTS = [
    "Robert van Gasteren (BBB) is beëdigd als lid van de Eerste Kamer.",
    "Tineke in 't Veld (VVD) is beëdigd als lid van de Eerste Kamer.",
    "Ruud op de Beek (PVV) vertrekt per 1 juli 2024 uit de Eerste Kamer.",
    "Dick de la Court (D66) is beëdigd als lid van de Eerste Kamer.",
    "Jan Jansen te Rotterdam (CDA) is beëdigd als lid van de Eerste Kamer.",
    "Op 4 juli is de Fractie-Van der Linden gevormd.",
]

# Holders of a post and the members of parliament they may be.
MEMBERS = [
    {"key": "wdv", "name": "Gerda Wallis de Vries", "family_name": "Wallis de Vries"},
    {"key": "kvc", "name": "Carel Kappeyne van de Coppello",
     "family_name": "Kappeyne van de Coppello"},
    {"key": "itv", "name": "Sophie in 't Veld", "family_name": "Veld"},
    {"key": "bdv", "name": "Hans Bij de Vaate", "family_name": "Bij de Vaate"},
    {"key": "dh", "name": "Jan d'Hondt", "family_name": "d'Hondt"},
    {"key": "ef", "name": "Hanna El Fassed", "family_name": "El Fassed"},
    {"key": "dlc", "name": "Pieter de la Court", "family_name": "de la Court"},
    {"key": "gru", "name": "Jan Gruijters", "family_name": "Gruijters"},
    {"key": "vdl", "name": "Anne vander Laan", "family_name": "vander Laan"},
]  # fmt: skip
HOLDERS = [
    ("Wallis de Vries", "g"),
    ("de Vries", "g"),
    ("Kappeyne van de Coppello", "c"),
    ("in 't Veld", "s"),
    ("Veld", "s"),
    ("Bij de Vaate", "h"),
    ("d'Hondt", "j"),
    ("Hondt", "j"),
    ("El Fassed", "h"),
    ("Fassed", "h"),
    ("de la Court", "p"),
    ("Court", "p"),
    ("Gruyters", "j"),
    ("vander Laan", "a"),
    ("van der Laan", "a"),
]

# The words of a person query.
QUERY_WORDS = (
    "mr dr drs prof ir ing de het der den van ten ter te op in uit la le du da di dos des "
    "von zu el al aan bij vander vande vanden gelder vermeulen jansen"
).split()


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_plain(v) for v in value]
        return (
            sorted(items, key=json.dumps)
            if isinstance(value, (set, frozenset))
            else items
        )
    return value


def _fixture(name: str) -> dict[str, Any]:
    root = parse_judgment(fixture_text(name))
    _, subjects = extract_rdf_metadata(root)
    paragraphs, _ = judgment_text(root)
    parties = read_parties(kop_lines(root), subjects)
    return {
        "advocate_general": advocate_general(root),
        "parties": read_counsel(parties, paragraphs, subjects),
    }


def _conclusion(line: str) -> str | None:
    return advocate_general(
        parse_judgment(f"<open><conclusie><para>{line}</para></conclusie></open>")
    )


def _counsel(sentence: str) -> list[dict[str, Any]]:
    parties = [
        {
            **p,
            "roles": [p["role"]],
            "role_stated": True,
            "alias": None,
            "representatives": [],
        }
        for p in COUNSEL_PARTIES
    ]
    paragraphs = [
        {"kind": "subheading", "text": "KOP"},
        {"kind": "body", "text": sentence},
    ]
    return read_counsel(parties, paragraphs, ["Bestuursrecht"])


def _holder(surname: str, letters: str) -> dict[str, Any]:
    return {
        "surname": surname,
        "letters": letters,
        "days": ["2025-06-03"],
        "factions": [],
    }


def _outputs() -> dict[str, Any]:
    return _plain(
        {
            "fixtures": {
                p.name: _fixture(p.name)
                for p in sorted(FIXTURES.glob("rechtspraak_*.xml"))
            },
            "advocate_general": {line: _conclusion(line) for line in AG_LINES},
            "counsel": {s: _counsel(s) for s in COUNSEL_SENTENCES},
            "same_person": [same_person(a, b) for a, b in SAME_PERSON],
            "parties": [read_parties(kop, ["Civiel recht"]) for kop in KOPS],
            "ek_surname": {n: ek_change_patterns.surname(n) for n in EK_NAMES},
            "ek_member_key": {n: ek_change_patterns.member_key(n) for n in EK_NAMES},
            "ek_texts": {
                t: ek_change_patterns.read(
                    ek_pages.Article("Personele mutatie", "2024-07-04", t)
                )
                for t in EK_TEXTS
            },
            "ek_articles": [
                ek_change_patterns.read(
                    ek_pages.Article(a["headline"], a["date"], a["text"], a["persons"])
                )
                for name in ("articles_2023.json", "articles_2003_2023.json")
                for a in json.loads(fixture_text(name, sub="eerstekamer"))
            ],
            "match_holder": {
                f"{s} {i}": match_holder(_holder(s, i), MEMBERS) for s, i in HOLDERS
            },
            "telling": {w: _telling(w) for w in QUERY_WORDS},
        }
    )


def test_what_the_readers_of_names_give_stays_the_same() -> None:
    expected = json.loads(GOLDEN.read_text("utf-8"))
    actual = _outputs()
    for part in expected:
        assert actual[part] == expected[part], part
    assert actual.keys() == expected.keys()


if __name__ == "__main__":
    GOLDEN.write_text(
        json.dumps(_outputs(), ensure_ascii=False, indent=0, sort_keys=True) + "\n",
        "utf-8",
    )
