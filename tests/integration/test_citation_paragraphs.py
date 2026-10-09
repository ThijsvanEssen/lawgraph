"""Where a judgment cites, for real: ``semantic rechtspraak-citations`` keeps on the edge to a
cited judgment the numbers of the paragraphs that name it (``meta.paragraphs``), and the
neighbours of a node give them on every entry, also for a judgment that cites an article
(from the paragraphs of its mentions), so a list of citing judgments needs no request per
row."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc
from tests.integration.test_judgment_relations import _xml

RULING = "ECLI:NL:HR:2021:10"
CITED = "ECLI:NL:HR:2015:1"


def _ruling() -> str:
    xml = _xml(
        RULING,
        "Hoge Raad",
        "2021-03-05",
        "20/00001",
        procedure="Cassatie",
        text=f"Zoals de Hoge Raad eerder oordeelde ({CITED}), faalt het middel.",
    )
    # a second numbered paragraph that names it again, and one that names nothing
    second = (
        "<paragroup><nr>4.3</nr><para>Dat volgt ook uit HR 1 mei 2015, "
        f"{CITED}.</para></paragroup><paragroup><nr>4.4</nr><para>Het middel faalt."
        "</para></paragroup>"
    )
    return xml.replace(
        "</paragroup></section>", "</paragroup>" + second + "</section>", 1
    )


def test_the_paragraphs_that_cite_are_on_the_edge_and_the_neighbour(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for ecli, xml in (
            (RULING, _ruling()),
            (CITED, _xml(CITED, "Hoge Raad", "2015-05-01", "14/00001")),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-citations")

    (meta,) = store.query(
        "SELECT doc -> 'meta' FROM edges WHERE relation = 'REFERS_TO'"
        " AND from_collection = 'judgments' AND to_collection = 'judgments'"
    )
    assert meta == {"cited_ecli": CITED, "paragraphs": ["1.1", "4.3"]}

    # a judgment that cites an article: its paragraphs come from its mentions
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"_key": "bwbr0005537_8_1", "type": "article", "labels": [], "props": {}}],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "judgments/ecli_nl_hr_2021_10",
                "articles/bwbr0005537_8_1",
                "REFERS_TO",
                source="t",
                meta={
                    "mentions": [
                        {"paragraph_id": "p1", "paragraph_number": "3.2"},
                        {"paragraph_id": "p2", "paragraph_number": "3.2"},
                        {"paragraph_id": "p3", "paragraph_number": "5.1"},
                    ]
                },
            )
        ]
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        cited = client.get("/api/nodes/judgments/ecli_nl_hr_2015_1").json()
        article = client.get(
            "/api/nodes/articles/bwbr0005537_8_1", params={"props": "canvas"}
        ).json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    def paragraphs(body: dict[str, Any]) -> list[Any]:
        return [
            (item.get("meta") or {}).get("paragraphs")
            for bucket in body["neighbors"]["buckets"]
            for item in bucket["items"]
        ]

    assert paragraphs(cited) == [["1.1", "4.3"]]
    assert paragraphs(article) == [["3.2", "5.1"]]


def test_a_run_over_all_in_slices_reads_each_judgment_once(
    database: str, cli: Any
) -> None:
    """``--after``, ``--limit``: the run over all that gives the citations of #419 their
    paragraphs goes at night in slices; each slice names where to go on, the edges of
    every slice stay, and a slice past the end reads nothing."""
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for ecli, xml in (
            (RULING, _ruling()),
            (CITED, _xml(CITED, "Hoge Raad", "2015-05-01", "14/00001")),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")

    after, slices = "", 0
    while True:
        args = ["semantic", "rechtspraak-citations", "--limit", "1"]
        done = cli(*args, *(["--after", after] if after else []))
        out = done.stdout + done.stderr
        after = out.split("go on with --after ")[-1].split(")")[0]
        slices += 1
        if after == "None":
            break
    assert slices == 3  # two judgments, one a slice, then one that reads nothing
    (meta,) = store.query(
        "SELECT doc -> 'meta' FROM edges WHERE relation = 'REFERS_TO'"
        " AND from_collection = 'judgments' AND to_collection = 'judgments'"
    )
    assert meta == {"cited_ecli": CITED, "paragraphs": ["1.1", "4.3"]}
