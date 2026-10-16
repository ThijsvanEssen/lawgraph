"""Client for the official publications of KOOP: the AMvBs in the Staatsblad and the
ministerial regulations in the Staatscourant, listed by the SRU of the repository
(https://repository.overheid.nl/sru) and fetched as XML from it."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests

from lawgraph.clients._sru import (
    fetch_publication_xml,
    iter_publications,
    record_identifier,
    records,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.sources import KOOP_REPOSITORY, KOOP_SRU
from lawgraph.core.identifiers import STB_ID_PATTERN, STCRT_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import find_own_text, own_texts

logger = get_logger(__name__)


@dataclass(frozen=True)
class PublicationKind:
    """What the client lists: the publications of one type in one publication."""

    code: str  # the repository's code of the publication: ``stb``
    publication: str  # its name: ``Staatsblad``, also the title of a record without one
    type_query: str  # the SRU query of the type: ``dt.type=AMvB``
    pattern: re.Pattern[
        str
    ]  # an identifier of it; group 1 the year, group 2 the number
    fields: tuple[str, ...] = ()  # single-valued elements read besides the common ones


AMVB = PublicationKind("stb", "Staatsblad", "dt.type=AMvB", STB_ID_PATTERN)
LAW = PublicationKind("stb", "Staatsblad", "dt.type=Wet", STB_ID_PATTERN)
MINISTERIAL_REGULATION = PublicationKind(
    "stcrt",
    "Staatscourant",
    "dt.type=Ministeriele-regeling",
    STCRT_ID_PATTERN,
    ("date",),
)


class KoopPublicationClient(BaseClient):
    """Lists the publications of one *kind* and fetches their XML."""

    def __init__(
        self, kind: PublicationKind, session: requests.Session | None = None
    ) -> None:
        super().__init__(base_url=KOOP_REPOSITORY.base_url, session=session)
        self.kind = kind

    def search(
        self, *, since: str | None = None, dossier: str | None = None
    ) -> list[dict[str, Any]]:
        """Every publication of the kind, ``since`` on ``dt.modified``, of the bill of
        *dossier* (``w.behandeldDossier``, ``36327``): dicts with identifier, year, number,
        title, content_url (its XML in the repository), modified and the kind's own fields.

        A record of another publication the query also matches (the Staatscourant query
        finds Staatsblad records) is left out, and counted in the log.
        """
        query = self.kind.type_query
        if since:
            query += f" AND dt.modified>={since}"
        if dossier:
            query += f' AND w.behandeldDossier=="{dossier}"'
        others: list[str] = []
        found = list(
            iter_publications(
                self,
                KOOP_SRU,
                query=query,
                parse=lambda root: self._publications(root, others),
                context=self.kind.publication,
            )
        )
        logger.info(
            "%s SRU search returned %d records (%d of another publication left out%s).",
            self.kind.publication,
            len(found),
            len(others),
            f", such as {others[0]}" if others else "",
        )
        return found

    def fetch_publication_xml(self, identifier: str) -> str:
        """The XML of a publication of the kind (``_sru.fetch_publication_xml``)."""
        return fetch_publication_xml(
            self, self.kind.code, self.kind.pattern, identifier
        )

    def creators(self, phrase: str, from_date: str, to_date: str) -> Counter[str]:
        """How many of the publications in the Staatscourant and the Staatsblad between the
        two days that name *phrase* each creator issued (``dcterms:creator``,
        ``Ministerie van Financiën``)."""
        query = (
            "c.product-area=officielepublicaties AND (w.publicatienaam=Staatscourant OR "
            f"w.publicatienaam=Staatsblad) AND dt.date>={from_date} AND "
            f'dt.date<={to_date} AND cql.textAndIndexes="{phrase}"'
        )
        found: Counter[str] = Counter()
        for record in iter_publications(
            self,
            KOOP_SRU,
            query=query,
            parse=lambda root: [
                {"creators": sorted(own_texts(r, "creator"))} for r in records(root)
            ],
            context=f"{self.kind.publication} {phrase!r}",
        ):
            found.update(record["creators"])
        return found

    def _publications(
        self, root: ET.Element, others: list[str]
    ) -> list[dict[str, Any]]:
        """The publications of the kind on a result page; the identifiers of the others
        are added to *others*."""
        found: list[dict[str, Any]] = []
        for record in records(root):
            identifier = record_identifier(record) or ""
            match = self.kind.pattern.search(identifier)
            if not match:
                others.append(identifier)
                continue
            year, number = match.group(1), match.group(2)
            found.append(
                {
                    "identifier": identifier,
                    "year": year,
                    "number": number,
                    "title": find_own_text(record, "title")
                    or f"{self.kind.publication} {year}/{number}",
                    "content_url": find_own_text(record, "url"),
                    "modified": find_own_text(record, "modified"),
                    **{name: find_own_text(record, name) for name in self.kind.fields},
                }
            )
        return found
