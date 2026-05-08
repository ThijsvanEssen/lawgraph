"""API route for TK publication full-text content."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas import (
    PublicationListResponse,
    PublicationSummary,
    PublicationTextResponse,
)
from lawgraph.config.settings import TK_BASE_URL
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_TK_DOCUMENT_RESOURCE = TK_BASE_URL.rstrip("/") + "/Document({external_id})/resource"


def _normalise_datum(props: dict) -> str | None:
    datum: str | None = props.get("datum")
    if datum is None:
        raw = props.get("raw") or {}
        datum = raw.get("Datum")
    if datum and "T" in str(datum):
        datum = str(datum).split("T")[0]
    return datum


@router.get("", response_model=PublicationListResponse)
def list_publications(
    store: Annotated[ArangoStore, Depends(get_store)],
    q: str | None = Query(None, description="Full-text filter op titel en soort."),
    soort: str | None = Query(
        None, description="Filter op documentsoort (exact match)."
    ),
) -> PublicationListResponse:
    """Return a list of all TK publications, optionally filtered.

    Intended for the publications index page; only lightweight metadata is
    returned (no full text).  With 372 documents the full list fits
    comfortably in a single response.
    """
    aql_filters = ['FILTER "TK" IN doc.labels']
    bind_vars: dict = {}

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

    filters_str = "\n    ".join(aql_filters)
    aql = f"""
FOR doc IN publications
    {filters_str}
    SORT doc.props.datum DESC, doc.props.title ASC
    LET linked = LENGTH(
        FOR e IN edges
            FILTER e._from == doc._id
            FILTER e.relation IN ["MENTIONS_ARTICLE", "EXPLAINS_ARTICLE", "CITES_ARTICLE"]
            RETURN 1
    )
    RETURN {{
        key: doc._key,
        title: doc.props.title,
        soort: doc.props.soort,
        datum: doc.props.datum,
        external_id: doc.props.external_id,
        has_text: doc.props.text != null,
        linked_articles: linked
    }}
"""
    rows = list(store.query(aql, bind_vars=bind_vars))

    items: list[PublicationSummary] = []
    for row in rows:
        datum = row.get("datum")
        if datum and "T" in str(datum):
            datum = str(datum).split("T")[0]
        items.append(
            PublicationSummary(
                key=row["key"],
                title=row.get("title") or None,
                soort=row.get("soort") or None,
                datum=datum,
                external_id=row.get("external_id") or None,
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
    doc = store.publications.get(key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Publication '{key}' not found.")

    props: dict = doc.get("props") or {}
    external_id: str | None = props.get("external_id")

    # Construct direct TK API resource URL when we have an external_id.
    tk_url: str | None = None
    if external_id:
        tk_url = _TK_DOCUMENT_RESOURCE.format(external_id=external_id)

    datum = _normalise_datum(props)

    return PublicationTextResponse(
        key=key,
        publication_id=doc["_id"],
        title=props.get("title"),
        soort=props.get("soort"),
        datum=datum,
        external_id=external_id,
        tk_url=tk_url,
        text=props.get("text"),
    )
