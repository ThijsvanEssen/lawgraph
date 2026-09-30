"""`retrieve tk-dossiers --dossier-number N`: the backfill of one dossier."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from tests.fakes import RawSourcesFake


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

    def query(self, aql: str, bind_vars: dict | None = None, **_: Any) -> list[Any]:
        return []

    def insert_raw_source(
        self, *, kind: str, external_id: str | None = None, **_: Any
    ) -> None:
        self.stored.append((kind, external_id or ""))


class _Client:
    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def fetch_dossiers(self, since: Any = None, number: int | None = None) -> Any:
        self.asked.append(("dossiers", {"since": since, "number": number}))
        return iter([{"Id": "dossier-35786", "Nummer": 35786}])

    def fetch_documents(
        self, since: Any = None, dossier_number: int | None = None
    ) -> Any:
        self.asked.append(("documents", {"since": since, "number": dossier_number}))
        return iter([{"Id": "doc-1"}, {"Id": "doc-2"}])

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"a backfill of one dossier asks for no {name}")


def test_the_backfill_of_a_dossier_stores_the_dossier_and_its_documents() -> None:
    """Without the dossier its documents are part of nothing, and no law is legislated in it."""
    store, client = _Store(), _Client()
    result = TKDossiersRetrievePipeline(store=store, client=client).run(  # type: ignore[arg-type]
        dossier_number=35786
    )
    assert result.errors == []
    assert client.asked == [
        ("dossiers", {"since": None, "number": 35786}),
        ("documents", {"since": None, "number": 35786}),
    ]
    assert store.stored == [
        ("tk-dossier", "dossier-35786"),
        ("tk-document", "doc-1"),
        ("tk-document", "doc-2"),
    ]


class _SomeUnknown(_Client):
    def fetch_dossiers(self, since: Any = None, number: int | None = None) -> Any:
        self.asked.append(("dossiers", {"since": since, "number": number}))
        return iter([] if number == 19952 else [{"Id": f"dossier-{number}"}])


def test_the_gaps_are_fetched_and_an_unknown_number_is_remembered() -> None:
    store, client = _Store(), _SomeUnknown()
    result = TKDossiersRetrievePipeline(store=store, client=client).run_gaps(  # type: ignore[arg-type]
        ["19952", "35790"]
    )
    assert result.errors == []
    assert store.stored == [
        ("tk-dossier-missing", "19952"),  # asked again once it is due
        ("tk-dossier", "dossier-35790"),
        ("tk-document", "doc-1"),
        ("tk-document", "doc-2"),
    ]
