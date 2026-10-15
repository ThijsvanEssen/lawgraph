"""Once after the deploy of E16: the Staatsblad publication of every stored BWB toestand into its
meta (``staatsblad_ref``), read from its XML as ``retrieve bwb`` now does when it stores one. A
toestand that has the key is left alone, so a second run reads nothing.

    .venv/bin/python ops/staatsblad-refs.py

Run under the lock (staatsblad-refs-steps.sh). The rebuild path is ``retrieve bwb``, which keeps
the ref with every toestand it stores.
"""

from __future__ import annotations

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

BATCH = 500


def fill(store: GraphStore) -> tuple[int, int]:
    """Write the ref of every toestand without one; ``(written, of them naming one)``."""
    records = raw_queries.iter_raw_records(
        store,
        source=SOURCE_BWB,
        kinds=[RAW_KIND_BWB_TOESTAND],
        since_iso=None,
        batch_size=50,
    )
    todo = (r for r in records if "staatsblad_ref" not in (r.get("meta") or {}))
    written = named = 0
    batch: list[dict[str, object]] = []
    for record in store.with_payloads(todo):
        xml = record.get("payload_text")
        if record.get("payload_ref"):  # read for this run, kept in the payload store
            del record["payload_text"]
        ref = staatsblad_ref_from_bwb_xml(xml) if xml else None
        record.pop("id", None)
        record["meta"] = {
            **(record.get("meta") or {}),
            "staatsblad_ref": f"stb-{ref[0]}-{ref[1]}" if ref else None,
        }
        batch.append(record)
        named += ref is not None
        if len(batch) == BATCH:
            store.insert_raw_sources(batch)
            written += len(batch)
            batch = []
    store.insert_raw_sources(batch)
    return written + len(batch), named


def main() -> None:
    store = GraphStore()
    try:
        written, named = fill(store)
    finally:
        store.close()
    print(
        f"Done: {written:,} toestanden written, {named:,} name a Staatsblad publication."
    )


if __name__ == "__main__":
    main()
