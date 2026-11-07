"""Retrieve pipeline: who issued each stored Staatsblad publication (``dcterms:creator``,
``_creators``)."""

from __future__ import annotations

from lawgraph.clients.koop_publications import AMVB
from lawgraph.config.constants import RAW_KIND_STAATSBLAD_AMVB, SOURCE_STAATSBLAD

from ._creators import PublicationCreatorsRetrievePipeline


class StaatsbladCreatorsRetrievePipeline(PublicationCreatorsRetrievePipeline):
    """The creators of the stored AMvBs of the Staatsblad."""

    source = SOURCE_STAATSBLAD
    kind = RAW_KIND_STAATSBLAD_AMVB
    publication = AMVB
