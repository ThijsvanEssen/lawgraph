"""What every pipeline shares: the store it works on, and the sign to stop.

A pipeline has a ``run`` that returns a ``PipelineResult``. What ``run`` takes differs per
phase and is said where it matters: a retrieve pipeline takes what its command parsed
(``retrieve_commands``), a normalize or semantic pipeline takes ``since`` or nothing
(``command.PipelineCommand`` reads that from its signature, and a test holds every
registered pipeline to it).
"""

from __future__ import annotations

import threading

from lawgraph.db import Store


class PipelineBase:
    """A pipeline works on one store."""

    def __init__(self, store: Store) -> None:
        self.store = store


# Set when the user interrupts a command that runs steps on threads (``retrieve all
# --jobs``). Ctrl-C only reaches the main thread; the steps look here between two records,
# store what they have and stop, instead of fetching on for hours.
STOP = threading.Event()
