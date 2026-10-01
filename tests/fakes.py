"""Pieces shared by the fake stores of the tests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import pytest

from lawgraph.db.queries import state as state_queries


class RawSourcesFake:
    """``insert_raw_sources`` of the store, on top of the ``insert_raw_source`` of a fake.

    The fake sees one call per record, with the fields of the record; a call that raises is
    a document the server refused. A fake keeps a record's text payload on the record, so
    ``with_payloads`` passes the records on as they are.
    """

    def with_payloads(
        self, records: Iterable[dict[str, Any]], **_: Any
    ) -> Iterator[dict[str, Any]]:
        return iter(records)

    def insert_raw_sources(
        self, docs: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        failures = []
        for doc in docs:
            fields = {k: v for k, v in doc.items() if k not in ("_key", "fetched_at")}
            try:
                self.insert_raw_source(**fields)  # type: ignore[attr-defined]
            except Exception as exc:
                failures.append((doc, str(exc)))
        return failures


class ExistingKeysFake:
    """``existing_keys`` of the store, on top of the ``get_node`` of a fake."""

    def existing_keys(self, collection: str, keys: Any) -> set[str]:
        return {
            key
            for key in set(keys)
            if self.get_node(collection, key) is not None  # type: ignore[attr-defined]
        }


class FakeResponse:
    """What a client reads of a ``requests.Response``: the body as text and as bytes."""

    def __init__(self, text: str, content_type: str = "text/xml") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status_code = 200


class PipelineStateFake:
    """A store as ``pipelines/watermark`` sees it: until when each phase is covered, in
    ``state`` (phase -> moment). ``patch_pipeline_state`` points the state queries at it."""

    def __init__(self) -> None:
        self.state: dict[str, str] = {}

    def vacuum_analyze(self) -> None:
        """What the phases after retrieve ask of the database when they are done."""


def patch_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of ``db/queries/state.py``, answered from a ``PipelineStateFake``."""

    def covered_until(store: PipelineStateFake, phase: str) -> str | None:
        return store.state.get(phase)

    def set_covered_until(store: PipelineStateFake, phase: str, began_iso: str) -> None:
        store.state[phase] = began_iso

    monkeypatch.setattr(state_queries, "covered_until", covered_until)
    monkeypatch.setattr(state_queries, "set_covered_until", set_covered_until)
