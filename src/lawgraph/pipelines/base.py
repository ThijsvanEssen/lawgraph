"""Shared base class for all pipeline types (retrieve, normalize, semantic)."""

from __future__ import annotations

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
