"""Pieces shared by the fake stores of the tests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


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
    """A store as ``pipelines/watermark`` sees it: the ``pipeline_state`` collection."""

    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> PipelineStateFake:
        assert name == "pipeline_state"
        return self

    def get(self, key: str) -> dict[str, Any] | None:
        return self.state.get(key)

    def insert(self, doc: dict[str, Any], overwrite: bool = False) -> None:
        assert overwrite
        self.state[doc["_key"]] = doc
