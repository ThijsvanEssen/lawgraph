"""The store of the BWB normalize pipelines in memory, and the queries they ask of it."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import pytest

from lawgraph.db.queries.normalize import bwb as normalize_bwb
from tests.fakes.queries import patch_kept_state
from tests.fakes.store import InMemoryStore


class BwbStore(InMemoryStore):
    """The shared store, with the BWB normalize queries it was asked in ``queries``."""

    def __init__(
        self, nodes: dict[str, Iterable[dict[str, Any]]] | None = None
    ) -> None:
        super().__init__(nodes)
        self.queries: list[str] = []


def patch_bwb_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of the BWB normalize pipelines, answered from the nodes of a ``BwbStore``;
    each call is recorded in ``store.queries``. No toestand start is stored: a version
    ends where the next one begins. What a pipeline keeps in ``pipeline_state`` is in
    ``store.kept``."""
    patch_kept_state(monkeypatch)

    def recorded(name: str, answer: Any) -> Any:
        def recording(store: BwbStore, *args: Any, **kwargs: Any) -> Any:
            store.queries.append(name)
            return answer(store, *args, **kwargs)

        return recording

    def article_versions(store: BwbStore, bwb_ids: list[str]) -> Iterator[dict]:
        return iter(
            {
                "key": k,
                "bwb_id": d["props"].get("bwb_id"),
                "stam_id": d["props"].get("stam_id"),
                "number": d["props"].get("article_number"),
                "valid_from": d["props"].get("valid_from"),
                "valid_until": d["props"].get("valid_until"),
                "title": d["props"].get("instrument_citation_title"),
            }
            for k, d in store.nodes.get("article_versions", {}).items()
            if d["props"].get("bwb_id") in bwb_ids
        )

    def article_identities(store: BwbStore, bwb_ids: list[str]) -> Iterator[dict]:
        return iter(
            {
                "key": k,
                "bwb_id": d["props"].get("bwb_id"),
                "stam_id": d["props"].get("stam_id"),
            }
            for k, d in store.nodes.get("articles", {}).items()
            if d["props"].get("bwb_id") in bwb_ids
        )

    for name, answer in (
        ("article_versions", article_versions),
        ("article_identities", article_identities),
        ("toestand_starts", lambda store, bwb_ids: {}),
        ("instrument_dates", lambda store, keys: iter(())),
        ("update_abbreviations", lambda store, rows: 0),
        ("update_instrument_abbreviations", lambda store, rows: 0),
        ("series_inputs", lambda store: []),
        ("update_instrument_series", lambda store, rows: 0),
    ):
        monkeypatch.setattr(normalize_bwb, name, recorded(name, answer))
