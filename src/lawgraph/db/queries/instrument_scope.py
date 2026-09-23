"""The instrument a URL names, and which articles belong to it.

An instrument is named by its BWB id (`BWBR0001854`), its CELEX number (`32016L0680`) or its
node key (`bwbr0001854`, `32016l0680`, `echr_convention`). The articles of a BWB regulation
carry `props.bwb_id`, those of an EU act `props.celex`; both are indexed, so the articles of
an instrument are read by the identifying prop and not through `PART_OF` (which the articles
of the ECHR Convention lack, and which costs an edge lookup per article).

`scope_of` is pure: the instrument sub-routes use it without a lookup, so an identifier that
matches nothing answers an empty list, as before. `resolve_instrument` is the lookup for the
routes that answer about the instrument itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.identifiers import parse_celex
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.queries._helpers import _ensure_doc


@dataclass(frozen=True)
class InstrumentScope:
    """The prop that identifies the articles of an instrument, and its value."""

    prop: Literal["bwb_id", "celex"]
    value: str  # upper-cased, as the props are stored

    @property
    def node_key(self) -> str:
        return make_node_key(self.value)


def scope_of(identifier: str) -> InstrumentScope:
    """A CELEX number scopes by `props.celex`; anything else by `props.bwb_id`.

    An identifier that is neither (a treaty key, `ECHR-CONVENTION`) is a `bwb_id` to the
    articles that carry one, and matches nothing otherwise.
    """
    value = identifier.strip().upper()
    if parse_celex(value) is not None:
        return InstrumentScope("celex", value)
    return InstrumentScope("bwb_id", value)


def resolve_instrument(store: ArangoStore, identifier: str) -> dict[str, Any] | None:
    """The instrument node named by a BWB id, CELEX number or node key; ``None`` if unknown.

    One lookup in the primary index: instrument keys are `make_node_key` of the BWB id, the
    CELEX number or the source's own id, and the key of an identifier is the same in any case.
    """
    key = make_node_key(identifier)
    return _ensure_doc(store.collection(COLLECTION_INSTRUMENTS).get(key))


def scope_of_node(doc: dict[str, Any]) -> InstrumentScope | None:
    """The scope of a resolved instrument; ``None`` when its articles carry no identifier."""
    props = doc.get("props") or {}
    if props.get("bwb_id"):
        return InstrumentScope("bwb_id", str(props["bwb_id"]).upper())
    if props.get("celex"):
        return InstrumentScope("celex", str(props["celex"]).upper())
    return None
