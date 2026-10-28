"""``lawgraph.freshness``: the limits of the freshness watch and what it says, no database."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph import freshness as fresh
from lawgraph.freshness import ALERT, OK, WARN, Finding
from tests.paths import ROOT

RULES: dict[str, Any] = json.loads(
    (ROOT / "deploy" / "server" / "freshness.json").read_text(encoding="utf-8")
)
WEDNESDAY = dt.datetime(2026, 10, 28, 9, 30, tzinfo=dt.UTC)
MONDAY = dt.datetime(2026, 10, 26, 9, 30, tzinfo=dt.UTC)


def _source(
    newest: str | None = None,
    retrieved: str | None = None,
    as_of: str | None = None,
    state: str = "done",
) -> dict[str, Any]:
    return {
        "newest": newest,
        "retrieved_at": retrieved,
        "completeness": {"source": {"state": state, "as_of": as_of}},
    }


def _level(findings: list[Finding], subject: str) -> str:
    return next(f.level for f in findings if f.subject == subject)


def _stats(**overrides: dict[str, Any]) -> dict[str, Any]:
    """Every source of the rules as fresh as can be, except the ones given."""
    fine = "2026-10-28T01:00:00Z"
    stats = {
        s["source"]: _source("2026-10-28", fine, fine)
        for s in RULES["rules"]
        if s["kind"] == "stats"
    }
    return {**stats, **overrides}


COVERAGE: dict[str, Any] = {
    "tiers": [
        {"tier": t["tier"], "last_date": "2026-10-27"}
        for t in RULES["rules"]
        if t["kind"] == "tier"
    ],
    "courts": [],
}


def test_the_state_of_the_day_is_fine() -> None:
    findings = fresh.evaluate(RULES, _stats(), COVERAGE, WEDNESDAY)
    assert {f.level for f in findings} == {OK}


def test_the_weekend_is_not_a_lag_for_a_source_that_publishes_on_workdays() -> None:
    friday = _stats(tk=_source("2026-10-23"))
    on_monday = fresh.evaluate(RULES, friday, COVERAGE, MONDAY)
    assert _level(on_monday, "tk") == OK
    assert fresh.workdays_between(dt.date(2026, 10, 23), MONDAY.date()) == 1
    # the same lag in days is more than a week for tk on a Wednesday of the week after
    late = fresh.evaluate(RULES, _stats(tk=_source("2026-10-16")), COVERAGE, WEDNESDAY)
    assert _level(late, "tk") == ALERT


@pytest.mark.parametrize(
    ("newest", "level"),
    [
        ("2026-10-22", OK),  # 4 workdays: on the limit is not past it
        ("2026-10-21", WARN),  # 5
        ("2026-10-14", WARN),  # 10
        ("2026-10-13", ALERT),  # 11
    ],
)
def test_staatscourant_limits(newest: str, level: str) -> None:
    findings = fresh.evaluate(
        RULES, _stats(staatscourant=_source(newest)), COVERAGE, WEDNESDAY
    )
    assert _level(findings, "staatscourant") == level


def test_staatscourant_of_a_week_ago_warns_today() -> None:
    findings = fresh.evaluate(
        RULES, _stats(staatscourant=_source("2026-10-21")), COVERAGE, WEDNESDAY
    )
    found = next(f for f in findings if f.subject == "staatscourant")
    assert (found.level, found.detail) == (WARN, "5 wd > 4 wd")


def test_the_parket_of_43_days_alerts_today() -> None:
    coverage = {
        **COVERAGE,
        "tiers": [
            {"tier": "parket", "last_date": "2026-09-15"},
            *[t for t in COVERAGE["tiers"] if t["tier"] != "parket"],
        ],
    }
    findings = fresh.evaluate(RULES, _stats(), coverage, WEDNESDAY)
    found = next(f for f in findings if f.subject == "parket")
    assert (found.level, found.detail) == (ALERT, "43 d > 30 d")


def test_a_source_without_a_date_is_an_alert() -> None:
    findings = fresh.evaluate(
        RULES, _stats(bwb=_source(retrieved=None)), COVERAGE, WEDNESDAY
    )
    assert _level(findings, "bwb") == ALERT


def test_hours_count_from_the_moment_not_the_date() -> None:
    old = _stats(tooi=_source(as_of="2026-10-26T20:00:00Z"))  # 37.5 hours before
    assert _level(fresh.evaluate(RULES, old, COVERAGE, WEDNESDAY), "tooi") == WARN
    older = _stats(tooi=_source(as_of="2026-10-25T08:00:00Z"))  # 72.5
    assert _level(fresh.evaluate(RULES, older, COVERAGE, WEDNESDAY), "tooi") == ALERT


def test_the_courts_that_have_ended_do_not_count() -> None:
    rule = next(r for r in RULES["rules"] if r["kind"] == "courts")
    row = {"tier": "rechtbank", "count": 5000}
    courts = [
        {**row, "court_code": "OLD", "last_date": "2012-12-28"},  # ended in 2013
        {**row, "court_code": "SMALL", "count": 10, "last_date": "2026-09-01"},
        {**row, "court_code": "A", "last_date": "2026-10-01"},
        {**row, "court_code": "A2", "last_date": "2026-10-02"},
        {**row, "court_code": "B", "last_date": "2026-10-27"},
    ]
    assert (
        fresh.evaluate({"rules": [rule]}, {}, {"courts": courts}, WEDNESDAY)[0].level
        == WARN
    )
    many = [
        {**row, "court_code": f"C{n}", "last_date": "2026-10-01"}
        for n in range(rule["alert"] + 1)
    ]
    assert (
        fresh.evaluate({"rules": [rule]}, {}, {"courts": many}, WEDNESDAY)[0].level
        == ALERT
    )


def test_the_rules_about_the_coverage_are_skipped_without_it() -> None:
    findings = fresh.evaluate(RULES, _stats(), None, WEDNESDAY)
    assert "parket" not in {f.subject for f in findings}
    assert "tk" in {f.subject for f in findings}


def test_a_state_other_than_done_warns_and_alerts_after_two_days() -> None:
    stats = _stats(
        eurlex=_source(as_of="2026-10-28T01:00:00Z", state="failed"),
        kiesraad=_source(as_of="2026-10-20T01:00:00Z", state="failed"),
        echr=_source(as_of="2026-10-08T01:00:00Z", state="paused"),
        tooi=_source(as_of="2026-10-28T01:00:00Z", state="paused"),
    )
    findings = fresh.evaluate(RULES, stats, COVERAGE, WEDNESDAY)
    assert _level(findings, "eurlex status") == WARN
    assert _level(findings, "kiesraad status") == ALERT
    assert _level(findings, "echr status") == OK  # paused on purpose
    assert _level(findings, "tooi status") == WARN  # paused without being listed


def test_a_subject_says_it_once_and_again_when_worse_or_after_a_day() -> None:
    warn = [Finding("tk", WARN, "5 wd > 4 wd")]
    lines, state = fresh.decide(warn, {}, WEDNESDAY)
    assert lines == ["Versheid tk: waarschuwing, 5 wd > 4 wd [actie]"]
    later = WEDNESDAY + dt.timedelta(hours=23)
    assert fresh.decide(warn, state, later)[0] == []
    worse = [Finding("tk", ALERT, "8 wd > 7 wd")]
    assert fresh.decide(worse, state, later)[0] == [
        "Versheid tk: achterstand, 8 wd > 7 wd [actie]"
    ]
    assert len(fresh.decide(warn, state, WEDNESDAY + dt.timedelta(hours=24))[0]) == 1


def test_a_better_level_is_kept_quiet_and_a_return_to_worse_says_it_again() -> None:
    _, state = fresh.decide([Finding("tk", ALERT, "8 wd > 7 wd")], {}, WEDNESDAY)
    soon = WEDNESDAY + dt.timedelta(hours=1)
    lines, state = fresh.decide([Finding("tk", WARN, "5 wd > 4 wd")], state, soon)
    assert lines == []
    lines, _ = fresh.decide([Finding("tk", ALERT, "8 wd > 7 wd")], state, soon)
    assert len(lines) == 1


def test_a_subject_that_is_back_says_so_once() -> None:
    _, state = fresh.decide([Finding("parket", ALERT, "43 d > 30 d")], {}, WEDNESDAY)
    lines, state = fresh.decide([Finding("parket", OK)], state, WEDNESDAY)
    assert lines == ["Versheid parket: hersteld"]
    assert state == {}
    assert fresh.decide([Finding("parket", OK)], state, WEDNESDAY)[0] == []


def test_a_subject_not_seen_keeps_its_state() -> None:
    _, state = fresh.decide([Finding("parket", ALERT, "43 d > 30 d")], {}, WEDNESDAY)
    assert fresh.decide([], state, WEDNESDAY)[1] == state


def test_the_command_reads_the_files_and_keeps_the_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"rules": RULES, "stats": {"data_as_of": _stats()}, "coverage": COVERAGE}
    for name, content in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(content))
    argv = [f"--{n}={tmp_path / f'{n}.json'}" for n in files] + [
        f"--state={tmp_path / 'state.json'}",
        f"--now={WEDNESDAY.isoformat()}",
    ]
    assert fresh.main(argv) == 0
    assert capsys.readouterr().out.strip() == ""
    assert json.loads((tmp_path / "state.json").read_text()) == {}


def test_every_rule_names_what_it_needs() -> None:
    for rule in RULES["rules"]:
        assert rule["warn"] < rule["alert"]
        assert {"stats": "source", "tier": "tier", "courts": "tiers"}[
            rule["kind"]
        ] in rule
        if rule["kind"] != "courts":
            assert rule["unit"] in {"days", "workdays", "hours"}
    assert RULES["states"]["paused_ok"] == ["echr"]


def test_the_alert_of_the_script_has_the_form_the_watch_says() -> None:
    script = (ROOT / "deploy" / "server" / "bin" / "freshness-watch.sh").read_text()
    assert "lawgraph.freshness" in script
    assert "Versheid watch: mislukt, onverwacht [actie]" in script
