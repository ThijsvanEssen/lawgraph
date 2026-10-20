"""Generic node DTOs: the base node payload, neighbour lists and the node graph views."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    CITE,
    KIND_GROUP,
    JudgmentCiteDTO,
    StrictModel,
    WithPath,
    judgment_cite_dto,
)
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    Collection,
    Relation,
)
from lawgraph.core.documents import chamber_of, document_sender, number_in_dossier
from lawgraph.core.dossier_names import dossier_name
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.ecli import ecli_source
from lawgraph.core.judgment_metadata import derive_court
from lawgraph.core.models import TYPE_OF_COLLECTION, Direction, NodeType, parse_node_id
from lawgraph.core.names import article_cite, title_of
from lawgraph.core.tk_links import tk_url
from lawgraph.core.tk_records.kinds import KindGroup, kind_group
from lawgraph.db._rows import GRAPH_PROPS_LEFT_OUT

# The nodes of the Kamer whose Soort (``props.kind``) gives a ``kind_group``.
_GROUPED_BY_KIND = (NodeType.DOCUMENT.value, NodeType.CASE.value)


def node_type_of(collection: str) -> str:
    node_type = TYPE_OF_COLLECTION.get(collection)
    return node_type.value if node_type else ""


def _court_props(props: dict[str, Any]) -> dict[str, Any]:
    """Of a judgment whose props lack them (a neighbour: ``lg_judgment_light`` keeps
    neither always) its ``tier``, by its court code and, of code XX, the court it names
    (``derive_court``, as ``semantic graph-list-stats`` stores it), and its ``source``, by
    its ECLI: what the explorer tells the HvJ EU and the EHRM by."""
    ecli = props.get("ecli") if isinstance(props.get("ecli"), str) else None
    found: dict[str, Any] = {}
    if not props.get("tier"):
        found["tier"] = derive_court(ecli, props.get("court"))[1]
    if not props.get("source"):
        found["source"] = ecli_source(ecli)
    return {key: value for key, value in found.items() if value}


def _build_node_payload(
    doc: dict[str, Any],
    *,
    graph: bool = False,
    titled: bool = True,
    note: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The fields of ``BaseNodeDTO``: in a graph view without the props it leaves out of
    every node (``GRAPH_PROPS_LEFT_OUT``; a neighbour leaves out more, in its SQL:
    ``NEIGHBOR_PROPS_LEFT_OUT``); its title from the props it has (``core.names``), of a
    publication with its *note* (``seo.notes_of``), when *titled*."""
    props: dict[str, Any] = {}
    raw_props = doc.get("props")
    if isinstance(raw_props, dict):
        props = raw_props
    left_out = GRAPH_PROPS_LEFT_OUT if graph else ()
    sanitized = {key: value for key, value in props.items() if key not in left_out}
    link = tk_url(doc.get("type"), props)
    if link:
        sanitized["tk_url"] = link
    if doc.get("type") == NodeType.DOCUMENT.value and "number" not in props:
        # A paper's number as its chamber cites it, under the name an EK paper stores it.
        number = number_in_dossier(chamber_of(doc.get("labels")), props)
        if number:
            sanitized["number"] = number
        sender = document_sender(props.get("actors"), props.get("date"))
        if sender:
            sanitized["sender"] = sender
    kind = (
        kind_group(props.get("kind")) if doc.get("type") in _GROUPED_BY_KIND else None
    )
    if kind:
        # in its props too, beside the ``kind`` it is read from
        sanitized["kind_group"] = kind
    if doc.get("type") == NodeType.DOSSIER.value:
        # the name it goes by (``Cyberbeveiligingswet``) and where it comes from, as the
        # feed gives them (``core.dossier_names``)
        short, basis = dossier_name(props)
        sanitized["short_title"] = short
        sanitized["short_title_basis"] = basis
    if doc.get("type") == NodeType.DECISION.value:
        # what was voted on by the name it goes by (``Wet AI-toezicht``, ``Begroting
        # Defensie 2027``; ``core.dossier_numbers.short_title``), null without one
        sanitized["short_subject"] = short_title(props.get("subject"))
    collection = parse_node_id(doc["id"])[0]
    if collection == COLLECTION_JUDGMENTS:
        sanitized.update(_court_props(props))
    return {
        "id": doc["id"],
        "key": doc["key"],
        "collection": collection,
        "type": doc.get("type", ""),
        # an article as it is cited (``Art. 6:162 BW``), its long name kept in its props
        "display_name": article_cite(props)
        if collection == COLLECTION_ARTICLES
        else props.get("display_name"),
        "labels": list(doc.get("labels") or []),
        "props": sanitized or None,
        "cite": judgment_cite_dto(props)
        if collection == COLLECTION_JUDGMENTS
        else None,
        "title": title_of(doc["id"], props, note=note) if titled else None,
        **({"kind_group": kind} if kind else {}),
    }


class BaseNodeDTO(WithPath):
    """Common node representation used by multiple responses."""

    id: str
    key: str
    collection: Collection
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None
    kind_group: KindGroup | None = Field(
        None,
        exclude_if=lambda value: value is None,
        description=f"Of a paper or a case: {KIND_GROUP} Absent for any other node.",
    )
    cite: JudgmentCiteDTO | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=f"Of a judgment: {CITE} Absent for a node of another collection.",
    )
    title: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Its title, as the `<title>` of its page has it and `title` of "
        "`/api/nodes/{collection}/{key}` (`Art. 6:162 BW, Onrechtmatige daad`, `HR 20 "
        "december 2019 (Urgenda), ECLI:NL:HR:2019:2006`, `36496 Wet AI-toezicht`), from "
        "the props it carries (with `props=canvas` too, which keeps what it reads).",
    )

    @classmethod
    def fields_of(
        cls,
        doc: dict[str, Any],
        *,
        graph: bool = False,
        names: dict[str, dict[str, Any]] | None = None,
        titled: bool = True,
        note: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The fields of a node document, in a *graph* view without its large props; with
        *names* a paper, an activity or a decision gets the name of its first dossier
        (``with_dossier_short_title``); *titled* with its title (of a publication with its
        *note*)."""
        payload = _build_node_payload(doc, graph=graph, titled=titled, note=note)
        if names is not None:
            with_dossier_short_title(payload, names)
        return payload

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        graph: bool = False,
        names: dict[str, dict[str, Any]] | None = None,
        titled: bool = True,
        note: dict[str, Any] | None = None,
    ) -> BaseNodeDTO:
        return cls(
            **cls.fields_of(doc, graph=graph, names=names, titled=titled, note=note)
        )


# The neighbours that carry the short title of their first dossier (``NeighborDTO``).
_NAMED_BY_DOSSIER = ("documents", "activities", "decisions")


def with_dossier_short_title(
    payload: dict[str, Any], names: dict[str, dict[str, Any]]
) -> None:
    """Of a paper, an activity or a decision, ``dossier_short_title`` in its props: the name
    its first dossier goes by (by *names*, ``load_dossier_names``; null without one)."""
    props = payload.get("props")
    if payload.get("collection") not in _NAMED_BY_DOSSIER or not isinstance(
        props, dict
    ):
        return
    # a copy: the node may be one kept for every request
    props = payload["props"] = dict(props)
    numbers = props.get("dossier_numbers") or [props.get("dossier_number")]
    first = str(numbers[0] or "") if isinstance(numbers, list) and numbers else ""
    props["dossier_short_title"] = (names.get(first) or {}).get("short_title")


class NeighborDTO(BaseNodeDTO):
    """A neighbour with the edge that leads to it, used by the generic node explorer."""

    edge_id: str
    relation: Relation | None
    direction: Direction
    confidence: float | None
    status: str | None
    meta: dict[str, Any] | None

    @classmethod
    def from_entry(
        cls,
        doc: dict[str, Any],
        edge: dict[str, Any],
        direction: Direction,
        confidence: float | None,
        names: dict[str, dict[str, Any]] | None = None,
        titled: bool = True,
        note: dict[str, Any] | None = None,
    ) -> NeighborDTO:
        """From the neighbour and its edge; a paper, an activity or a decision has in its
        props ``dossier_short_title``, the name its first dossier goes by (by *names*,
        ``load_dossier_names``; null without one); *titled* with its title."""
        meta = edge.get("meta")
        return cls(
            **BaseNodeDTO.fields_of(
                doc, graph=True, names=names, titled=titled, note=note
            ),
            edge_id=edge["key"],
            relation=edge.get("relation"),
            direction=direction,
            confidence=confidence,
            status=edge.get("status"),
            meta=meta if isinstance(meta, dict) else None,
        )


class NeighborBucketDTO(StrictModel):
    """The neighbours that share a relation, a direction and a collection: one page of them."""

    relation: Relation | None
    direction: Direction
    collection: Collection
    type: str
    total: int
    next_offset: int | None
    lid_counts: dict[str, int] | None = Field(
        None,
        description=(
            "Of an article: per lid the edges of the whole bucket cite, how many do "
            '("" for those that cite none; an edge that cites two counts for each); '
            "null when none of them cites a lid."
        ),
    )
    capacity_counts: dict[str, int] | None = Field(
        None,
        description=(
            "Of a member's ``AUTHORED`` (outbound): per capacity they signed in "
            "(``meta.capacity``: ``kamerlid``, ``bewindspersoon``, ``overig``; "
            '"" for none), how many of the whole bucket, not only of its page. Null for '
            "every other bucket, with a ``status`` filter, and before the signatures "
            "are kept with their capacity."
        ),
    )
    items: list[NeighborDTO]


class NodeNeighborsDTO(StrictModel):
    """Neighbors returned by /api/nodes/{collection}/{key}."""

    total: int
    buckets: list[NeighborBucketDTO] = Field(default_factory=list)


class NodeGraphResponse(StrictModel):
    """Response for GET /api/nodes/{collection}/{key}."""

    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO
    title: str = Field(
        "",
        description="The title of the node as its page has it (``Artikel 6:162 BW: "
        "onrechtmatige daad``), without the name of the site.",
    )
    description: str = Field("", description="The description of its page.")
    path: str | None = Field(
        None,
        description="Its readable address (``/wetten/BWBR0005289/artikel/6:162``); null "
        "for a node without one.",
    )
    lid_counts_pending: bool = Field(
        False,
        description="Of an article asked with ``limit=1``: its lid counts are being "
        "counted, so every ``lid_counts`` is null; a request with a larger ``limit`` "
        "waits for them and has them. False otherwise.",
    )


class EdgePassage(StrictModel):
    """A place where a judgment cites, as the edge keeps it: to show without the judgment."""

    paragraph_id: str = Field(
        description="The paragraph, as `paragraph_id` of `/api/judgments/{ecli}`; of a "
        "footnote the paragraph that refers to it."
    )
    paragraph_number: str | None = Field(
        description="Its printed number (`5.3`), null when it has none."
    )
    footnote: str | None = Field(
        description="The label of the footnote it stands in, null in the paragraph itself."
    )
    snippet: str = Field(description="The text around the citation.")
    text: str = Field(description="The citation as written: `snippet[start:end]`.")
    start: int
    end: int


class NodeNeighborhoodEdge(StrictModel):
    """Edge in a BFS-neighborhood response."""

    id: str
    source: str
    target: str
    relation: Relation | None
    confidence: float | None = None
    status: str | None = None
    passages: list[EdgePassage] | None = Field(
        None,
        exclude_if=lambda value: value is None,
        description="With `edge_meta=passages`: where a judgment cites the article or the "
        "judgment the edge reaches (absent otherwise, and for an edge without them).",
    )
    meta: dict[str, Any] | None = Field(
        None,
        description="The `meta` of the edge as a neighbour's edge has it (without the "
        "places a judgment cites; with `props=canvas` only the keys the canvas reads), "
        "without `passages`: the period of a membership (`from_date`, `to_date`), the "
        "posts, the lid cited. Null for an edge without one.",
    )

    @classmethod
    def from_doc(cls, edge: dict[str, Any]) -> NodeNeighborhoodEdge:
        """From an edge (``_rows.light_edge_doc`` or ``canvas_edge_doc``): its ``meta``,
        and the passages of its ``meta`` on their own."""
        confidence = edge.get("confidence")
        meta = edge.get("meta")
        passages = meta.get("passages") if isinstance(meta, dict) else None
        rest = (
            {k: v for k, v in meta.items() if k != "passages"}
            if isinstance(meta, dict)
            else None
        )
        return cls(
            id=edge["id"],
            source=edge["from_id"],
            target=edge["to_id"],
            relation=edge.get("relation"),
            confidence=(
                float(confidence) if isinstance(confidence, int | float) else None
            ),
            status=edge.get("status"),
            **({"passages": passages} if passages else {}),
            meta=rest or None,
        )


class NeighborhoodCollectionDTO(StrictModel):
    """Of the focal node's own neighbours in one collection: how many, and how many the
    neighbourhood holds under its cap."""

    collection: Collection
    total: int = Field(
        ...,
        description="Its neighbours there along the edges walked, of the types asked "
        "(from the edges: one that is gone counts too).",
    )
    kept: int = Field(..., description="Of those, the ones in `nodes`.")


class NodeNeighborhoodResponse(StrictModel):
    """One-shot N-hop neighborhood: focal + reachable nodes + spanning edges."""

    focal_id: str
    nodes: list[BaseNodeDTO]
    edges: list[NodeNeighborhoodEdge]
    buckets: list[NeighborhoodCollectionDTO] = Field(
        default_factory=list,
        description="Per collection of the focal node's own neighbours (the first level), "
        "by name: `total` and `kept`; where `kept` is less, the cap left the rest out "
        "(`GET /api/nodes/{collection}/{key}` lists them all).",
    )
