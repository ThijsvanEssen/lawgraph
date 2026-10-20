"""A write of what did not change leaves its rows alone, and one of what did writes only
those. (Runs of the chain over records that did not change: ``test_chain``.)"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.db import GraphStore
from tests.integration.graph import revisions
from tests.integration.seed import write_toestanden
from tests.optional import present


def test_a_changed_document_is_written_and_the_rest_is_left_alone(
    database: str,
) -> None:
    store = GraphStore()
    docs = [
        {"key": f"n{n}", "type": "case", "labels": ["TK"], "props": {"title": "a"}}
        for n in range(3)
    ]
    assert store.bulk_insert_or_update_nodes("cases", docs) == (3, 0)
    before = revisions(store, "cases")

    docs[1] = docs[1] | {"props": {"title": "b"}}
    assert store.bulk_insert_or_update_nodes("cases", docs) == (0, 1)
    after = revisions(store, "cases")
    assert after["n0"] == before["n0"] and after["n2"] == before["n2"]
    assert after["n1"] != before["n1"]
    assert present(store.get_document("cases", "n1"))["props"]["title"] == "b"

    # The same key twice in one batch: the lookup does not see the write before it.
    new_and_twice = [
        {"key": "n9", "type": "case", "labels": [], "props": {"title": "x"}},
        {"key": "n9", "type": "case", "labels": [], "props": {"title": "y"}},
    ]
    store.bulk_insert_or_update_nodes("cases", new_and_twice)
    assert present(store.get_document("cases", "n9"))["props"]["title"] == "y"


_LAW = """<toestand bwb-id="BWBR9100001"><wetgeving soort="wet"><citeertitel>Testwet</citeertitel>
<wet-besluit><wettekst>
<artikel><kop><nr>1</nr></kop><al>De minister stelt regels.</al></artikel>
<artikel><kop><nr>2</nr></kop><al>In afwijking van <intref doc="jci1.3:c:BWBR9100001&amp;artikel=1"
 bwb-id="BWBR9100001">artikel 1</intref> geldt dit artikel niet voor gemeenten.</al></artikel>
</wettekst></wet-besluit></wetgeving></toestand>"""


def test_classifying_relations_again_writes_only_what_changed(
    database: str, cli: Any
) -> None:
    """`updated_at` was set to now on every edge on every run, so all 330,000 classified
    edges of the rebuild were written again each time (a minute, and "328,571 updated")."""
    from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND

    store = GraphStore()
    write_toestanden(
        store, [(RAW_KIND_BWB_TOESTAND, "BWBR9100001", _LAW, {"bwb_id": "BWBR9100001"})]
    )
    cli("normalize", "bwb")
    cli("semantic", "bwb")
    first = cli("semantic", "bwb-relation-types")
    classified = "semantic_type IS NOT NULL"
    before = revisions(store, "edges", classified)
    assert before, first.stderr[-600:]

    again = cli("semantic", "bwb-relation-types")
    assert revisions(store, "edges", classified) == before
    assert re.search(r"Done in \S+: [\d,]+ unchanged", again.stderr), again.stderr[
        -300:
    ]
