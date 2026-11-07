"""Retrieve pipeline: who issued each stored ministerial regulation of the Staatscourant
(``dcterms:creator``, ``_creators``)."""

from __future__ import annotations

from lawgraph.clients.koop_publications import MINISTERIAL_REGULATION
from lawgraph.config.constants import (
    RAW_KIND_STAATSCOURANT_REGELING,
    SOURCE_STAATSCOURANT,
)

from ._creators import PublicationCreatorsRetrievePipeline


class StaatscourantCreatorsRetrievePipeline(PublicationCreatorsRetrievePipeline):
    """The creators of the stored ministerial regulations of the Staatscourant."""

    source = SOURCE_STAATSCOURANT
    kind = RAW_KIND_STAATSCOURANT_REGELING
    publication = MINISTERIAL_REGULATION
