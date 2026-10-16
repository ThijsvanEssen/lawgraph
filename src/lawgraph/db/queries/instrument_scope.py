"""The instrument a URL names, and which articles belong to it.

An instrument is named by its BWB id (`BWBR0001854`), its CELEX number (`32016L0680`) or its
node key (`bwbr0001854`, `32016l0680`, `bwbv0001000`, `wet_stb_2026_56`). The articles of a
BWB regulation carry `props.bwb_id`, those of an EU act `props.celex`, those of a law of the
Staatsblad the BWB does not hold (yet) `props.official_id` (`stb-2026-56`, which names the
law in a URL too); each is indexed, so the articles of an instrument are read by the
identifying prop and not through `PART_OF` (which a stub article lacks, and which costs an
edge lookup per article).

`scope_of` is pure: the instrument sub-routes use it without a lookup, so an identifier that
matches nothing answers an empty list. `resolve_instrument` is the lookup for the
routes that answer about the instrument itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.identifiers import parse_celex
from lawgraph.core.models import make_node_key
from lawgraph.core.publications import LAW_KEY_PREFIX, law_key, official_of_law_key
from lawgraph.core.readable_paths import STB_LAW
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._helpers import _ensure_doc

# The column of the articles of a law that names it: of the BWB, of the EU, of the
# Staatsblad.
LawColumn = Literal["bwb_id", "celex", "official_id"]


@dataclass(frozen=True)
class InstrumentScope:
    """The prop that identifies the articles of an instrument, and its value."""

    prop: LawColumn
    value: str  # as the props are stored: a BWB id and a CELEX number upper-cased, an
    # official id lower-cased

    @property
    def node_key(self) -> str:
        if self.prop == "official_id":
            return law_key(self.value)
        return make_node_key(self.value)


def scope_of(identifier: str) -> InstrumentScope:
    """A CELEX number scopes by `props.celex`; a law of the Staatsblad, by its
    publication (`STB-2026-56`) or its key (`wet_stb_2026_56`), by `props.official_id`;
    anything else by `props.bwb_id`.

    An identifier that is none of these (a treaty key such as `verdrag_012345`) is a
    `bwb_id` to the articles that carry one, and matches nothing otherwise.
    """
    value = identifier.strip().upper()
    if parse_celex(value) is not None:
        return InstrumentScope("celex", value)
    official = official_of_law_key(identifier.strip().lower()) or identifier.strip()
    if STB_LAW.match(official):
        return InstrumentScope("official_id", official.lower())
    return InstrumentScope("bwb_id", value)


def resolve_instrument(store: GraphStore, identifier: str) -> dict[str, Any] | None:
    """The instrument node named by a BWB id, CELEX number or node key; ``None`` if unknown.

    One lookup in the primary index: instrument keys are `make_node_key` of the BWB id, the
    CELEX number or the source's own id, and the key of an identifier is the same in any case.
    """
    key = make_node_key(identifier)
    return _ensure_doc(store.get_document(COLLECTION_INSTRUMENTS, key))


def same_treaty(store: GraphStore, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The other instruments with the treaty number of *doc*: the Verdragenbank record of a
    BWB treaty, the BWB text of a Verdragenbank treaty; by key. Empty for an instrument
    without a treaty number."""
    number = (doc.get("props") or {}).get("treaty_number")
    # Treaty numbers are strings; the column holds nothing else.
    if not number or not isinstance(number, str):
        return []
    rows = store.query(
        f"""
        SELECT id, key, type, labels, props FROM {COLLECTION_INSTRUMENTS}
        WHERE treaty_number = %(number)s AND key <> %(key)s
        ORDER BY key
        """,
        {"number": number, "key": doc["key"]},
    )
    return [node_doc(row) for row in rows]


def law_column(props: dict[str, Any]) -> LawColumn:
    """The prop (and column) that names the law of an article, or of a law, of *props*:
    ``bwb_id``, else ``celex``, else ``official_id`` (a law of the Staatsblad)."""
    if props.get("bwb_id"):
        return "bwb_id"
    if props.get("celex"):
        return "celex"
    return "official_id" if props.get("official_id") else "bwb_id"


def law_of_article(instrument: str, article: str) -> str:
    """SQL: whether the instrument (alias *instrument*) is the law of the article (alias
    *article*): by its BWB id, its CELEX number, or the key of its law of the Staatsblad
    (``wet_stb_2026_56`` of ``stb-2026-56``)."""
    i, a = instrument, article
    return (
        f"({i}.bwb_id = {a}.bwb_id OR {i}.celex = {a}.celex"
        f" OR {i}.id = '{COLLECTION_INSTRUMENTS}/' || lg_node_key('{LAW_KEY_PREFIX}_'"
        f" || {a}.official_id))"
    )


def is_staatsblad_law(instrument: str) -> str:
    """SQL: whether the instrument (alias *instrument*) is a law of the Staatsblad the BWB
    does not hold (yet): its key is that of the law of its publication
    (``wet_stb_2026_56`` of ``stb-2026-56``), not the publication itself."""
    i = instrument
    return f"{i}.key = lg_node_key('{LAW_KEY_PREFIX}_' || lg_str({i}.props -> 'official_id'))"


def scope_of_node(doc: dict[str, Any]) -> InstrumentScope | None:
    """The scope of a resolved instrument; ``None`` when its articles carry no identifier."""
    props = doc.get("props") or {}
    if props.get("bwb_id"):
        return InstrumentScope("bwb_id", str(props["bwb_id"]).upper())
    if props.get("celex"):
        return InstrumentScope("celex", str(props["celex"]).upper())
    official = official_of_law_key(str(doc.get("key") or ""))
    if official:
        return InstrumentScope("official_id", official)
    return None
