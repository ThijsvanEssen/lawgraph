"""The freshness watch (``deploy/server/bin/freshness-watch.sh``, daily): how far each source is
behind, by what ``/api/stats`` (``data_as_of``) and ``/api/stats/coverage`` already say, against
the limits of ``deploy/server/freshness.json``. No database and no source is touched here: the
rules, the two answers and the state of the last run go in, the lines to alert come out.

    python -m lawgraph.freshness --rules R --stats S [--coverage C] --state T

A rule has a ``kind``, a ``warn`` and an ``alert`` limit, and (but ``courts``) a ``unit``: ``days``,
``workdays`` (Monday to Friday only) or ``hours``.

    stats    a measure (``newest``, ``retrieved_at``, ``as_of`` or ``commitments_registered``) of a
             ``source`` in ``data_as_of``; named by its ``id`` when there is one, else its source
    tier     the last date of a ``tier`` of the coverage
    courts   how many courts of the ``tiers`` with at least ``min_count`` judgments are behind
             ``stale_days`` (and not ended: a last judgment within ``active_days``)

``states`` is the rule for the state a source's last run recorded. A line is made when a subject
gets worse, and again after ``repeat_hours`` while it stays so; ``hersteld`` when it is back. A
subject whose input is missing (no coverage answer) keeps what the last run recorded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OK, WARN, ALERT = "ok", "waarschuwing", "achterstand"
_RANK = {OK: 0, WARN: 1, ALERT: 2}
_UNIT_LABEL = {"days": "d", "workdays": "wd", "hours": "u"}


@dataclass(frozen=True, slots=True)
class Finding:
    """One subject's level, and the part of its line after the outcome."""

    subject: str
    level: str
    detail: str = ""


def parse_time(value: str) -> dt.datetime:
    """A date or an ISO timestamp (``Z`` or an offset) as an aware UTC moment."""
    if len(value) == 10:
        return dt.datetime.fromisoformat(value).replace(tzinfo=dt.UTC)
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def workdays_between(since: dt.date, until: dt.date) -> int:
    """The Mondays to Fridays after *since* up to and including *until*."""
    days = (until - since).days
    return sum((since + dt.timedelta(days=n)).weekday() < 5 for n in range(1, days + 1))


def lag(unit: str, since: dt.datetime, now: dt.datetime) -> int:
    """How far *since* is behind *now*, in whole *unit*s (days by the calendar date)."""
    if unit == "hours":
        return int((now - since).total_seconds() // 3600)
    if unit == "workdays":
        return workdays_between(since.date(), now.date())
    return (now.date() - since.date()).days


def level_of(value: float, rule: Mapping[str, Any]) -> str:
    if value > rule["alert"]:
        return ALERT
    return WARN if value > rule["warn"] else OK


def _behind(
    subject: str, rule: Mapping[str, Any], since: str | None, now: dt.datetime
) -> Finding:
    """The finding of a rule about one moment; a source without one is as bad as it gets."""
    if not since:
        return Finding(subject, ALERT, "geen datum")
    unit = rule["unit"]
    found = lag(unit, parse_time(since), now)
    level = level_of(found, rule)
    label = _UNIT_LABEL[unit]
    limit = rule["alert"] if level == ALERT else rule["warn"]
    return Finding(subject, level, f"{found} {label} > {limit} {label}")


def _stats_rule(
    rule: Mapping[str, Any], stats: Mapping[str, Any], now: dt.datetime
) -> Finding:
    source = rule["source"]
    entry = stats.get(source) or {}
    measure = rule["measure"]
    if measure == "as_of":
        since = ((entry.get("completeness") or {}).get("source") or {}).get("as_of")
    else:
        since = entry.get(measure)
    return _behind(rule.get("id", source), rule, since, now)


def _tier_rule(
    rule: Mapping[str, Any], coverage: Mapping[str, Any], now: dt.datetime
) -> Finding:
    rows = [r for r in coverage.get("tiers", []) if r.get("tier") == rule["tier"]]
    return _behind(rule["tier"], rule, rows[0].get("last_date") if rows else None, now)


def _courts_rule(
    rule: Mapping[str, Any], coverage: Mapping[str, Any], now: dt.datetime
) -> Finding:
    """The courts of the tiers that carry volume and are behind: their last judgment is older than
    ``stale_days`` but not older than ``active_days`` (a court past that has ended: the courts
    of before the reorganisation of 2013 stop in 2012)."""
    subject = rule.get("id", "+".join(rule["tiers"]))
    stale = [
        row["court_code"]
        for row in coverage.get("courts", [])
        if row.get("tier") in rule["tiers"]
        and row.get("count", 0) >= rule["min_count"]
        and row.get("last_date")
        and rule["stale_days"]
        < lag("days", parse_time(row["last_date"]), now)
        <= rule["active_days"]
    ]
    level = level_of(len(stale), rule)
    if level == OK:
        return Finding(subject, OK)
    limit = rule["alert"] if level == ALERT else rule["warn"]
    return Finding(
        subject, level, f"{len(stale)} gerechten > {limit} ({rule['stale_days']} d)"
    )


def _state_rules(
    rule: Mapping[str, Any], stats: Mapping[str, Any], now: dt.datetime
) -> Iterable[Finding]:
    """A source whose last run did not end ``done`` (a ``paused`` one only when not listed in
    ``paused_ok``): a warning, an alert once it has been so for ``alert_after_hours``."""
    for source, entry in sorted(stats.items()):
        recorded = (entry.get("completeness") or {}).get("source") or {}
        state = recorded.get("state")
        subject = f"{source} status"
        if state == "done" or (state == "paused" and source in rule["paused_ok"]):
            yield Finding(subject, OK)
            continue
        as_of = recorded.get("as_of")
        long = (
            not as_of
            or lag("hours", parse_time(as_of), now) > rule["alert_after_hours"]
        )
        yield Finding(subject, ALERT if long else WARN, str(state))


def evaluate(
    rules: Mapping[str, Any],
    stats: Mapping[str, Any],
    coverage: Mapping[str, Any] | None,
    now: dt.datetime,
) -> list[Finding]:
    """Every subject's finding. Rules about the coverage are skipped without an answer of it."""
    findings: list[Finding] = []
    for rule in rules["rules"]:
        kind = rule["kind"]
        if kind == "stats":
            findings.append(_stats_rule(rule, stats, now))
        elif coverage is not None:
            check = _tier_rule if kind == "tier" else _courts_rule
            findings.append(check(rule, coverage, now))
    if "states" in rules:
        findings.extend(_state_rules(rules["states"], stats, now))
    return findings


def _line(finding: Finding) -> str:
    return f"Versheid {finding.subject}: {finding.level}, {finding.detail} [actie]"


def decide(
    findings: Sequence[Finding],
    previous: Mapping[str, Mapping[str, str]],
    now: dt.datetime,
    repeat_hours: int = 24,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """The lines to alert and the state to keep: a subject says something when it is worse than
    the last time it was seen, or has said nothing for *repeat_hours* while it stays bad, and
    ``hersteld`` when it was bad and is not."""
    lines: list[str] = []
    state = {key: dict(value) for key, value in previous.items()}
    for finding in findings:
        before = state.get(finding.subject)
        if finding.level == OK:
            if before:
                lines.append(f"Versheid {finding.subject}: hersteld")
                del state[finding.subject]
            continue
        sent = before["sent_at"] if before else None
        worse = before is None or _RANK[finding.level] > _RANK[before["level"]]
        quiet = (
            sent is None
            or (now - parse_time(sent)).total_seconds() >= repeat_hours * 3600
        )
        if worse or quiet:
            lines.append(_line(finding))
            sent = now.isoformat()
        state[finding.subject] = {"level": finding.level, "sent_at": str(sent)}
    return lines, state


def _read(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--rules", required=True)
    parser.add_argument("--stats", required=True, help="the answer of /api/stats")
    parser.add_argument(
        "--coverage",
        help="the answer of /api/stats/coverage; none: its rules are skipped",
    )
    parser.add_argument(
        "--state", required=True, help="kept between runs; read when it is there"
    )
    parser.add_argument("--now", help="an ISO timestamp instead of the clock (tests)")
    args = parser.parse_args(argv)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.UTC)
    rules = _read(args.rules)
    coverage = _read(args.coverage) if args.coverage else None
    findings = evaluate(rules, _read(args.stats)["data_as_of"], coverage, now)
    state_file = Path(args.state)
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    lines, state = decide(findings, previous, now, rules.get("repeat_hours", 24))
    for finding in findings:
        if finding.level != OK:
            print(
                f"{finding.subject}: {finding.level} {finding.detail}", file=sys.stderr
            )
    state_file.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
