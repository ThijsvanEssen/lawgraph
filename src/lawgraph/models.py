from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class PipelineResult:
    """Uniform result returned by every pipeline's run() method."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def merge(self, other: PipelineResult) -> PipelineResult:
        return PipelineResult(
            created=self.created + other.created,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            errors=[*self.errors, *other.errors],
        )

    def summary(self) -> str:
        parts: list[str] = []
        if self.created:
            parts.append(f"{self.created} created")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts) if parts else "nothing to do"


class NodeType(str, Enum):
    """High-level domain types for nodes in the legal graph."""

    INSTRUMENT = "instrument"  # EU/NL law, directive, regulation, act
    ARTICLE = "article"  # Individual article of an instrument
    PROCEDURE = "procedure"  # TK Zaak — one legislative track
    PUBLICATION = "publication"  # TK document, Staatsblad, OJ publication
    JUDGMENT = "judgment"  # Case law (Rechtspraak, Hoge Raad, CJEU)
    TOPIC = "topic"  # Semantic topic node
    # Parliamentary dossier entities
    DOSSIER = "dossier"  # Kamerstukdossier — groups one or more Zaak
    ACTIVITEIT = "activiteit"  # Debate/hearing in which documents are treated
    STEMMING = "stemming"  # Vote on a motion or wetsvoorstel
    TOEZEGGING = "toezegging"  # Ministerial commitment made during a debate
    COMMISSIE = "commissie"  # Parliamentary committee
    LID = "lid"  # Parliamentary member / minister


@dataclass
class Node:
    """
    Basic node abstraction for documents stored in ArangoDB.

      - collection: the ArangoDB collection the document lives in
      - key: deterministic `_key` (set via `make_node_key`)
      - type: semantic node type (NodeType enum)
      - labels: domain tags (e.g. ["Strafrecht", "TK"])
      - props: domain-specific metadata (should always include `display_name`)
    """

    collection: str
    type: NodeType
    key: str | None = None
    labels: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str | None:
        if self.key is None:
            return None
        return f"{self.collection}/{self.key}"

    def to_document(self) -> dict[str, Any]:
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
        key = doc.get("_key")
        type_str = doc.get("type", NodeType.TOPIC.value)
        try:
            node_type = NodeType(type_str)
        except ValueError:
            node_type = NodeType.TOPIC
        labels = list(doc.get("labels", []))

        props_field = doc.get("props")
        if isinstance(props_field, dict):
            props = dict(props_field)
        else:
            props = {
                k: v for k, v in doc.items() if k not in {"_key", "type", "labels"}
            }

        return cls(
            collection=collection,
            key=key,
            type=node_type,
            labels=labels,
            props=props,
        )

    def with_key(self, key: str) -> Node:
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
    joined = "_".join(part for part in parts if part is not None and part.strip())
    if not joined:
        joined = fallback
    return _sanitize_key(joined, fallback=fallback)
