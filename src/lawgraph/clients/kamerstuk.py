"""Client for the Kamerstukken as XML, and the transposition tables among their
attachments, from the KOOP repository.

The Tweede Kamer's own API serves a document as a PDF. The same paper is published as
structured XML (headings, paragraphs, tables) in the official publications, filed under its
dossier: https://repository.overheid.nl/frbr/officielepublicaties/kst/<dossier>/
kst-<dossier>-<number>/1/xml/kst-<dossier>-<number>.xml, where the dossier is the number
with its addition (``37020-X`` for a budget chapter).

An attachment (``dt.type`` ``Bijlage``, ``blg-1081574``) is published as a PDF, a few older
ones as XML too; the SRU lists it with its dossier, the paper it belongs to and the URL of
each manifestation (``itemUrl``). Its ``url`` is the XML when there is one. The SRU also
searches the full text of the papers (``cql.textAndIndexes``).

The SRU also lists every Kamerstuk of the Tweede Kamer since December 1994
(``iter_tk_kamerstukken``), which its own API hardly has before 2008-2009: per paper its
identifier, the title (``<dossier>; <kind>``), the numbers it has in its dossier (``1`` and
``2`` for a bill with its royal message), the dossier, the session year, the date and the URL
of each manifestation.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.clients._sru import fetch_publication_xml, iter_publications, record_dicts
from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient, Unexpected, UnexpectedAnswer
from lawgraph.config.sources import KOOP_REPOSITORY, KOOP_SRU
from lawgraph.core.identifiers import KST_ID_PATTERN
from lawgraph.core.transposition_xml import TABLE_WORDS
from lawgraph.core.xml import iter_named, own_texts

_TABLE_FIELDS = {
    "title": "title",
    "dossier": "dossiernummer",
    "main_document": "hoofddocument",
    "modified": "modified",
}
_TK_QUERY = (
    'dt.creator=="Tweede Kamer der Staten-Generaal" '
    "AND w.publicatienaam==Kamerstuk AND dt.type==Kamerstuk"
)
_TK_FIELDS = {
    "title": "title",
    "dossier_title": "dossiertitel",
    "session_year": "vergaderjaar",
    "dossier_number": "dossiernummer",
    "date": "date",
    "modified": "modified",
    "url": "preferredUrl",
    "replaced_by": "isReplacedBy",
}
_DOCUMENT_FIELDS = {
    "title": "title",
    "dossier": "dossiernummer",
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
            raise UnexpectedAnswer(Unexpected.BAD_ID, f"Kamerstuk {identifier!r}")
        return fetch_publication_xml(
            self, "kst", KST_ID_PATTERN, identifier, group=match.group(1)
        )

    def iter_tk_kamerstukken(
        self, session_year: str, *, since: str | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield the Kamerstukken of the Tweede Kamer of *session_year* (``1997-1998``), page
        by page, ``since`` on ``dt.modified``.

        One session year holds at most some 11,000; ``iter_publications`` pages by key, so
        the HTTP 504 the SRU answers from position 10,000 on is never reached. *limit* stops
        early. A failing request or an SRU error raises, after the papers of the earlier
        pages were yielded.
        """
        query = f"{_TK_QUERY} AND w.vergaderjaar=={session_year}"
        if since:
            query += f" AND dt.modified>={since}"
        return iter_publications(
            self,
            KOOP_SRU,
            query=query,
            parse=self._tk_kamerstukken,
            context=f"Tweede Kamer {session_year}",
            connection=None,
            limit=limit,
        )

    def search_tables(self) -> list[dict[str, Any]]:
        """Every attachment whose title names a transposition or concordance table
        (``TABLE_WORDS``: "Transponeringstabellen nieuw naar huidig en huidig naar nieuw
        Sv"): its identifier, title, dossier, main document (the paper it
        is an attachment of), the URL of its PDF and when it was modified."""
        words = " ".join(TABLE_WORDS)
        return list(
            iter_publications(
                self,
                KOOP_SRU,
                query=f'dt.type=Bijlage AND dt.title any "{words}"',
                parse=self._tables,
                context="Bijlagen",
            )
        )

    def search_documents_naming_tables(self) -> list[dict[str, Any]]:
        """Every Kamerstuk whose text names a transposition or concordance table
        (``TABLE_WORDS``, anywhere in it: a heading, a sentence, a cell) and is published
        as XML: its identifier, title, dossier, the URL of its XML and when it was
        modified. A paper only scanned (Staten-Generaal Digitaal) or only a PDF has none."""
        words = " OR ".join(f'cql.textAndIndexes="{word}"' for word in TABLE_WORDS)
        documents = iter_publications(
            self,
            KOOP_SRU,
            query=f"dt.type=Kamerstuk AND ({words})",
            parse=self._documents,
            context="Kamerstukken",
        )
        return [document for document in documents if document["xml_url"]]

    def fetch_xml(self, url: str) -> str:
        """The XML at *url*; raises when the answer is no XML."""
        return self.get_xml(url, timeout=PAGE_TIMEOUT)

    def fetch_pdf(self, url: str) -> bytes:
        """The PDF at *url*; raises when the answer is no PDF."""
        content = self.get(url, timeout=PAGE_TIMEOUT).content
        if not content.startswith(b"%PDF"):
            raise UnexpectedAnswer(Unexpected.NOT_PDF, url)
        return content

    @staticmethod
    def _tables(root: ET.Element) -> list[dict[str, Any]]:
        return record_dicts(root, _TABLE_FIELDS, pdf_url=lambda r: _item_url(r, "pdf"))

    @staticmethod
    def _tk_kamerstukken(root: ET.Element) -> list[dict[str, Any]]:
        return record_dicts(
            root,
            _TK_FIELDS,
            numbers=lambda r: own_texts(r, "ondernummer"),
            dossier_numbers=lambda r: own_texts(r, "dossiernummer"),
            xml_url=lambda r: _item_url(r, "xml"),
            pdf_url=lambda r: _item_url(r, "pdf"),
        )

    @staticmethod
    def _documents(root: ET.Element) -> list[dict[str, Any]]:
        return record_dicts(
            root, _DOCUMENT_FIELDS, xml_url=lambda r: _item_url(r, "xml")
        )


def _item_url(record: ET.Element, manifestation: str) -> str | None:
    """The URL of the *manifestation* (``pdf``, ``xml``) of an SRU record."""
    for item in iter_named(record, "itemUrl"):
        if item.get("manifestation") == manifestation and item.text:
            return item.text.strip()
    return None
