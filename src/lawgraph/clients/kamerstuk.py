"""Client for the Kamerstukken as XML, from the KOOP repository.

The Tweede Kamer's own API serves a document as a PDF. The same paper is published as
structured XML (headings, paragraphs, tables) in the official publications, filed under its
dossier: https://repository.overheid.nl/frbr/officielepublicaties/kst/<dossier>/
kst-<dossier>-<number>/1/xml/kst-<dossier>-<number>.xml, where the dossier is the number
with its addition (``37020-X`` for a budget chapter).
"""

from __future__ import annotations

from lawgraph.clients._sru import fetch_publication_xml
from lawgraph.clients.base import BaseClient, UnexpectedAnswer
from lawgraph.config.sources import KOOP_REPOSITORY
from lawgraph.core.identifiers import KST_ID_PATTERN


class KamerstukClient(BaseClient):
    """Fetches the XML of a Kamerstuk by its identifier."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=KOOP_REPOSITORY.base_url, session=session)

    def fetch_kamerstuk_xml(self, identifier: str) -> str:
        """The XML of ``kst-<dossier>-<number>`` (``_sru.fetch_publication_xml``)."""
        match = KST_ID_PATTERN.fullmatch(identifier)
        if not match:
            raise UnexpectedAnswer(f"not a Kamerstuk identifier: {identifier!r}")
        return fetch_publication_xml(
            self, "kst", KST_ID_PATTERN, identifier, group=match.group(1)
        )
