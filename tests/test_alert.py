"""``lawgraph.alert``: the alert of a run in its fixed form, from the record its script kept.

<run> <step>: <outcome>, <cause> [<follow-up>]
"""

from __future__ import annotations

import re

import pytest

from lawgraph import alert
from lawgraph.pipelines.command import KNOWN_FAILURES
from tests.paths import ROOT


def _record(*lines: tuple[str, str, str]) -> str:
    return "".join("\t".join(line) + "\n" for line in lines)


@pytest.mark.parametrize(
    ("run", "record", "said"),
    [
        (
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph check --skip-edges",
                    "DatabaseUnavailable: Cannot connect to PostgreSQL at localhost:5432 "
                    "(db=lawgraph): refused (Writing a batch of 9 edges failed; it stays "
                    "queued.)",
                )
            ),
            "Dag check: mislukt, db-weg [herhaalt]",
        ),
        (
            # a step of a parent: the step that failed is named, not the parent
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph semantic all --since last",
                    "semantic tk-government failed: KeyError: 'ministry' (and 3 more)",
                )
            ),
            "Dag semantic tk-government: mislukt, onverwacht KeyError 'ministry' [actie]",
        ),
        (
            ["poll", "echr"],
            _record(
                (
                    "unavailable",
                    "lawgraph poll echr --since 1d",
                    "retrieve echr: the source is unavailable (HTTP 403) after 0 records "
                    "were stored: HTTPError: 403 Forbidden",
                )
            ),
            "Poll echr retrieve echr: bron-weg, http-403 [herhaalt]",
        ),
        (
            ["poll", "tk"],
            _record(("held", "", "")),
            "Poll tk: 3x overgeslagen, lock-bezet [actie]",
        ),
        (
            ["weekly"],
            _record(
                ("skipped", "lawgraph check", ""),
                ("skipped", "lawgraph search-candidates", ""),
            ),
            "Week check +1: overgeslagen, lock-bezet [herhaalt]",
        ),
        (
            ["night", "relink-citations"],
            _record(
                (
                    "failed",
                    "lawgraph semantic rechtspraak-citations --after x --limit 150000",
                    "StoreUnavailable: 12 raw records could not be written: timeout",
                )
            ),
            "Nacht relink-citations semantic rechtspraak-citations: mislukt, "
            "db-weigert [actie]",
        ),
        (
            # a failed download names its cause, not the exception or the URL
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph retrieve all --since 1d",
                    "retrieve tk-content failed: 3 x download failed (geen PDF) "
                    "(first: kst-36867-3)",
                )
            ),
            "Dag retrieve tk-content: mislukt, download geen-pdf [herhaalt]",
        ),
        (
            ["daily"],
            _record(("failed", "lawgraph sitemaps", "exit code 137")),
            "Dag sitemaps: mislukt, exit-137 [actie]",
        ),
        (
            # a failure that does not pass by itself asks for action in any run
            ["poll", "rechtspraak"],
            _record(
                (
                    "failed",
                    "lawgraph poll rechtspraak --since 6h",
                    "normalize rechtspraak failed: SchemaOutdated: the tables are not "
                    "those of the schema: run `lawgraph check`",
                )
            ),
            "Poll rechtspraak normalize rechtspraak: mislukt, schema [actie]",
        ),
        (
            ["weekly"],
            _record(("stuck", "lawgraph semantic rechtspraak", "no progress after k1")),
            "Week semantic rechtspraak: vast, geen-voortgang [actie]",
        ),
        (
            # a statement that waited past lock_timeout: another holds the lock
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph normalize bwb --since last",
                    "LockNotGranted: writing statements together waited past "
                    "lock_timeout for a lock another session holds",
                )
            ),
            "Dag normalize bwb: mislukt, lock-bezet [herhaalt]",
        ),
        (
            # an ops script goes on past a source that was away; nothing tries it again
            ["ops", "ek-seats-steps"],
            _record(
                ("unavailable", "lawgraph retrieve kiesraad", "a challenge page: x")
            ),
            "Ops ek-seats-steps retrieve kiesraad: bron-weg, challenge [actie]",
        ),
    ],
)
def test_an_alert_has_the_fixed_form(run: list[str], record: str, said: str) -> None:
    assert alert.told(run, record) == said


def test_steps_that_failed_alike_are_told_once() -> None:
    """The database down fails every step of the night: one cause, the steps counted."""
    why = "DatabaseUnavailable: Cannot connect to PostgreSQL"
    record = _record(
        ("failed", "lawgraph retrieve all --since last", f"retrieve tk failed: {why}"),
        ("failed", "lawgraph normalize all --since last", why),
        ("failed", "lawgraph feed-events", why),
        ("failed", "lawgraph sitemaps", "exit code 1"),
    )
    assert alert.told(["daily"], record) == (
        "Dag retrieve tk +2: mislukt, db-weg [herhaalt]; "
        "Dag sitemaps: mislukt, exit-1 [actie]"
    )


def test_an_unexpected_message_is_cut_at_60() -> None:
    message = "column x does not exist " + "word " * 80
    said = alert.told(
        ["daily"], _record(("failed", "lawgraph check", f"ProgrammingError: {message}"))
    )
    assert said == (
        f"Dag check: mislukt, onverwacht ProgrammingError {message[:60].rstrip()} [actie]"
    )


def test_a_poll_is_not_named_twice() -> None:
    record = _record(("failed", "lawgraph poll tk --since 4h", "exit code 1"))
    assert alert.told(["poll", "tk"], record) == "Poll tk: mislukt, exit-1 [actie]"


# ── the sets are those of docs/operations.md, "Alerts" ──────────────────────


def _table(heading: str) -> set[str]:
    """The codes in the first column of the table under *heading* in "Alerts"."""
    docs = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    section = docs.split("\n### Alerts\n", 1)[1].split("\n#", 1)[0]
    table = section.split(f"\n{heading}\n\n", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"^\| `([^`]+)` \|", table, re.M))


def test_every_run_is_in_the_docs() -> None:
    assert {*alert.RUNS.values(), "Deploy <versie>"} == _table("Runs:")


def test_every_outcome_is_in_the_docs() -> None:
    assert set(alert.OUTCOMES) == _table("Outcomes:")


def test_every_cause_is_in_the_docs() -> None:
    known = {failure.code for failure in KNOWN_FAILURES.values()}
    assert len(known) == len(KNOWN_FAILURES)
    assert known | set(alert.CAUSES) == _table("Causes:")


def test_every_follow_up_is_in_the_docs() -> None:
    assert set(alert.FOLLOW_UPS) == _table("Follow-ups:")


def test_the_deploy_alerts_have_the_form_and_the_codes_of_the_tables() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    said = re.findall(
        r'alert "Deploy \$\{?\w+\}?: ([\w-]+), ([\w-]+) \[(\w+)\]"', workflow
    )
    assert len(said) == 4
    known = {failure.code for failure in KNOWN_FAILURES.values()}
    for outcome, cause, follow_up in said:
        assert outcome in alert.OUTCOMES
        assert cause in {*alert.CAUSES, *known}
        assert follow_up in alert.FOLLOW_UPS
