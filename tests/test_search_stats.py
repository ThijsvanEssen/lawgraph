"""The counts of the terms searched: per day, without who asked or when in the day; kept in
full for a week, then only what was asked often enough."""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections import Counter
from pathlib import Path

from lawgraph.commands import search_stats as command
from lawgraph.core import search_stats as stats
from lawgraph.core.search_stats import SearchTermCounter

TODAY = dt.date(2026, 10, 20)


def _day(n: int) -> dt.date:
    return TODAY - dt.timedelta(days=n)


def _file(directory: Path, day: dt.date) -> Path:
    return directory / f"search-{day.isoformat()}.json"


def test_a_term_is_counted_as_it_is_normalised() -> None:
    assert stats.normalise("  Rechtszaak\tJANSEN \n") == "rechtszaak jansen"
    assert stats.normalise("Ａrt") == "ａrt"  # NFC, not folded further
    assert len(stats.normalise("x" * 500)) == stats.MAX_TERM_CHARS
    assert stats.normalise("   ") == ""


def test_the_counter_keeps_terms_per_day_and_nothing_else() -> None:
    counter = SearchTermCounter()
    for q in ("Huurrecht", "huurrecht", " ", "AVG"):
        counter.add(q, today=TODAY)
    counter.add("avg", today=_day(1))
    assert counter.take() == {
        TODAY.isoformat(): Counter({"huurrecht": 2, "avg": 1}),
        _day(1).isoformat(): Counter({"avg": 1}),
    }
    assert counter.take() == {}


def test_the_counter_is_safe_across_threads() -> None:
    counter = SearchTermCounter()

    def ask() -> None:
        for _ in range(1000):
            counter.add("awb", today=TODAY)

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counter.take()[TODAY.isoformat()]["awb"] == 8000


def test_a_flush_adds_to_the_day_file_and_holds_only_terms_and_counts(
    tmp_path: Path,
) -> None:
    counter = SearchTermCounter()
    counter.add("awb", today=TODAY)
    counter.flush(tmp_path)
    counter.add("Awb", today=TODAY)  # a later flush, or an API that started again
    counter.add("bw", today=TODAY)
    counter.flush(tmp_path)
    data = json.loads(_file(tmp_path, TODAY).read_text())
    assert data == {"awb": 2, "bw": 1}  # term → n: no address, no time, no session
    assert [p.name for p in tmp_path.iterdir() if not p.name.startswith(".")] == [
        f"search-{TODAY.isoformat()}.json"
    ]


def test_prune_keeps_the_last_days_whole_and_only_frequent_terms_after(
    tmp_path: Path,
) -> None:
    # day 8 is the first to go (7 days are kept: today and the 6 before it)
    stats.merge_day(tmp_path, _day(8).isoformat(), Counter({"jansen": 1, "awb": 2}))
    for n in range(0, 7):
        stats.merge_day(
            tmp_path, _day(n).isoformat(), Counter({"awb": 1, f"rare{n}": 1})
        )
    moved = stats.prune(tmp_path, TODAY, keep_days=7, min_count=5)
    assert moved == [_day(8).isoformat()]
    assert not _file(tmp_path, _day(8)).exists()
    month = json.loads(
        (tmp_path / f"search-{_day(8).isoformat()[:7]}.json").read_text()
    )
    # awb: 2 that day + 6 in the days kept after it ≥ 5; jansen once: gone
    assert month == {"awb": 2}
    for n in range(0, 7):
        assert _file(tmp_path, _day(n)).exists()  # kept in full, rare terms too


def test_a_term_asked_now_and_then_adds_up_in_its_month(tmp_path: Path) -> None:
    """Asked once a day, a term reaches the threshold over the window and is kept."""
    for n in range(0, 20):
        stats.merge_day(tmp_path, _day(n).isoformat(), Counter({"omgevingswet": 1}))
    stats.prune(tmp_path, TODAY, keep_days=7, min_count=5)
    kept = sum(
        json.loads(p.read_text()).get("omgevingswet", 0)
        for p in tmp_path.glob("search-????-??.json")
    )
    assert kept == 13  # every day moved (20 - 7) counted


def test_totals_read_the_days_and_the_months(tmp_path: Path) -> None:
    stats.merge_day(tmp_path, TODAY.isoformat(), Counter({"awb": 3}))
    stats.merge_day(tmp_path, _day(2).isoformat(), Counter({"awb": 1, "bw": 4}))
    stats.merge_day(tmp_path, _day(30).isoformat(), Counter({"old": 9}))
    assert stats.totals(tmp_path, TODAY, 7) == Counter({"awb": 4, "bw": 4})
    assert stats.totals(tmp_path / "none", TODAY, 7) == Counter()


def test_the_command_prints_the_top_terms(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(command, "SEARCH_STATS_DIR", tmp_path)
    today = dt.date.today()
    stats.merge_day(tmp_path, today.isoformat(), Counter({"awb": 3, "bw": 1}))
    command.main(["--top", "1"])
    assert capsys.readouterr().out.split() == ["3", "awb"]
    stats.merge_day(
        tmp_path, (today - dt.timedelta(days=9)).isoformat(), Counter({"x": 1})
    )
    result = command.main(["prune"])
    assert result.updated == 1
