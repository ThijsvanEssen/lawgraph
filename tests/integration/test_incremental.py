"""An incremental run must find in the database what is not in its window."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from lawgraph.config.constants import RAW_KIND_TK_STEMMING, RELATION_VOTED, SOURCE_TK
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import FACTIONS, seed, uid


def _voted_edges(store: ArangoStore) -> int:
    aql = "FOR e IN edges FILTER e.relation == @relation COLLECT WITH COUNT INTO n RETURN n"
    return next(iter(store.query(aql, {"relation": RELATION_VOTED})))


def test_votes_of_a_new_decision_are_linked_to_factions_loaded_earlier(
    database: str, cli: Any
) -> None:
    """`retrieve all` skips the members and factions on incremental runs (--skip-members)."""
    store = ArangoStore()
    seed(store, documents=120, judgments=1, regulations=1)
    cli("normalize", "tk-dossiers")
    before = _voted_edges(store)
    assert before > 0

    time.sleep(1.1)  # fetched_at has a precision of a second
    window = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    decision = uid(999_999, 7)
    with RawSourceWriter(store) as writer:
        for number in range(FACTIONS):
            vote = {
                "Id": uid(900_000 + number, 6),
                "Besluit_Id": decision,
                "Soort": "Voor",
                "FractieGrootte": 10,
                "ActorFractie": f"Fractie {number}",
                "Fractie_Id": uid(number, 8),
                "GewijzigdOp": "2025-06-01T10:00:00+02:00",
                "Besluit": {"Id": decision, "BesluitSoort": "Stemmen - aangenomen"},
            }
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_STEMMING,
                    external_id=vote["Id"],
                    payload_json=vote,
                )
            )

    cli("normalize", "tk-dossiers", "--since", window.isoformat())
    assert _voted_edges(store) == before + FACTIONS
