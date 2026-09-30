"""The reads and updates of the semantic phase, one module per source domain. ``slim``
projects a node onto the props a step reads."""

from __future__ import annotations


def slim(var: str, *fields: str) -> str:
    """AQL for the document *var* with only *fields* of its props.

    A judgment carries its XML, its text and its paragraphs, a TK document the whole API
    payload; a pipeline that reads one of them must not have the rest sent over. The result
    has the shape of a document, so ``Node.from_document`` reads it.
    """
    names = ", ".join(f'"{field}"' for field in fields)
    return (
        f"{{_key: {var}._key, type: {var}.type, labels: {var}.labels, "
        f"props: KEEP({var}.props, {names})}}"
    )
