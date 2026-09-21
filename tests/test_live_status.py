"""The progress block of a terminal: rewritten in place, log lines above it, nothing left behind."""

from __future__ import annotations

import io
import logging
import os
import re
import threading

import pytest

from lawgraph.core import logging as lg
from lawgraph.core.logging import LiveStatusHandler


class Screen:
    """Enough of a terminal for what the handler sends: text, CR, LF, cursor up, clear, SGR."""

    def __init__(self, columns: int) -> None:
        self.columns, self.rows, self.row, self.column = columns, [[]], 0, 0
        self.wrapped = 0

    def feed(self, data: str) -> Screen:
        for token in re.findall(r"\x1b\[[0-9;]*[A-Za-z]|\r|\n|[^\x1b\r\n]", data):
            if token == "\r":
                self.column = 0
            elif token == "\n":
                self.row, self.column = self.row + 1, 0
                while len(self.rows) <= self.row:
                    self.rows.append([])
            elif token.startswith("\x1b["):
                count, kind = token[2:-1], token[-1]
                if kind == "A":
                    self.row = max(0, self.row - int(count or 1))
                elif kind == "J":
                    self.rows[self.row] = self.rows[self.row][: self.column]
                    del self.rows[self.row + 1 :]
            else:
                if self.column >= self.columns:
                    self.row, self.column, self.wrapped = (
                        self.row + 1,
                        0,
                        self.wrapped + 1,
                    )
                while len(self.rows) <= self.row:
                    self.rows.append([])
                line = self.rows[self.row]
                line.extend(" " * (self.column + 1 - len(line)))
                line[self.column] = token
                self.column += 1
        return self

    def lines(self) -> list[str]:
        return [text for row in self.rows if (text := "".join(row).rstrip())]


@pytest.fixture()
def terminal(monkeypatch: pytest.MonkeyPatch):
    def make(
        columns: int = 120, lines: int = 30
    ) -> tuple[LiveStatusHandler, io.StringIO]:
        size = os.terminal_size((columns, lines))
        monkeypatch.setattr(lg.shutil, "get_terminal_size", lambda *a, **k: size)
        stream = io.StringIO()
        handler = LiveStatusHandler(stream, color=False)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        return handler, stream

    return make


def _record(message: str, *, status: bool = False) -> logging.LogRecord:
    record = logging.LogRecord(
        "lawgraph.test", logging.INFO, __file__, 1, message, None, None
    )
    record.status = status
    return record


def test_progress_is_rewritten_in_place_and_log_lines_scroll_above_it(terminal) -> None:
    handler, stream = terminal()
    handler.emit(_record("retrieve all: starting"))
    for done in range(1, 200):
        handler.update("retrieve bwb", f"{done} / 200 regulations")
        handler.update("retrieve rechtspraak", f"{done * 3} / 600 records")
        if done == 100:
            handler.emit(_record("repository.overheid.nl is throttling"))

    assert Screen(120).feed(stream.getvalue()).lines() == [
        "INFO retrieve all: starting",
        "INFO repository.overheid.nl is throttling",
        "[retrieve bwb] 199 / 200 regulations",
        "[retrieve rechtspraak] 597 / 600 records",
    ]


def test_a_finished_step_leaves_the_block_and_closing_leaves_nothing_behind(
    terminal,
) -> None:
    handler, stream = terminal()
    handler.update("retrieve bwb", "10 / 200 regulations")
    handler.update("retrieve tk", "5 / 9 records")
    handler.update("retrieve tk", None)
    handler.emit(_record("retrieve tk: completed"))
    assert (
        Screen(120).feed(stream.getvalue()).lines()[-1]
        == "[retrieve bwb] 10 / 200 regulations"
    )

    handler.close()
    assert Screen(120).feed(stream.getvalue()).lines() == [
        "INFO retrieve tk: completed"
    ]


def test_a_status_line_never_wraps_because_a_wrapped_line_breaks_the_rewrite(
    terminal,
) -> None:
    handler, stream = terminal(columns=40)
    for done in range(50):
        handler.update(
            "retrieve staatscourant", f"{done} / 1,759 records · 1.9/s · ~12m left"
        )
    screen = Screen(40).feed(stream.getvalue())
    assert screen.wrapped == 0
    assert screen.lines() == [
        "[retrieve staatscourant] 49 / 1,759 re…"
    ]  # 39 of 40 columns


def test_the_periodic_progress_record_is_not_printed_the_block_shows_it(
    terminal,
) -> None:
    handler, stream = terminal()
    handler.emit(_record("12,400 / 34,593 (36%) records", status=True))
    assert stream.getvalue() == ""


def test_lanes_on_threads_share_one_block(terminal) -> None:
    handler, stream = terminal()

    def lane(step: str) -> None:
        for done in range(300):
            handler.update(step, f"{done} records")
            if done % 50 == 0:
                handler.emit(_record(f"{step}: {done}"))

    threads = [
        threading.Thread(target=lane, args=(f"retrieve s{n}",)) for n in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = Screen(120).feed(stream.getvalue()).lines()
    assert lines[-6:] == sorted(
        lines[-6:], key=lines.index
    )  # still six lines, one per lane
    assert {line for line in lines if line.startswith("[retrieve s")} == {
        f"[retrieve s{n}] 299 records" for n in range(6)
    }
    assert len([line for line in lines if line.startswith("INFO")]) == 36


def test_only_a_terminal_gets_the_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lg, "LOG_JSON", False)
    monkeypatch.setattr(lg.sys, "stderr", io.StringIO())  # a pipe, a file: no isatty
    assert lg._terminal_is_live() is False

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(lg.sys, "stderr", Tty())
    assert lg._terminal_is_live() is True
    monkeypatch.setattr(lg, "LOG_JSON", True)  # one JSON object per line stays that
    assert lg._terminal_is_live() is False
