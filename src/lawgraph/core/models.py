from __future__ import annotations

import re
import unicodedata
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Any

from pydantic import ValidationError

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
    COLLECTION_TOPICS,
)
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

# Collections in which a pipeline creates a stub for a record it has not loaded.
STUB_COLLECTIONS = frozenset(
    {
        COLLECTION_ANNEXES,
        COLLECTION_ARTICLES,
        COLLECTION_INSTRUMENTS,
        COLLECTION_JUDGMENTS,
    }
)


@dataclass
class PipelineResult:
    """Uniform result returned by every pipeline's run() method."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0  # written as it already was: looked up, left alone
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def merge(self, other: PipelineResult) -> PipelineResult:
        return PipelineResult(
            created=self.created + other.created,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            skipped=self.skipped + other.skipped,
            errors=[*self.errors, *other.errors],
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


class NodeType(str, Enum):
    """High-level domain types for nodes in the legal graph."""

    INSTRUMENT = (
        "instrument"  # law, regulation, treaty, directive; also an amending publication
    )
    ARTICLE = "article"  # one article (identity across versions)
    CASE = "case"  # TK Zaak: any item the Tweede Kamer handles
    DOCUMENT = "document"  # kamerstuk, MvT, amendment, motion, advice
    JUDGMENT = "judgment"  # case law (Rechtspraak, Hoge Raad, CJEU, ECHR)
    TOPIC = "topic"  # semantic topic node
    # Parliamentary entities
    DOSSIER = "dossier"  # kamerstukdossier: numbered file of documents around one bill
    ACTIVITY = "activity"  # debate or hearing
    DECISION = "decision"  # a Besluit that was voted on
    COMMITMENT = "commitment"  # ministerial commitment (toezegging)
    COMMITTEE = "committee"  # parliamentary committee
    MEMBER = "member"  # member of parliament or minister
    FACTION = "faction"  # parliamentary party / political group
    CABINET = "cabinet"  # a Dutch cabinet (kabinet), from Wikidata
    INSTRUMENT_VERSION = "instrument_version"  # dated version of an instrument
    ARTICLE_VERSION = "article_version"  # dated version of an article
    ANNEX = "annex"  # annex (bijlage) of an instrument


# The collection of every node type: one collection per type and one type per collection, so
# the collection in an id says the type without reading the node.
COLLECTION_OF_TYPE: dict[NodeType, str] = {
    NodeType.INSTRUMENT: COLLECTION_INSTRUMENTS,
    NodeType.ARTICLE: COLLECTION_ARTICLES,
    NodeType.INSTRUMENT_VERSION: COLLECTION_INSTRUMENT_VERSIONS,
    NodeType.ARTICLE_VERSION: COLLECTION_ARTICLE_VERSIONS,
    NodeType.ANNEX: COLLECTION_ANNEXES,
    NodeType.JUDGMENT: COLLECTION_JUDGMENTS,
    NodeType.DOSSIER: COLLECTION_DOSSIERS,
    NodeType.CASE: COLLECTION_CASES,
    NodeType.DOCUMENT: COLLECTION_DOCUMENTS,
    NodeType.ACTIVITY: COLLECTION_ACTIVITIES,
    NodeType.DECISION: COLLECTION_DECISIONS,
    NodeType.COMMITMENT: COLLECTION_COMMITMENTS,
    NodeType.MEMBER: COLLECTION_MEMBERS,
    NodeType.FACTION: COLLECTION_FACTIONS,
    NodeType.CABINET: COLLECTION_CABINETS,
    NodeType.COMMITTEE: COLLECTION_COMMITTEES,
    NodeType.TOPIC: COLLECTION_TOPICS,
}
TYPE_OF_COLLECTION: dict[str, NodeType] = {
    collection: node_type for node_type, collection in COLLECTION_OF_TYPE.items()
}


@dataclass
class Node:
    """
    Basic node abstraction for documents stored in ArangoDB.

      - collection: the ArangoDB collection the document lives in
      - key: deterministic `_key` (set via `make_node_key`)
      - type: semantic node type (NodeType enum)
      - labels: domain tags (e.g. ["Strafrecht", "TK"])
      - props: domain-specific metadata (should always include `display_name`)
      - _skip_validation: pass True to bypass props schema validation. Only use
        this for internal copies (from_document, with_key) or trusted tools that
        write partial/arbitrary props outside the normalize pipeline contract.
    """

    collection: str
    type: NodeType
    key: str | None = None
    labels: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)
    _skip_validation: InitVar[bool] = False

    def __post_init__(self, _skip_validation: bool) -> None:
        if _skip_validation:
            return
        from lawgraph.core.props import (  # deferred to avoid circular import
            COLLECTION_SCHEMAS,
        )

        schema = COLLECTION_SCHEMAS.get(self.collection)
        if schema is None:
            return
        try:
            schema.model_validate(self.props)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid props for collection {self.collection!r}:\n{exc}"
            ) from exc

    @property
    def arango_id(self) -> str | None:
        if self.key is None:
            return None
        return f"{self.collection}/{self.key}"

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
            doc["_key"] = self.key
        return doc

    @classmethod
    def from_document(cls, collection: str, doc: dict[str, Any]) -> Node:
        """Deserialise a raw ArangoDB document — bypasses props validation."""
        key = doc.get("_key")
        if "type" not in doc:
            logger.warning(
                "Document %r in collection %r has no 'type' field; defaulting to TOPIC",
                key,
                collection,
            )
        type_str = doc.get("type", NodeType.TOPIC.value)
        try:
            node_type = NodeType(type_str)
        except ValueError:
            logger.warning(
                "Unknown node type %r in collection %r; treating as TOPIC",
                type_str,
                collection,
            )
            node_type = NodeType.TOPIC
        labels = list(doc.get("labels", []))

        props_field = doc.get("props")
        if isinstance(props_field, dict):
            props = dict(props_field)
        else:
            props = {
                k: v for k, v in doc.items() if k not in {"_key", "type", "labels"}
            }

        # Use object.__new__ to bypass __init__ (and __post_init__ validation).
        # A stored document may carry fields the current schema does not name.
        instance = object.__new__(cls)
        instance.collection = collection
        instance.key = key
        instance.type = node_type
        instance.labels = labels
        instance.props = props
        return instance

    def with_key(self, key: str) -> Node:
        return Node(
            collection=self.collection,
            type=self.type,
            key=key,
            labels=list(self.labels),
            props=dict(self.props),
            _skip_validation=True,  # props were already validated at construction
        )


_KEY_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")
_KEY_COLLAPSE_RE = re.compile(r"_{2,}")


def _sanitize_key(value: str, *, fallback: str = "node") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = _KEY_SANITIZE_RE.sub("_", normalized)
    normalized = _KEY_COLLAPSE_RE.sub("_", normalized)
    normalized = normalized.strip("_")
    if not normalized:
        normalized = fallback
    return normalized


def collection_from_id(node_id: str, fallback: str) -> str:
    """Return the collection name from an ArangoDB document ID (collection/key)."""
    return node_id.split("/")[0] if "/" in node_id else fallback


def parse_arango_id(arango_id: str) -> tuple[str, str]:
    """Split an ArangoDB document ID into (collection, key).

    Raises ValueError if the ID does not contain a '/'.
    """
    if "/" not in arango_id:
        raise ValueError(f"Not a valid ArangoDB document ID: {arango_id!r}")
    collection, key = arango_id.split("/", 1)
    return collection, key


def make_node_key(*parts: str | None, fallback: str = "node") -> str:
    joined = "_".join(part for part in parts if part is not None and part.strip())
    if not joined:
        joined = fallback
    return _sanitize_key(joined, fallback=fallback)
