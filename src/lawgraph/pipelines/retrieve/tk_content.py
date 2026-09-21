"""Pipeline that fetches the text of Tweede Kamer papers as XML and stores it in props.text.

Only papers whose kind contains a substring (default ``toelichting``) qualify: the ones that
feed the memorandum context (``mvt-articles``, ``amendment-articles``), not the whole corpus.
The Tweede Kamer's own API serves only a PDF; the KOOP repository has the same paper as
structured XML, filed under its dossier.

Flow:
    1. Query papers WHERE kind CONTAINS filter AND props.text IS NULL, with the dossier they
       are part of (number and addition) and their number in it
    2. Build the identifier ``kst-<dossier>-<number>`` and fetch its XML
    3. Take the plain text of the XML
    4. Store it via AQL MERGE so the other props are untouched, one paper at a time
    5. Report created / skipped / error counts
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    RELATION_PART_OF,
)
from lawgraph.core.identifiers import kamerstuk_identifier
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.core.xml import text_of
from lawgraph.db import ArangoStore
from lawgraph.pipelines.base import PipelineBase
from lawgraph.pipelines.retrieve.base import (
    MISSING_FOR_DAYS,
    FailureStreak,
    SourceDown,
    add_outcome,
    failure_reason,
)

logger = get_logger(__name__)

# kind substrings that qualify a publication for text hydration
_DEFAULT_KIND_FILTER = "toelichting"

# Hard cap on stored text (chars). The semantic pipelines have their own read caps; storing
# more lets us raise those later without fetching again.
_STORE_TEXT_LIMIT = 500_000


def xml_text(xml: str) -> str | None:
    """The plain text of a Kamerstuk XML, or ``None`` for XML without any text.

    Raises ``ET.ParseError`` for a document that is not XML: that must not pass for an empty
    paper.
    """
    root = ET.fromstring(xml.lstrip("﻿"))
    return text_of(root, " ").strip() or None


class TKContentRetrievePipeline(PipelineBase):
    """Fetch and store the text of Tweede Kamer papers from their XML.

    Only papers whose ``props.kind`` contains *kind_filter* (case-insensitive) and that do
    not yet have ``props.text`` are processed.
    """

    def __init__(
        self,
        *,
        store: ArangoStore,
        client: KamerstukClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    # ── public ────────────────────────────────────────────────────────────────

    def run(
        self,
        *,
        kind_filter: str = _DEFAULT_KIND_FILTER,
        dry_run: bool = False,
        papers: list[dict[str, Any]] | None = None,
    ) -> PipelineResult:
        """Hydrate text for all qualifying papers.

        Args:
            kind_filter: Case-insensitive substring matched against ``props.kind``.
            dry_run: When True, log what would happen but make no changes.
            papers: What ``unhydrated`` answered, when the caller asked already.
        """
        result = PipelineResult()
        if papers is None:
            papers = self.unhydrated(kind_filter)

        if not papers:
            logger.info("No unhydrated papers found for kind filter '%s'.", kind_filter)
            return result

        logger.info(
            "Fetching the XML of %d papers (kind contains '%s')%s.",
            len(papers),
            kind_filter,
            " — DRY RUN" if dry_run else "",
        )

        progress = self.progress = Progress("papers", total=len(papers))
        streak = FailureStreak("Kamerstuk XML")
        try:
            for paper in papers:
                identifier = kamerstuk_identifier(
                    paper["number"], paper.get("suffix"), paper["sequence"]
                )
                if dry_run:
                    progress.skip("dry run", identifier)
                    continue
                self._hydrate_one(paper, identifier, streak)
        except SourceDown as exc:
            logger.error(str(exc))
            down = [str(exc)]
        else:
            down = []
        finally:
            progress.finish()

        result.created = progress.done
        add_outcome(result, progress)
        result.errors.extend(down)
        return result

    def unhydrated(self, kind_filter: str) -> list[dict[str, Any]]:
        """Papers without text, with the dossier they belong to (a paper without one is left).

        Also what ``fill-gaps`` reports: a report from a query of its own listed the papers
        this one leaves out (no dossier, no sequence, a text that was missing last month).
        """
        aql = f"""
            FOR pub IN {COLLECTION_DOCUMENTS}
                FILTER "TK" IN pub.labels
                FILTER CONTAINS(LOWER(pub.props.kind || ""), @kind)
                FILTER pub.props.text == null OR pub.props.text == ""
                FILTER pub.props.text_missing_at == null
                    OR pub.props.text_missing_at < @missing_before
                FILTER pub.props.sequence != null
                LET dossier = FIRST(
                    FOR e IN {COLLECTION_EDGES}
                        FILTER e._from == pub._id AND e.relation == @part_of
                        FILTER STARTS_WITH(e._to, "{COLLECTION_DOSSIERS}/")
                        FOR d IN {COLLECTION_DOSSIERS}
                            FILTER d._id == e._to
                            RETURN d
                )
                FILTER dossier != null AND dossier.props.number != null
                RETURN {{
                    key: pub._key,
                    title: pub.props.title || pub.props.display_name || pub._key,
                    number: dossier.props.number,
                    suffix: dossier.props.suffix,
                    sequence: pub.props.sequence
                }}
        """
        missing_before = iso_timestamp(_now() - dt.timedelta(days=MISSING_FOR_DAYS))
        bind = {
            "kind": kind_filter.lower(),
            "part_of": RELATION_PART_OF,
            "missing_before": missing_before,
        }
        return list(self.store.query(aql, bind))

    def _hydrate_one(
        self, paper: dict[str, Any], identifier: str, streak: FailureStreak
    ) -> None:
        progress = self.progress
        try:
            xml = self.client.fetch_kamerstuk_xml(identifier)
        except Exception as exc:
            progress.fail(f"download failed ({failure_reason(exc)})", identifier)
            streak.failed(identifier, exc)
            return
        streak.ok()

        if xml is None:
            progress.skip("no XML in the repository (HTTP 404)", identifier)
            self._set_prop(paper["key"], "text_missing_at", iso_timestamp(_now()))
            return
        try:
            text = xml_text(xml)
        except ET.ParseError:
            progress.fail("the XML cannot be read", identifier)
            return
        if not text:
            progress.skip("no text in the XML", identifier)
            return

        if len(text) > _STORE_TEXT_LIMIT:
            progress.note(
                f"text longer than {_STORE_TEXT_LIMIT:,} chars; storing the first part",
                identifier,
            )
            text = text[:_STORE_TEXT_LIMIT]
        self._set_prop(paper["key"], "text", text)
        progress.ok()

    def _set_prop(self, key: str, name: str, value: str) -> None:
        """Set one prop of the paper without touching the others."""
        aql = f"""
            FOR pub IN {COLLECTION_DOCUMENTS}
                FILTER pub._key == @key
                UPDATE pub WITH {{props: {{[@name]: @value}}}} IN {COLLECTION_DOCUMENTS}
        """
        # Consume the cursor (even though it returns nothing useful).
        list(self.store.query(aql, {"key": key, "name": name, "value": value}))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
