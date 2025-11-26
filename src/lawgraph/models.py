# src/lawgraph/models.py

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """High-level domain types for nodes in the legal graph."""

    INSTRUMENT = "instrument"          # EU/NL law, directive, regulation, act
    ARTICLE = "article"                # Individual article of an instrument
    PROCEDURE = "procedure"            # Parliamentary / legislative procedure
    PUBLICATION = "publication"        # Staatsblad, Staatscourant, OJ, TK-stuk
    # Case law (Raad van State, Hoge Raad, EU)
    JUDGMENT = "judgment"
    ACTOR = "actor"                    # Institution, court, chamber, ministry
    TOPIC = "topic"                    # Semantic topic node (asielrecht, etc.)


@dataclass
class Node:
    """
    Basic node abstraction for documents stored in ArangoDB.

    The fields map directly to the Arango representation:

      - collection: the collection the document lives in
      - key: deterministic `_key` (May be set via `make_node_key`)
      - type: semantic node type (enum)
      - labels: domain tags (e.g. `["Strafrecht"]`)
      - props: domain-specific metadata (should include `display_name`)
    """

    collection: str
    type: NodeType
    key: str | None = None
    labels: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str | None:
        """
        Return the Arango `_id` for this node when the key is present.
        """
        if self.key is None:
            return None
        return f"{self.collection}/{self.key}"

    def to_document(self) -> dict[str, Any]:
        """
        Convert the node into a dictionary suitable for Arango inserts/updates.
        """
        doc: dict[str, Any] = {
            "type": self.type.value,
            "labels": list(self.labels),
            "props": dict(self.props),
        }
        if self.key is not None:
            doc["_key"] = self.key
        return doc

    @classmethod
    def from_document(cls, collection: str, doc: dict[str, Any]) -> Node:
        """
        Instantiate a Node from an Arango document representation.
        """
        key = doc.get("_key")
        type_str = doc.get("type", NodeType.TOPIC.value)
        node_type = NodeType(type_str)
        labels = list(doc.get("labels", []))

        props_field = doc.get("props")
        if isinstance(props_field, dict):
            props = dict(props_field)
        else:
            props = {
                k: v
                for k, v in doc.items()
                if k not in {"_key", "type", "labels"}
            }

        return cls(
            collection=collection,
            key=key,
            type=node_type,
            labels=labels,
            props=props,
        )

    def with_key(self, key: str) -> Node:
        """Return a copy of this node explicitly keyed."""
        return Node(
            collection=self.collection,
            type=self.type,
            key=key,
            labels=list(self.labels),
            props=dict(self.props),
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


def make_node_key(*parts: str, fallback: str = "node") -> str:
    joined = "_".join(
        part for part in parts if part is not None and part.strip())
    if not joined:
        joined = fallback
    return _sanitize_key(joined, fallback=fallback)


class EdgeType(str, Enum):
    """
    Optional enum for well-known relation types.

    You don't have to use this everywhere, but it helps structure queries.
    """

    ENACTS = "ENACTS"              # publication → instrument
    AMENDS = "AMENDS"              # instrument → instrument
    IMPLEMENTS = "IMPLEMENTS"      # national law → EU directive
    PART_OF_PROCEDURE = "PART_OF_PROCEDURE"  # document → procedure
    DISCUSSES = "DISCUSSES"        # procedure → instrument
    APPLIES = "APPLIES"            # judgment → instrument/article
    REFERS_TO = "REFERS_TO"        # judgment → instrument/article
    RELATED_TOPIC = "RELATED_TOPIC"
