"""A Tweede Kamer paper that names a law by its official abbreviation cites the law: the real
``semantic tk`` on the small test server.

"het EVRM" is the ECHR Convention, BWB treaty BWBV0001000, whose WTI gives EVRM as its
abbreviation; "de AVG" the EU act the curated list abbreviates. An abbreviation is matched as
written: "evrm" in lower case is no citation.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.db import ArangoStore


def _put(
    store: ArangoStore, collection: str, key: str, labels: list[str], **props: Any
) -> None:
    doc = {
        "_key": key,
        "type": collection.rstrip("s"),
        "labels": labels,
        "props": props,
    }
    store.bulk_insert_or_update_nodes(collection, [doc])


def _cited(store: ArangoStore, document: str) -> set[str]:
    return set(
        store.query(
            "FOR e IN edges FILTER e._from == @d AND e.relation == @r "
            "RETURN PARSE_IDENTIFIER(e._to).key",
            {"d": f"documents/{document}", "r": RELATION_REFERS_TO},
        )
    )


def test_a_paper_that_names_the_evrm_and_the_avg_cites_them(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "bwbv0001000",
        [],
        bwb_id="BWBV0001000",
        title="Verdrag tot bescherming van de rechten van de mens en de fundamentele "
        "vrijheden",
        citation_title="Verdrag tot bescherming van de rechten van de mens en de "
        "fundamentele vrijheden",
        short_title="EVRM",
        aliases=["EVRM"],
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        "32016r0679",
        [],
        celex="32016R0679",
        title="Verordening (EU) 2016/679 van het Europees Parlement en de Raad",
        citation_title="Verordening (EU) 2016/679",
        short_title="Algemene verordening gegevensbescherming",
    )
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "tk_1",
        ["TK"],
        external_id="tk-1",
        title="Brief over privacy",
        text="Het voorstel moet passen binnen het EVRM en de AVG.",
    )
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "tk_2",
        ["TK"],
        external_id="tk-2",
        title="Brief",
        text="Een woord als evrm of avg in kleine letters is geen afkorting.",
    )

    cli("semantic", "tk")

    assert _cited(store, "tk_1") == {"bwbv0001000", "32016r0679"}
    assert _cited(store, "tk_2") == set()
