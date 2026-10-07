"""``scripts/ci_shard.py``: the integration files over the CI shards, by their time."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ci_shard", ROOT / "scripts" / "ci_shard.py"
)
assert _spec and _spec.loader
ci_shard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_shard)


def test_every_integration_file_runs_in_exactly_one_shard() -> None:
    files = []
    for shard in (1, 2, 3):
        files += [f for f in _shard(shard) if f]
    expected = sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "tests" / "integration").glob("test_*.py")
    )
    assert sorted(files) == expected


def _shard(shard: int) -> list[str]:
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert ci_shard.main(["tests/integration", "3", str(shard)]) == 0
    return out.getvalue().split()


def test_the_longest_files_are_spread_and_the_shards_weigh_the_same() -> None:
    times = {"a": 10.0, "b": 9.0, "c": 5.0, "d": 4.0, "e": 1.0, "f": 1.0}
    groups = ci_shard.shards(list(times), times, 2)
    assert groups == [["a", "d", "e"], ["b", "c", "f"]]
    assert [sum(times[f] for f in g) for g in groups] == [15.0, 15.0]


def test_a_new_file_counts_as_the_average() -> None:
    groups = ci_shard.shards(["old", "new", "small"], {"old": 6.0, "small": 2.0}, 2)
    assert groups == [["old"], ["new", "small"]]  # new weighs 4, the average


def test_the_times_are_read_from_the_durations_of_pytest() -> None:
    lines = [
        "12.50s call     tests/integration/test_x.py::test_one",
        "0.50s setup    tests/integration/test_x.py::test_one",
        "1.00s teardown tests/pg/test_y.py::test_two[param]",
        "(3 durations < 0.005s hidden.)",
    ]
    assert ci_shard.record(lines) == {
        "tests/integration/test_x.py": 13.0,
        "tests/pg/test_y.py": 1.0,
    }
