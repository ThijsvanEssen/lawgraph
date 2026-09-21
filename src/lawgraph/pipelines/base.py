"""Shared base class for all pipeline types (retrieve, normalize, semantic)."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore


class PipelineBase(ABC):
    """Common foundation for retrieve, normalize, and semantic pipelines.

    Provides: db store reference and the run() contract.
    Subclasses add phase-specific orchestration and helpers on top.
    """

    def __init__(self, store: ArangoStore) -> None:
        self.store = store

    @abstractmethod
    def run(self, **kwargs: Any) -> PipelineResult:
        """Execute the pipeline and return a result summary."""


# Set when the user interrupts a command that runs steps on threads (``retrieve all
# --jobs``). Ctrl-C only reaches the main thread; the steps look here between two records,
# store what they have and stop, instead of fetching on for hours.
STOP = threading.Event()
