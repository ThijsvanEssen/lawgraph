"""Which lists of changes ``retrieve eerstekamer-mutations`` reads: the current term's on
every run, that of a term that ended only while it is not stored (it does not change)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import RAW_KIND_EK_MUTATION, RAW_KIND_EK_MUTATIONS
from lawgraph.core import ek_changes
from lawgraph.pipelines.retrieve import eerstekamer_mutations as retrieve

CURRENT = (
    Path(__file__).parent / "fixtures" / "eerstekamer" / "personele_mutaties_2023.html"
).read_text("utf-8")
TERMS = ek_changes.term_page(CURRENT).terms
ITEMS = [item.path for item in ek_changes.term_page(CURRENT).items]


class _Client(EerstekamerSiteClient):
    """The site, answered from the fixture: the current list, an empty one per term."""

    def __init__(self) -> None:
        super().__init__()
        self.read: list[str] = []

    def _page(self, url: str) -> str:
        path = url.removeprefix(self.url(""))
        self.read.append("/" + path.lstrip("/"))
        return CURRENT if path.lstrip("/") == "personele_mutaties" else "<html></html>"


def _read(stored_terms: list[str]) -> list[str]:
    pipeline = object.__new__(retrieve.EerstekamerMutationsRetrievePipeline)
    client = _Client()
    pipeline.client = client  # type: ignore[assignment]
    at = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)

    def stored_at(source: str, kind: str) -> dict[str, Any]:
        if kind == RAW_KIND_EK_MUTATIONS:
            return dict.fromkeys(stored_terms, at)
        assert kind == RAW_KIND_EK_MUTATION
        return dict.fromkeys(ITEMS, at)  # every item stored already

    pipeline._stored_at = stored_at  # type: ignore[method-assign]
    records = list(pipeline.fetch())
    assert [r.external_id for r in records] == client.read
    return client.read


def test_the_lists_of_the_terms_that_ended_are_read_once() -> None:
    assert len(TERMS) == 6
    assert _read([]) == [ek_changes.MUTATIONS_PATH, *TERMS]
    # stored: only the current term's list again, every day
    assert _read([ek_changes.MUTATIONS_PATH, *TERMS]) == [ek_changes.MUTATIONS_PATH]
    # a term not stored yet (one that just ended): that one too
    assert _read([ek_changes.MUTATIONS_PATH, *TERMS[1:]]) == [
        ek_changes.MUTATIONS_PATH,
        TERMS[0],
    ]
