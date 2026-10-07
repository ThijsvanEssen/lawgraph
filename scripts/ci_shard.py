#!/usr/bin/env python3
"""The test files of one CI shard, balanced by how long each file took.

    python scripts/ci_shard.py <directory> <shards> <shard>    the files of shard 1..N
    pytest ... --durations=0 | python scripts/ci_shard.py --record    write the times

The times are those of ``.github/test-durations.json`` (seconds per file, all of its tests
with setup and teardown). The files go to the shards longest first, each to the shard with
the least so far, so every shard gets about the same time; a file without a time (a new one)
counts as the average. The same files and times give the same shards on every runner.
Under ``--dist loadfile`` a file runs on one worker, so no shard is shorter than its longest
file.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = ROOT / ".github" / "test-durations.json"
# a line of ``--durations=0``: "12.34s call     tests/integration/test_x.py::test_y"
_DURATION = re.compile(r"([\d.]+)s (?:call|setup|teardown)\s+(tests/[^:\s]+)::")


def shards(files: list[str], times: dict[str, float], count: int) -> list[list[str]]:
    """*files* in *count* groups of about equal time (longest first, each to the lightest)."""
    known = [times[f] for f in files if f in times]
    average = sum(known) / len(known) if known else 1.0
    groups: list[list[str]] = [[] for _ in range(count)]
    load = [0.0] * count
    for name in sorted(files, key=lambda f: (-times.get(f, average), f)):
        lightest = min(range(count), key=lambda i: (load[i], i))
        groups[lightest].append(name)
        load[lightest] += times.get(name, average)
    return [sorted(group) for group in groups]


def record(lines: list[str]) -> dict[str, float]:
    """Seconds per file from the output of ``pytest --durations=0``."""
    times: dict[str, float] = defaultdict(float)
    for line in lines:
        if found := _DURATION.search(line):
            times[found[2]] += float(found[1])
    return {name: round(seconds, 1) for name, seconds in sorted(times.items())}


def main(argv: list[str]) -> int:
    if argv == ["--record"]:
        known = json.loads(DURATIONS.read_text()) if DURATIONS.exists() else {}
        known.update(record(sys.stdin.read().splitlines()))
        DURATIONS.write_text(json.dumps(dict(sorted(known.items())), indent=1) + "\n")
        return 0
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    directory, count, shard = argv[0], int(argv[1]), int(argv[2])
    files = sorted(
        str(path.relative_to(ROOT)) for path in (ROOT / directory).glob("test_*.py")
    )
    times = json.loads(DURATIONS.read_text())
    print(" ".join(shards(files, times, count)[shard - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
