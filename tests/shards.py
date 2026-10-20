"""The database shards of ``.github/workflows/tests.yaml``: which files of ``tests/pg`` and
``tests/integration`` each runs, from the durations CI measured (``tests/durations.json``).

A file stays whole in one shard, so the tests that share a database (``xdist_group``) stay
together. The files go, longest first, each to the shard with the least so far; a file not yet
measured counts as the median measured file, so it lands in a shard all the same.

    python -m tests.shards SHARD TOTAL       the files of shard SHARD (1..TOTAL)
    python -m tests.shards --record XML...   durations.json from the junit files of runs
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys
import xml.etree.ElementTree as ET

from tests.paths import ROOT, TESTS

DURATIONS = TESTS / "durations.json"


def database_test_files() -> list[str]:
    """Every test file of ``tests/pg`` and ``tests/integration``, relative to the root."""
    return sorted(
        p.relative_to(ROOT).as_posix()
        for folder in ("pg", "integration")
        for p in (TESTS / folder).glob("test_*.py")
    )


def measured() -> dict[str, float]:
    """The seconds of each measured file (the sum of its tests, setup included)."""
    durations: dict[str, float] = json.loads(DURATIONS.read_text(encoding="utf-8"))
    return durations


def split(files: list[str], durations: dict[str, float], total: int) -> list[list[str]]:
    """*files* over *total* shards of about equal seconds."""
    default = statistics.median(durations.values()) if durations else 1.0
    seconds = {name: durations.get(name, default) for name in files}
    shards: list[list[str]] = [[] for _ in range(total)]
    loads = [0.0] * total
    for name in sorted(files, key=lambda n: (-seconds[n], n)):
        least = loads.index(min(loads))
        shards[least].append(name)
        loads[least] += seconds[name]
    return [sorted(shard) for shard in shards]


def record(junit_files: list[pathlib.Path], files: list[str]) -> dict[str, float]:
    """The seconds per file in the junit files of one or more runs: a file runs in one shard
    of a run, so its seconds are the mean over the junit files that hold it (``classname``
    is the module, followed by the class when there is one)."""
    modules = {name.removesuffix(".py").replace("/", "."): name for name in files}
    runs: dict[str, list[float]] = {}
    for path in junit_files:
        seconds: dict[str, float] = {}
        for case in ET.parse(path).iter("testcase"):
            parts = case.get("classname", "").split(".")
            for end in range(len(parts), 0, -1):
                name = modules.get(".".join(parts[:end]))
                if name:
                    seconds[name] = seconds.get(name, 0.0) + float(case.get("time", 0))
                    break
        for name, total in seconds.items():
            runs.setdefault(name, []).append(total)
    return {name: round(statistics.mean(runs[name]), 1) for name in sorted(runs)}


def main(args: list[str]) -> None:
    files = database_test_files()
    if args[0] == "--record":
        durations = record([pathlib.Path(a) for a in args[1:]], files)
        DURATIONS.write_text(json.dumps(durations, indent=2) + "\n", encoding="utf-8")
        return
    shard, total = int(args[0]), int(args[1])
    print(" ".join(split(files, measured(), total)[shard - 1]))


if __name__ == "__main__":
    main(sys.argv[1:])
