"""A large result must stream from the server, not be built in its memory first."""

from __future__ import annotations

from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

# 3,000 documents of 120 KB: 360 MB, more than the 256 MiB a query may use on the test server
# and a third of all the memory it has. The real corpus has 41,000 toestanden of 80 KB.
DOCUMENTS = 3_000
SIZE = 120_000


def _seed(store: ArangoStore) -> None:
    body = "<artikel>" + "x" * SIZE + "</artikel>"
    with RawSourceWriter(store) as writer:
        for number in range(DOCUMENTS):
            writer.add(
                raw_source_doc(
                    source="bwb",
                    kind="bwb-toestand-xml",
                    external_id=f"BWBR{number:07d}",
                    payload_text=body,
                    meta={"bwb_id": f"BWBR{number:07d}"},
                )
            )


def test_every_large_payload_can_be_read_through_store_query(database: str) -> None:
    store = ArangoStore()
    _seed(store)
    aql = "FOR r IN raw_sources FILTER r.source == @source RETURN r"
    read = total = 0
    for row in store.query(aql, {"source": "bwb"}, batch_size=20):
        read += 1
        total += len(row["payload_text"])
    assert read == DOCUMENTS and total > DOCUMENTS * SIZE


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
