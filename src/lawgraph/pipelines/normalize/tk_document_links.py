"""Normalize the links of Tweede Kamer documents (``retrieve tk-document-links``) into edges.

A document is the record of an activity (a stenogram of its debate: MADE_IN) and a letter
has attachments (ACCOMPANIES, from the attachment to the letter). ``normalize tk-dossiers``
makes the same edges of the documents it reads, from their own records; this makes them of
the link records, which hold every paper, also those stored before their records named
their links. Edges only between nodes that exist; a link to a paper or activity not yet
stored is made by a later run.
"""

from __future__ import annotations

from lawgraph.config.constants import RAW_KIND_TK_DOCUMENT_LINKS
from lawgraph.core.tk_records.documents import document_links
from lawgraph.pipelines.normalize._tk_cases import (
    LinkRecordsPipelineBase,
    link_documents,
)


class TKDocumentLinksNormalizePipeline(LinkRecordsPipelineBase):
    """Write MADE_IN and ACCOMPANIES edges from the stored links of TK documents."""

    kind = RAW_KIND_TK_DOCUMENT_LINKS
    read = document_links
    link = link_documents
    edge_source = "tk-document-links"
    what = "Document links"
