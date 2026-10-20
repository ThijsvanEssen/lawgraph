"""The database shards of ``.github/workflows/tests.yaml`` run every file of ``tests/pg`` and
``tests/integration`` once, on the measured durations (``tests/shards.py``), and keep the tests
of a file that share a worker (``xdist_group``) together (``--dist loadgroup``; worksteal
ignores the group).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from tests import shards
from tests.paths import ROOT

JOB: dict[str, Any] = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "tests.yaml").read_text(encoding="utf-8")
)["jobs"]["database-shard"]
NUMBERS: list[int] = JOB["strategy"]["matrix"]["shard"]
FILES = shards.database_test_files()
RUNS = [step["run"] for step in JOB["steps"] if "tests.shards" in step.get("run", "")]


def test_each_shard_runs_its_own_part_of_the_split() -> None:
    assert NUMBERS == list(range(1, len(NUMBERS) + 1))
    assert len(RUNS) == 1
    assert (
        "python -m tests.shards ${{ matrix.shard }} ${{ strategy.job-total }}"
        in RUNS[0]
    )


def test_every_database_test_file_is_in_one_shard() -> None:
    split = shards.split(FILES, shards.measured(), len(NUMBERS))
    assert FILES
    assert sorted(name for shard in split for name in shard) == FILES
    assert [number for number, shard in enumerate(split, 1) if not shard] == []


def test_a_file_not_measured_lands_in_one_shard() -> None:
    new = "tests/pg/test_not_measured_yet.py"
    durations = shards.measured()
    assert new not in durations
    split = shards.split([*FILES, new], durations, len(NUMBERS))
    assert sorted(shard.count(new) for shard in split) == [0] * (len(NUMBERS) - 1) + [1]


def test_the_measured_shards_take_about_as_long() -> None:
    durations = shards.measured()
    loads = [
        sum(durations.get(name, 0.0) for name in shard)
        for shard in shards.split(FILES, durations, len(NUMBERS))
    ]
    mean = sum(loads) / len(loads)
    assert all(abs(load - mean) <= 0.2 * mean for load in loads), loads


def test_record_sums_the_tests_of_a_file(tmp_path: pathlib.Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.pg.test_a" name="x" time="1.5"/>'
        '<testcase classname="tests.pg.test_a.TestB" name="y" time="2.0"/>'
        '<testcase classname="tests.integration.test_c" name="z" time="3.0"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    files = ["tests/integration/test_c.py", "tests/pg/test_a.py"]
    assert shards.record([junit], files) == {
        "tests/integration/test_c.py": 3.0,
        "tests/pg/test_a.py": 3.5,
    }


def test_the_shards_keep_a_group_on_one_worker() -> None:
    grouped = [
        name
        for name in FILES
        if "xdist_group" in (ROOT / name).read_text(encoding="utf-8")
    ]
    assert grouped
    assert RUNS and all("--dist loadgroup" in run for run in RUNS), RUNS
