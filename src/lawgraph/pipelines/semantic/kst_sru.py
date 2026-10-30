"""Link the Kamerstukken of the Tweede Kamer from the KOOP SRU to their dossier.

A paper names the number of its dossier (``dossier_number``, ``dossier_suffix``; one on more
than one bill the others in ``dossier_numbers``): the same PART_OF edge as a paper of the
Eerste Kamer from the same SRU (``semantic eerstekamer``), and as a document of the Tweede
Kamer's API gets through its case. Derived in full on every run.
"""

from __future__ import annotations

from lawgraph.config.constants import SOURCE_KST
from lawgraph.sources.addresses import edge_source

from .eerstekamer import EerstekamerSemanticPipeline

# A paper of the SRU on the dossier its number names.
EDGE_SOURCE = edge_source(__name__)


class KstSruSemanticPipeline(EerstekamerSemanticPipeline):
    """Links the Tweede Kamer papers of the SRU to their dossiers via their number."""

    documents_of = SOURCE_KST
    edge_source = EDGE_SOURCE
