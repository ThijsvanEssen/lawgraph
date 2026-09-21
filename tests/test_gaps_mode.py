"""``retrieve <source> --mode gaps`` fetches what the gap query of that source answers."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import retrieve_commands
from lawgraph.pipelines.retrieve import _gaps


@pytest.fixture
def ran(monkeypatch) -> dict[str, Any]:
    """The arguments each retrieve pipeline was run with; no store, no network."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(retrieve_commands, "ArangoStore", lambda: object())
    for name in ("BWB", "Rechtspraak", "Eurlex", "ECHR", "Verdragenbank"):
        cls = getattr(retrieve_commands, f"{name}RetrievePipeline")

        def run(self, _name=name, **kwargs):
            seen[_name] = kwargs
            return PipelineResult(created=1)

        monkeypatch.setattr(cls, "__init__", lambda self, *a, **k: None)
        monkeypatch.setattr(cls, "run", run)
    return seen


def test_bwb_fetches_the_laws_with_enough_referred_articles(monkeypatch, ran) -> None:
    asked: list[int] = []
    monkeypatch.setattr(
        _gaps, "bwb_gaps", lambda store, min_stubs: asked.append(min_stubs) or ["BWBR1"]
    )
    retrieve_commands.retrieve_bwb(["--mode", "gaps", "--min-stubs", "5"])
    assert asked == [5] and ran["BWB"] == {"bwb_ids": ["BWBR1"]}


def test_rechtspraak_fetches_the_cited_judgments_of_any_court(monkeypatch, ran) -> None:
    monkeypatch.setattr(
        _gaps, "rechtspraak_gaps", lambda store: ["ECLI:NL:RBAMS:2020:1"]
    )
    retrieve_commands.retrieve_rechtspraak(["--mode", "gaps"])
    assert ran["Rechtspraak"] == {"courts": [], "eclis": ["ECLI:NL:RBAMS:2020:1"]}


def test_eurlex_and_echr_fetch_what_is_named(monkeypatch, ran) -> None:
    monkeypatch.setattr(_gaps, "eurlex_gaps", lambda store: ["32016R0679"])
    monkeypatch.setattr(_gaps, "echr_gaps", lambda store: ["ECLI:CE:ECHR:2020:1"])
    retrieve_commands.retrieve_eurlex(["--mode", "gaps"])
    retrieve_commands.retrieve_echr(["--mode", "gaps"])
    assert ran["Eurlex"]["celex_ids"] == ["32016R0679"]
    assert ran["ECHR"] == {"eclis": ["ECLI:CE:ECHR:2020:1"]}


def test_the_treaty_register_is_read_again_only_when_a_treaty_is_missing(
    monkeypatch, ran
) -> None:
    monkeypatch.setattr(_gaps, "verdragenbank_gaps", lambda store: [])
    assert retrieve_commands.retrieve_verdragenbank(["--mode", "gaps"]).created == 0
    assert "Verdragenbank" not in ran

    monkeypatch.setattr(_gaps, "verdragenbank_gaps", lambda store: ["trb-1"])
    retrieve_commands.retrieve_verdragenbank(["--mode", "gaps"])
    assert "Verdragenbank" in ran
