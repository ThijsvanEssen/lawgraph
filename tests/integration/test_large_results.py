"""A large result must stream from the server, not be built in its memory first."""

from __future__ import annotations

from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import seed

# 3,000 documents of 120 KB: 360 MB, more than the 256 MiB a query may use on the test server
# and a third of all the memory it has. The XML of the sources is in the payload store, but a
# JSON payload (and a judgment with its text and paragraphs) is in the database, this large.
DOCUMENTS = 3_000
SIZE = 120_000


def _seed(store: ArangoStore) -> None:
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
    store = ArangoStore()
    _seed(store)
    aql = "FOR r IN raw_sources FILTER r.source == @source RETURN r"
    read = total = 0
    for row in store.query(aql, {"source": "tk"}, batch_size=20):
        read += 1
        total += len(row["payload_json"]["Onderwerp"])
    assert read == DOCUMENTS and total >= DOCUMENTS * SIZE


def test_a_reader_that_stops_halfway_leaves_no_query_behind(database: str) -> None:
    """A pipeline that raises in its loop left its query, and the snapshot it holds, open for
    the hour of its ttl."""
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for number in range(3_000):
            writer.add(
                raw_source_doc(source="tk", kind="tk-zaak", external_id=str(number))
            )

    def running() -> int:
        return len([q for q in store.db.aql.queries() if "raw_sources" in q["query"]])

    rows = store.query("FOR r IN raw_sources RETURN r._key", batch_size=100)
    next(iter(rows))
    assert running() == 1
    rows.close()  # type: ignore[attr-defined]  # what a `for` loop that raises does
    assert running() == 0


def test_counting_raw_records_reads_the_index_not_the_documents(database: str) -> None:
    """`expand-graph` and `check` count raw records per kind. As a scan of the collection
    that read every document (an EU act is up to 1 MB): with 3,474 acts stored the server
    stopped both with "Memory limit reached: Insert failed due to LRU cache being full"."""
    from lawgraph.commands import check, expand_graph
    from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX
    from lawgraph.db.queries import raw as raw_queries

    store = ArangoStore()
    seed(store, documents=20, judgments=5, regulations=2)
    queries = {
        "expand-graph": (
            raw_queries.RECORD_COUNTS_AQL,
            {"missing": f"%{RAW_KIND_MISSING_SUFFIX}"},
        ),
        "check": (raw_queries.RAW_COUNTS_AQL, {}),
    }
    for name, (aql, bind) in queries.items():
        plan = store.db.aql.explain(aql, bind_vars=bind)
        nodes = [node["type"] for node in plan["nodes"]]
        assert "EnumerateCollectionNode" not in nodes, (name, nodes)
        index = next(node for node in plan["nodes"] if node["type"] == "IndexNode")
        assert index.get("indexCoversProjections"), (name, index.get("projections"))

    assert expand_graph._count_records(store) == sum(check._raw_counts(store).values())
