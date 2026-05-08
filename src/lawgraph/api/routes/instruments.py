from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    InstrumentStats,
    get_instrument_graph,
    get_instrument_history,
    get_instrument_index,
    get_instrument_publications,
    get_instrument_reader,
)
from lawgraph.api.schemas import (
    ArticleGraphNodeDTO,
    GraphEdgeDTO,
    InstrumentGraphResponse,
    InstrumentIndexResponse,
    InstrumentProceduresResponse,
    InstrumentPublicationLinkDTO,
    InstrumentPublicationsResponse,
    InstrumentReaderResponse,
    InstrumentSummaryDTO,
    JudgmentGraphNodeDTO,
    ParliamentaryProcedureDTO,
    ReaderArticleDTO,
)
from lawgraph.config.settings import (
    RELATION_CITES_ARTICLE,
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_INSTRUMENT,
    RELATION_REFERS_TO_ARTICLE,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import make_node_key

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=InstrumentIndexResponse,
    summary="Alle instrumenten met geaggregeerde statistieken",
    description=(
        "Geeft alle instrumenten (NL en EU) terug als een platte lijst, elk aangevuld met "
        "geaggregeerde statistieken: aantal artikelen, aantal uitspraken dat het instrument "
        "citeert, en inkomende/uitgaande inter-wet citaties. "
        "Geen artikelen of edges — geschikt voor overzichtstabellen en picker-UIs."
    ),
    tags=["instruments"],
)
def get_instrument_index_route(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentIndexResponse:
    data = get_instrument_index(store)
    instruments = [
        InstrumentSummaryDTO.from_document(doc, stats=data.stats.get(doc["_id"]))
        for doc in data.instruments
    ]
    return InstrumentIndexResponse(
        instruments=instruments,
        total=len(instruments),
        metadata=data.metadata,
    )


@router.get(
    "/{bwb_id}/graph",
    response_model=InstrumentGraphResponse,
    summary="Bulk instrument graph — alle artikelen + intra-wet citaties",
    description=(
        "Geeft alle artikelen van het instrument plus alle `REFERS_TO_ARTICLE`-edges "
        "tussen die artikelen terug als één payload. Vermijdt N round-trips vanuit de client."
    ),
    tags=["instruments"],
)
def get_instrument_graph_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentGraphResponse:
    try:
        data = get_instrument_graph(store, bwb_id)
    except ValueError as err:
        logger.debug("Instrument %s not found", bwb_id)
        raise HTTPException(status_code=404, detail="Instrument not found") from err

    articles = [ArticleGraphNodeDTO.from_document(doc) for doc in data.articles]
    judgments = [JudgmentGraphNodeDTO.from_document(doc) for doc in data.judgments]
    edges = [
        GraphEdgeDTO(
            from_id=e.from_id,
            to_id=e.to_id,
            relation_type=e.relation_type,
            start=e.start,
            end=e.end,
            text=e.text,
            confidence=e.confidence,
        )
        for e in data.edges
    ]

    related_instruments = [
        InstrumentSummaryDTO.from_document(doc) for doc in data.related_instruments
    ]

    return InstrumentGraphResponse(
        instrument=InstrumentSummaryDTO.from_document(data.instrument),
        articles=articles,
        judgments=judgments,
        edges=edges,
        related_instruments=related_instruments,
        citation_title=data.metadata.get("citation_title"),
        metadata=data.metadata,
    )


@router.get(
    "/{bwb_id}/reader",
    response_model=InstrumentReaderResponse,
    summary="Leesweergave — alle artikelen in volgorde met volledige tekst en sectiecontext",
    description=(
        "Geeft alle artikelen van het instrument terug in natuurlijke leesvolgorde "
        "(artikel 1, 1a, 2, … 10), inclusief volledige tekst, leden en breadcrumb "
        "(boek/titeldeel/hoofdstuk/afdeling/paragraaf). Bedoeld voor een reader-view."
    ),
    tags=["instruments"],
)
def get_instrument_reader_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentReaderResponse:
    try:
        data = get_instrument_reader(store, bwb_id)
    except ValueError as err:
        logger.debug("Instrument %s not found", bwb_id)
        raise HTTPException(status_code=404, detail="Instrument not found") from err

    instrument_id = data.instrument.get("_id", "")
    history_entries = (
        get_instrument_history(store, instrument_id) if instrument_id else []
    )
    history = [
        ParliamentaryProcedureDTO.from_entry(e.procedure, e.publications)
        for e in history_entries
    ]

    return InstrumentReaderResponse(
        instrument=InstrumentSummaryDTO.from_document(data.instrument),
        articles=[ReaderArticleDTO.from_document(doc) for doc in data.articles],
        history=history,
        citation_title=data.metadata.get("citation_title"),
        metadata=data.metadata,
    )


@router.get(
    "/{bwb_id}/procedures",
    response_model=InstrumentProceduresResponse,
    summary="TK-procedures die dit instrument hebben gewijzigd",
    description=(
        "Geeft alle Tweede Kamer-zaken (procedures) terug die via AMENDS_INSTRUMENT "
        "aan dit instrument zijn gekoppeld, elk met hun bijbehorende publicaties."
    ),
    tags=["instruments"],
)
def get_instrument_procedures_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentProceduresResponse:
    instrument_id = f"instruments/{make_node_key(bwb_id)}"
    entries = get_instrument_history(store, instrument_id)
    procedures = [
        ParliamentaryProcedureDTO.from_entry(e.procedure, e.publications)
        for e in entries
    ]
    return InstrumentProceduresResponse(
        instrument_id=instrument_id,
        procedures=procedures,
        total=len(procedures),
    )


@router.get(
    "/{bwb_id}/publications",
    response_model=InstrumentPublicationsResponse,
    summary="TK-publicaties die dit instrument noemen of wijzigen",
    description=(
        "Geeft Tweede Kamer-publicaties terug die dit instrument noemen (`mentions`) "
        "of wijzigen (`amends`). Gebruik de query-parameter `relation` om te filteren."
    ),
    tags=["instruments"],
)
def get_instrument_publications_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    relation: Annotated[
        str | None,
        Query(description="Filter op 'amends' of 'mentions'. Leeg = beide."),
    ] = None,
) -> InstrumentPublicationsResponse:
    instrument_id = f"instruments/{make_node_key(bwb_id)}"
    entries = get_instrument_publications(store, instrument_id, relation=relation)
    publications = [
        InstrumentPublicationLinkDTO.from_entry(e.publication, e.relation)
        for e in entries
    ]
    return InstrumentPublicationsResponse(
        instrument_id=instrument_id,
        publications=publications,
        total=len(publications),
    )


@router.get(
    "/{bwb_id}",
    response_model=InstrumentSummaryDTO,
    summary="Instrument metadata met statistieken — geen artikelen",
    description=(
        "Geeft metadata van één instrument (bwb_id of celex) terug, inclusief "
        "geaggregeerde statistieken (artikelcount, uitspraakcount, citaties). "
        "Geen artikelen geladen — gebruik `/{bwb_id}/graph` of `/{bwb_id}/reader` "
        "als je de volledige inhoud nodig hebt."
    ),
    tags=["instruments"],
)
def get_instrument_detail_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentSummaryDTO:
    # Fetch the instrument document (same lookup as get_instrument_graph).
    instrument_key = bwb_id.lower()
    db = store.db
    doc = db.collection("instruments").get(instrument_key)
    if doc is None:
        # Try by bwb_id prop or celex prop.
        rows = list(
            store.query(
                """
                FOR inst IN instruments
                    FILTER inst.props.bwb_id == @id OR inst.props.celex == @id
                    LIMIT 1 RETURN inst
                """,
                {"id": bwb_id},
            )
        )
        doc = rows[0] if rows else None
    if doc is None:
        raise HTTPException(status_code=404, detail="Instrument not found")

    inst_id = doc["_id"]

    # Compute per-instrument stats in a single AQL (no art_inst needed for counts).
    aql = """
        LET art_inst = MERGE(
            FOR e IN edges FILTER e.relation == @part_of RETURN {[e._to]: e._from}
        )

        LET article_count = LENGTH(
            FOR e IN edges FILTER e._from == @inst_id AND e.relation == @part_of RETURN 1
        )

        LET judgment_count = LENGTH(UNIQUE(
            FOR e IN edges
                FILTER e.relation IN @judgment_rels
                    AND STARTS_WITH(e._from, "judgments/")
                LET inst = art_inst[e._to]
                FILTER inst == @inst_id
                RETURN e._from
        ))

        LET cross_refs = (
            FOR e IN edges
                FILTER e.relation == @refers_to
                LET fi = art_inst[e._from]
                LET ti = art_inst[e._to]
                FILTER fi != null AND ti != null AND fi != ti
                FILTER fi == @inst_id OR ti == @inst_id
                RETURN {fi, ti}
        )

        LET outbound = LENGTH([
            FOR cr IN cross_refs FILTER cr.fi == @inst_id RETURN 1
        ])
        LET inbound = LENGTH([
            FOR cr IN cross_refs FILTER cr.ti == @inst_id RETURN 1
        ])

        RETURN {article_count, judgment_count, outbound, inbound}
    """
    rows = list(
        store.query(
            aql,
            {
                "inst_id": inst_id,
                "part_of": RELATION_PART_OF_INSTRUMENT,
                "judgment_rels": [RELATION_CITES_ARTICLE, RELATION_MENTIONS_ARTICLE],
                "refers_to": RELATION_REFERS_TO_ARTICLE,
            },
        )
    )
    r = rows[0] if rows else {}
    stats = InstrumentStats(
        article_count=int(r.get("article_count") or 0),
        judgment_count=int(r.get("judgment_count") or 0),
        inbound_citation_count=int(r.get("inbound") or 0),
        outbound_citation_count=int(r.get("outbound") or 0),
    )
    return InstrumentSummaryDTO.from_document(doc, stats=stats)
