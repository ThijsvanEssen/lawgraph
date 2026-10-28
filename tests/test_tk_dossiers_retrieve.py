"""`retrieve tk-dossiers --dossier-number N`: the backfill of one dossier."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

import pytest
import requests

from lawgraph.clients.tk import TKClient
from lawgraph.pipelines.retrieve.tk_dossiers import (
    DOCUMENT_CASE_KINDS,
    TKDossiersRetrievePipeline,
)
from tests.asserts import show_items
from tests.fakes import (
    InMemoryStore,
    external_ids,
)


def _stored(store: InMemoryStore) -> list[tuple[str, str]]:
    return [(doc["kind"], doc["external_id"]) for doc in store.raw.values()]


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
    store, client = InMemoryStore(), _Client()
    result = TKDossiersRetrievePipeline(store=store, client=cast(TKClient, client)).run(
        dossier_number=35786
    )
    assert result.errors == []
    assert client.asked == [
        ("dossiers", {"since": None, "number": 35786}),
        ("documents", {"since": None, "number": 35786}),
    ]
    assert _stored(store) == [
        ("tk-dossier", "dossier-35786"),
        ("tk-document", "doc-1"),
        ("tk-document", "doc-2"),
    ]


class _SomeUnknown(_Client):
    def fetch_dossiers(self, since: Any = None, number: int | None = None) -> Any:
        self.asked.append(("dossiers", {"since": since, "number": number}))
        return iter([] if number == 19952 else [{"Id": f"dossier-{number}"}])


def test_the_gaps_are_fetched_and_an_unknown_number_is_remembered() -> None:
    store, client = InMemoryStore(), _SomeUnknown()
    result = TKDossiersRetrievePipeline(
        store=store, client=cast(TKClient, client)
    ).run_gaps(["19952", "35790"])
    assert result.errors == []
    assert _stored(store) == [
        ("tk-dossier-missing", "19952"),  # asked again once it is due
        ("tk-dossier", "dossier-35790"),
        ("tk-document", "doc-1"),
        ("tk-document", "doc-2"),
    ]


class _Decisions:
    """A client that answers every fetch with nothing and records the Besluit fetches."""

    def __init__(self) -> None:
        self.decisions: list[tuple[tuple[str, ...], bool]] = []
        self.untils: list[Any] = []

    def fetch_bill_decisions(
        self,
        case_kinds: tuple[str, ...],
        since: Any = None,
        without_votes: bool = False,
        until: Any = None,
    ) -> Any:
        self.untils.append(until)
        self.decisions.append((tuple(case_kinds), without_votes))
        return iter([{"Id": f"besluit-{len(self.decisions)}"}])

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: iter([])


def test_a_window_also_fetches_the_decisions_without_a_vote_on_papers() -> None:
    store, client = InMemoryStore(), _Decisions()
    TKDossiersRetrievePipeline(store=store, client=cast(TKClient, client)).run(
        skip_members=True
    )
    assert ((*DOCUMENT_CASE_KINDS,), True) in client.decisions
    assert DOCUMENT_CASE_KINDS == ("Amendement", "Motie")


def test_the_backfill_of_the_decisions_without_a_vote_fetches_those_alone() -> None:
    """``retrieve tk-dossiers --mode unvoted``: about 25,000 Besluiten, not a whole window."""
    store, client = InMemoryStore(), _Decisions()
    result = TKDossiersRetrievePipeline(
        store=store, client=cast(TKClient, client)
    ).run_unvoted()
    assert result.errors == []
    assert client.decisions == [(("Amendement", "Motie"), True)]
    assert _stored(store) == [("tk-besluit", "besluit-1")]


def test_until_closes_the_window_of_every_decision_fetch() -> None:
    until = dt.datetime(2016, 1, 1, tzinfo=dt.UTC)
    client = _Decisions()
    TKDossiersRetrievePipeline(
        store=InMemoryStore(), client=cast(TKClient, client)
    ).run(since=dt.datetime(2015, 1, 1, tzinfo=dt.UTC), until=until, skip_members=True)
    assert client.untils == [until, until]


class _DossierClient:
    def fetch_dossiers(self, since=None, until=None):
        return iter([{"Id": "d1"}, {"Id": "d2"}])

    def fetch_activiteiten(self, since=None, until=None):
        yield {"Id": "a1"}
        raise requests.ConnectionError("dropped")

    def __getattr__(self, name):
        return lambda *a, **k: iter([])


@pytest.mark.usefixtures("raw_reads")
def test_tk_dossiers_keep_what_was_stored_when_one_entity_fails() -> None:
    store = InMemoryStore()
    result = TKDossiersRetrievePipeline(
        store=store, client=cast(TKClient, _DossierClient())
    ).run(since=dt.datetime(2024, 1, 1), skip_members=True)
    assert external_ids(store)[:3] == [
        "d1",
        "d2",
        "a1",
    ]  # the activity before the crash is kept
    assert any("Activiteit" in e or "tk-activiteit" in e for e in result.errors), (
        show_items(result.errors)
    )
