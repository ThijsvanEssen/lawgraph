"""API route for TK publication full-text content."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas import (
    PublicationListResponse,
    PublicationSummary,
    PublicationTextResponse,
)
from lawgraph.config.constants import (
    RELATION_CITES_ARTICLE,
    RELATION_EXPLAINS_ARTICLE,
    RELATION_MENTIONS_ARTICLE,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.time import strip_time_component
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get("", response_model=PublicationListResponse)
def list_publications(
    store: Annotated[ArangoStore, Depends(get_store)],
    q: str | None = Query(None, description="Full-text filter op titel en soort."),
    soort: str | None = Query(
        None, description="Filter op documentsoort (exact match)."
    ),
    chamber: str | None = Query(
        None,
        description="Filter op kamer: 'TK' voor Tweede Kamer, 'EK' voor Eerste Kamer.",
    ),
    source: str | None = Query(
        None,
        description="Filter op bron (props.source), e.g. 'eerstekamer', 'staatscourant'.",
    ),
) -> PublicationListResponse:
    """Return a paginated list of publications across all sources.

    Intended for the publications index page; only lightweight metadata is
    returned (no full text).
    """
    aql_filters: list[str] = []
    bind_vars: dict = {}

    if chamber:
        aql_filters.append("FILTER @chamber IN doc.labels")
        bind_vars["chamber"] = chamber.upper()

    if source:
        aql_filters.append("FILTER doc.props.source == @source")
        bind_vars["source"] = source

    if soort:
        aql_filters.append("FILTER doc.props.soort == @soort")
        bind_vars["soort"] = soort

    if q:
        # Simple case-insensitive contains search on title.
        aql_filters.append(
            "FILTER CONTAINS(LOWER(doc.props.title), LOWER(@q))"
            " OR CONTAINS(LOWER(doc.props.soort), LOWER(@q))"
        )
        bind_vars["q"] = q

    bind_vars["r_mentions"] = RELATION_MENTIONS_ARTICLE
    bind_vars["r_explains"] = RELATION_EXPLAINS_ARTICLE
    bind_vars["r_cites"] = RELATION_CITES_ARTICLE

    filters_str = "\n    ".join(aql_filters)
    aql = f"""
FOR doc IN publications
    {filters_str}
    SORT doc.props.datum DESC, doc.props.title ASC
    LET linked = LENGTH(
        FOR e IN edges
            FILTER e._from == doc._id
            FILTER e.relation IN [@r_mentions, @r_explains, @r_cites]
            RETURN 1
    )
    RETURN {{
        key: doc._key,
        title: doc.props.title,
        soort: doc.props.soort,
        datum: doc.props.datum,
        external_id: doc.props.external_id,
        source: doc.props.source,
        has_text: doc.props.text != null,
        linked_articles: linked
    }}
"""
    rows = list(store.query(aql, bind_vars=bind_vars))

    items: list[PublicationSummary] = []
    for row in rows:
        datum = strip_time_component(row.get("datum"))
        items.append(
            PublicationSummary(
                key=row["key"],
                title=row.get("title") or None,
                soort=row.get("soort") or None,
                datum=datum,
                external_id=row.get("external_id") or None,
                source=row.get("source") or None,
                has_text=bool(row.get("has_text")),
                linked_articles=int(row.get("linked_articles") or 0),
            )
        )

    return PublicationListResponse(total=len(items), items=items)


@router.get("/{key}", response_model=PublicationTextResponse)
def get_publication_text(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> PublicationTextResponse:
    """Return the full-text content of a TK publication.

    *key* is the ArangoDB document key (UUID with underscores, e.g.
    ``cd4beed6_f8c4_45ad_a2d3_2d638c08b96a``).

    The ``text`` field contains the plain text extracted from the source PDF.
    It is ``null`` when the hydration pipeline has not yet run for this
    document (e.g. scanned PDFs without a text layer).
    """
    # Publication keys are sanitised to lowercase at ingest; accept any case.
    raw_doc = store.publications.get(key.lower())
    if raw_doc is None:
        raise HTTPException(status_code=404, detail=f"Publication '{key}' not found.")

    doc = cast(dict, raw_doc)
    return PublicationTextResponse.from_document(doc)
