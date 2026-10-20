"""``retrieve <source> --mode gaps`` fetches what the gap query of that source answers."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.case_numbers import Referral
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import retrieve_commands
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.sources.registry import find
from tests.asserts import show_items


def _retrieve(name: str, argv: list[str]) -> PipelineResult:
    pipeline = find("retrieve", name)
    assert pipeline is not None
    return pipeline.command(argv)


@pytest.fixture
def ran(monkeypatch) -> dict[str, Any]:
    """The arguments each retrieve pipeline was run with; no store, no network."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(retrieve_commands, "GraphStore", lambda: object())
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

    def bwb_gaps(store: object, min_stubs: int) -> list[str]:
        asked.append(min_stubs)
        return ["BWBR1"]

    monkeypatch.setattr(_gaps, "bwb_gaps", bwb_gaps)
    _retrieve("bwb", ["--mode", "gaps", "--min-stubs", "5"])
    assert asked == [5] and ran["BWB"] == {"bwb_ids": ["BWBR1"]}


def test_rechtspraak_fetches_the_cited_judgments_of_any_court(monkeypatch, ran) -> None:
    referral = Referral(case_numbers=("8527084 VZ VERZ 20-9656",), date="2021-01-15")
    monkeypatch.setattr(
        _gaps, "rechtspraak_gaps", lambda store: ["ECLI:NL:RBAMS:2020:1"]
    )
    monkeypatch.setattr(_gaps, "unanswered_referrals", lambda store: [referral])
    _retrieve("rechtspraak", ["--mode", "gaps"])
    assert ran["Rechtspraak"] == {
        "courts": [],
        "eclis": ["ECLI:NL:RBAMS:2020:1"],
        "referrals": [referral],
    }


def test_eurlex_and_echr_fetch_what_is_named(monkeypatch, ran) -> None:
    monkeypatch.setattr(_gaps, "eurlex_gaps", lambda store: ["32016R0679"])
    monkeypatch.setattr(_gaps, "echr_gaps", lambda store: ["ECLI:CE:ECHR:2020:1"])
    _retrieve("eurlex", ["--mode", "gaps"])
    _retrieve("echr", ["--mode", "gaps"])
    assert ran["Eurlex"]["celex_ids"] == ["32016R0679"]
    assert ran["ECHR"] == {"eclis": ["ECLI:CE:ECHR:2020:1"]}


def test_the_treaty_register_is_read_again_only_when_a_treaty_is_missing(
    monkeypatch, ran
) -> None:
    monkeypatch.setattr(_gaps, "verdragenbank_gaps", lambda store: [])
    assert _retrieve("verdragenbank", ["--mode", "gaps"]).created == 0
    assert "Verdragenbank" not in ran

    monkeypatch.setattr(_gaps, "verdragenbank_gaps", lambda store: ["trb-1"])
    _retrieve("verdragenbank", ["--mode", "gaps"])
    assert "Verdragenbank" in ran


def test_a_gaps_run_says_when_it_takes_only_the_first_stubs(caplog) -> None:
    rows = [f"ECLI:{n}" for n in range(_gaps.MAX_GAPS_PER_RUN + 5)]
    with caplog.at_level("WARNING"):
        taken = _gaps.Gaps.capped(rows, "stub judgments")
    assert len(taken) == _gaps.MAX_GAPS_PER_RUN
    assert any(
        "takes the first" in m and "stub judgments" in m for m in caplog.messages
    ), show_items(caplog.messages)


def test_below_the_cap_nothing_is_said(caplog) -> None:
    with caplog.at_level("WARNING"):
        assert _gaps.Gaps.capped(["a", "b"], "x") == ["a", "b"]
    assert not caplog.messages
