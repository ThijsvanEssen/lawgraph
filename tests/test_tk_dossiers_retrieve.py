"""`retrieve tk-dossiers --dossier-number N`: the backfill of one dossier."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.retrieve.tk_dossiers import (
    PAPER_DECISION_KINDS,
    TKDossiersRetrievePipeline,
)
from tests.fakes import RawSourcesFake


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

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


class _Decisions:
    """A client that answers every fetch with nothing and records the Besluit fetches."""

    def __init__(self) -> None:
        self.decisions: list[tuple[tuple[str, ...], bool]] = []

    def fetch_bill_decisions(
        self,
        case_kinds: tuple[str, ...],
        since: Any = None,
        without_votes: bool = False,
    ) -> Any:
        self.decisions.append((tuple(case_kinds), without_votes))
        return iter([{"Id": f"besluit-{len(self.decisions)}"}])

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: iter([])


def test_a_window_also_fetches_the_decisions_without_a_vote_on_papers() -> None:
    store, client = _Store(), _Decisions()
    TKDossiersRetrievePipeline(store=store, client=client).run(skip_members=True)  # type: ignore[arg-type]
    assert ((*PAPER_DECISION_KINDS,), True) in client.decisions
    assert PAPER_DECISION_KINDS == ("Amendement", "Motie")


def test_the_backfill_of_the_decisions_without_a_vote_fetches_those_alone() -> None:
    """``retrieve tk-dossiers --mode unvoted``: about 25,000 Besluiten, not a whole window."""
    store, client = _Store(), _Decisions()
    result = TKDossiersRetrievePipeline(store=store, client=client).run_unvoted()  # type: ignore[arg-type]
    assert result.errors == []
    assert client.decisions == [(("Amendement", "Motie"), True)]
    assert store.stored == [("tk-besluit", "besluit-1")]
