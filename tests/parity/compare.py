"""Strict comparison of two API responses, and the named deviations the plan allows.

A JSON body is compared as parsed with its object keys in order: the same keys in another
order is a difference. ``1`` and ``1.0`` are equal (D6). An Atom body is compared after C14N.
Headers: the same status, content type and ``Cache-Control``; an ``ETag`` on both or on
neither, of the form ``W/"<api version>-<data version>"``.

The allowed deviations are not silent: ``compare`` names them (``D3`` search ranking, ``D9``
the neighbourhood over its cap), and the report counts them apart.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

ETAG = re.compile(r'^W/"\d+\.\d+\.\d+-[^"]+"$')
HEADERS = ("content-type", "cache-control")


@dataclass(frozen=True)
class Pairs:
    """A JSON object as its ``(key, value)`` pairs, in order."""

    items: tuple[tuple[str, Any], ...]


def parse(text: str) -> Any:
    return json.loads(text, object_pairs_hook=lambda pairs: Pairs(tuple(pairs)))


@dataclass
class Result:
    same: bool
    where: str = ""
    detail: str = ""
    allowed: str = ""  # the decision that allows the deviation (D3, D9), if any


def compare(
    path: str, query: dict[str, str], golden: dict[str, Any], other: dict[str, Any]
) -> Result:
    if golden["status"] != other["status"]:
        return Result(False, "status", f"{golden['status']} != {other['status']}")
    headers = _headers(golden["headers"], other["headers"])
    if headers:
        return Result(False, "headers", headers)
    kind = golden["headers"].get("content-type", "")
    if "json" in kind:
        return _json(path, query, golden["body"], other["body"])
    if "xml" in kind:
        same = _c14n(golden["body"]) == _c14n(other["body"])
        return Result(
            same, "" if same else "body", "" if same else "Atom differs after C14N"
        )
    same = golden["body"] == other["body"]
    return Result(same, "" if same else "body", "" if same else "bytes differ")


def _headers(golden: dict[str, str], other: dict[str, str]) -> str:
    for name in HEADERS:
        if golden.get(name) != other.get(name):
            return f"{name}: {golden.get(name)!r} != {other.get(name)!r}"
    tags = golden.get("etag"), other.get("etag")
    if (tags[0] is None) != (tags[1] is None):
        return f"etag: {tags[0]!r} != {tags[1]!r}"
    if tags[1] is not None and not ETAG.match(tags[1]):
        return f"etag has another form: {tags[1]!r}"
    return ""


def _c14n(text: str) -> str:
    return ET.canonicalize(text, strip_text=True)


def _json(
    path: str, query: dict[str, str], golden_text: str, other_text: str
) -> Result:
    golden, other = parse(golden_text), parse(other_text)
    where = first_difference(golden, other)
    if where is None:
        return Result(True)
    allowed = allowed_deviation(path, query, golden, other)
    return Result(False, where[0], where[1], allowed)


def first_difference(a: Any, b: Any, where: str = "$") -> tuple[str, str] | None:
    """Where *a* and *b* first differ, and how; ``None`` when they are the same."""
    if isinstance(a, Pairs) and isinstance(b, Pairs):
        keys_a, keys_b = [k for k, _ in a.items], [k for k, _ in b.items]
        if keys_a != keys_b:
            return where, f"keys {keys_a} != {keys_b}"
        for (key, va), (_, vb) in zip(a.items, b.items, strict=True):
            found = first_difference(va, vb, f"{where}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return where, f"length {len(a)} != {len(b)}"
        for n, (va, vb) in enumerate(zip(a, b, strict=True)):
            found = first_difference(va, vb, f"{where}[{n}]")
            if found:
                return found
        return None
    if _number(a) and _number(b):
        return None if a == b else (where, f"{a!r} != {b!r}")  # D6: 1 == 1.0
    if type(a) is not type(b) or a != b:
        return where, f"{_short(a)} != {_short(b)}"
    return None


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _short(value: Any) -> str:
    text = repr(value.items if isinstance(value, Pairs) else value)
    return text if len(text) < 120 else text[:117] + "..."


# ── allowed deviations ───────────────────────────────────────────────────────


def allowed_deviation(path: str, query: dict[str, str], golden: Any, other: Any) -> str:
    if path == "/api/search" and same_outside_hits(golden, other):
        return "D3"
    if path.endswith("/neighborhood"):
        cap = int(query.get("cap", "200"))
        a, b = plain(golden), plain(other)
        if _capped(a, cap) and _capped(b, cap) and a["focal_id"] == b["focal_id"]:
            return "D9"
    return ""


def plain(value: Any) -> Any:
    """*value* with its objects as dicts: for the comparisons that ignore key order."""
    if isinstance(value, Pairs):
        return {k: plain(v) for k, v in value.items}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def hit_groups(body: Any) -> dict[str, list[str]]:
    """The ids of the hits of a search answer per type, in their order."""
    results = plain(body).get("results") if isinstance(plain(body), dict) else None
    if not isinstance(results, dict):
        return {}
    return {
        kind: [str(hit.get("id") or hit.get("key")) for hit in hits]
        for kind, hits in results.items()
        if isinstance(hits, list)
    }


def hit_ids(body: Any) -> list[str]:
    """The ids of the hits of a search answer, type after type."""
    return [hit for hits in hit_groups(body).values() for hit in hits]


def same_outside_hits(golden: Any, other: Any) -> bool:
    """D3: the answers differ only in which hits each type has and in their order (how
    close the hits are is measured apart: ``search_agreement``)."""
    a, b = plain(golden), plain(other)
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    rest = [
        {k: v for k, v in x.items() if k not in ("results", "total")} for x in (a, b)
    ]
    return rest[0] == rest[1] and list(hit_groups(a)) == list(hit_groups(b))


def search_agreement(golden: Any, other: Any) -> list[tuple[bool, float]]:
    """Per type with hits: (the same first hit, the overlap of the hits as |A∩B| / |A∪B|)."""
    found = []
    theirs = hit_groups(other)
    for kind, mine in hit_groups(golden).items():
        other_hits = theirs.get(kind, [])
        if not mine and not other_hits:
            continue
        union = set(mine) | set(other_hits)
        overlap = len(set(mine) & set(other_hits)) / len(union)
        found.append((mine[:1] == other_hits[:1], overlap))
    return found


def _capped(body: Any, cap: int) -> bool:
    """D9: a neighbourhood that reached its cap; which nodes it holds then is a valid BFS
    prefix, not one exact set."""
    return isinstance(body, dict) and len(body.get("nodes", [])) > cap
