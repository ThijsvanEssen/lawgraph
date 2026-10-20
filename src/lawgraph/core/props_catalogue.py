"""The props tables of ``docs/data-model.md``, generated from the schemas of ``core.props``.

Each node collection has a block of its own in the docs, between ``<!-- props:<collection>:
begin ... -->`` and ``<!-- props:<collection>:end -->``, and the fields every collection
shares have the block ``common``. A row is a field: its path (``ek_bill.progress[].phase``
for a field of a nested object), its type and its description, the attribute docstring of
the field. ``python -m lawgraph.core.props_catalogue`` writes them; a test fails while the
docs differ.
"""

from __future__ import annotations

import pathlib
import re
import types
from collections.abc import Iterator, Mapping
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from lawgraph.core.models import COLLECTIONS
from lawgraph.core.props import _CommonProps
from lawgraph.core.xml import collapse_ws

COMMON = "common"
_MARKER = re.compile(
    r"<!-- props:(?P<name>[a-z_]+):begin [^>]*-->\n.*?<!-- props:(?P=name):end -->",
    re.DOTALL,
)


def _begin(name: str) -> str:
    return f"<!-- props:{name}:begin (generated: python -m lawgraph.core.props_catalogue) -->"


def _bare(annotation: Any) -> Any:
    """*annotation* without ``| None``."""
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    return annotation


def _model(annotation: Any) -> type[BaseModel] | None:
    """The nested schema of a field, of the field itself or of each item of its list."""
    bare = _bare(annotation)
    if get_origin(bare) is list:
        bare = _bare(get_args(bare)[0])
    return bare if isinstance(bare, type) and issubclass(bare, BaseModel) else None


def _type(annotation: Any, names: Mapping[Any, str]) -> str:
    """*annotation* as the docs write it; one of *names* by its name."""
    bare = _bare(annotation)
    if bare in names:
        return names[bare]
    origin = get_origin(bare)
    if origin in (Union, types.UnionType):
        return " \\| ".join(_type(arg, names) for arg in get_args(bare))
    if origin is list:
        return f"list[{_type(get_args(bare)[0], names)}]"
    if origin is dict:
        key, value = get_args(bare)
        return (
            "object"
            if value is Any
            else f"{{{_type(key, names)}: {_type(value, names)}}}"
        )
    if origin is Literal:
        return " \\| ".join(f'"{value}"' for value in get_args(bare))
    if isinstance(bare, type) and issubclass(bare, BaseModel):
        return "object"
    return getattr(bare, "__name__", str(bare))


def field_rows(
    schema: type[BaseModel],
    seen: set[type[BaseModel]],
    prefix: str = "",
    skip: frozenset[str] = frozenset(),
    names: Mapping[Any, str] | None = None,
) -> Iterator[str]:
    """A row per field of *schema* (``| `name` | `type` | meaning |``, the name as stored),
    each followed by the rows of its nested schema the first time the table meets that
    schema (*seen*); a type in *names* is written by its name."""
    for name, field in schema.model_fields.items():
        if name in skip:
            continue
        stored = field.alias or name
        meaning = collapse_ws(field.description).replace("``", "`").replace("|", "\\|")
        yield f"| `{prefix}{stored}` | `{_type(field.annotation, names or {})}` | {meaning} |"
        nested = _model(field.annotation)
        if nested is not None and nested not in seen:
            seen.add(nested)
            many = get_origin(_bare(field.annotation)) is list
            yield from field_rows(
                nested, seen, f"{prefix}{stored}{'[]' if many else ''}.", names=names
            )


def render_table(name: str) -> str:
    """The Markdown table of the props of collection *name*, or of ``common``."""
    if name == COMMON:
        rows = field_rows(_CommonProps, set())
    else:
        spec = next(spec for spec in COLLECTIONS if spec.name == name)
        rows = field_rows(
            spec.props_schema, set(), skip=frozenset(_CommonProps.model_fields)
        )
    head = ["| Prop | Type | Meaning |", "|------|------|---------|"]
    return "\n".join([*head, *rows]) + "\n"


def block_names() -> list[str]:
    """``common`` and every node collection: the blocks the docs hold."""
    return [COMMON, *(spec.name for spec in COLLECTIONS)]


def replace_blocks(document: str) -> str:
    """*document* with every props block between its markers refreshed."""

    def fresh(match: re.Match[str]) -> str:
        name = match["name"]
        return f"{_begin(name)}\n\n{render_table(name)}\n<!-- props:{name}:end -->"

    return _MARKER.sub(fresh, document)


def blocks_in(document: str) -> list[str]:
    """The names of the props blocks in *document*, in their order."""
    return [match["name"] for match in _MARKER.finditer(document)]


if __name__ == "__main__":
    path = pathlib.Path(__file__).resolve().parents[3] / "docs" / "data-model.md"
    text = path.read_text()
    missing = set(block_names()) - set(blocks_in(text))
    if missing:
        raise SystemExit(f"no props block in docs/data-model.md for: {sorted(missing)}")
    path.write_text(replace_blocks(text))
