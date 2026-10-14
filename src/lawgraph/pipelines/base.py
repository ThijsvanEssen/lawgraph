"""What every pipeline shares: the store it works on, and the sign to stop.

A pipeline has a ``run`` that returns a ``PipelineResult``. What ``run`` takes differs per
phase and is said where it matters: a retrieve pipeline takes what its command parsed
(``retrieve_commands``) or nothing, a normalize or semantic pipeline takes ``since`` or nothing
(``command.PipelineCommand`` reads that from its signature, and a test holds every
registered pipeline to it).
"""

from __future__ import annotations

import threading

from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.db import Store


class PipelineBase:
    """A pipeline works on one store.

    ``progress`` counts the records of the loop the pipeline is in: a record it leaves out
    is ``progress.skip(reason, id)``, one it cannot read ``progress.fail(reason, id)``, and
    ``add_outcomes`` puts what every loop counted on the result (a failure makes the step
    fail; the run goes on).
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.progress = Progress()
        self._loops = [self.progress]

    def _loop(self, what: str, *, total: int | None = None) -> Progress:
        """The progress of the next loop over records; it is ``progress`` from now on."""
        self.progress = Progress(what, total=total)
        self._loops.append(self.progress)
        return self.progress

    def add_outcomes(self, result: PipelineResult) -> None:
        """Add what every loop so far counted to *result*, once: its skips and failures as
        skipped, and one error per cause of a failure (with its count and first record)."""
        loops, self._loops = self._loops, []
        for progress in loops:
            result.skipped += progress.skipped + progress.failed
            result.errors.extend(progress.errors())


# Set when the user interrupts a command that runs steps on threads (``retrieve all
# --jobs``). Ctrl-C only reaches the main thread; the steps look here between two records,
# store what they have and stop, instead of fetching on for hours.
STOP = threading.Event()
