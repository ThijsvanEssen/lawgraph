from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import EdgeMeta, parse_choices
from lawgraph.api.schemas.nodes import (
    BaseNodeDTO,
    NeighborBucketDTO,
    NeighborDTO,
    NeighborhoodCollectionDTO,
    NodeGraphResponse,
    NodeNeighborhoodEdge,
    NodeNeighborhoodResponse,
    NodeNeighborsDTO,
    node_type_of,
)
from lawgraph.api.seo.pages.titles import title_and_description
from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENT_VERSIONS,
    EDGE_STATUS_CANONIEK,
    EDGE_STATUS_VOORGESTELD,
    as_collection,
    as_relation,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Direction, NodeType
from lawgraph.core.readable_paths import path_of
from lawgraph.core.relations import RELATION_NAMES, without_unknown_relations
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import seo as seo_queries
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.feed import official_short
from lawgraph.db.queries.nodes import (
    CANVAS_BUCKET_LIMIT,
    DEFAULT_BUCKET_LIMIT,
    FIRST_LEVEL_CAP,
    FULL_BUCKET_LIMIT,
    NEIGHBORHOOD_CAP,
    NeighborFilter,
    UnsupportedCollectionError,
    get_node_neighborhood,
    get_node_with_neighbors,
    version_law_name,
)
from lawgraph.db.queries.overlay import (
    HEAT_MAX_LIMIT,
    get_heat_counts,
    get_in_flux_counts,
    stored_heat,
)

# How much of a node's props a neighbor carries.
PropsView = Literal["full", "canvas"]


router = APIRouter()
logger = get_logger(__name__)

# The two overlays answer raw JSON: validating a map of 40,000 keys through a response
# model took about 200 ms a request. The schema says what the map is.
_COUNT_PER_NODE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Node id (`collection/key`) to count.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                    "example": {"articles/bwbr0001854_287": 3},
                }
            }
        },
    }
}


@router.get(
    "/in-flux",
    summary="Bulk in-flux count per node",
    description=(
        "A map of node id → number of open proposed changes. Only nodes with "
        "at least one open change are included. Use it to render the in-flux "
        "ring on graph nodes."
        "\n\n"
        "node id to count of open proposed mutations; node id to incoming edges "
        "created in the last `months` (default 6) plus the citations of an article, "
        "`min_count`; `ids` (comma-separated, at most 500) counts those nodes alone, "
        "the ones a view draws (one index read per node); without it the `limit` nodes "
        "with the highest counts (default 10,000, at most 50,000; the whole graph has "
        "1.85 million) of the window of 3, 6, 12 or 24 months that holds `months` (5 "
        "counts as 6), as `semantic graph-heat` last counted them (`lg_heat`, the "
        "50,000 highest of each window; the API never counts them itself, which reads "
        "every edge): 503 until that step has run (with `ids` it still answers). Both "
        'answer a plain map (`{"articles/bwbr0001854_287": 3}`), not validated through '
        "a response model"
    ),
    tags=["nodes"],
    response_class=JSONResponse,
    responses=_COUNT_PER_NODE,
)
def bulk_in_flux(
    store: Annotated[GraphStore, Depends(get_store)],
) -> JSONResponse:
    """Return all nodes that have at least one VOORGESTELD edge, with counts (kept while
    the edges stand still, ``get_in_flux_counts``). After a poll that wrote edges, the
    count of the edges before is answered at once while the new one computes: a signal
    that hardly moves is not worth a wait."""
    with version_cache.stale_wait(0.0):
        return JSONResponse(get_in_flux_counts(store))


# The nodes a request may name, and how many the map of the whole graph keeps.
HEAT_MAX_IDS = 500
HEAT_LIMIT = 10_000


@router.get(
    "/heat",
    summary="Bulk activity score per node (heat layer)",
    description=(
        "A map of node id → activity count over the past N months, where "
        "activity is the number of incoming edges created in that window. "
        "Pass months=3 for a 90-day window. `ids` (comma-separated node ids, at most "
        f"{HEAT_MAX_IDS}) counts those nodes alone, the ones a view draws; without it the "
        "`limit` nodes with the highest counts (the whole graph has 1.85 million), as "
        "`semantic graph-heat` last counted them; 503 until it has."
    ),
    tags=["nodes"],
    response_class=JSONResponse,
    responses=_COUNT_PER_NODE,
)
def bulk_heat(
    store: Annotated[GraphStore, Depends(get_store)],
    months: int = Query(
        default=6, ge=1, le=24, description="Terugkijkvenster in maanden"
    ),
    min_count: int = Query(
        default=1,
        ge=1,
        le=1000,
        description=(
            "Drop nodes with fewer than this many activity hits. Default 1 "
            "returns everything; bump to 2-5 for a much smaller payload "
            "without losing visible heat halos."
        ),
    ),
    ids: str | None = Query(
        default=None,
        description=f"Comma-separated node ids to count, at most {HEAT_MAX_IDS}.",
    ),
    limit: int = Query(
        default=HEAT_LIMIT,
        ge=1,
        le=HEAT_MAX_LIMIT,
        description="Without ids: the nodes with the highest counts, this many.",
    ),
) -> JSONResponse:
    """Return activity counts per node for the heat-layer overlay."""
    if ids is not None:
        wanted = sorted({i.strip() for i in ids.split(",") if i.strip()})
        if len(wanted) > HEAT_MAX_IDS:
            raise HTTPException(status_code=422, detail=f"At most {HEAT_MAX_IDS} ids.")
        return JSONResponse(
            get_heat_counts(store, months=months, min_count=min_count, ids=wanted)
        )
    kept = stored_heat(store, months, min_count, limit)
    if kept is None:
        raise HTTPException(
            status_code=503,
            detail="The heat of the whole graph is not counted yet (semantic graph-heat).",
            headers={"Retry-After": "3600"},
        )
    return JSONResponse(kept)


def neighbor_filter(
    relations: Annotated[
        str | None,
        Query(description="Comma-separated relations to keep (`REFERS_TO,PART_OF`)."),
    ] = None,
    node_types: Annotated[
        str | None,
        Query(
            description="Comma-separated node types to keep (`article,judgment`).",
        ),
    ] = None,
    direction: Annotated[
        Direction | None,
        Query(description="Keep the edges that leave (`outbound`) or reach the node."),
    ] = None,
    status: Annotated[
        str | None,
        Query(description="Keep the edges of this status (`canoniek`, `voorgesteld`)."),
    ] = None,
) -> NeighborFilter:
    """The edges the caller asks for; 422 for a relation, type or status that does not exist."""
    statuses = (EDGE_STATUS_CANONIEK, EDGE_STATUS_VOORGESTELD)
    if status is not None and status not in statuses:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status: {status}; allowed: {', '.join(statuses)}",
        )
    return NeighborFilter(
        relations=parse_choices(relations, RELATION_NAMES, "relations"),
        node_types=parse_choices(node_types, [t.value for t in NodeType], "node_types"),
        direction=direction,
        status=status,
    )


NeighborFilterParams = Annotated[NeighborFilter, Depends(neighbor_filter)]


@router.get(
    "/{collection}/{key}",
    response_model=NodeGraphResponse,
    summary="Explore a node and its neighbors",
    description=(
        "Fetches a node from the given collection and returns its neighbors from "
        "the unified edge collection in buckets, one per relation, direction and "
        "neighbor collection. Each neighbor carries the edge that leads to it: "
        "`edge_id`, `status`, `confidence` and `meta`. A bucket holds one page "
        "(`limit` neighbors from `offset`, in the same order on every request), "
        "its `total`, and the `next_offset` of the following page (null on the "
        "last). `relations`, `node_types`, `direction` and `status` narrow the "
        "edges; the totals count what remains."
        "\n\n"
        "a node (any node collection) with its neighbours in buckets of one relation, "
        "direction and neighbour collection, a page of `limit` (at most 200; 500 with "
        "`props=canvas`) from `offset` in each. An article's `lid_counts` are waited "
        "for only on the first page with every prop: a further page or a page of the "
        "canvas gives those counted before, or none while they are being counted. "
        "Every neighbour carries its edge: `edge_id` (the edge `key`), `status`, "
        "`confidence`, `meta`. The node, every neighbour and every node of a "
        "neighbourhood or path has `title`, the `<title>` of its page "
        "(`core.names.title_of`; of a publication with the title of its nota van "
        "toelichting; with `props=canvas` too, which keeps what it reads), and a "
        "judgment `cite` (as on `/api/judgments/{ecli}`); a dossier has in its props "
        "`short_title` and `short_title_basis` as the feed gives them. `props=canvas` "
        "gives a neighbour only what the canvas "
        "of the explorer draws: of its props those of its collection and those its "
        "title reads (`_rows.canvas_keys`; of each of its `actors` the role, name and faction; an "
        "instrument its `kind` (`wet`, as `/api/instruments/{identifier}` gives it), "
        "an annex its `label` and `title`, an instrument version the citation title of "
        "its law, `instrument_citation_title`, from the columns of `instruments`; a "
        "motion, an amendment or a judgment its `outcome` alone of how it ended), of "
        "its edge's `meta` the keys the canvas reads (null when none, never `{}`); the "
        "node itself stays whole. A bucket has `type`, `total` (its edges), "
        "`next_offset` (null on the last page), `lid_counts`, `capacity_counts` and "
        "`items`; `capacity_counts`, of a member's `AUTHORED` (outbound): per capacity "
        'they signed in (`meta.capacity`: `kamerlid`, `bewindspersoon`, `overig`; `""` '
        "for none), how many of the whole bucket and not only of its page "
        '(`{"kamerlid": 980, "bewindspersoon": 503}`), from `lg_authored`; null for '
        "every other bucket and with a `status` filter; `lid_counts`, of an article: "
        "per lid the edges of the whole bucket cite (in their `meta`: `lid`, `leden`, "
        "and the `leden` of each of a judgment's `mentions`), how many do (only the "
        "leden the article has: a citation can give it the lid of another article it "
        'names), `""` for those that cite none and an edge that cites two counted for '
        'each (`{"1": 28, "2": 174, "": 12}`); with `limit=1` (the light node) an '
        "article whose lid counts are not kept yet waits for them 0.5 s at most, then "
        "answers with every `lid_counts` null and `lid_counts_pending` true while they "
        "are counted (a larger `limit` waits for them), so that a reader can show them "
        "without reading every page (counted over the meta of every edge of the "
        "article, so kept an hour whatever the data does, a newer count made in the "
        "background after that; those of the 20 most cited articles warmed); null for "
        "a bucket that cites no lid and for a node that is no article; `limit` "
        "(default 30, max 200) and `offset` page inside every bucket. Bucket and page "
        "order are the same on every request. A neighbour is light: its `props` leave "
        "out besides those the text of a paper (`sections`, `footnotes`), the "
        "structure of an article (`parts`, `references`, `breadcrumb`) and the rollups "
        "of an activity (`case_ids`, `case_kinds_by_dossier`; the node itself keeps "
        "them); a judgment carries `ecli`, `display_name`, `names`, `summary`, `date`, "
        "`court`, `court_code`, `case_number`, `source`, `stub`, "
        "`translation_of`, `advocate_general`, `advocate_general_role`, `outcome`, "
        "`outcome_text`, `conclusion_outcome`, `conclusion_outcome_text` and "
        "`echr_findings` alone (`lg_judgment_light`), and its `tier` (`hoge_raad`, "
        "`hvj_eu`, `ehrm`: by its court code, of code XX by the court it names) and its "
        "`source` (by its ECLI) where those lack them; its `summary` is cut at 400 "
        "characters (with `…`), and the `meta` of its edge leaves out `mentions` (each "
        "place a judgment cites the article or the judgment; `/api/judgments/{ecli}` "
        "has them), which the node itself, `/api/documents/{key}` and "
        "`/api/articles/...` carry. The answer has the `title` and `description` of "
        "the node's page (as `/render` gives them, from the node's own props: without "
        "the outcome of a motion or the counts of an article; `title` is the page's "
        "`<title>` without `, Concordans`, never cut, the title the app's tab shows: "
        "`Art. 6:162 BW, Onrechtmatige daad` (an article with its heading, else its "
        "`caption`), `Motie 36496-71 Bolhuis over een AI-killswitch` (a motion or an "
        "amendment by its number, then every word of its subject), `HR 20 december "
        "2019 (Urgenda), ECLI:NL:HR:2019:2006`, `36600-VII Begroting Binnenlandse "
        "Zaken en Koninkrijksrelaties 2025`; a day in a title or a description as `20 "
        "december 2019`) and its readable `path` (null for a node without one, an "
        "activity). The `meta` of a neighbour's edge holds `paragraphs` where a "
        'judgment cites: the numbers of the paragraphs it cites in ("4.3", as the '
        "judgment prints them), stored on an edge to a cited judgment and taken from "
        "the mentions of an edge to a cited article, so a list of citing judgments "
        "shows where each cites without a request per row. With `edge_meta=passages` "
        "(also with `props=canvas`) it holds `passages` too, from the mentions of the "
        "edge: the first place in each of its first three paragraphs (a footnote "
        "counts apart), each `paragraph_id`, `paragraph_number`, `footnote` (its "
        "label, null in the paragraph itself), `snippet`, `text` (the citation as "
        "written) and `start`, `end` (`snippet[start:end]` is `text`), so a row or a "
        "card shows the passage without the judgment; none of a mention linked before "
        "it kept `snippet_start`. `light` (the default) leaves them out: they weigh "
        "about 0.9 kB an edge. The `meta` of an edge from a Tweede Kamer paper holds "
        "`place`, where its citation stands in what `/api/documents/{key}` serves "
        "(`part` `title`, `text` with `section_id`, or `footnote` with `footnote_id`; "
        "`start` and `end` in that part; see data-model (docs/data-model.md#judgment))"
    ),
    tags=["nodes"],
)
def get_node_graph(
    collection: str,
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    filters: NeighborFilterParams,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=CANVAS_BUCKET_LIMIT,
            description="Neighbors per bucket, not per response: at most "
            f"{FULL_BUCKET_LIMIT} with every prop, {CANVAS_BUCKET_LIMIT} with "
            "``props=canvas``.",
        ),
    ] = DEFAULT_BUCKET_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Neighbors to skip in every bucket."),
    ] = 0,
    props: Annotated[
        PropsView,
        Query(
            description=(
                "`canvas`: of a neighbour only the props the canvas of the explorer "
                "draws, per collection, and of its edge only the `meta` it reads (null "
                "when none); `full` (the default) every prop but the text"
            )
        ),
    ] = "full",
    edge_meta: EdgeMeta = "light",
) -> NodeGraphResponse:
    """Return a node together with a page of its incoming/outgoing neighbors per bucket."""
    if props == "full" and limit > FULL_BUCKET_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit is at most {FULL_BUCKET_LIMIT} with every prop "
            f"({CANVAS_BUCKET_LIMIT} with props=canvas)",
        )
    try:
        data = get_node_with_neighbors(
            store,
            collection,
            key,
            filters=filters,
            limit=limit,
            offset=offset,
            canvas=props == "canvas",
            # an article's lid counts are waited for on the first page a reader opens
            # alone: not by the light node (one per bucket), a further page or what the
            # canvas loads, which draws none (the first page of 8:75 Awb took 13.8 s cold
            # for them); kept an hour and counted on in the background
            wait_for_lids=limit > 1 and offset == 0 and props == "full",
            passages=edge_meta == "passages",
        )
    except UnsupportedCollectionError as err:
        logger.debug("Node lookup %s/%s failed: %s", collection, key, err)
        raise HTTPException(status_code=400, detail=str(err)) from err

    names = load_dossier_names(store)
    # the notes of the publications among them, whose titles their titles read
    notes = seo_queries.notes_of(
        store, (entry.doc for bucket in data.buckets for entry in bucket.entries)
    )
    buckets = [
        NeighborBucketDTO(
            relation=(
                as_relation(bucket.facet.relation) if bucket.facet.relation else None
            ),
            direction=bucket.facet.direction,
            collection=as_collection(bucket.facet.collection),
            type=node_type_of(bucket.facet.collection),
            total=bucket.facet.count,
            next_offset=bucket.next_offset,
            lid_counts=bucket.lid_counts,
            capacity_counts=bucket.capacity_counts,
            items=[
                NeighborDTO.from_entry(
                    doc=entry.doc,
                    edge=entry.edge,
                    direction=entry.direction,
                    confidence=entry.confidence,
                    names=names,
                    note=notes.get(entry.doc["id"]),
                )
                for entry in bucket.entries
            ],
        )
        for bucket in without_unknown_relations(
            data.buckets, lambda b: b.facet.relation or None
        )
    ]
    node_props = data.node.get("props") or {}
    if collection == COLLECTION_INSTRUMENT_VERSIONS and node_props.get("bwb_id"):
        # the name of its law for its title (one row of ``instruments`` by its bwb_id)
        law = version_law_name(store, str(node_props["bwb_id"]))
        node_props = {**node_props, "instrument_citation_title": law}
    if collection == COLLECTION_DOSSIERS:
        # the name its bill goes by, which its title names it by without one of its own
        label = str(node_props.get("label") or key)
        node_props = {**node_props, "official_short": official_short(store, label)}
    page_law = None
    if collection in (COLLECTION_ARTICLES, COLLECTION_ANNEXES) and node_props.get(
        "bwb_id"
    ):
        # its law as its page names it (one row of ``instruments`` by its bwb_id)
        page_law = seo_queries.law_of(store, str(node_props["bwb_id"]))
    # of a publication its nota van toelichting, whose title its page has (one light row)
    note = seo_queries.notes_of(store, [data.node]).get(data.node["id"])
    title, description = title_and_description(
        data.node["id"], node_props, page_law, note
    )
    node = BaseNodeDTO.from_document(
        {**data.node, "props": node_props}, graph=True, titled=False
    )
    return NodeGraphResponse(
        node=node.model_copy(update={"title": title}),
        neighbors=NodeNeighborsDTO(
            total=sum(bucket.total for bucket in buckets), buckets=buckets
        ),
        title=title,
        description=description,
        path=path_of(data.node["id"], node_props),
        lid_counts_pending=data.lid_counts_pending,
    )


@router.get(
    "/{collection}/{key}/neighborhood",
    response_model=NodeNeighborhoodResponse,
    summary="BFS neighborhood around a node",
    description=(
        "Returns every node and edge within `depth` hops of the focal node in "
        "a single traversal query. `relations` and `status` restrict the edges "
        "the traversal follows, `direction` restricts it to edges leaving "
        "(`outbound`) or reaching (`inbound`) each node on the way, and "
        "`node_types` to paths through nodes of those types (the focal node is "
        "always included)."
    ),
    tags=["nodes"],
)
def get_node_neighborhood_route(
    collection: str,
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    filters: NeighborFilterParams,
    depth: Annotated[int, Query(ge=1, le=4)] = 3,
    cap: Annotated[
        int,
        Query(
            ge=1,
            le=FIRST_LEVEL_CAP,
            description=f"The nodes kept: at most {NEIGHBORHOOD_CAP}, and "
            f'{FIRST_LEVEL_CAP} with ``depth=1`` (every direct neighbour, "alles '
            'laden").',
        ),
    ] = 200,
    props: Annotated[
        PropsView,
        Query(
            description=(
                "`canvas`: of a node but the focal one only the props the canvas of the "
                "explorer draws, per collection, as the neighbours of a node with "
                "`props=canvas`; `full` (the default) every prop a neighbour carries"
            )
        ),
    ] = "full",
    edge_meta: EdgeMeta = "light",
) -> NodeNeighborhoodResponse:
    if depth > 1 and cap > NEIGHBORHOOD_CAP:
        raise HTTPException(
            status_code=422,
            detail=f"cap is at most {NEIGHBORHOOD_CAP} past the first level "
            f"({FIRST_LEVEL_CAP} with depth=1)",
        )
    try:
        data = get_node_neighborhood(
            store,
            collection,
            key,
            depth=depth,
            cap=cap,
            filters=filters,
            canvas=props == "canvas",
            passages=edge_meta == "passages",
        )
    except UnsupportedCollectionError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    focal = data["focal"]
    # for the canvas a paper, an activity or a decision is described by its dossier's name,
    # as a neighbour of ``props=canvas`` is
    names = load_dossier_names(store) if props == "canvas" else None
    notes = seo_queries.notes_of(store, [focal, *data["nodes"]])
    nodes = [
        BaseNodeDTO.from_document(n, graph=True, names=names, note=notes.get(n["id"]))
        for n in data["nodes"]
    ]
    # Focal first so the client can pin layout to it without searching.
    nodes.insert(
        0, BaseNodeDTO.from_document(focal, graph=True, note=notes.get(focal["id"]))
    )
    return NodeNeighborhoodResponse(
        focal_id=focal["id"],
        nodes=nodes,
        edges=[
            NodeNeighborhoodEdge.from_doc(e)
            for e in without_unknown_relations(
                data["edges"], lambda e: e.get("relation")
            )
        ],
        buckets=[NeighborhoodCollectionDTO(**c) for c in data["buckets"]],
    )
