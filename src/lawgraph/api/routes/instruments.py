"""Instrument list endpoint — paginated catalogue of laws and regulations."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    INSTRUMENT_SORTS,
    get_instrument_article_history,
    get_instrument_articles,
    get_instrument_articles_at,
    get_instrument_dossiers,
    get_instrument_edges_bundle,
    get_instrument_judgments,
    get_instrument_related_instruments,
    get_instrument_versions,
    get_instruments_list,
)
from lawgraph.api.queries import props as _props
from lawgraph.api.schemas import (
    CitedArticleRef,
    InstrumentArticleNodeDTO,
    InstrumentArticlesAtResponse,
    InstrumentArticlesResponse,
    InstrumentArticleVersionDTO,
    InstrumentArticleVersionsResponse,
    InstrumentCitationEdge,
    InstrumentCitationsResponse,
    InstrumentDossierItem,
    InstrumentDossiersResponse,
    InstrumentJudgmentItem,
    InstrumentJudgmentsResponse,
    InstrumentListItemDTO,
    InstrumentListResponse,
    InstrumentRelatedItem,
    InstrumentRelatedResponse,
    InstrumentVersionDTO,
    InstrumentVersionsResponse,
)
from lawgraph.db import ArangoStore


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
    "instrument_articles": (
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
    "publications": (
        "soort",
        "titel",
        "title",
        "datum",
        "volgnummer",
        "dossier_nummer",
        "tk_url",
        "display_name",
    ),
    "kamerstukdossiers": (
        "kamerstuknummer",
        "titel",
        "display_name",
        "huidige_fase",
    ),
    "instruments": (
        "bwb_id",
        "display_name",
        "citation_title",
        "short_title",
    ),
}


# Articles loaded via stub fall back to a verbose display_name that bakes the
# full instrument title plus a trailing " (niet geladen)" marker. The FE
# label pipeline assembles its own "short_title + article_number" label, so
# we strip both the suffix and the long title here, leaving a clean
# "Artikel <num>" that callers can decorate.
_STUB_SUFFIX = " (niet geladen)"


def _clean_article_display_name(
    display_name: str | None, article_number: str | None
) -> str | None:
    if not display_name:
        return display_name
    name = display_name
    if name.endswith(_STUB_SUFFIX):
        name = name[: -len(_STUB_SUFFIX)].rstrip()
    # A typical stub label is "Artikel 5 <full instrument title>". Trim back
    # to the canonical "Artikel <num>" shape — the FE rebuilds the wet part
    # itself from short_title.
    if article_number:
        prefix = f"Artikel {article_number}"
        if name.lower().startswith(prefix.lower()):
            return prefix
    return name


def _minimise_node(doc: dict, collection: str) -> dict:
    """Project one side-payload node down to its whitelisted props."""
    props = _props(doc)
    whitelist = _NODE_FIELD_WHITELIST.get(collection, ())
    return {
        "id": doc.get("_id"),
        "key": doc.get("_key"),
        "collection": collection,
        "props": {k: props.get(k) for k in whitelist if k in props},
    }


def _minimise_articles_with_short_title(
    store: ArangoStore, docs: list[dict]
) -> list[dict]:
    """Project foreign articles, joining short_title from their parent wet.

    The graph-loader displays article labels as ``<short_title> <article_number>``
    (e.g. "Sr 287"). For articles outside the focal instrument we don't ship
    full text — but we *do* need the parent wet's short_title so the FE's
    label pipeline can render the friendly form without a second round-trip.
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

    # One AQL pass — uses the (props.bwb_id) and (props.celex) indexes.
    short_by_bwb: dict[str, str] = {}
    short_by_celex: dict[str, str] = {}
    if bwb_ids or celexes:
        for inst in store.query(
            """
            FOR i IN instruments
                FILTER i.props.bwb_id IN @bwbs OR i.props.celex IN @celexes
                RETURN {
                    bwb_id: i.props.bwb_id,
                    celex: i.props.celex,
                    short_title: i.props.short_title,
                    citation_title: i.props.citation_title
                }
            """,
            {"bwbs": list(bwb_ids), "celexes": list(celexes)},
        ):
            # Prefer short_title; fall back to citation_title when the wet
            # doesn't carry an abbreviated form.
            short = inst.get("short_title") or inst.get("citation_title")
            if not short:
                continue
            if inst.get("bwb_id"):
                short_by_bwb[inst["bwb_id"]] = short
            if inst.get("celex"):
                short_by_celex[inst["celex"]] = short

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
                "collection": "instrument_articles",
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


def _compute_article_diffs(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each version with a unified diff vs its predecessor (older version)."""
    import difflib

    # versions are newest-first; predecessor = next item in list
    result = []
    for i, doc in enumerate(versions):
        props = _props(doc)
        current_text = props.get("text") or ""
        if i + 1 < len(versions):
            prev_props = _props(versions[i + 1])
            prev_text = prev_props.get("text") or ""
        else:
            prev_text = ""
        if current_text != prev_text:
            diff_lines = list(
                difflib.unified_diff(
                    prev_text.splitlines(keepends=True),
                    current_text.splitlines(keepends=True),
                    lineterm="",
                )
            )
            diff = "".join(diff_lines) if diff_lines else None
        else:
            diff = None
        result.append({**doc, "_diff": diff})
    return result


router = APIRouter()


@router.get(
    "",
    response_model=InstrumentListResponse,
    summary="Gepagineerde lijst van instrumenten",
    description=(
        "Geeft een gepagineerde lijst van wetten, regelingen en EU-instrumenten. "
        "Ondersteunt vrije-tekstzoek (`q`), jurisdictie-filter (`nl`/`eu`), "
        "kind-filter en een minimum-artikelcount filter."
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


@router.get(
    "/{bwb_id}/articles",
    response_model=InstrumentArticlesResponse,
    summary="Alle artikelen van een instrument",
    description=(
        "Lijst van artikelen die bij dit BWB-instrument horen, gesorteerd op "
        "natuurlijke artikelnummering (Artikel 9 vóór Artikel 10, '24c' tussen "
        "'24' en '25'). Bedoeld voor graph-loaders; tekst is een korte preview, "
        "gebruik /api/articles/{bwb_id}/{article_number} voor de volledige inhoud."
    ),
    tags=["instruments"],
)
def list_instrument_articles(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    include_stubs: Annotated[
        bool,
        Query(description="Include placeholder/stub articles (default: false)"),
    ] = False,
    text_preview_chars: Annotated[
        int, Query(ge=0, le=600, description="Chars of text to inline as preview")
    ] = 160,
    limit: Annotated[int, Query(ge=1, le=2000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentArticlesResponse:
    docs, total = get_instrument_articles(
        store,
        bwb_id,
        include_stubs=include_stubs,
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
    summary="Alle edges incident op dit instrument (bulk)",
    description=(
        "Eén round-trip met alle edges die raken aan een artikel van deze wet: "
        "REFERS_TO_ARTICLE (intra + cross-wet), CITES_ARTICLE (jurisprudentie), "
        "WIJZIGT/INTRODUCEERT/TREKT_IN/LICHT_TOE (wetshistorie), enz. "
        "PART_OF_INSTRUMENT is standaard uitgesloten — dat is de structurele "
        "backbone, geen citatie. Naast `edges` levert dit endpoint ook een "
        "`nodes` side-payload met de buitenliggende eindpunten, gegroepeerd "
        "per collection."
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
                "Comma-separated whitelist van relaties. Default = alle, "
                "behalve PART_OF_INSTRUMENT."
            )
        ),
    ] = None,
    include_part_of_instrument: Annotated[
        bool,
        Query(description="Voeg de structurele article→instrument edges toe."),
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
        include_part_of_instrument=include_part_of_instrument,
        max_edges=max_edges,
    )
    raw_nodes = bundle.get("nodes") or {}
    minimised_nodes: dict[str, list[dict]] = {}
    for coll, docs in raw_nodes.items():
        if coll == "instrument_articles":
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
    summary="Alle uitspraken die dit instrument citeren",
    description=(
        "Per uitspraak: light metadata + de specifieke artikelen waarnaar "
        "verwezen wordt. Bedoeld voor de jurisprudentie-laag in de graph. "
        "``total`` is het absolute aantal (onafhankelijk van ``limit``)."
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
    summary="Kamerstukdossiers die deze wet raken",
    description=(
        "Combineert direct (dossier -RAAKT-> instrument) en afgeleid "
        "(kamerstuk wijzigt/introduceert/etc. een artikel). ``total`` is "
        "het absolute aantal (onafhankelijk van ``limit``)."
    ),
    tags=["instruments"],
)
def get_instrument_dossiers_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentDossiersResponse:
    rows, total = get_instrument_dossiers(store, bwb_id, limit=limit)
    items = [
        InstrumentDossierItem(
            id=d.get("_id") or "",
            key=d.get("_key") or "",
            kamerstuknummer=_props(d).get("kamerstuknummer"),
            titel=_props(d).get("titel"),
            display_name=_props(d).get("display_name"),
            huidige_fase=_props(d).get("huidige_fase"),
            geopend_op=_props(d).get("geopend_op"),
            afgedaan=_props(d).get("afgedaan"),
        )
        for d in rows
    ]
    return InstrumentDossiersResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/related-instruments",
    response_model=InstrumentRelatedResponse,
    summary="Andere instrumenten die hieraan refereren (of waarvan dit refereert)",
    description=(
        "Aggregatie van REFERS_TO_ARTICLE edges tussen artikelen van deze wet "
        "en artikelen van andere wetten. Per gerelateerd instrument staat "
        "`outbound_count` (refs vanuit deze wet naar de andere) en "
        "`inbound_count` (refs vanuit de andere wet naar deze). ``total`` is "
        "het absolute aantal (onafhankelijk van ``limit``)."
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
    summary="Historische versies van een instrument",
    description=(
        "Alle historische toestanden (versies) van een BWB-wet, gesorteerd van "
        "nieuwste naar oudste. Elke versie heeft een geldigheidsperiode "
        "(valid_from, valid_until). De huidige versie heeft ``current=true``."
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
    summary="Artikelen op een specifieke datum",
    description=(
        "Geeft alle artikelen van een BWB-instrument zoals ze golden op ``at_date`` "
        "(formaat YYYY-MM-DD). Gebruikt de historische versie-tabel; valt terug op "
        "lege lijst als er geen historische data beschikbaar is."
    ),
    tags=["instruments"],
)
def list_instrument_articles_at(
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
    docs = get_instrument_articles_at(store, bwb_id, at_date)
    items = [
        InstrumentArticleVersionDTO(
            key=d["_key"],
            bwb_id=_props(d).get("bwb_id", ""),
            article_number=_props(d).get("article_number", ""),
            valid_from=_props(d).get("valid_from"),
            valid_until=_props(d).get("valid_until"),
            current=bool(_props(d).get("current", False)),
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
    "/{bwb_id}/articles/{article_number}/history",
    response_model=InstrumentArticleVersionsResponse,
    summary="Historische versies van één artikel",
    description=(
        "Volledige versiegeschiedenis van één artikel, nieuwste versie eerst. "
        "Elk item bevat de artikeltekst en een ``diff`` ten opzichte van de "
        "vorige versie (unified diff formaat)."
    ),
    tags=["instruments"],
)
def get_article_version_history(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentArticleVersionsResponse:
    docs = get_instrument_article_history(store, bwb_id, article_number)
    annotated = _compute_article_diffs(docs)
    items = [
        InstrumentArticleVersionDTO(
            key=d["_key"],
            bwb_id=_props(d).get("bwb_id", ""),
            article_number=_props(d).get("article_number", ""),
            valid_from=_props(d).get("valid_from"),
            valid_until=_props(d).get("valid_until"),
            current=bool(_props(d).get("current", False)),
            text=_props(d).get("text"),
            diff=d.get("_diff"),
        )
        for d in annotated
    ]
    return InstrumentArticleVersionsResponse(
        bwb_id=bwb_id,
        article_number=article_number,
        items=items,
    )
