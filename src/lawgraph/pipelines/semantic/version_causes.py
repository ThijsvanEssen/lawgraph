"""Semantic pipeline that links publications to the article versions they caused.

For each instrument_article_version, finds TK/EK publications with a
WIJZIGT/INTRODUCEERT/TREKT_IN edge to the corresponding current article and
whose datum is closest to (but not after) the version's valid_from.  Creates a
CAUSED_VERSION edge from that publication to the article_version.

The date window (default 365 days) prevents false positives where an old
amendment proposal is mistakenly linked to a much later version.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_PUBLICATIONS,
    EDGE_STATUS_CANONIEK,
    RELATION_CAUSED_VERSION,
    RELATION_INTRODUCEERT,
    RELATION_TREKT_IN,
    RELATION_WIJZIGT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db import _edge_key as _sha1_edge_key
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

_AMENDMENT_RELATIONS = [RELATION_WIJZIGT, RELATION_INTRODUCEERT, RELATION_TREKT_IN]
_DEFAULT_WINDOW_DAYS = 365


class VersionCausesSemanticPipeline(PipelineBase):
    """Create CAUSED_VERSION edges from publications to instrument_article_versions.

    For each (bwb_id, article_number, valid_from) version node, this pipeline
    finds the publication whose datum is closest-but-not-after valid_from among
    all publications that have a WIJZIGT/INTRODUCEERT/TREKT_IN edge to the
    current article with the same bwb_id/article_number.
    """

    def __init__(
        self, *, store: ArangoStore, window_days: int = _DEFAULT_WINDOW_DAYS
    ) -> None:
        super().__init__(store)
        self.window_days = window_days

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        linked = self._link_versions(since=since)
        result.created = linked
        logger.info(
            "VersionCausesSemanticPipeline: %d CAUSED_VERSION edges created/updated.",
            linked,
        )
        return result

    def _link_versions(self, *, since: dt.datetime | None) -> int:
        """Create CAUSED_VERSION edges by starting from amendment edges (not article versions).

        Inverted approach: iterate the small set of WIJZIGT/INTRODUCEERT/TREKT_IN edges
        (O(hundreds)) rather than all article versions (O(hundreds of thousands)), then
        for each publication find the earliest article version it could have caused.
        """
        since_filter = ""
        bind_vars: dict[str, Any] = {
            "window_days": self.window_days,
            "relations": _AMENDMENT_RELATIONS,
        }
        if since:
            since_filter = "FILTER pub.props.datum >= @since"
            bind_vars["since"] = since.date().isoformat()

        # For each amendment edge (pub → article), find the earliest article version
        # whose valid_from is in [pub.datum, pub.datum + window_days].
        # That version is the one the publication most likely caused.
        aql = f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation IN @relations
            LET art = DOCUMENT(e._to)
            FILTER art != null
            FILTER art.props.bwb_id != null AND art.props.article_number != null
            FOR pub IN {COLLECTION_PUBLICATIONS}
                FILTER pub._id == e._from
                FILTER pub.props.datum != null
                {since_filter}
                // Find the first article version that took effect after this publication,
                // within the allowed window (published before the version, not too long before)
                LET versions = (
                    FOR av IN {COLLECTION_INSTRUMENT_ARTICLE_VERSIONS}
                        FILTER av.props.bwb_id == art.props.bwb_id
                        FILTER av.props.article_number == art.props.article_number
                        FILTER av.props.valid_from != null AND av.props.valid_from != "unknown"
                        FILTER av.props.valid_from >= pub.props.datum
                        FILTER DATE_DIFF(pub.props.datum, av.props.valid_from, "d") <= @window_days
                        SORT av.props.valid_from ASC
                        LIMIT 1
                        RETURN av._id
                )
                FILTER LENGTH(versions) > 0
                RETURN {{
                    av_id: versions[0],
                    pub_id: pub._id,
                    datum: pub.props.datum
                }}
        """

        edge_docs: list[dict[str, Any]] = []
        for row in self.store.query(aql, bind_vars):
            av_id = row.get("av_id")
            pub_id = row.get("pub_id")
            if not av_id or not pub_id:
                continue
            edge_docs.append(
                {
                    "_key": _sha1_edge_key(pub_id, RELATION_CAUSED_VERSION, av_id),
                    "_from": pub_id,
                    "_to": av_id,
                    "relation": RELATION_CAUSED_VERSION,
                    "source": "version-causes",
                    "status": EDGE_STATUS_CANONIEK,
                    "meta": {},
                }
            )

        if not edge_docs:
            return 0

        _BATCH_SIZE = 500
        created_total = 0
        for start in range(0, len(edge_docs), _BATCH_SIZE):
            batch = edge_docs[start : start + _BATCH_SIZE]
            try:
                created, _ = self.store.bulk_insert_or_update_edges(batch)
                created_total += created
            except Exception as exc:
                logger.error("CAUSED_VERSION edge batch failed: %s", exc)
                raise

        return created_total
