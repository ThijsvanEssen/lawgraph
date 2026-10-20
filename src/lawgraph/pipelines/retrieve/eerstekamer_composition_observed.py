"""Retrieve pipeline that keeps the composition of the Eerste Kamer observed so far.

Before the pages of the composition were stored per version, only the graph held the
periods observed (``observed_from``, ``observed_until``). This stores them once in raw: the
factions and committees (``chamber`` ``EK``) and members (``ek``) with their props and the
``MEMBER_OF`` edges into them, as the graph holds them, and the external ids of the versions
of the pages stored now, which that composition covers (``ek-composition-observed``, external
id ``observed``). ``normalize eerstekamer-composition`` walks the later versions from it.

Once stored it is not written again; a graph without a composition of the Eerste Kamer stores
nothing. No request is made.
"""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_COMPOSITION,
    RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.time import dutch_today
from lawgraph.db.queries.normalize import tk as normalize_tk

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

OBSERVED_ID = "observed"


class EerstekamerCompositionObservedRetrievePipeline(RetrievePipelineBase):
    """Store the composition of the Eerste Kamer the graph holds, once."""

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        if self._stored_ids(
            SOURCE_EERSTEKAMER, RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED
        ):
            logger.info("The observed composition is stored already.")
            return
        held = normalize_tk.ek_composition(self.store)
        if not held["factions"]:
            logger.info("The graph holds no composition of the Eerste Kamer.")
            return
        yield RetrieveRecord(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED,
            external_id=OBSERVED_ID,
            payload_json={
                **held,
                "covers": sorted(
                    self._stored_ids(
                        SOURCE_EERSTEKAMER, RAW_KIND_EERSTEKAMER_COMPOSITION
                    )
                ),
            },
            meta={"read_on": dutch_today().isoformat()},
        )
