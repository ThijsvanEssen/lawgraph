"""Old law to new law for real: excerpts of the transposition tables of the new Wetboek van
Strafvordering (the PDF blg-1081574 and the XML of its second memorie van toelichting,
kst-36636-3, as ``retrieve tk-transposition-tables`` stores them), of the Omgevingswet (the
tables of the Waterwet, the Woningwet and the Wet milieubeheer in kst-34986-3), of the
Mediawet 2008 (kst-31356-3,
``Huidige Mediawet | Mediawet 20..``) and of the Erfgoedwet (kst-34109-3, ``oud | nieuw``
under the old law's name), the new Sv read from its Staatsblad XML (``normalize
staatsblad-laws``) and a few articles of the laws of the BWB, through ``semantic
tk-transposition-tables``, the API and ``lawgraph succession-gaps``.

- A row that holds is a part of the ``TRANSPOSED_TO`` of its pair of articles; the tables
  between the same two laws are read together.
- A table of the law the paper proposes finds it by the name its column or its dossier
  gives it, a year still open standing for any; the old law by its column or its title.
- An article of the old law the law has lost since (a historical identity of
  ``normalize bwb-history``: Woningwet 101a, moved into the Omgevingswet) is one too.
- The API reads it both ways: on the old article where it went, on the new one where it came
  from.
- What a table answers instead of a place ("vervallen", "–", "Blijft in Waterwet", "naar de
  Gratiewet (via de invoeringswet)") is an edge to the new law, no gap; of an old article
  that is a gap, the edge keeps what the table writes. A division of the old law ("§ 1.2")
  is each article of it.
- An article of the new law worked out in an AMvB under it ("20, derde lid, besluit",
  kst-36440-3) is a place in the new law; an article of another law with the law that puts
  it there ("art. 1a WED (door artikel 2.46 IwOw)", kst-34986-3) one of that law.
- A row that does not hold, and an old article without a place, is a gap in the report; an
  old article without a row only of a law that expired no later than the new law came into
  force.
- An edge no table gives any more goes.
- A table of the Wet voortgezet onderwijs 2020 (kst-35297-3) with a column per old law, each
  with a column of its leden, is a table per old law; it names the old laws by their
  abbreviations of the WTI (``WVO``, ``WVO-BES``), of two laws of one name the one in force
  when the new law came into force.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_STAATSBLAD_LAW,
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    RELATION_PART_OF,
    RELATION_TRANSPOSED_TO,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.core.bwb_xml import article_key, historical_article_key
from lawgraph.db import EdgeWriter, GraphStore, RawSourceWriter, raw_source_doc
from tests.databases import Api, ModuleStore, module_store
from tests.paths import FIXTURES

OLD_SV = "instruments/bwbr0001903"
TABLE = "blg-1081574"


def _lid(number: str) -> dict[str, Any]:
    return {
        "id": f"lid-{number}",
        "kind": "lid",
        "number": number,
        "start": 0,
        "end": 1,
    }


# number -> leden, repealed
_OLD_ARTICLES = {
    "1": ((), False),
    "126ee": ((), False),
    "126ff": (("1", "2", "3", "4"), False),
    "126ffa": (("1", "2", "3", "4"), False),
    "126zz": (("1",), False),  # on no page of the excerpt
    "127a": ((), True),
    "5.1.1": (("1", "2"), False),  # the Vijfde Boek: in kst-36636-3 only
    "6:1:1": (("1", "2", "3"), False),
    "6:1:2": ((), False),
    "10": (("1", "2", "3"), False),  # lapses (p. 4: "vervalllen", "vervallen")
    "6:7:1": ((), False),  # to the Gratiewet (kst-36636-3)
}
_NONE: tuple[tuple[str, ...], bool] = ((), False)
_WATERWET = dict.fromkeys(
    (
        *("1.1", "1.2", "1.3", "1.4", "2.1", "2.8", "2.9", "3.1", "3.2", "3.3"),
        *("3.6a", "3.6b", "3.6c", "3.6d", "3.6e", "3.14"),
    ),
    _NONE,
)
_OMGEVINGSWET = dict.fromkeys(
    (
        *("1.3", "1.5", "1.6", "2.6", "2.13", "2.18", "2.19", "2.20", "2.21", "2.21a"),
        *("2.22", "2.23", "2.32", "4.23", "16.25", "19.17", "19.18"),
    ),
    _NONE,
)
# The Wet milieubeheer (it stays): § 1.2 and § 2.4, each a division of articles.
_WET_MILIEUBEHEER = dict.fromkeys(("1.1a", "1.2", "1.3", "2.42"), _NONE)
_DIVISIONS = {
    "BWBR0003245": {
        "1.1a": ("Hoofdstuk 1",),
        "1.2": ("Hoofdstuk 1", "§ 1.2"),
        "1.3": ("Hoofdstuk 1", "§ 1.2"),
        "2.42": ("Hoofdstuk 2", "§ 2.4"),
    },
    "BWBR0037885": {
        "1.6": ("Hoofdstuk 1", "Afdeling 1.3"),
        "16.25": ("Hoofdstuk 16", "Afdeling 16.3", "§ 16.3.5"),
    },
}
# The Woningwet: 101 in its current text, 101a to 103 only in its history.
_WONINGWET = {"101": _NONE}
_WONINGWET_LOST = ("101a", "102", "103")
_MEDIAWET = dict.fromkeys(("1", "3", "4", "9", "10", "11", "12"), _NONE)
_MEDIAWET_2008 = {
    **dict.fromkeys(("1.1", "1.2", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7"), _NONE),
    "7.1": (("1", "2"), False),
    "7.8": (("1",), False),
}
_UNESCO = dict.fromkeys(("1", "2", "3", "4", "5", "6"), _NONE)
_ERFGOEDWET = dict.fromkeys(("1.1", "3.13", "6.1", "6.3", "6.7"), _NONE)
# kst-36440-3: the Wet zeevarenden to the Wet bemanning zeeschepen
_WET_ZEEVARENDEN = dict.fromkeys(("5", "6", "20"), _NONE)
_WET_BEMANNING_ZEESCHEPEN: dict[str, tuple[tuple[str, ...], bool]] = {
    "20": (("1", "2", "3", "4", "5", "6"), False),
    **dict.fromkeys(("23", "24", "25", "26"), _NONE),
}


def _historical(store: GraphStore, bwb_id: str, numbers: tuple[str, ...]) -> None:
    """The historical identities of *numbers* of the law, as ``normalize bwb-history``
    writes them: no ``article_number``, the last one in ``last_article_number``."""
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": historical_article_key(bwb_id, number, str(stam)),
                "type": "article",
                "labels": ["BWB", "Article"],
                "props": {
                    "bwb_id": bwb_id,
                    "last_article_number": number,
                    "label": f"Artikel {number}",
                    "stam_id": str(stam),
                    "repealed": True,
                },
            }
            for stam, number in enumerate(numbers, start=1)
        ],
    )


def _bwb_law(
    store: GraphStore,
    bwb_id: str,
    title: str,
    articles: dict[str, tuple[tuple[str, ...], bool]],
    expired: str | None = None,
    in_force: str | None = None,
    short_title: str | None = None,
    aliases: tuple[str, ...] = (),
) -> None:
    key = bwb_id.lower()
    divisions = _DIVISIONS.get(bwb_id, {})
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": key,
                "type": "instrument",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": bwb_id,
                    "title": title,
                    "citation_title": title,
                    "short_title": short_title,
                    "kind": "wet",
                    "in_force": expired is None,
                    "date_expired": expired,
                    "date_in_force": in_force,
                    "aliases": list(aliases),
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": article_key(bwb_id, number, None),
                "type": "article",
                "labels": ["BWB", "Article"],
                "props": {
                    "bwb_id": bwb_id,
                    "article_number": number,
                    "label": f"Artikel {number}",
                    "text": "…",
                    "parts": [_lid(n) for n in leden],
                    "repealed": repealed,
                    "position": position,
                    "breadcrumb": [
                        {"type": label.split()[0].lower(), "label": label}
                        for label in divisions.get(number, ())
                    ]
                    or None,
                },
            }
            for position, (number, (leden, repealed)) in enumerate(articles.items())
        ],
    )
    with EdgeWriter(store, what=None) as edges:
        for number in articles:
            edges.add(
                f"articles/{article_key(bwb_id, number, None)}",
                f"instruments/{key}",
                RELATION_PART_OF,
                source="test",
            )


# A table whose columns run from the new law to the old one (made up for the test).
_REVERSED = """<officiele-publicatie><kamerstuk><bijlage>
<kop><titel>TRANSPONERINGSTABELLEN</titel></kop>
<table><title>Transponeringstabel Waterwet</title><tgroup>
<thead><row><entry colname="col1"><al>Artikel Omgevingswet</al></entry>
<entry colname="col2"><al>Artikel Waterwet</al></entry></row></thead>
<tbody><row><entry colname="col1"><al>2.20</al></entry>
<entry colname="col2"><al>3.2</al></entry></row></tbody>
</tgroup></table></bijlage></kamerstuk></officiele-publicatie>"""


def _paper(store: GraphStore, identifier: str, xml: str | None = None) -> None:
    """The Kamerstuk *identifier* with its XML, as ``retrieve tk-transposition-tables``
    stores it."""
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
                external_id=identifier,
                payload_text=xml
                or (
                    FIXTURES / f"{identifier.replace('-', '_')}_excerpt.xml"
                ).read_text(),
                meta={"identifier": identifier, "dossier": identifier.split("-")[1]},
            )
        )


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {"key": n, "type": "dossier", "labels": ["TK"], "props": {"number": n}}
            for n in ("36327", "36636", "34986")
        ],
    )
    _bwb_law(store, "BWBR0001903", "Wetboek van Strafvordering", _OLD_ARTICLES)
    _bwb_law(store, "BWBR0025458", "Waterwet", _WATERWET, expired="2024-01-01")
    _bwb_law(store, "BWBR0037885", "Omgevingswet", _OMGEVINGSWET, in_force="2024-01-01")
    _bwb_law(store, "BWBR0005181", "Woningwet", _WONINGWET)
    _historical(store, "BWBR0005181", _WONINGWET_LOST)
    _bwb_law(store, "BWBR0003245", "Wet milieubeheer", _WET_MILIEUBEHEER)
    # expired after the Mediawet 2008 came into force: it does not replace it
    _bwb_law(store, "BWBR0004025", "Mediawet", _MEDIAWET, expired="2009-01-02")
    _bwb_law(
        store, "BWBR0025028", "Mediawet 2008", _MEDIAWET_2008, in_force="2009-01-01"
    )
    _bwb_law(store, "BWBR0024186", "Uitvoeringswet UNESCO-verdrag 1970", _UNESCO)
    _bwb_law(store, "BWBR0037521", "Erfgoedwet", _ERFGOEDWET)
    _bwb_law(
        store, "BWBR0009124", "Wet zeevarenden", _WET_ZEEVARENDEN, expired="2025-07-01"
    )
    _bwb_law(
        store,
        "BWBR0050681",
        "Wet bemanning zeeschepen",
        _WET_BEMANNING_ZEESCHEPEN,
        in_force="2025-07-01",
    )
    _bwb_law(store, "BWBR0008331", "Wet beheer rijkswaterstaatswerken", {"11": _NONE})
    _bwb_law(
        store,
        "BWBR0002063",
        "Wet op de economische delicten",
        {"1a": _NONE},
        short_title="WED",
    )
    with RawSourceWriter(store) as writer:
        for official in ("stb-2026-56", "stb-2026-57"):
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STAATSBLAD_LAW,
                    external_id=official,
                    payload_text=(
                        FIXTURES / f"{official.replace('-', '_')}_excerpt.xml"
                    ).read_text(),
                    meta={"identifier": official},
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_TRANSPOSITION_TABLE,
                external_id=TABLE,
                payload_text=base64.b64encode(
                    (FIXTURES / "blg_1081574_excerpt.pdf").read_bytes()
                ).decode("ascii"),
                meta={"identifier": TABLE, "dossier": "36327", "encoding": "base64"},
            )
        )
    for document in (
        *("kst-36636-3", "kst-34986-3", "kst-31356-3", "kst-34109-3"),
        "kst-36440-3",
    ):
        _paper(store, document)
    _paper(store, "kst-34986-99", _REVERSED)
    # rows of the tables of the Waterwet and the Wet milieubeheer in kst-34986-3 the table
    # answers for, or with a division of the old law
    _paper(
        store,
        "kst-34986-98",
        (FIXTURES / "kst_34986_3_answers_excerpt.xml").read_text(),
    )
    # the row of the Wet beheer rijkswaterstaatswerken in kst-34986-3 with the WED
    _paper(
        store, "kst-34986-97", (FIXTURES / "kst_34986_3_wbr_excerpt.xml").read_text()
    )


# The tests read one database built for them all (``built``), on the worker that built it;
# the one that writes has a database of its own (``database``).
pytestmark = pytest.mark.xdist_group("transposition_tables")


def _build(store: GraphStore, cli: Any) -> None:
    _seed(store)
    cli("normalize", "staatsblad-laws")
    cli("semantic", "tk-transposition-tables")
    cli("semantic", "tk-transposition-tables")  # a second run changes nothing


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as built:
        _build(*built)
        yield built


@pytest.fixture(scope="module")
def store(built: ModuleStore) -> GraphStore:
    return built.store


def _transposed(store: GraphStore, to: str = "articles") -> dict[tuple[str, str], Any]:
    """The ``TRANSPOSED_TO`` edges to an article, or (*to* ``instruments``) to a law."""
    return {
        (row["from_id"], row["to_id"]): row["meta"]
        for row in store.query(
            "SELECT from_id, to_id, doc -> 'meta' AS meta FROM edges "
            "WHERE relation = %(r)s AND to_collection = %(to)s",
            {"r": RELATION_TRANSPOSED_TO, "to": to},
        )
    }


def test_a_row_that_holds_is_a_part_of_the_edge_of_its_pair(store: GraphStore) -> None:
    edges = _transposed(store)
    assert set(edges) == {
        ("articles/bwbr0001903_1", "articles/stb_2026_56_1_1_1"),
        ("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6"),
        ("articles/bwbr0001903_6_1_1", "articles/stb_2026_56_1_10_1"),
        ("articles/bwbr0001903_6_1_1", "articles/stb_2026_56_7_1_1"),
        ("articles/bwbr0025458_1_2", "articles/bwbr0037885_1_5"),
        ("articles/bwbr0025458_1_3", "articles/bwbr0037885_1_5"),
        ("articles/bwbr0025458_1_4", "articles/bwbr0037885_1_5"),
        ("articles/bwbr0025458_1_2", "articles/bwbr0037885_2_21"),
        ("articles/bwbr0025458_1_3", "articles/bwbr0037885_2_21"),
        ("articles/bwbr0025458_1_4", "articles/bwbr0037885_2_21"),
        # "bijlage A in samenhang met 1.3, 2.17, 4.10, 4.12, 4.23 en 5.9"
        ("articles/bwbr0025458_1_1", "articles/bwbr0037885_1_3"),
        ("articles/bwbr0025458_1_1", "articles/bwbr0037885_4_23"),
        ("articles/bwbr0025458_2_1", "articles/bwbr0037885_1_3"),
        ("articles/bwbr0025458_2_1", "articles/bwbr0037885_4_23"),
        ("articles/bwbr0025458_2_8", "articles/bwbr0037885_2_13"),
        ("articles/bwbr0025458_3_1", "articles/bwbr0037885_2_19"),
        ("articles/bwbr0025458_3_1", "articles/bwbr0037885_2_20"),
        ("articles/bwbr0025458_3_1", "articles/bwbr0037885_2_21"),
        ("articles/bwbr0025458_3_1", "articles/bwbr0037885_2_21a"),
        # the table whose columns run from the new law to the old
        ("articles/bwbr0025458_3_2", "articles/bwbr0037885_2_20"),
        # the Wet milieubeheer's § 1.2: each of its articles
        *(
            (f"articles/bwbr0003245_{old}", f"articles/bwbr0037885_{new}")
            for old in ("1_2", "1_3")
            for new in ("2_6", "2_18", "2_22", "2_23", "2_32")
        ),
        # the Woningwet: its current 101 and the 101a to 103 it has lost since
        *(
            (old, f"articles/bwbr0037885_19_{new}")
            for old in (
                "articles/bwbr0005181_101",
                "articles/bwbr0005181_101a_stam_1",
                "articles/bwbr0005181_102_stam_2",
                "articles/bwbr0005181_103_stam_3",
            )
            for new in ("17", "18")
        ),
        # Huidige Mediawet | Mediawet 20..: the Mediawet 2008
        *(
            (f"articles/bwbr0004025_{old}", f"articles/bwbr0025028_{new}")
            for old, new in (
                ("1", "1_1"),
                ("3", "1_1"),
                ("4", "1_2"),
                ("9", "7_1"),
                ("10", "7_2"),
                ("10", "7_3"),
                ("11", "7_4"),
                ("11", "7_8"),
                ("12", "7_5"),
                ("12", "7_6"),
                ("12", "7_7"),
            )
        ),
        # oud | nieuw under "Uitvoeringswet UNESCO-verdrag 1970": the Erfgoedwet
        *(
            (f"articles/bwbr0024186_{old}", f"articles/bwbr0037521_{new}")
            for old, new in (
                ("1", "1_1"),
                ("1", "6_1"),
                ("2", "3_13"),
                ("3", "6_3"),
                ("4", "6_7"),
            )
        ),
        # Wet zeevarenden | Wetsvoorstel: the Wet bemanning zeeschepen
        ("articles/bwbr0009124_5", "articles/bwbr0050681_20"),
        ("articles/bwbr0009124_6", "articles/bwbr0050681_20"),
        *(
            ("articles/bwbr0009124_20", f"articles/bwbr0050681_{new}")
            for new in ("23", "24", "25", "26")
        ),
        # a place in another law: the WED
        ("articles/bwbr0008331_11", "articles/bwbr0002063_1a"),
    }
    assert edges[("articles/bwbr0024186_1", "articles/bwbr0037521_6_1")] == {
        "basis": "transposition_table",
        "source": "kst-34109-3",
        "parts": [{"from": "Onder b-d", "to": "6.1", "article": "6.1", "leden": []}],
    }
    assert edges[("articles/bwbr0001903_6_1_1", "articles/stb_2026_56_7_1_1")] == {
        "basis": "transposition_table",
        "source": "kst-36636-3",
        "parts": [
            {
                "from": "tweede lid",
                "to": "7.1.1, eerste lid",
                "article": "7.1.1",
                "leden": ["1"],
            },
            {
                "from": "derde lid",
                "to": "7.1.1, tweede lid",
                "article": "7.1.1",
                "leden": ["2"],
            },
        ],
    }
    assert edges[("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6")] == {
        "basis": "transposition_table",
        "source": TABLE,
        "parts": [
            {"from": "1", "to": "2.8.6, 1", "article": "2.8.6", "leden": ["1"]},
            {"from": "2", "to": "2.8.6, 1", "article": "2.8.6", "leden": ["1"]},
            {"from": "3", "to": "2.8.6, 1", "article": "2.8.6", "leden": ["1"]},
            {"from": "4", "to": "2.8.6, 2", "article": "2.8.6", "leden": ["2"]},
        ],
    }


def test_what_a_table_answers_is_an_edge_to_the_new_law(store: GraphStore) -> None:
    """blg-1081574 p. 4, art. 10 lapses ("vervalllen", "vervallen"); kst-34986-3: the
    Waterwet's 3.6a t/m 3.6e stay in it, its 3.14 is not taken over ("–"), the Wet
    milieubeheer's § 2.4 neither; its 1.1a is placed in "afdeling 1.3" only: a gap, with
    what the table writes."""
    answers = _transposed(store, "instruments")
    new_sv, ow = "instruments/wet_stb_2026_56", "instruments/bwbr0037885"
    assert answers[("articles/bwbr0001903_10", new_sv)] == {
        "basis": "transposition_table",
        "source": TABLE,
        "outcome": "vervallen",
        "parts": [
            {"from": "1", "to": "vervalllen", "outcome": "vervallen"},
            {"from": "2", "to": "vervallen", "outcome": "vervallen"},
            {"from": "3", "to": "vervallen", "outcome": "vervallen"},
        ],
    }
    assert (
        {old: meta["outcome"] for (old, law), meta in answers.items() if law == ow}
        == {
            **{f"articles/bwbr0025458_3_6{n}": "blijft_in:Waterwet" for n in "abcde"},
            "articles/bwbr0025458_3_14": "niet_overgenomen",
            "articles/bwbr0003245_2_42": "niet_overgenomen",
            "articles/bwbr0003245_1_1a": "gat",
            "articles/bwbr0025458_2_9": "gat",  # "2.42": the Omgevingswet has no such article
        }
    )
    assert answers[("articles/bwbr0003245_2_42", ow)]["parts"] == [
        {"from": "", "to": "–", "outcome": "niet_overgenomen", "via": "§ 2.4"}
    ]
    assert answers[("articles/bwbr0003245_1_1a", ow)]["parts"] == [
        {"from": "", "to": "afdeling 1.3", "outcome": "gat"}
    ]
    # each article of the Wet milieubeheer's § 1.2 placed by the row of the division
    assert {
        part.get("via")
        for (old, _), meta in _transposed(store).items()
        if old.startswith("articles/bwbr0003245_")
        for part in meta["parts"]
    } == {"§ 1.2"}


def test_a_place_in_an_amvb_or_in_another_law_by_its_note(store: GraphStore) -> None:
    """kst-36440-3: "20, derde lid, besluit" is 20, third lid, of the new law (it delegates
    to the AMvB); kst-34986-3, Wbr 11: "art. 1a WED (door artikel 2.46 IwOw)" is 1a of the
    WED; kst-36636-3, Sv 6:7:1: "naar de Gratiewet (via de invoeringswet)" an outcome."""
    edges = _transposed(store)
    wzv, wbz = "articles/bwbr0009124", "articles/bwbr0050681"
    assert edges[(f"{wzv}_6", f"{wbz}_20")]["parts"] == [
        {"from": "", "to": "20, derde lid, besluit", "article": "20", "leden": ["3"]}
    ]
    assert {new for old, new in edges if old == f"{wzv}_20"} == {
        f"{wbz}_{n}" for n in ("23", "24", "25", "26")
    }
    assert edges[(f"{wzv}_20", f"{wbz}_24")]["parts"] == [
        {"from": "", "to": "23 tot en met 26, besluit", "article": "24", "leden": []}
    ]
    assert edges[("articles/bwbr0008331_11", "articles/bwbr0002063_1a")]["parts"] == [
        {
            "from": "",
            "to": "art. 1a WED (door artikel 2.46 IwOw)",
            "article": "1a",
            "leden": [],
        }
    ]
    answers = _transposed(store, "instruments")
    gratie = f"articles/{article_key('BWBR0001903', '6:7:1', None)}"
    assert answers[(gratie, "instruments/wet_stb_2026_56")] == {
        "basis": "transposition_table",
        "source": "kst-36636-3",
        "outcome": "naar:Gratiewet",
        "parts": [
            {
                "from": "",
                "to": "naar de Gratiewet (via de invoeringswet)",
                "outcome": "naar:Gratiewet",
            }
        ],
    }


def test_the_api_reads_it_both_ways(api: Api) -> None:
    old = api.get_json("/api/articles/BWBR0001903/126ffa")
    (successor,) = old["successors"]
    assert successor["article"]["id"] == "articles/stb_2026_56_2_8_6"
    assert successor["article"]["article_number"] == "2.8.6"
    assert (successor["in_force"], successor["status"]) == (False, "vastgesteld")
    assert successor["parts"][-1] == {
        "old_part": "4",
        "new_place": "2.8.6, 2",
        "new_article": "2.8.6",
        "new_leden": ["2"],
    }
    assert successor["source_url"] == (
        "https://zoek.officielebekendmakingen.nl/blg-1081574.html"
    )
    assert old["predecessors"] == []

    new = api.get_json("/api/articles/STB-2026-56/2.8.6")
    (predecessor,) = new["predecessors"]
    assert predecessor["article"]["id"] == "articles/bwbr0001903_126ffa"
    assert predecessor["in_force"] is True
    assert new["successors"] == []

    # a table in the XML of a memorandum: the memorandum is the source
    sixth = api.get_json("/api/articles/BWBR0001903/6:1:1")
    assert {s["article"]["article_number"] for s in sixth["successors"]} == {
        "1.10.1",
        "7.1.1",
    }
    # one old article in two new ones: a successor each, with its own parts
    assert {
        s["article"]["article_number"]: [
            (p["old_part"], p["new_article"], p["new_leden"]) for p in s["parts"]
        ]
        for s in sixth["successors"]
    }["7.1.1"] == [("tweede lid", "7.1.1", ["1"]), ("derde lid", "7.1.1", ["2"])]
    assert {s["source_url"] for s in sixth["successors"]} == {
        "https://zoek.officielebekendmakingen.nl/kst-36636-3.html"
    }


def test_the_report_lists_what_does_not_hold(built: ModuleStore) -> None:
    out = built.cli("succession-gaps").stdout
    assert f"{OLD_SV} -> instruments/wet_stb_2026_56" in out
    assert f"  {TABLE} (dossier 36327): rows that do not hold" in out
    assert "p. 4: art. 126ee: 2.8.4 [the new law has no such article]" in out
    assert "p. 4: art. 126ff 1: 2.8.5, 1 [the new law has no such article]" in out
    assert (
        "  kst-36636-3 III. TRANSPONERINGSTABELLEN – Huidig naar nieuw (dossier 36636): "
        "rows that do not hold (3)"
    ) in out
    assert (
        "rij 2: art. 5.1.1 eerste lid: 8.2.1 [the new law has no such article]" in out
    )
    assert (
        "rij 9: art. 6:1:2: 1.10.2, eerste lid [the new law has no such article]" in out
    )
    # the articles without a place in any table between the two laws
    assert "art. 126zz [no row]" in out
    # with what the table writes for it
    assert (
        f"{TABLE} p. 4: art. 126ff: 2.8.5, 1; 2.8.5, 2; Besluit B2; 2.8.5, 3 "
        "[no row of it holds]"
    ) in out
    assert (
        "kst-36636-3 rij 9: art. 6:1:2: 1.10.2, eerste lid [no row of it holds]" in out
    )
    assert "art. 127a" not in out  # repealed
    assert "art. 126ffa" not in out
    assert "art. 6:1:1 " not in out

    assert "instruments/bwbr0025458 -> instruments/bwbr0037885" in out
    assert "rij 2: art. 1.1: 2.17 [the new law has no such article]" in out
    assert "rij 6: art. 2.9: 2.42 [the new law has no such article]" in out
    # the Waterwet expired when the Omgevingswet came into force
    assert "art. 3.3 [no row]" in out
    assert "art. 3.2 " not in out
    # what the tables answer is no gap
    assert "art. 3.14" not in out
    assert "art. 3.6a" not in out
    assert (
        "What the tables say instead of a place (no gap): blijft_in:Waterwet 5, "
        "niet_overgenomen 1"
    ) in out
    # the Wet milieubeheer stays; its 1.1a is placed in a division of the Omgevingswet
    assert "art. 1.1a: afdeling 1.3 [placed in a division only]" in out
    # the Mediawet expired after the Mediawet 2008 came into force: no row is no gap
    assert "instruments/bwbr0004025 -> instruments/bwbr0025028" in out
    assert "(the old law is not replaced: no row is no gap)" in out

    # a table of the Erfgoedwet whose old law the graph does not have
    assert (
        "kst-34109-3 Wet tot behoud van cultuurbezit (dossier 34109): places nothing: "
        "no one law of the BWB named 'oud' or 'Wet tot behoud van cultuurbezit'."
    ) in out


def test_one_table_and_the_laws_it_is_between(built: ModuleStore) -> None:
    out = built.cli("succession-gaps", "--table", "kst-34986-3").stdout
    assert "instruments/bwbr0025458 -> instruments/bwbr0037885" in out
    assert OLD_SV not in out


def test_an_edge_no_table_gives_any_more_goes(database: str, cli: Any) -> None:
    store = GraphStore()
    _build(store, cli)
    store.execute(
        "DELETE FROM raw_sources WHERE kind = ANY(%(k)s)",
        {"k": [RAW_KIND_TK_TRANSPOSITION_TABLE, RAW_KIND_TK_TRANSPOSITION_DOCUMENT]},
    )
    cli("semantic", "tk-transposition-tables")
    assert _transposed(store) == {}


# The Wet voortgezet onderwijs 2020 and the laws it replaced (kst-35297-3): number -> leden.
_WVO = {
    **dict.fromkeys(("1", "2", "2a", "7", "10", "15", "33", "42", "118u"), _NONE),
    "4": (("1", "2"), False),
    "119": (("1", "2"), False),
}
_WVO_BES = dict.fromkeys(
    ("1", "2", "3", "5", "13", "16", "41", "80", "96", "214b"), _NONE
)
_WVO_2020 = {
    **dict.fromkeys(
        ("1.1", "1.3", "1.4", "2.2", "2.3", "2.13", "2.26", "7.11", "8.28", "11.1"),
        _NONE,
    ),
    "2.24": (("1", "2", "3", "4", "5", "6"), False),
    "7.9": (("1", "2"), False),
}


def test_a_column_per_old_law_with_its_leden(database: str, cli: Any) -> None:
    store = GraphStore()
    _bwb_law(
        store,
        "BWBR0002399",
        "Wet op het voortgezet onderwijs",
        _WVO,
        expired="2022-08-01",
        aliases=("WVO",),
    )
    # the WVO BES of its first months, and the one of 2011 on
    _bwb_law(
        store,
        "BWBR0028424",
        "Wet voortgezet onderwijs BES",
        dict.fromkeys(("1", "3"), _NONE),
        expired="2011-02-17",
        aliases=("WVO BES",),
    )
    _bwb_law(
        store,
        "BWBR0030284",
        "Wet voortgezet onderwijs BES",
        _WVO_BES,
        expired="2022-08-01",
        in_force="2011-02-17",
        aliases=("WVO BES",),
    )
    _bwb_law(
        store,
        "BWBR0044212",
        "Wet voortgezet onderwijs 2020",
        _WVO_2020,
        in_force="2022-08-01",
    )
    _paper(store, "kst-35297-3")
    cli("semantic", "tk-transposition-tables")

    def article(bwb_id: str, number: str) -> str:
        return f"articles/{article_key(bwb_id, number, None)}"

    edges = _transposed(store)
    pairs = {
        "BWBR0002399": [
            ("1", "1.1"), ("1", "2.13"), ("2", "1.4"), ("2a", "7.9"), ("4", "8.28"),
            ("10", "2.24"), ("15", "2.26"), ("33", "7.11"), ("42", "2.3"),
            ("119", "1.3"), ("7", "2.2"),
        ],
        "BWBR0030284": [
            ("1", "1.1"), ("1", "2.13"), ("1", "11.1"), ("2", "1.4"), ("3", "7.9"),
            ("5", "8.28"), ("16", "2.24"), ("41", "2.26"), ("80", "7.11"),
            ("96", "2.3"), ("13", "2.2"),
        ],
    }  # fmt: skip
    assert set(edges) == {
        (article(old_law, old), article("BWBR0044212", new))
        for old_law, rows in pairs.items()
        for old, new in rows
    }
    assert edges[article("BWBR0002399", "2a"), article("BWBR0044212", "7.9")][
        "parts"
    ] == [{"from": "", "to": "7.9, lid 1", "article": "7.9", "leden": ["1"]}]
    assert edges[article("BWBR0002399", "10"), article("BWBR0044212", "2.24")][
        "parts"
    ] == [
        {
            "from": "lid 4 t/m 8 (deels) en 10 (deels)",
            "to": "2.24, lid 1 t/m 5",
            "article": "2.24",
            "leden": ["1", "2", "3", "4", "5"],
        }
    ]
    out = cli("succession-gaps", "--table", "kst-35297-3").stdout
    assert "instruments/bwbr0002399 -> instruments/bwbr0044212" in out
    assert "instruments/bwbr0030284 -> instruments/bwbr0044212" in out
    assert "rij 11: art. 118u: 12.* [does not read]" in out
