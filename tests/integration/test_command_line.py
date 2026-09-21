"""What a command looks like from outside: its exit code and what it says it did.

These tests run the real ``lawgraph`` process, so they hold whatever the layers inside are
called: 0 when all went well, 1 when something failed, 2 when the command line is wrong.
"""

from __future__ import annotations

import os
from typing import Any

from lawgraph.db import ArangoStore
from tests.integration.seed import seed


def test_a_step_that_went_well_exits_0_and_says_what_it_wrote(
    database: str, cli: Any
) -> None:
    seed(ArangoStore(), documents=5, judgments=3, regulations=1)
    done = cli("normalize", "rechtspraak", check=False)
    assert done.returncode == 0
    assert "[normalize rechtspraak]" in done.stderr
    assert "3 created" in done.stderr


def test_a_command_that_finds_problems_exits_1(database: str, cli: Any) -> None:
    ArangoStore()  # an empty database: every raw kind is missing
    done = cli("check", "--skip-edges", check=False)
    assert done.returncode == 1
    assert "no records" in done.stderr


def test_a_wrong_command_line_exits_2(database: str, cli: Any) -> None:
    assert cli("normalize", "no-such-source", check=False).returncode == 2
    assert cli("normalize", "bwb", "--no-such-option", check=False).returncode == 2
    assert cli("normalize", "all", "--since", "sometime", check=False).returncode == 2


def test_a_phase_lists_every_step_with_how_it_ended(
    database: str, cli: Any, monkeypatch: Any
) -> None:
    seed(ArangoStore(), documents=5, judgments=3, regulations=1)
    monkeypatch.setitem(os.environ, "LAWGRAPH_NORMALIZE_SKIP_BWB", "true")
    done = cli("normalize", "all", check=False)
    assert done.returncode == 0
    table = [
        line
        for line in done.stderr.splitlines()
        if line.rstrip().endswith((" ok", " skipped"))
    ]
    assert sum(line.rstrip().endswith(" skipped") for line in table) == 1
    assert sum(line.rstrip().endswith(" ok") for line in table) >= 8
    assert "LAWGRAPH_NORMALIZE_SKIP_BWB" in done.stderr
    # a skipped step is a hole: the mark of `--since last` stays where it was
    assert ArangoStore().db.collection("pipeline_state").get("normalize") is None


def test_a_judgment_that_is_no_xml_is_left_out_and_named(
    database: str, cli: Any
) -> None:
    """It became a judgment without court, date or text, and the run said "1 created"."""
    from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
    from lawgraph.db import RawSourceWriter, raw_source_doc

    store = ArangoStore()
    seed(store, documents=0, judgments=2, regulations=0)
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id="ECLI:NL:HR:2020:999",
                payload_text="<open",
                meta={"ecli": "ECLI:NL:HR:2020:999"},
            )
        )
    done = cli("normalize", "rechtspraak")
    assert store.db.collection("judgments").count() == 2
    assert "1 judgment(s) whose stored XML cannot be read" in done.stderr
    assert "ECLI:NL:HR:2020:999" in done.stderr and "1 skipped" in done.stderr
