"""Generic node DTOs: the base node payload, neighbour lists and the node graph views."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from lawgraph.api.schemas.common import (
    CITE,
    KIND_GROUP,
    FacetCountDTO,
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
    props: dict[str, Any] | None = Field(
        description="Its props. In a graph view (a neighbour, a node of a neighbourhood, "
        "the focal one too, or of a path) a law, a publication or a version also has "
        "`date`, an ISO day where the source gives one: of a publication (`Stb. 1991, "
        "600`) the day it was published; of a law or a treaty the day its text in force "
        "came into force (its last change in force, else the day it came into force); of "
        "a version of a law or an article its `valid_from`. Absent where the source gives "
        "none.",
    )
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
    tier_counts: dict[str, int] | None = Field(
        None,
        description=(
            "Of a judgment's bucket of judgments: per tier (``hoge_raad``, "
            '``gerechtshof``, …; "" for a judgment without one), how many of the whole '
            "bucket, not only of its page. Null for every other bucket."
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


class SharedLinkDTO(StrictModel):
    """The edge by which a shared neighbour hangs at one of the nodes asked for."""

    source: str = Field(
        description="The node asked for (`collection/key`) it hangs at."
    )
    edge_id: str
    relation: Relation | None
    direction: Direction = Field(
        description="`outbound`: the edge leaves the source for the neighbour."
    )
    status: str | None
    confidence: float | None


class SharedNeighborDTO(BaseNodeDTO):
    """A neighbour of every node asked for, with the edges that tie it to each."""

    links: list[SharedLinkDTO] = Field(
        description="Every edge between the neighbour and a node asked for, the nodes in "
        "the order of `ids`, each node with at least one."
    )

    @classmethod
    def from_shared(
        cls,
        doc: dict[str, Any],
        links: list[SharedLinkDTO],
        names: dict[str, dict[str, Any]] | None = None,
        note: dict[str, Any] | None = None,
    ) -> SharedNeighborDTO:
        return cls(
            **BaseNodeDTO.fields_of(doc, graph=True, names=names, note=note),
            links=links,
        )


class SharedBucketDTO(StrictModel):
    """The shared neighbours of one collection: one page of them."""

    collection: Collection
    type: str
    total: int = Field(description="Under the filters, whatever the page.")
    next_offset: int | None = Field(description="Null on the last page.")
    items: list[SharedNeighborDTO]


class SharedFacetsDTO(StrictModel):
    """Counts of the shared neighbours, each facet under the filters but its own."""

    collection: list[FacetCountDTO] = Field(
        description="Per collection (`value`), most first."
    )
    tier: list[FacetCountDTO] = Field(
        description="Of the judgments, per tier, most first, under `subject_area`."
    )
    subject_area: list[FacetCountDTO] = Field(
        description="Of the judgments, per main area of law (a judgment counts for each "
        "of its areas), most first, under `tier`."
    )


class SharedNeighborsResponse(StrictModel):
    """Response for GET /api/nodes/shared."""

    ids: list[str]
    total: int = Field(description="The shared neighbours of every collection.")
    buckets: list[SharedBucketDTO]
    facets: SharedFacetsDTO


class SurroundingKindDTO(StrictModel):
    """How many edges of a relation reach nodes of a collection."""

    relation: Relation
    collection: Collection
    count: int


class SurroundingItemDTO(StrictModel):
    """A node of a section and the edge that ties it to the node asked for."""

    node: BaseNodeDTO
    relation: Relation
    direction: Direction = Field(
        description="`outbound`: the edge leaves `via` for the node."
    )
    edge_id: str
    status: str | None
    via: str = Field(
        description="The node the edge hangs at: the node asked for, or its paper, case "
        "or dossier (`collection/key`)."
    )


class SurroundingSectionDTO(StrictModel):
    """Some nodes of one kind of surrounding, and how many there are."""

    total: int = Field(
        description="The distinct nodes of the section's kinds at the node and its "
        "document, case and dossier, per relation, whatever `items` holds."
    )
    kinds: list[SurroundingKindDTO] = Field(
        description="`total` per relation and collection."
    )
    items: list[SurroundingItemDTO]


class SurroundingSubmitterDTO(StrictModel):
    """Who signed a paper or case, or made a commitment."""

    node: BaseNodeDTO
    edge_id: str
    role: str | None = Field(
        description="`Eerste ondertekenaar`, `Mede ondertekenaar`, `toezegger`, as the "
        "source writes it."
    )
    function: str | None
    capacity: str | None = Field(
        description="`kamerlid`, `bewindspersoon` or `overig`."
    )
    faction: BaseNodeDTO | None = Field(
        description="The faction they sat in on the day of the node; null for a "
        "bewindspersoon and where no membership covers that day."
    )


class SurroundingHeldDTO(StrictModel):
    """What a dossier holds, counted."""

    documents: int
    cases: int
    decisions: int
    commitments: int
    activities: int
    laws: int = Field(description="The publications that legislated in it.")


class SurroundingDossierDTO(StrictModel):
    """A dossier as one node, with what it holds counted (never its members)."""

    node: BaseNodeDTO
    via: str
    held: SurroundingHeldDTO


class SurroundingFactionVoteDTO(StrictModel):
    """How one faction voted on a decision."""

    faction: BaseNodeDTO
    choice: str | None = Field(
        description="`Voor`, `Tegen`, ...; of a roll call `Verdeeld` when the members "
        "of the faction did not all vote alike."
    )
    seats: int | None = Field(
        description="The seats of the faction's vote; of a roll call the members who voted."
    )
    members: dict[str, int] | None = Field(
        description="Of a roll call: how many members of the faction cast each choice, by "
        "the faction they sat in on the day; null for a vote by faction."
    )


class SurroundingVoteDTO(StrictModel):
    """A decision on the node or its paper or case, with the vote of each faction."""

    node: BaseNodeDTO = Field(
        description="The decision; `props.tally`, `passed` and `vote_kind` say how it "
        "ended."
    )
    about: str | None = Field(
        description="The paper or case the decision is on (`collection/key`); null for "
        "the decision asked for."
    )
    factions: list[SurroundingFactionVoteDTO] = Field(
        description="Of a vote by faction its `VOTED` edges; of a roll call (`props."
        "vote_kind` `member`) derived from the votes of its members; empty for a "
        "hamerstuk and a roll call whose member votes or memberships are not read."
    )


class SurroundingGapDTO(StrictModel):
    """Something the data does not hold, said as it is."""

    section: Literal["submitters", "dossiers", "laws", "votes", "follows", "context"]
    reason: str


class SurroundingsResponse(StrictModel):
    """What stands around a paper, case, decision, commitment or activity: who put it
    forward, the dossier as one node, the laws it touches, the votes on it per faction,
    what follows from it, and where it was made."""

    focal: BaseNodeDTO
    submitters: list[SurroundingSubmitterDTO]
    submitters_total: int
    dossiers: list[SurroundingDossierDTO]
    dossiers_total: int
    laws: SurroundingSectionDTO
    votes: list[SurroundingVoteDTO]
    votes_total: int
    follows: SurroundingSectionDTO
    context: SurroundingSectionDTO
    gaps: list[SurroundingGapDTO] = Field(
        description="Per section that is empty or incomplete, why: the source lacks it."
    )


class InFluxDossierDTO(StrictModel):
    """A dossier that has not ended (not ``closed``) with an open change of a node: a
    document of it proposes the change."""

    id: str = Field(description="The dossier (`dossiers/36000`).")
    dossier_number: str | None = Field(description="Its Kamerstuk number (`36000`).")
    title: str | None
    bill_id: str | None = Field(
        description="Its bill: the first document of the dossier of kind `Voorstel van "
        "wet` (also of an initiative), by date (`documents/…`); null when the dossier "
        "holds none."
    )
    closed_known: bool = Field(
        description="Whether its end is derived (`semantic tk-dossier-outcomes`); false: "
        "not yet, and it counts as open."
    )
    count: int = Field(
        description="The open changes of the node its documents propose."
    )


class InFluxNodeDTO(StrictModel):
    """A node with open changes, and the dossiers that propose them."""

    id: str
    count: int = Field(
        description="Its open changes, as `/api/nodes/in-flux` counts them: proposed "
        "changes of documents of a dossier that has not ended."
    )
    dossiers: list[InFluxDossierDTO] = Field(
        description="Most open changes first, then the newest number."
    )


class InFluxDossiersResponse(StrictModel):
    """The open changes of the nodes asked, with their dossiers (`GET /api/nodes/in-flux/
    dossiers`)."""

    nodes: list[InFluxNodeDTO] = Field(
        description="The nodes asked that have an open change, by id; one without is "
        "left out, as in `/api/nodes/in-flux`."
    )

    @classmethod
    def from_nodes(cls, nodes: dict[str, dict[str, Any]]) -> InFluxDossiersResponse:
        return cls(
            nodes=[
                InFluxNodeDTO(
                    id=node_id,
                    count=node["count"],
                    dossiers=[
                        InFluxDossierDTO(
                            id=d["id"],
                            dossier_number=d["number"],
                            title=d["title"],
                            bill_id=d["bill_id"],
                            closed_known=d["closed_known"],
                            count=d["count"],
                        )
                        for d in node["dossiers"]
                    ],
                )
                for node_id, node in sorted(nodes.items())
            ]
        )
