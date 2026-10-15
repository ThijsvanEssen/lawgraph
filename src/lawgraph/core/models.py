from __future__ import annotations

from collections.abc import Iterable
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Any, Literal, get_args

from pydantic import BaseModel, ValidationError

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core import props
from lawgraph.core.text_fold import ascii_slug


@dataclass
class PipelineResult:
    """Uniform result returned by every pipeline's run() method."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0  # written as it already was: looked up, left alone
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    # What the counts do not say and whoever reads the table of a phase must know: work
    # left for a next run, or work the graph gave nothing to choose from.
    notes: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def merge(self, other: PipelineResult) -> PipelineResult:
        return PipelineResult(
            created=self.created + other.created,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            skipped=self.skipped + other.skipped,
            errors=[*self.errors, *other.errors],
            notes=[*self.notes, *other.notes],
        )

    def summary(self) -> str:
        parts: list[str] = []
        counts = (
            ("created", self.created),
            ("updated", self.updated),
            ("unchanged", self.unchanged),
            ("skipped", self.skipped),
        )
        parts.extend(f"{count:,} {what}" for what, count in counts if count)
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts) if parts else "nothing to do"


# The way an edge is followed from a node: the edges that leave it, or those that reach it.
Direction = Literal["outbound", "inbound"]
DIRECTIONS: tuple[Direction, ...] = get_args(Direction)


class NodeType(str, Enum):
    """High-level domain types for nodes in the legal graph."""

    INSTRUMENT = (
        "instrument"  # law, regulation, treaty, directive; also an amending publication
    )
    ARTICLE = "article"  # one article (identity across versions)
    CASE = "case"  # TK Zaak: any item the Tweede Kamer handles
    DOCUMENT = "document"  # kamerstuk, MvT, amendment, motion, advice
    JUDGMENT = "judgment"  # case law (Rechtspraak, Hoge Raad, CJEU, ECHR)
    # Parliamentary entities
    DOSSIER = "dossier"  # kamerstukdossier: numbered file of documents around one bill
    ACTIVITY = "activity"  # debate or hearing
    DECISION = "decision"  # a Besluit that was voted on
    COMMITMENT = "commitment"  # ministerial commitment (toezegging)
    COMMITTEE = "committee"  # parliamentary committee
    MEMBER = "member"  # member of parliament or minister
    FACTION = "faction"  # parliamentary party / political group
    CABINET = "cabinet"  # a Dutch cabinet since 1945 (kabinet), from Rijksoverheid
    INSTRUMENT_VERSION = "instrument_version"  # dated version of an instrument
    ARTICLE_VERSION = "article_version"  # dated version of an article
    ANNEX = "annex"  # annex (bijlage) of an instrument


@dataclass(frozen=True)
class CollectionSpec:
    """A node collection: its table, the one type of its nodes (so the collection in an id
    says the type without reading the node), the concept the docs and the API name it by,
    the schema of its props, and whether a pipeline makes a stub in it for a record it has
    not loaded."""

    name: str
    node_type: NodeType
    concept: str
    props_schema: type[BaseModel]
    stub: bool = False


# In the order of the tables of the schema (``db.schema.NODE_COLLECTIONS``).
COLLECTIONS: tuple[CollectionSpec, ...] = (
    CollectionSpec(
        COLLECTION_INSTRUMENTS,
        NodeType.INSTRUMENT,
        "Instrument",
        props.InstrumentProps,
        stub=True,
    ),
    CollectionSpec(
        COLLECTION_ARTICLES, NodeType.ARTICLE, "Article", props.ArticleProps, stub=True
    ),
    CollectionSpec(
        COLLECTION_INSTRUMENT_VERSIONS,
        NodeType.INSTRUMENT_VERSION,
        "InstrumentVersion",
        props.InstrumentVersionProps,
    ),
    CollectionSpec(
        COLLECTION_ARTICLE_VERSIONS,
        NodeType.ARTICLE_VERSION,
        "ArticleVersion",
        props.ArticleVersionProps,
    ),
    CollectionSpec(COLLECTION_CASES, NodeType.CASE, "Case", props.CaseProps),
    CollectionSpec(
        COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "Document", props.DocumentProps
    ),
    CollectionSpec(
        COLLECTION_JUDGMENTS,
        NodeType.JUDGMENT,
        "Judgment",
        props.JudgmentProps,
        stub=True,
    ),
    CollectionSpec(
        COLLECTION_DOSSIERS, NodeType.DOSSIER, "Dossier", props.DossierProps
    ),
    CollectionSpec(
        COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "Activity", props.ActivityProps
    ),
    CollectionSpec(
        COLLECTION_DECISIONS, NodeType.DECISION, "Decision", props.DecisionProps
    ),
    CollectionSpec(
        COLLECTION_COMMITMENTS, NodeType.COMMITMENT, "Commitment", props.CommitmentProps
    ),
    CollectionSpec(
        COLLECTION_COMMITTEES, NodeType.COMMITTEE, "Committee", props.CommitteeProps
    ),
    CollectionSpec(COLLECTION_MEMBERS, NodeType.MEMBER, "Member", props.MemberProps),
    CollectionSpec(
        COLLECTION_FACTIONS, NodeType.FACTION, "Faction", props.FactionProps
    ),
    CollectionSpec(
        COLLECTION_CABINETS, NodeType.CABINET, "Cabinet", props.CabinetProps
    ),
    CollectionSpec(
        COLLECTION_ANNEXES, NodeType.ANNEX, "Annex", props.AnnexProps, stub=True
    ),
)
COLLECTION_SPECS: dict[str, CollectionSpec] = {spec.name: spec for spec in COLLECTIONS}
COLLECTION_OF_TYPE: dict[NodeType, str] = {
    spec.node_type: spec.name for spec in COLLECTIONS
}
TYPE_OF_COLLECTION: dict[str, NodeType] = {
    spec.name: spec.node_type for spec in COLLECTIONS
}
# Collections in which a pipeline creates a stub for a record it has not loaded.
STUB_COLLECTIONS = frozenset(spec.name for spec in COLLECTIONS if spec.stub)


def require_named_props(collection: str, keys: Iterable[str]) -> None:
    """Raise ``ValueError`` when the props schema of *collection* does not name one of
    *keys*: what a write that skips validation (a skeleton, a bulk or SQL update) may set on
    a node is what ``core.props`` names, and so what ``docs/data-model.md`` lists."""
    named = COLLECTION_SPECS[collection].props_schema.model_fields
    unnamed = sorted(set(keys) - set(named))
    if unnamed:
        raise ValueError(f"Props of {collection!r} the schema does not name: {unnamed}")


@dataclass
class Node:
    """A node of the graph as a pipeline writes it.

    - collection: the table it lives in, which says its type (``type``)
    - key: deterministic key (set via `make_node_key`)
    - labels: domain tags (e.g. ["Strafrecht", "TK"])
    - props: domain-specific metadata, validated against the schema of the collection
    - _skip_validation: pass True to bypass props schema validation. Only use
      this for internal copies (from_document) or trusted tools that
      write partial/arbitrary props outside the normalize pipeline contract.
    """

    collection: str
    key: str | None = None
    labels: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)
    _skip_validation: InitVar[bool] = False

    def __post_init__(self, _skip_validation: bool) -> None:
        spec = COLLECTION_SPECS.get(self.collection)
        if spec is None:
            raise ValueError(f"Unknown node collection: {self.collection!r}")
        if _skip_validation:
            return
        try:
            spec.props_schema.model_validate(self.props)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid props for collection {self.collection!r}:\n{exc}"
            ) from exc

    @classmethod
    def skeleton(
        cls, collection: str, key: str | None, props: dict[str, Any] | None = None
    ) -> Node:
        """A node with only the props given (none by default), for an update that merges
        them into the stored node: not validated, a pipeline names only what it changes."""
        return cls(
            collection=collection, key=key, props=props or {}, _skip_validation=True
        )

    @property
    def type(self) -> NodeType:
        return TYPE_OF_COLLECTION[self.collection]

    @property
    def node_id(self) -> str | None:
        return None if self.key is None else node_id(self.collection, self.key)

    def to_document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "type": self.type.value,
            "labels": list(self.labels),
            "props": dict(self.props),
        }
        if self.collection in STUB_COLLECTIONS:
            # An upsert merges props, so a stub that is loaded for real keeps ``stub: true``
            # unless the node says otherwise: the API would go on hiding it and expand-graph
            # would never see a gap close. A node is a stub only when it says so itself.
            doc["props"].setdefault("stub", False)
        if self.key is not None:
            doc["key"] = self.key
        return doc

    @classmethod
    def from_document(cls, collection: str, doc: dict[str, Any]) -> Node:
        """The node of a stored document of *collection*, its type that of the collection;
        not validated (a stored document may carry fields the current schema does not
        name)."""
        props_field = doc.get("props")
        if isinstance(props_field, dict):
            props = dict(props_field)
        else:
            props = {k: v for k, v in doc.items() if k not in {"key", "type", "labels"}}
        return cls(
            collection=collection,
            key=doc.get("key"),
            labels=list(doc.get("labels", [])),
            props=props,
            _skip_validation=True,
        )


def _sanitize_key(value: str, *, fallback: str = "node") -> str:
    return ascii_slug(value, "_") or fallback


def node_id(collection: str, key: str) -> str:
    """The id of the node *key* in *collection*: ``collection/key``."""
    return f"{collection}/{key}"


def parse_node_id(node_id: str) -> tuple[str, str]:
    """Split a node id into (collection, key).

    Raises ValueError if the id does not contain a '/'.
    """
    if "/" not in node_id:
        raise ValueError(f"Not a valid node id: {node_id!r}")
    collection, key = node_id.split("/", 1)
    return collection, key


def key_of(node_id: str) -> str:
    """The key of a node id (``judgments/ecli_nl_hr_2020_1`` -> ``ecli_nl_hr_2020_1``)."""
    return parse_node_id(node_id)[1]


def make_node_key(*parts: str | None, fallback: str = "node") -> str:
    joined = "_".join(part for part in parts if part is not None and part.strip())
    if not joined:
        joined = fallback
    return _sanitize_key(joined, fallback=fallback)


def judgment_id(ecli: str) -> str:
    """The id of the judgment *ecli* names, as its normalizer keys it (a dot is ``_``)."""
    return node_id(COLLECTION_JUDGMENTS, make_node_key(ecli))


def article_id(bwb_id: str, number: str) -> str:
    """The id of article *number* of the law *bwb_id*."""
    return node_id(COLLECTION_ARTICLES, make_node_key(bwb_id, number))
