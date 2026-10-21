"""How many references in the text of an EU article and of a paper of the Tweede Kamer were
recognized and not linked: the real ``semantic eurlex`` and ``semantic tk`` and the API on
their answer (``completeness.references``).

- An EU article names two acts by CELEX number; the graph holds one.
- A paper cites ``artikel 287 Sr``, which the graph holds, and ``artikel 140.1 Sr``, a number
  of a shape the Wetboek van Strafrecht never uses: recognized, linked to nothing.
- A paper cites ``artikel 300 Sr``, which the graph holds as a stub only: linked, to a target
  that is not loaded. A judgment cites ``artikel 287 Sr`` and a judgment not loaded (a stub
  of its ECLI): one of its references goes to a target that is not loaded.
- A record without text to read has no ``completeness.references``; the count of a record
  that is gone goes in a run over all.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import rechtspraak_xml, write_judgments

SR, CELEX = "BWBR0001854", "32019L1158"
RULING, CITED = "ECLI:NL:HR:2021:10", "ECLI:NL:HR:2015:1"


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    labels = ["TK"] if collection == COLLECTION_DOCUMENTS else []
    doc = {"key": key, "type": collection.rstrip("s"), "labels": labels, "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


pytestmark = pytest.mark.xdist_group("unlinked_references")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _put(
            store, COLLECTION_INSTRUMENTS, CELEX.lower(), celex=CELEX, title="Richtlijn"
        )
        _put(
            store,
            COLLECTION_ARTICLES,
            "32016r0679_6",
            celex="32016R0679",
            article_number="6",
            text=f"Zie CELEX:{CELEX} en CELEX:32020L0001.",
        )
        _put(
            store,
            COLLECTION_INSTRUMENTS,
            SR.lower(),
            bwb_id=SR,
            title="Wetboek van Strafrecht",
            citation_title="Wetboek van Strafrecht",
            short_title="Sr",
        )
        _put(
            store,
            COLLECTION_ARTICLES,
            make_node_key(SR, "287"),
            bwb_id=SR,
            article_number="287",
            text="Hij die opzettelijk een ander van het leven berooft.",
        )
        _put(
            store,
            COLLECTION_DOCUMENTS,
            "kst-36000-7",
            title="Motie",
            text="Gelet op artikel 287 Sr en artikel 140.1 Sr verzoekt de Kamer.",
        )
        # an article some reference made a stub of: its text is not loaded
        _put(
            store,
            COLLECTION_ARTICLES,
            make_node_key(SR, "300"),
            bwb_id=SR,
            article_number="300",
            stub=True,
        )
        _put(
            store,
            COLLECTION_DOCUMENTS,
            "kst-36000-9",
            title="Motie",
            text="Gelet op artikel 287 Sr en artikel 300 Sr verzoekt de Kamer.",
        )
        _put(
            store,
            COLLECTION_DOCUMENTS,
            "kst-36000-10",
            title="Motie",
            text="Gelet op artikel 300 Sr en artikel 140.1 Sr verzoekt de Kamer.",
        )
        ruling = rechtspraak_xml(
            RULING,
            "Hoge Raad",
            "2021-03-05",
            "20/00001",
            procedure="Cassatie",
            text=f"Zoals in {CITED} geoordeeld, is artikel 287 Sr geschonden.",
        )
        write_judgments(store, {RULING: ruling})
        cli("normalize", "rechtspraak")
        _put(store, COLLECTION_DOCUMENTS, "kst-36000-8", kind="Brief")
        # of a paper that is gone: a run over all removes it
        store.execute(
            "INSERT INTO lg_unlinked_references VALUES ('documents/gone', %(s)s, 3)",
            {"s": "tk-article-linker"},
        )
        for _ in range(2):  # a second run changes nothing
            cli("semantic", "eurlex")
            cli("semantic", "tk")
            cli("semantic", "rechtspraak")
            cli("semantic", "rechtspraak-citations")
        yield store


def test_an_eu_article_says_how_many_acts_it_names_are_not_linked(api: Api) -> None:
    completeness = api.get_json("/api/articles/32016R0679/6")["completeness"]
    assert completeness == {
        "references": {"state": "partial", "as_of": None, "missing": 1, "reason": None}
    }


def test_a_paper_says_how_many_citations_are_not_linked(api: Api) -> None:
    completeness = api.get_json("/api/documents/kst-36000-7")["completeness"]
    assert completeness["references"] == {
        "state": "partial",
        "as_of": None,
        "missing": 1,
        "reason": None,
    }


def test_a_paper_says_how_many_citations_go_to_a_target_not_loaded(api: Api) -> None:
    completeness = api.get_json("/api/documents/kst-36000-9")["completeness"]
    assert completeness["references"] == {
        "state": "partial",
        "as_of": None,
        "missing": 1,
        "reason": "target_not_loaded",
    }


def test_a_paper_with_both_counts_them_both_without_a_reason(api: Api) -> None:
    """One citation not linked, one to a stub: two missing, not all for one reason."""
    completeness = api.get_json("/api/documents/kst-36000-10")["completeness"]
    assert completeness["references"] == {
        "state": "partial",
        "as_of": None,
        "missing": 2,
        "reason": None,
    }


def test_a_judgment_counts_a_cited_judgment_not_loaded(api: Api) -> None:
    completeness = api.get_json(f"/api/judgments/{RULING}")["completeness"]
    assert completeness == {
        "references": {
            "state": "partial",
            "as_of": None,
            "missing": 1,
            "reason": "target_not_loaded",
        }
    }


def test_a_record_no_step_read_has_no_completeness(api: Api) -> None:
    paper = api.get_json("/api/documents/kst-36000-8")["completeness"]
    assert "references" not in paper  # only what of its text there is
    assert api.get_json(f"/api/articles/{SR}/287")["completeness"] is None


def test_a_count_is_kept_per_record_read(store: GraphStore) -> None:
    rows = store.query("SELECT id, step, count FROM lg_unlinked_references ORDER BY id")
    assert list(rows) == [
        {"id": "articles/32016r0679_6", "step": "eu-article-linker", "count": 1},
        {"id": "documents/kst-36000-10", "step": "tk-article-linker", "count": 1},
        {"id": "documents/kst-36000-7", "step": "tk-article-linker", "count": 1},
        {"id": "documents/kst-36000-9", "step": "tk-article-linker", "count": 0},
        {"id": "judgments/ecli_nl_hr_2021_10", "step": "rechtspraak-article-linker",
         "count": 0},
    ]  # fmt: skip
