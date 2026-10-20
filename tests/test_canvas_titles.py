"""A node read with ``props=canvas`` has the title it has with all its props: the canvas
keeps what its title reads (``_rows.canvas_keys``, ``core.names.title_of``)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.names import title_of
from lawgraph.db._rows import CANVAS_PROPS, canvas_keys

# Per collection nodes with every prop their title may read, as the graph has them.
SAMPLES: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "articles": [
        (
            "articles/bwbr0005289_162",
            {
                "bwb_id": "BWBR0005289",
                "article_number": "162",
                "label": "Artikel 162",
                "caption": "Onrechtmatige daad",
                "instrument_citation_title": "Burgerlijk Wetboek Boek 6",
                "display_name": "Artikel 162 Burgerlijk Wetboek Boek 6",
            },
        ),
        (
            "articles/bwbr0001854_287",
            {
                "bwb_id": "BWBR0001854",
                "article_number": "287",
                "heading": "Doodslag",
                "instrument_citation_title": "Wetboek van Strafrecht",
                "instrument_abbreviation": "Sr",
            },
        ),
        (
            "articles/bwbr0001840_algemene_bepaling",
            {
                "label": "Algemene bepaling",
                "display_name": "Algemene bepaling Grondwet",
            },
        ),
    ],
    "instruments": [
        (
            "instruments/bwbr0001854",
            {
                "bwb_id": "BWBR0001854",
                "citation_title": "Wetboek van Strafrecht",
                "short_title": "Sr",
                "title": "Wetboek van Strafrecht",
                "display_name": "Wetboek van Strafrecht",
            },
        ),
        (
            "instruments/stb_2026_187",
            {"official_id": "stb-2026-187", "citation_title": "Stb. 2026, 187"},
        ),
    ],
    "judgments": [
        (
            "judgments/ecli_eu_c_2023_492",
            {
                "ecli": "ECLI:EU:C:2023:492",
                "date": "2023-06-22",
                "court": "Hof van Justitie van de Europese Unie",
                "court_code": "C",
                "case_number": "C-160/20",
                "names": ["Stichting Rookpreventie"],
                "display_name": "HvJ EU, C-160/20",
            },
        ),
        (
            "judgments/ecli_nl_phr_2019_1",
            {
                "ecli": "ECLI:NL:PHR:2019:1",
                "date": "2019-01-04",
                "court_code": "PHR",
                "advocate_general": "Hartlief",
                "advocate_general_role": "A-G",
                "translation_of": "ECLI:NL:PHR:2019:2",
            },
        ),
    ],
    "documents": [
        (
            "documents/motie",
            {
                "kind": "Motie (gewijzigd/nader)",
                "subject": "Gewijzigde motie van het lid Bolhuis over een AI-killswitch",
                "title": "Wet AI-toezicht",
                "dossier_number": "36496",
                "dossier_suffix": "VII",
                "sequence": 71,
            },
        ),
        (
            "documents/brief",
            {"kind": "Brief regering", "title": "Stand van zaken", "number": "A"},
        ),
    ],
    "dossiers": [
        (
            "dossiers/36496",
            {"label": "36496", "title": "Regels over toezicht (Wet AI-toezicht)"},
        )
    ],
    "members": [
        (
            "members/m",
            {
                "name": "Rob Jetten",
                "government_functions": [
                    {"function": "Minister-president", "to_date": None}
                ],
                "faction_memberships": [{"abbreviation": "D66", "to_date": None}],
            },
        ),
        (
            "members/ek",
            {
                "full_name": "A. Lid",
                "ek": {"abbreviation": "VVD", "observed_until": None},
            },
        ),
    ],
    "factions": [
        ("factions/d66", {"name": "Democraten 66", "abbreviation": "D66"}),
        ("factions/x", {"name": "D66-fractie", "chamber": "EK"}),
    ],
    "committees": [
        (
            "committees/szw",
            {
                "title": "Vaste commissie voor Sociale Zaken",
                "name": "Sociale Zaken",
                "abbreviation": "SZW",
                "chamber": "EK",
            },
        )
    ],
    "cabinets": [
        (
            "cabinets/rutte_iv",
            {"name": "kabinet-Rutte IV", "from_date": "2022-01-10", "to_date": "2024"},
        )
    ],
    "activities": [
        (
            "activities/a",
            {
                "kind": "Wetgevingsoverleg",
                "date": "2026-03-23",
                "agenda_title": "Cyberbeveiligingswet",
                "number": "2026A01323",
            },
        )
    ],
    "commitments": [
        (
            "commitments/tz",
            {"number": "TZ202609-124", "text": "Een brief voor de zomer."},
        )
    ],
    "cases": [
        (
            "cases/z",
            {
                "number": "2025Z15468",
                "citation_title": "Motie Bolhuis",
                "kind": "Motie",
            },
        )
    ],
    "annexes": [
        (
            "annexes/a",
            {
                "label": "II",
                "title": "Lijst II",
                "bwb_id": "BWBR0001941",
                "instrument_abbreviation": "Ow",
                "instrument_citation_title": "Opiumwet",
            },
        )
    ],
    "instrument_versions": [
        (
            "instrument_versions/v",
            {
                "bwb_id": "BWBR0001840",
                "instrument_citation_title": "Grondwet",
                "valid_from": "2002-03-21",
                "valid_until": "2005-02-08",
            },
        )
    ],
    "decisions": [
        (
            "decisions/d",
            {
                "agenda_item_subject": "Wet AI-toezicht",
                "date": "2026-09-08",
                "result": "Aangenomen",
                "decision_kind": "Stemmen - aangenomen",
            },
        ),
        (
            "decisions/e",
            {"subject": "Motie Bolhuis", "decision_kind": "Stemmen - uitstellen"},
        ),
    ],
}


def test_every_collection_of_the_canvas_has_its_samples() -> None:
    assert set(SAMPLES) == set(CANVAS_PROPS)


@pytest.mark.parametrize(
    ("node", "props"),
    [sample for samples in SAMPLES.values() for sample in samples],
)
def test_the_canvas_keeps_what_the_title_of_a_node_reads(
    node: str, props: dict[str, Any]
) -> None:
    keys = canvas_keys(node.split("/")[0])
    kept = {key: value for key, value in props.items() if key in keys}
    assert title_of(node, kept) == title_of(node, props)
