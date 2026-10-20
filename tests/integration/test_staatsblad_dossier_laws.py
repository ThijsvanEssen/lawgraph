"""The law of a dossier that the BWB does not name it by closes the dossier, for real: the XML
of three laws as ``retrieve staatsblad`` stores them, through ``normalize staatsblad-laws``
and ``semantic tk-dossier-outcomes``.

- Stb. 2020, 429: the verklaringswet of 35418 (a first reading of a change of the Grondwet),
  a law that enacts no regulation of its own.
- Stb. 2023, 14: the budget law of 36200-VII (Binnenlandse Zaken 2023): a law with articles,
  of a budget, which the BWB never holds; its publication is no law of the graph.
- Stb. 2014, 10: the Rijkswet changing the Paspoortwet, of 33440-(R1990): the Staatsblad names
  its dossier without the number of the Rijkswet (``33440``).

Each publication is ``LEGISLATED_IN`` its dossier, and the dossier is closed as adopted on
the day the law was published.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_STAATSBLAD_LAW, SOURCE_STAATSBLAD
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAWS = ("stb-2020-429", "stb-2023-14", "stb-2014-10")


def _dossier(key: str, label: str, number: str, kind: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": "dossier",
        "labels": ["TK"],
        "props": {"label": label, "number": number, "kind": kind},
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _dossier("35418", "35418", "35418", "Wetgeving"),
            _dossier("36200_vii", "36200-VII", "36200", "Begroting"),
            _dossier("33440_r1990", "33440-(R1990)", "33440", "Wetgeving"),
        ],
    )
    with RawSourceWriter(store) as writer:
        for official in LAWS:
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STAATSBLAD_LAW,
                    external_id=official,
                    payload_text=(
                        FIXTURES / f"{official.replace('-', '_')}.xml"
                    ).read_text(),
                    meta={"identifier": official},
                )
            )


def _legislated_in(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'LEGISLATED_IN'"
        )
    }


def test_the_law_of_each_dossier_closes_it(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    cli("normalize", "staatsblad-laws")
    cli("normalize", "staatsblad-laws")  # a second run changes nothing
    cli("semantic", "tk-dossier-outcomes")

    assert _legislated_in(store) == {
        ("instruments/stb_2020_429", "dossiers/35418"),
        ("instruments/stb_2023_14", "dossiers/36200_vii"),
        ("instruments/stb_2014_10", "dossiers/33440_r1990"),
    }
    publication = store.get_node("instruments", "stb_2023_14")
    assert publication is not None
    assert publication.props["kind"] == "publicatie"
    assert publication.props["dossier_numbers"] == ["36200-VII"]
    # neither the budget law nor the verklaringswet is a law of the graph
    laws = store.query("SELECT key FROM instruments WHERE key LIKE 'wet_stb_%'")
    assert list(laws) == []

    closed = {
        key: (props["closed"], props["outcome"], props["closed_on"])
        for key, props in (
            (row["key"], row["props"])
            for row in store.query("SELECT key, props FROM dossiers")
        )
    }
    assert closed == {
        "35418": (True, "aangenomen", "2020-11-09"),
        "36200_vii": (True, "aangenomen", "2023-01-19"),
        "33440_r1990": (True, "aangenomen", "2014-01-17"),
    }
