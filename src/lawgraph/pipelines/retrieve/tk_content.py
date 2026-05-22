"""Pipeline that fetches full-text content for TK publications and stores it in props.text.

Only targets publication types whose soort contains a configured substring
(default: "toelichting"), so we only download the documents that actually feed
the MvT-context endpoint — not the full ~400-document corpus.

Flow:
    1. Query publications WHERE soort CONTAINS filter AND props.text IS NULL
    2. For each: fetch binary from TK API (Document({id})/resource)
    3. Extract text from PDF (pdfminer.six)
    4. Store text via AQL MERGE so other props are untouched
    5. Report created / skipped / error counts
"""

from __future__ import annotations

import time
from io import BytesIO
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

logger = get_logger(__name__)

# soort substrings that qualify a publication for text hydration
_DEFAULT_SOORT_FILTER = "toelichting"

# Hard cap on stored text (chars).  The semantic pipeline has its own read cap
# (_MAX_TEXT_LENGTH = 40 000), but storing more lets us raise that cap later
# without re-fetching.
_STORE_TEXT_LIMIT = 500_000

# Seconds to wait between TK API calls to avoid hammering the endpoint
_RATE_LIMIT_SLEEP = 0.5


def _extract_pdf_text(content: bytes) -> str | None:
    """Return plain text extracted from *content* (PDF bytes), or None on failure."""
    try:
        from pdfminer.high_level import extract_text  # lazy import

        text = extract_text(BytesIO(content)).strip()
        return text if text else None
    except Exception as exc:
        logger.debug("PDF text extraction failed: %s", exc)
        return None


class TKTextHydratePipeline:
    """Fetch and store full-text content for TK publications.

    Only publications whose ``props.soort`` contains *soort_filter* (case-
    insensitive) and that do not yet have ``props.text`` are processed.
    """

    def __init__(
        self,
        *,
        store: ArangoStore,
        tk_client: TKClient | None = None,
    ) -> None:
        self.store = store
        self.tk = tk_client or TKClient()

    # ── public ────────────────────────────────────────────────────────────────

    def run(
        self,
        *,
        soort_filter: str = _DEFAULT_SOORT_FILTER,
        dry_run: bool = False,
    ) -> PipelineResult:
        """Hydrate text for all qualifying publications.

        Args:
            soort_filter: Case-insensitive substring matched against
                ``props.soort``.  Defaults to ``"toelichting"``.
            dry_run: When True, log what would happen but make no changes.
        """
        result = PipelineResult()
        publications = self._query_unhydrated(soort_filter)

        if not publications:
            logger.info(
                "No unhydrated publications found for soort filter '%s'.", soort_filter
            )
            return result

        logger.info(
            "Hydrating text for %d publications (soort contains '%s')%s.",
            len(publications),
            soort_filter,
            " — DRY RUN" if dry_run else "",
        )

        for pub in publications:
            key = pub.get("_key", "")
            props: dict[str, Any] = pub.get("props") or {}
            external_id: str | None = props.get("external_id")
            title = props.get("title") or props.get("display_name") or key

            if not external_id:
                logger.debug("Skipping publication %s — no external_id.", key)
                result.skipped += 1
                continue

            if dry_run:
                logger.info("DRY RUN: would fetch %s (%s)", external_id, title)
                result.skipped += 1
                continue

            self._hydrate_one(key, external_id, title, result)
            time.sleep(_RATE_LIMIT_SLEEP)

        logger.info("TK content hydration: %s.", result.summary())
        return result

    # ── private ───────────────────────────────────────────────────────────────

    def _query_unhydrated(self, soort_filter: str) -> list[dict[str, Any]]:
        aql = """
            FOR pub IN publications
                FILTER CONTAINS(LOWER(pub.props.soort), @soort)
                    AND (pub.props.text == null OR pub.props.text == "")
                    AND pub.props.external_id != null
                RETURN pub
        """
        return list(self.store.query(aql, {"soort": soort_filter.lower()}))

    def _hydrate_one(
        self,
        key: str,
        external_id: str,
        title: str,
        result: PipelineResult,
    ) -> None:
        try:
            logger.info("Fetching %s — %s", external_id, title[:80])
            content = self.tk.fetch_document_bytes(external_id)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", external_id, exc)
            result.errors.append(f"{external_id}: fetch failed — {exc}")
            return

        text = _extract_pdf_text(content)
        if not text:
            logger.warning(
                "No text extracted from %s (content length=%d).",
                external_id,
                len(content),
            )
            result.skipped += 1
            return

        text = text[:_STORE_TEXT_LIMIT]
        self._store_text(key, text)
        logger.info(
            "Stored %d chars for %s (%s).",
            len(text),
            external_id,
            title[:60],
        )
        result.created += 1

    def _store_text(self, key: str, text: str) -> None:
        """Merge props.text into the publication without touching other props."""
        aql = """
            FOR pub IN publications
                FILTER pub._key == @key
                UPDATE pub WITH {props: MERGE(pub.props, {text: @text})} IN publications
        """
        # Consume the cursor (even though it returns nothing useful).
        list(self.store.query(aql, {"key": key, "text": text}))
