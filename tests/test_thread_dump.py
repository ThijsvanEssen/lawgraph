"""``SIGUSR1`` writes the stack of every thread to stderr, and nothing without it."""

from __future__ import annotations

import faulthandler
import os
import signal

import pytest

from lawgraph.api.app import _thread_dump_on_signal


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 on this system")
def test_the_signal_dumps_every_thread(capfd: pytest.CaptureFixture[str]) -> None:
    _thread_dump_on_signal()
    try:
        assert capfd.readouterr().err == ""  # nothing without the signal
        os.kill(os.getpid(), signal.SIGUSR1)
        dumped = capfd.readouterr().err
    finally:
        faulthandler.unregister(signal.SIGUSR1)
    assert "Current thread" in dumped or "Thread 0x" in dumped
    assert "test_the_signal_dumps_every_thread" in dumped
