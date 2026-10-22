"""The official publications of KOOP as documents: one pipeline, a spec per publication
(the AMvBs in the Staatsblad, the ministerial regulations in the Staatscourant)."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from itertools import batched
from typing import Any, ClassVar

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.identifiers import find_bwb_id
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.publication_xml import publication_title
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.xml import find_text
from lawgraph.db import NodeWriter
from lawgraph.db.counting import Store
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


@dataclass(frozen=True)
class Parsed:
    """What every publication reads alike."""

    identifier: str
    year: str
    number: str
    title: str


@dataclass(frozen=True)
class PublicationSpec:
    """One publication: where its records are, what its documents are called, and how its
    text, date and display name are read."""

    source: str
    raw_kind: str
    publication: (
        str  # ``Staatsblad``: the title of a record without one, the first label
    )
    pattern: re.Pattern[
        str
    ]  # an identifier of it; group 1 the year, group 2 the number
    key_prefix: str
    label: str
    kind: str
    # the props of its own: ``text``, ``display_name`` and, when known, ``date``
    own_props: Callable[[ET.Element, Parsed], dict[str, Any]]
    # Of ``{identifier: bwb_id}``, the regulation retrieve fetched each publication for, the
    # identifiers whose regulation its source confirms names that publication; None: all.
    confirmed: Callable[[Store, Mapping[str, str]], set[str]] | None = None


# The records a claim of their regulation is checked for at once.
_CLAIMS_AT_ONCE = 200


class PublicationNormalizePipeline(NormalizePipelineBase[Records]):
    """A document per publication of the spec: its text, year, number, title and the
    regulation it belongs to (``bwb_id``: the one retrieve found it for, where the spec's
    source confirms it, else the first its text names)."""

    spec: ClassVar[PublicationSpec]

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=self.spec.source,
            kinds=[self.spec.raw_kind],
            since=since,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The document of every publication. No edges here: the semantic pipeline writes
        EXPLAINS."""
        count = 0
        writer = NodeWriter(self.store)
        for chunk in batched(raw, _CLAIMS_AT_ONCE, strict=False):
            claims = self._claims(chunk)
            for record in chunk:
                identifier = record.get("external_id") or ""
                text = payload_text(record)
                if not text:
                    self.progress.skip("no payload", identifier or record.get("key"))
                    continue
                node = self._parse_publication(identifier, text, claims.get(identifier))
                if node is None:
                    continue
                writer.add(node)
                count += 1
        writer.flush()
        logger.info(
            "%s normalize: %d publications processed.", self.spec.publication, count
        )

    def _claims(self, records: tuple[dict[str, Any], ...]) -> dict[str, str]:
        """``{identifier: bwb_id}``: the regulation retrieve fetched each of *records* for,
        where the spec's source confirms it (``PublicationSpec.confirmed``)."""
        claims = {
            identifier: bwb_id
            for record in records
            if (identifier := record.get("external_id"))
            and isinstance(bwb_id := meta(record).get("bwb_id"), str)
            and bwb_id
        }
        if not claims or self.spec.confirmed is None:
            return claims
        kept = self.spec.confirmed(self.store, claims)
        return {identifier: claims[identifier] for identifier in kept}

    def _parse_publication(
        self, identifier: str, xml_text: str, bwb_id: str | None = None
    ) -> Node | None:
        """The document of a publication's XML; None for XML that does not parse."""
        spec = self.spec
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.progress.fail("publication not XML", f"{identifier}: {exc}")
            return None

        if m := spec.pattern.search(identifier):
            year, number = m.group(1), m.group(2)
        else:
            year = find_text(root, "publicatiejaar") or ""
            number = find_text(root, "publicatienummer") or ""
        parsed = Parsed(
            identifier,
            year,
            number,
            publication_title(root, f"{spec.publication} {year}/{number}"),
        )
        props: dict[str, Any] = {
            "source": spec.source,
            "identifier": identifier,
            "kind": spec.kind,
            "title": parsed.title,
            "year": year,
            "number": number,
            **spec.own_props(root, parsed),
        }
        if bwb_id := bwb_id or find_bwb_id(xml_text):
            props["bwb_id"] = bwb_id
        return Node(
            collection=COLLECTION_DOCUMENTS,
            key=make_node_key(spec.key_prefix, identifier),
            labels=[spec.publication, spec.label],
            props=props,
        )
