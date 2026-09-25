"""Instrument list endpoint — paginated catalogue of laws and regulations."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.annexes import AnnexDTO, AnnexListItem
from lawgraph.api.schemas.common import ArticleRelationDTO, JudgmentSummaryDTO
from lawgraph.api.schemas.instruments import (
    AmendedByResponse,
    AmendingInstrumentDTO,
    CitedArticleRef,
    CrossLawDependenciesResponse,
    CrossLawDependencyItem,
    EuLinkDTO,
    InstrumentArticleNodeDTO,
    InstrumentArticlesAtResponse,
    InstrumentArticlesResponse,
    InstrumentArticleVersionDTO,
    InstrumentCitationEdge,
    InstrumentCitationsResponse,
    InstrumentDetailDTO,
    InstrumentDossierItem,
    InstrumentDossiersResponse,
    InstrumentEuLinksResponse,
    InstrumentJudgmentItem,
    InstrumentJudgmentsResponse,
    InstrumentListItemDTO,
    InstrumentListResponse,
    InstrumentRelatedItem,
    InstrumentRelatedResponse,
    InstrumentVersionDTO,
    InstrumentVersionsResponse,
    InternationalLinkDTO,
    LinkedInstrumentDTO,
    SharedAnnexesResponse,
)
from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.bwb_xml import article_label
from lawgraph.core.official_urls import article_url
from lawgraph.core.tk_links import tk_url
from lawgraph.db import ArangoStore
from lawgraph.db.queries._helpers import props as _props
from lawgraph.db.queries.annexes import get_shared_annexes_for_law
from lawgraph.db.queries.instrument_links import (
    get_eu_links,
    get_international_links,
)
from lawgraph.db.queries.instrument_scope import resolve_instrument, scope_of_node
from lawgraph.db.queries.instruments import (
    INSTRUMENT_SORTS,
    get_articles,
    get_articles_at,
    get_instrument_amended_by,
    get_instrument_dossiers,
    get_instrument_edges_bundle,
    get_instrument_judgments,
    get_instrument_related_instruments,
    get_instrument_versions,
    get_instruments_list,
    get_short_titles,
)
from lawgraph.db.queries.relationships import get_cross_law_dependencies


def _extract_judgment_item(row: dict) -> InstrumentJudgmentItem:
    judgment = row.get("judgment") or {}
    props = _props(judgment)
    return InstrumentJudgmentItem(
        id=judgment.get("_id") or "",
        key=judgment.get("_key") or "",
        ecli=props.get("ecli"),
        display_name=props.get("display_name"),
        cited_articles=[
            CitedArticleRef(**a) for a in (row.get("cited_articles") or [])
        ],
    )


# Field whitelists for the side-payload nodes on /citations. Kept lean so the
# graph-loader payload doesn't carry full article text or judgment paragraphs.
_NODE_FIELD_WHITELIST: dict[str, tuple[str, ...]] = {
    "articles": (
        "bwb_id",
        "celex",
        "article_number",
        "display_name",
        # ``short_title`` is not a real article prop — we lift it from the
        # article's parent instrument in _minimise_articles_with_short_title.
        # Listed here so the whitelist allows it through after enrichment.
        "short_title",
        "stub",
    ),
    "judgments": ("ecli", "display_name"),
    "documents": (
        "kind",
        "title",
        "date",
        "sequence",
        "dossier_number",
        "display_name",
    ),
    "dossiers": (
        "number",
        "label",
        "title",
        "display_name",
        "current_stage",
    ),
    "instruments": (
        "bwb_id",
        "celex",
        "display_name",
        "citation_title",
        "short_title",
    ),
}


# A stub article carries a verbose display_name that bakes in the full
# instrument title plus a trailing " (niet geladen)" marker. The frontend
# assembles its own "short_title + article_number" label, so both the suffix
# and the long title are stripped here, leaving a clean "Artikel <num>".
_STUB_SUFFIX = " (niet geladen)"


def _clean_article_display_name(
    display_name: str | None, article_number: str | None
) -> str | None:
    if not display_name:
        return display_name
    name = display_name
    if name.endswith(_STUB_SUFFIX):
        name = name[: -len(_STUB_SUFFIX)].rstrip()
    # A typical stub label is "Artikel 5 <full instrument title>". Trim back to
    # the canonical "Artikel <num>" shape — the frontend rebuilds the
    # instrument part itself from short_title.
    if article_number:
        prefix = article_label(article_number)
        if name.lower().startswith(prefix.lower()):
            return prefix
    return name


def _minimise_node(doc: dict, collection: str) -> dict:
    """Project one side-payload node down to its whitelisted props."""
    props = _props(doc)
    whitelist = _NODE_FIELD_WHITELIST.get(collection, ())
    kept = {k: props.get(k) for k in whitelist if k in props}
    link = tk_url(doc.get("type"), props)
    if link:
        kept["tk_url"] = link
    return {
        "id": doc.get("_id"),
        "key": doc.get("_key"),
        "collection": collection,
        "props": kept,
    }


def _minimise_articles_with_short_title(
    store: ArangoStore, docs: list[dict]
) -> list[dict]:
    """Project foreign articles, joining short_title from their parent instrument.

    The graph loader displays article labels as ``<short_title> <article_number>``
    (e.g. "Sr 287"). Articles outside the focal instrument ship without their
    full text, but they do need the parent instrument's short_title so the
    frontend can render the friendly label without a second round-trip.
    """
    if not docs:
        return []

    # Collect unique parent identifiers across this side payload.
    bwb_ids: set[str] = set()
    celexes: set[str] = set()
    for doc in docs:
        props = _props(doc)
        bwb = props.get("bwb_id")
        if isinstance(bwb, str) and bwb:
            bwb_ids.add(bwb)
        celex = props.get("celex")
        if isinstance(celex, str) and celex:
            celexes.add(celex)

    short_by_bwb, short_by_celex = get_short_titles(store, bwb_ids, celexes)

    enriched: list[dict] = []
    for doc in docs:
        props = _props(doc)
        article_number = props.get("article_number")
        bwb = props.get("bwb_id")
        celex = props.get("celex")
        short_title: str | None = None
        if isinstance(bwb, str) and bwb in short_by_bwb:
            short_title = short_by_bwb[bwb]
        elif isinstance(celex, str) and celex in short_by_celex:
            short_title = short_by_celex[celex]

        enriched.append(
            {
                "id": doc.get("_id"),
                "key": doc.get("_key"),
                "collection": COLLECTION_ARTICLES,
                "props": {
                    "bwb_id": bwb,
                    "celex": celex,
                    "article_number": article_number,
                    "display_name": _clean_article_display_name(
                        props.get("display_name"), article_number
                    ),
                    "short_title": short_title,
                    "stub": bool(props.get("stub", False)),
                },
            }
        )
    return enriched


router = APIRouter()


@router.get(
    "",
    response_model=InstrumentListResponse,
    summary="Paginated list of instruments",
    description=(
        "A paginated list of statutes, regulations and EU instruments. Supports "
        "free-text search (`q`), a jurisdiction filter (`nl`/`eu`), a kind "
        "filter and a minimum article count."
    ),
    tags=["instruments"],
)
def list_instruments(
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Free-text match")] = None,
    jurisdiction: Annotated[Literal["nl", "eu"] | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    article_count_min: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[Literal["title", "article_count"], Query()] = "title",
) -> InstrumentListResponse:
    if sort not in INSTRUMENT_SORTS:  # belt-and-braces; Literal already validates
        sort = "title"
    data = get_instruments_list(
        store,
        q=q,
        jurisdiction=jurisdiction,
        kind=kind,
        article_count_min=article_count_min,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [InstrumentListItemDTO.from_document(row) for row in data.get("items", [])]
    return InstrumentListResponse(items=items, total=int(data.get("total", 0)))


def _instrument_or_404(store: ArangoStore, identifier: str) -> dict:
    doc = resolve_instrument(store, identifier)
    if doc is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return doc


@router.get(
    "/{identifier}",
    response_model=InstrumentDetailDTO,
    summary="One instrument",
    description=(
        "The instrument named by its BWB id (`BWBR0001854`), its CELEX number "
        "(`32016L0680`) or its node key (`echr_convention`, `verdrag_012345`): "
        "identifiers, names, jurisdiction, kind, dates and article count. 404 for an "
        "unknown instrument."
    ),
    tags=["instruments"],
)
def get_instrument(
    identifier: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentDetailDTO:
    return InstrumentDetailDTO.from_document(_instrument_or_404(store, identifier))


def _international_link(
    row: dict, kind: Literal["treaty", "echr_judgment"]
) -> InternationalLinkDTO:
    """One `international` item from a treaty row or an ECHR judgment row."""
    edge = row.get("edge") or {}
    own = row.get("own_article")
    counterpart = row.get("counterpart_article")
    return InternationalLinkDTO(
        kind=kind,
        instrument=(
            LinkedInstrumentDTO.from_document(row["instrument"])
            if kind == "treaty"
            else None
        ),
        judgment=(
            JudgmentSummaryDTO.from_document(row["judgment"])
            if kind == "echr_judgment"
            else None
        ),
        own_article=CitedArticleRef(**own) if own else None,
        counterpart_article=CitedArticleRef(**counterpart) if counterpart else None,
        confidence=edge.get("confidence"),
        source=edge.get("source"),
        meta=edge.get("meta") or {},
    )


@router.get(
    "/{identifier}/eu-links",
    response_model=InstrumentEuLinksResponse,
    summary="EU and international links of an instrument",
    description=(
        "`implements`: EU acts whose CELEX number the text of this instrument names. "
        "`implemented_by`: national regulations that name the CELEX number of this EU "
        "act. Both are `IMPLEMENTS` edges between instruments, written from a CELEX "
        "number named in the text (`basis`): not a transposition relation, not per "
        "article. `international`: treaties (BWB treaties) that articles of this "
        "instrument refer to, and ECHR judgments that refer to it or to its articles, "
        "each with the evidence of its edge; the graph holds no other links to treaties "
        "or to the articles of the ECHR Convention from Dutch text. The instrument is "
        "named by BWB id, CELEX number or node key; 404 when unknown. `limit` bounds "
        "each list; the `*_total` fields are absolute."
    ),
    tags=["instruments"],
)
def get_instrument_eu_links(
    identifier: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentEuLinksResponse:
    doc = _instrument_or_404(store, identifier)
    eu = get_eu_links(store, doc["_id"], limit=limit)
    international = get_international_links(
        store, doc["_id"], scope_of_node(doc), limit=limit
    )
    links = [_international_link(r, "treaty") for r in international.treaties] + [
        _international_link(r, "echr_judgment") for r in international.judgments
    ]
    return InstrumentEuLinksResponse(
        instrument=LinkedInstrumentDTO.from_document(doc),
        implements=[EuLinkDTO.from_row(r) for r in eu.implements],
        implements_total=eu.implements_total,
        implemented_by=[EuLinkDTO.from_row(r) for r in eu.implemented_by],
        implemented_by_total=eu.implemented_by_total,
        international=links[:limit],
        international_total=international.treaties_total
        + international.judgments_total,
    )


@router.get(
    "/{bwb_id}/articles",
    response_model=InstrumentArticlesResponse,
    summary="All articles of an instrument",
    description=(
        "The articles in force of this instrument (BWB id or CELEX number), in the order "
        "of the document: an article with only a heading (the Algemene bepaling of the "
        "Grondwet) where it stands, an annex after the regulation. `include_repealed` "
        "adds the repealed identities (last). The text is a short preview; "
        "/api/articles/{bwb_id}/{address} has the full content."
    ),
    tags=["instruments"],
)
def list_articles(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    include_stubs: Annotated[
        bool,
        Query(description="Include placeholder/stub articles (default: false)"),
    ] = False,
    include_repealed: Annotated[
        bool,
        Query(
            description="Include the articles no longer in force: identities whose "
            "number another article has now, and articles their current version repeals."
        ),
    ] = False,
    text_preview_chars: Annotated[
        int, Query(ge=0, le=600, description="Chars of text to inline as preview")
    ] = 160,
    limit: Annotated[int, Query(ge=1, le=2000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentArticlesResponse:
    docs, total = get_articles(
        store,
        bwb_id,
        include_stubs=include_stubs,
        include_repealed=include_repealed,
        limit=limit,
        offset=offset,
    )
    return InstrumentArticlesResponse(
        bwb_id=bwb_id,
        total=total,
        items=[
            InstrumentArticleNodeDTO.from_document(
                d, text_preview_chars=text_preview_chars
            )
            for d in docs
        ],
    )


# ── Citation-graph bulk + per-layer endpoints ─────────────────────────────────


@router.get(
    "/{bwb_id}/citations",
    response_model=InstrumentCitationsResponse,
    summary="Every edge incident to this instrument (bulk)",
    description=(
        "One round-trip with every edge touching an article of this instrument: "
        "REFERS_TO (within and across laws), AMENDS / INTRODUCES / REPEALS and "
        "EXPLAINS (legislative history), and so on. PART_OF is excluded by "
        "default — it is the structural backbone, not a reference. Beside "
        "`edges` the endpoint returns a `nodes` side-payload with the outside "
        "endpoints, grouped per collection."
    ),
    tags=["instruments"],
)
def get_instrument_citations(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    relations: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated whitelist of relations. Default: every "
                "relation except PART_OF."
            )
        ),
    ] = None,
    include_part_of: Annotated[
        bool,
        Query(description="Include the structural article-to-instrument edges."),
    ] = False,
    max_edges: Annotated[int, Query(ge=1, le=100000)] = 20000,
) -> InstrumentCitationsResponse:
    relation_list = (
        [r.strip() for r in relations.split(",") if r.strip()] if relations else None
    )
    bundle = get_instrument_edges_bundle(
        store,
        bwb_id,
        relations=relation_list,
        include_part_of=include_part_of,
        max_edges=max_edges,
    )
    raw_nodes = bundle.get("nodes") or {}
    minimised_nodes: dict[str, list[dict]] = {}
    for coll, docs in raw_nodes.items():
        if coll == COLLECTION_ARTICLES:
            # Special-case: lift parent-wet short_title onto each article
            # and strip the stub-suffix from display_name so the FE label
            # path renders "Sr 287" without extra adapter code.
            minimised_nodes[coll] = _minimise_articles_with_short_title(store, docs)
        else:
            minimised_nodes[coll] = [_minimise_node(d, coll) for d in docs]
    edges = [
        InstrumentCitationEdge.model_validate(
            {
                "from": e["from"],
                "to": e["to"],
                "relation": e["relation"],
                "direction": e["direction"],
                "meta": e.get("meta"),
            }
        )
        for e in bundle["edges"]
    ]
    return InstrumentCitationsResponse(
        bwb_id=bundle["bwb_id"],
        article_count=bundle["article_count"],
        total_edges=bundle["total_edges"],
        edges=edges,
        nodes=minimised_nodes,
    )


@router.get(
    "/{bwb_id}/judgments",
    response_model=InstrumentJudgmentsResponse,
    summary="Every judgment citing this instrument",
    description=(
        "Per judgment: light metadata plus the specific articles it refers to. "
        "Meant for the case-law layer of the graph. ``total`` is the absolute "
        "count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_judgments_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentJudgmentsResponse:
    rows, total = get_instrument_judgments(store, bwb_id, limit=limit)
    items = [_extract_judgment_item(row) for row in rows]
    return InstrumentJudgmentsResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/dossiers",
    response_model=InstrumentDossiersResponse,
    summary="Parliamentary dossiers touching this law",
    description=(
        "Dossiers reached through LEGISLATED_IN from (a) the regulation itself "
        "and (b) the amending publications (Stb/Trb) that change, introduce or "
        "repeal one of its articles. ``via`` says how the dossier is linked "
        "(``instrument`` or ``amending_publication``; in the latter case "
        "``publication`` names the newest publication). ``total`` is the "
        "absolute count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_dossiers_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentDossiersResponse:
    rows, total = get_instrument_dossiers(store, bwb_id, limit=limit)
    items = []
    for row in rows:
        d = row["dossier"]
        items.append(
            InstrumentDossierItem(
                id=d.get("_id") or "",
                key=d.get("_key") or "",
                dossier_number=_props(d)["label"],
                title=_props(d).get("title"),
                display_name=_props(d).get("display_name"),
                stage=_props(d).get("current_stage"),
                opened_on=_props(d).get("opened_on"),
                closed=_props(d).get("closed"),
                via=row["via"],
                publication=row.get("publication"),
            )
        )
    return InstrumentDossiersResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/amended-by",
    response_model=AmendedByResponse,
    summary="Amending publications of a regulation",
    description=(
        "The amending instruments (Staatsblad, Tractatenblad, ...) that change, "
        "introduce or repeal articles of this regulation (AMENDS / INTRODUCES / "
        "REPEALS), newest first. Per publication: the edge count per kind, the "
        "number of articles affected, the first effective date and the "
        "dossiers. ``total`` is the absolute count, independent of ``limit`` "
        "and ``offset``."
    ),
    tags=["instruments"],
)
def get_instrument_amended_by_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AmendedByResponse:
    data = get_instrument_amended_by(store, bwb_id, limit=limit, offset=offset)
    items = [AmendingInstrumentDTO.from_row(r, data.dossier_titles) for r in data.items]
    return AmendedByResponse(bwb_id=bwb_id, total=data.total, items=items)


@router.get(
    "/{bwb_id}/related-instruments",
    response_model=InstrumentRelatedResponse,
    summary="Instruments referring to this one, or referred to by it",
    description=(
        "An aggregation of the REFERS_TO edges between articles of this law and "
        "articles of other laws. Each related instrument carries "
        "`outbound_count` (references from this law to the other) and "
        "`inbound_count` (references from the other law to this one). "
        "``total`` is the absolute count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_related_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> InstrumentRelatedResponse:
    rows, total = get_instrument_related_instruments(store, bwb_id, limit=limit)
    items = [
        InstrumentRelatedItem(
            id=(r.get("instrument") or {}).get("_id") or "",
            key=(r.get("instrument") or {}).get("_key") or "",
            bwb_id=((r.get("instrument") or {}).get("props") or {}).get("bwb_id"),
            celex=((r.get("instrument") or {}).get("props") or {}).get("celex"),
            display_name=((r.get("instrument") or {}).get("props") or {}).get(
                "display_name"
            ),
            citation_title=((r.get("instrument") or {}).get("props") or {}).get(
                "citation_title"
            ),
            outbound_count=int(r.get("outbound_count") or 0),
            inbound_count=int(r.get("inbound_count") or 0),
        )
        for r in rows
    ]
    return InstrumentRelatedResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/versions",
    response_model=InstrumentVersionsResponse,
    summary="Historical versions of an instrument",
    description=(
        "Every historical toestand (version) of a BWB law, newest first. Each "
        "version carries a validity period (valid_from, valid_until); the "
        "current one has ``current=true``."
    ),
    tags=["instruments"],
)
def list_instrument_versions(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentVersionsResponse:
    docs = get_instrument_versions(store, bwb_id)
    items = [InstrumentVersionDTO.from_document(d) for d in docs]
    return InstrumentVersionsResponse(bwb_id=bwb_id, total=len(items), items=items)


@router.get(
    "/{bwb_id}/articles/at/{at_date}",
    response_model=InstrumentArticlesAtResponse,
    summary="Articles as they stood on a given date",
    description=(
        "The articles of a BWB instrument as they applied on ``at_date`` "
        "(YYYY-MM-DD), read from the article versions. Empty when no version "
        "covers that date."
    ),
    tags=["instruments"],
)
def list_articles_at(
    bwb_id: str,
    at_date: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentArticlesAtResponse:
    try:
        dt.date.fromisoformat(at_date)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="at_date must be YYYY-MM-DD"
        ) from None
    docs = get_articles_at(store, bwb_id, at_date)
    items = [
        InstrumentArticleVersionDTO(
            key=d["_key"],
            bwb_id=_props(d).get("bwb_id", ""),
            article_number=_props(d).get("article_number", ""),
            valid_from=_props(d).get("valid_from"),
            valid_until=_props(d).get("valid_until"),
            current=bool(_props(d).get("current", False)),
            official_url=article_url(
                _props(d).get("bwb_id"),
                _props(d).get("article_number"),
                on=_props(d).get("valid_from"),
            ),
            text=_props(d).get("text"),
        )
        for d in docs
    ]
    return InstrumentArticlesAtResponse(
        bwb_id=bwb_id,
        at_date=at_date,
        total=len(items),
        items=items,
    )


@router.get(
    "/{bwb_id}/cross-law-dependencies",
    response_model=CrossLawDependenciesResponse,
    summary="References to articles of other laws",
    description=(
        "Article references from this law into articles of other laws, with "
        "the semantic type where one has been classified."
    ),
    tags=["instruments"],
)
def get_cross_law_dependencies_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> CrossLawDependenciesResponse:
    rows = get_cross_law_dependencies(store, bwb_id, limit=limit)
    dependencies = [
        CrossLawDependencyItem(
            source_article=ArticleRelationDTO.from_documents(
                row["source_article"], None
            ),
            target_article=ArticleRelationDTO.from_documents(row["target"], None),
            semantic_type=(row.get("edge") or {}).get("semantic_type"),
            explanation=(row.get("edge") or {}).get("explanation"),
            confidence=(row.get("edge") or {}).get("confidence"),
        )
        for row in rows
    ]
    return CrossLawDependenciesResponse(bwb_id=bwb_id, dependencies=dependencies)


@router.get(
    "/{bwb_id}/shared-annexes",
    response_model=SharedAnnexesResponse,
    summary="Annexes shared with other laws",
    description=(
        "The annexes connecting this law to others: its own annexes that other "
        "laws refer to, and annexes of other laws that articles of this law "
        "refer to."
    ),
    tags=["instruments"],
)
def get_shared_annexes_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> SharedAnnexesResponse:
    rows = get_shared_annexes_for_law(store, bwb_id)
    items = [
        AnnexListItem(
            annex=AnnexDTO.from_document(row["annex"]),
            referencing_laws=list(row.get("referencing_laws") or []),
        )
        for row in rows
    ]
    return SharedAnnexesResponse(bwb_id=bwb_id, annexes=items)
