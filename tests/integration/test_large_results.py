"""A large result must stream from the server, not be built in its memory first."""

from __future__ import annotations

from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import seed

# 3,000 documents of 120 KB: 360 MB, a third of all the memory the test server has. The XML
# of the sources is in the payload store, but a JSON payload (and a judgment with its text
# and paragraphs) is in the database, this large.
DOCUMENTS = 3_000
SIZE = 120_000


def _seed(store: GraphStore) -> None:
    body = "x" * SIZE
    with RawSourceWriter(store) as writer:
        for number in range(DOCUMENTS):
            writer.add(
                raw_source_doc(
                    source="tk",
                    kind="tk-document",
                    external_id=f"doc-{number}",
                    payload_json={"Id": f"doc-{number}", "Onderwerp": body},
                )
            )


def test_every_large_document_can_be_read_through_store_query(database: str) -> None:
    store = GraphStore()
    _seed(store)
    statement = "SELECT doc FROM raw_sources WHERE source = %(source)s"
    read = total = 0
    for row in store.query(statement, {"source": "tk"}, batch_size=20):
        read += 1
        total += len(row["payload_json"]["Onderwerp"])
    assert read == DOCUMENTS and total >= DOCUMENTS * SIZE


def test_expand_graph_and_check_count_the_same_raw_records(database: str) -> None:
    """`expand-graph` and `check` count raw records per kind, each in its own query."""
    from lawgraph.commands import check, expand_graph

    store = GraphStore()
    seed(store, documents=20, judgments=5, regulations=2)

    assert expand_graph._count_records(store) == sum(check._raw_counts(store).values())


# ── no silent caps ───────────────────────────────────────────────────────────


def _nodes(store: GraphStore, collection: str, docs: list[dict]) -> None:
    for start in range(0, len(docs), 5_000):
        store.bulk_insert_or_update_nodes(collection, docs[start : start + 5_000])


def test_the_staatscourant_text_scan_reads_every_publication(database: str) -> None:
    """The scan for BWB ids in the texts had a silent cap of 5,000 publications."""
    from lawgraph.config.constants import COLLECTION_DOCUMENTS, SOURCE_STAATSCOURANT
    from lawgraph.db.queries.semantic import bwb as semantic_bwb

    store = GraphStore()
    publications = 5_001
    text = "Regeling op grond van BWBR0001854. " * 5  # longer than 100 characters
    _nodes(
        store,
        COLLECTION_DOCUMENTS,
        [
            {
                "_key": f"stcrt-2025-{n}",
                "type": "document",
                "labels": ["Staatscourant"],
                "props": {"source": SOURCE_STAATSCOURANT, "text": text},
            }
            for n in range(publications)
        ],
    )

    rows = list(semantic_bwb.staatscourant_texts(store, None))

    assert len(rows) == publications


def test_the_stub_judgments_are_not_capped_in_the_database(database: str) -> None:
    """Filling the gaps had a silent cap of 50,000 stubs; the cap is a named one of the
    pipeline now (``_gaps.MAX_GAPS_PER_RUN``), reported when it is hit."""
    from lawgraph.config.constants import COLLECTION_JUDGMENTS
    from lawgraph.db.queries import gaps as gap_queries

    store = GraphStore()
    stubs = 50_001
    eclis = [f"ECLI:NL:HR:2020:{n}" for n in range(stubs)]
    _nodes(
        store,
        COLLECTION_JUDGMENTS,
        [
            {
                "_key": f"ecli_nl_hr_2020_{n}",
                "type": "judgment",
                "labels": ["Rechtspraak"],
                "props": {"ecli": ecli, "stub": True},
            }
            for n, ecli in enumerate(eclis)
        ],
    )

    assert list(gap_queries.stub_dutch_eclis(store)) == sorted(eclis)
