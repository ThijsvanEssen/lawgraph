"""Client for the Kamerstukken as XML, and the transposition tables among their
attachments, from the KOOP repository.

The Tweede Kamer's own API serves a document as a PDF. The same paper is published as
structured XML (headings, paragraphs, tables) in the official publications, filed under its
dossier: https://repository.overheid.nl/frbr/officielepublicaties/kst/<dossier>/
kst-<dossier>-<number>/1/xml/kst-<dossier>-<number>.xml, where the dossier is the number
with its addition (``37020-X`` for a budget chapter).

An attachment (``dt.type`` ``Bijlage``, ``blg-1081574``) is published as a PDF only; the
SRU lists it with its dossier, the paper it belongs to and the URL of the PDF.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import requests

from lawgraph.clients._sru import fetch_publication_xml, iter_publications, record_dicts
from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient, UnexpectedAnswer
from lawgraph.config.sources import KOOP_REPOSITORY, KOOP_SRU
from lawgraph.core.identifiers import KST_ID_PATTERN

# The words of the title of an attachment that is a table placing the articles of one law in
# another: "Transponeringstabellen nieuw naar huidig en huidig naar nieuw Sv".
TABLE_TITLE_WORDS = (
    "transponeringstabel",
    "transponeringstabellen",
    "concordantietabel",
    "concordantietabellen",
)
_TABLE_FIELDS = {
    "title": "title",
    "dossier": "dossiernummer",
    "main_document": "hoofddocument",
    "pdf_url": "url",
    "modified": "modified",
}


class KamerstukClient(BaseClient):
    """Fetches the XML of a Kamerstuk by its identifier."""

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=KOOP_REPOSITORY.base_url, session=session)

    def fetch_kamerstuk_xml(self, identifier: str) -> str:
        """The XML of ``kst-<dossier>-<number>`` (``_sru.fetch_publication_xml``)."""
        match = KST_ID_PATTERN.fullmatch(identifier)
        if not match:
            raise UnexpectedAnswer(f"not a Kamerstuk identifier: {identifier!r}")
        return fetch_publication_xml(
            self, "kst", KST_ID_PATTERN, identifier, group=match.group(1)
        )

    def search_tables(self) -> list[dict[str, Any]]:
        """Every attachment whose title names a transposition or concordance table
        (``TABLE_TITLE_WORDS``): its identifier, title, dossier, main document (the paper it
        is an attachment of), the URL of its PDF and when it was modified."""
        words = " ".join(TABLE_TITLE_WORDS)
        return list(
            iter_publications(
                self,
                KOOP_SRU,
                query=f'dt.type=Bijlage AND dt.title any "{words}"',
                parse=self._tables,
                context="Bijlagen",
            )
        )

    def fetch_pdf(self, url: str) -> bytes:
        """The PDF at *url*; raises when the answer is no PDF."""
        content = self.get(url, timeout=PAGE_TIMEOUT).content
        if not content.startswith(b"%PDF"):
            raise UnexpectedAnswer(f"not a PDF: {url}")
        return content

    @staticmethod
    def _tables(root: ET.Element) -> list[dict[str, Any]]:
        return record_dicts(root, _TABLE_FIELDS)
