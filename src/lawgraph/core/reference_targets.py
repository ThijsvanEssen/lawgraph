"""The node a reference stored on an article (``props.references``) names: the article
of a link to one, the regulation of a link to a chapter or a title, the annex of a link to
one, the EU act of a CELEX link."""

from __future__ import annotations

from typing import Any, Literal

from lawgraph.core.models import make_node_key

ReferenceCollection = Literal["articles", "instruments", "annexes"]


def reference_target(ref: dict[str, Any]) -> tuple[ReferenceCollection, str] | None:
    """The ``(collection, key)`` of the node a stored reference names, or None."""
    bwb_id, article = ref.get("bwb_id"), ref.get("article")
    if ref.get("annex"):
        return "annexes", str(ref["annex"])
    if ref.get("celex"):
        return "instruments", make_node_key(str(ref["celex"]))
    if bwb_id and article:
        return "articles", make_node_key(str(bwb_id), str(article))
    if bwb_id:
        return "instruments", make_node_key(str(bwb_id))
    return None


def reference_targets(references: Any) -> dict[str, set[str]]:
    """The keys the stored *references* name, per collection: what is looked up to say
    whether each exists."""
    wanted: dict[str, set[str]] = {}
    for ref in references if isinstance(references, list) else []:
        target = reference_target(ref) if isinstance(ref, dict) else None
        if target is not None:
            wanted.setdefault(target[0], set()).add(target[1])
    return wanted
