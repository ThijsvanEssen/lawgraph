"""Pieces shared by the fake stores of the tests."""

from __future__ import annotations

from typing import Any


class RawSourcesFake:
    """``insert_raw_sources`` of the store, on top of the ``insert_raw_source`` of a fake.

    The fake sees one call per record, with the fields of the record; a call that raises is
    a document the server refused.
    """

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
