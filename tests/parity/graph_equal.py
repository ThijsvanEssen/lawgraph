"""Is the graph PostgreSQL built the graph ArangoDB built from the same raw records?

    python -m tests.parity.graph_equal --arango-db lawgraph_parity --pg-db lawgraph_parity_pg

Per node collection the ids, per relation the edge keys, and per document all of it: type,
labels and props of a node; ``_from``, ``_to`` and the fields of an edge. Strict, with the
keys of an object in order; ``1`` and ``1.0`` are equal (D6). Only the time of writing
(``VOLATILE``) is left out, and the order of an edge's own fields: the API never serves an
edge whole but picks its fields by name (``api/schemas``), and ArangoDB adds the fields an
update gives in the order of a hash map. Its ``meta`` is served whole, in order.

A difference that a port chose on purpose, where the AQL left a tie open, is a ``CHOICE``
when its entry in ``KNOWN_CHOICES`` matches it; each entry carries its reason. Any other
difference is a ``FAIL``. The exit status is 1 when one is left.

Both databases are only read. Each document is first reduced to a digest; only the
documents whose digests differ are read again, to name where they differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
from arango.client import ArangoClient
from arango.database import StandardDatabase

from lawgraph.config import settings
from lawgraph.config.constants import COLLECTION_EDGES
from lawgraph.db.schema import NODE_COLLECTIONS

from .compare import Pairs, first_difference, parse

SYSTEM = ("_key", "_id", "_rev")
# Fields that hold the time a document was written: the two builds ran at other times.
VOLATILE = frozenset({"created_at", "updated_at"})
SAMPLES = 5
BATCH = 500


# ── known choices ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Choice:
    """A difference a port chose on purpose: ``matches(part, where, arango, pg)`` says
    whether a difference of *part* (a collection or ``edges/<RELATION>``) at *where* is
    this choice. ``arango`` or ``pg`` is ``None`` for a document only one side has."""

    name: str
    reason: str
    matches: Callable[[str, str, Any, Any], bool]


KNOWN_CHOICES: list[Choice] = []


# ── reading ──────────────────────────────────────────────────────────────────


def _volatile_free(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in SYSTEM and k not in VOLATILE}


def _node_text(doc: dict[str, Any]) -> str:
    return json.dumps(
        {
            "type": doc.get("type", ""),
            "labels": list(doc.get("labels") or []),
            "props": doc.get("props") or {},
        },
        ensure_ascii=False,
    )


def _edge_text(doc: dict[str, Any]) -> str:
    fields = _volatile_free(doc)
    return json.dumps(dict(sorted(fields.items())), ensure_ascii=False)


def _canonical(value: Any) -> Any:
    """*value* as parsed with its keys in order, a whole float as an int (D6)."""
    if isinstance(value, Pairs):
        return [[k, _canonical(v)] for k, v in value.items]
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def digest(text: str) -> str:
    canonical = json.dumps(_canonical(parse(text)), ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()


def _arango(db: StandardDatabase, aql: str, **bind: Any) -> Iterator[Any]:
    cursor = db.aql.execute(  # type: ignore[union-attr]
        aql, bind_vars=bind, stream=True, batch_size=2000, ttl=3600
    )
    yield from cursor  # type: ignore[misc]


def arango_nodes(db: StandardDatabase, collection: str) -> Iterator[tuple[str, str]]:
    for doc in _arango(db, f"FOR d IN {collection} RETURN d"):
        yield doc["_id"], _node_text(doc)


def arango_edges(db: StandardDatabase) -> Iterator[tuple[str, str, str]]:
    for doc in _arango(db, f"FOR e IN {COLLECTION_EDGES} RETURN e"):
        yield doc.get("relation", ""), doc["_key"], _edge_text(doc)


def pg_nodes(conn: psycopg.Connection, collection: str) -> Iterator[tuple[str, str]]:
    sql = f"SELECT id, type, labels, props::text FROM {collection}"
    with conn.cursor(name=f"graph_equal_{collection}") as cursor:
        cursor.itersize = 2000
        for node_id, kind, labels, props in cursor.execute(sql.encode()):
            yield node_id, _pg_node_text(kind, labels, props)


def _pg_node_text(kind: str, labels: list[str], props: str) -> str:
    head = json.dumps({"type": kind, "labels": list(labels)}, ensure_ascii=False)
    return f'{head[:-1]}, "props": {props}}}'


def pg_edges(conn: psycopg.Connection) -> Iterator[tuple[str, str, str]]:
    sql = f"SELECT key, from_id, to_id, doc::text FROM {COLLECTION_EDGES}"
    with conn.cursor(name="graph_equal_edges") as cursor:
        cursor.itersize = 2000
        for key, from_id, to_id, doc in cursor.execute(sql.encode()):
            yield _pg_edge(key, from_id, to_id, doc)


def _pg_edge(key: str, from_id: str, to_id: str, doc: str) -> tuple[str, str, str]:
    fields = parse(doc)
    pairs = [("_from", from_id), ("_to", to_id), *fields.items]
    text = json.dumps(
        {
            k: _plain(v)
            for k, v in sorted(pairs, key=lambda kv: kv[0])
            if k not in VOLATILE
        },
        ensure_ascii=False,
    )
    relation = next((v for k, v in fields.items if k == "relation"), "")
    return relation, key, text


def _plain(value: Any) -> Any:
    """Parsed *value* back as dicts (which keep their order) and lists, to dump again."""
    if isinstance(value, Pairs):
        return {k: _plain(v) for k, v in value.items}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


# ── comparing ────────────────────────────────────────────────────────────────


@dataclass
class Part:
    """The outcome of one collection or one relation."""

    name: str
    arango: int = 0
    pg: int = 0
    fails: list[str] = field(default_factory=list)
    choices: Counter[str] = field(default_factory=Counter)
    fail_count: int = 0

    @property
    def status(self) -> str:
        if self.fail_count:
            return "FAIL"
        return "CHOICE" if self.choices else "OK"


def _choice(part: str, where: str, arango: Any, pg: Any) -> str:
    for choice in KNOWN_CHOICES:
        if choice.matches(part, where, arango, pg):
            return choice.name
    return ""


def judge(
    result: Part,
    differing: Iterable[tuple[str, str | None, str | None]],
) -> None:
    """Name each difference a choice or a failure: *differing* is ``(id, arango, pg)`` with
    the texts of the document, ``None`` on the side that lacks it."""
    for doc_id, a_text, b_text in differing:
        a = parse(a_text) if a_text is not None else None
        b = parse(b_text) if b_text is not None else None
        if a is None or b is None:
            where = "only in " + ("PostgreSQL" if a is None else "ArangoDB")
        else:
            found = first_difference(a, b)
            if found is None:  # the digests differ only in a whole float (D6)
                continue
            where, how = found
            where = f"{where}: {how}"
        name = _choice(result.name, where, a, b)
        if name:
            result.choices[name] += 1
            continue
        result.fail_count += 1
        if len(result.fails) < SAMPLES:
            result.fails.append(f"{doc_id} {where}")


def compare_digests(
    a: dict[str, str], b: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """The ids only in *a*, only in *b*, and in both with other digests."""
    only_a = sorted(a.keys() - b.keys())
    only_b = sorted(b.keys() - a.keys())
    other = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    return only_a, only_b, other


def _nodes(db: StandardDatabase, conn: psycopg.Connection, collection: str) -> Part:
    result = Part(collection)
    a = {i: digest(t) for i, t in arango_nodes(db, collection)}
    b = {i: digest(t) for i, t in pg_nodes(conn, collection)}
    result.arango, result.pg = len(a), len(b)
    only_a, only_b, other = compare_digests(a, b)
    wanted = set(only_a) | set(only_b) | set(other)
    texts_a = _arango_node_texts(db, collection, sorted(set(only_a) | set(other)))
    texts_b = _pg_node_texts(conn, collection, sorted(set(only_b) | set(other)))
    judge(result, ((i, texts_a.get(i), texts_b.get(i)) for i in sorted(wanted)))
    return result


def _arango_node_texts(
    db: StandardDatabase, collection: str, ids: list[str]
) -> dict[str, str]:
    texts: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        keys = [i.split("/", 1)[1] for i in ids[start : start + BATCH]]
        aql = f"FOR d IN {collection} FILTER d._key IN @keys RETURN d"
        texts.update((d["_id"], _node_text(d)) for d in _arango(db, aql, keys=keys))
    return texts


def _pg_node_texts(
    conn: psycopg.Connection, collection: str, ids: list[str]
) -> dict[str, str]:
    sql = f"SELECT id, type, labels, props::text FROM {collection} WHERE id = ANY(%s)"
    texts: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        rows = conn.execute(sql.encode(), (ids[start : start + BATCH],))
        texts.update((i, _pg_node_text(k, lab, p)) for i, k, lab, p in rows)
    return texts


def _edges(db: StandardDatabase, conn: psycopg.Connection) -> list[Part]:
    a: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    b: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for relation, key, text in arango_edges(db):
        a[relation][key] = (digest(text), text)
    for relation, key, text in pg_edges(conn):
        b[relation][key] = (digest(text), text)
    parts = []
    for relation in sorted(a.keys() | b.keys()):
        result = Part(f"edges/{relation}")
        sa, sb = a.get(relation, {}), b.get(relation, {})
        result.arango, result.pg = len(sa), len(sb)
        only_a, only_b, other = compare_digests(
            {k: d for k, (d, _) in sa.items()}, {k: d for k, (d, _) in sb.items()}
        )
        wanted = sorted({*only_a, *only_b, *other})
        judge(
            result,
            (
                (k, sa[k][1] if k in sa else None, sb[k][1] if k in sb else None)
                for k in wanted
            ),
        )
        parts.append(result)
    return parts


def report(parts: list[Part]) -> tuple[bool, str]:
    lines = []
    for part in parts:
        counts = f"{part.arango:,} / {part.pg:,}"
        lines.append(f"{part.status:6} {part.name:40} {counts}")
        for name, n in sorted(part.choices.items()):
            lines.append(f"         CHOICE {name}: {n:,}")
        if part.fail_count:
            lines.append(f"         {part.fail_count:,} differ, for example:")
            lines.extend(f"           {sample}" for sample in part.fails)
    fails = [p.name for p in parts if p.status == "FAIL"]
    choices = [p.name for p in parts if p.status == "CHOICE"]
    lines.append(
        f"{len(parts)} parts: {len(fails)} FAIL, {len(choices)} CHOICE, "
        f"{len(parts) - len(fails) - len(choices)} OK"
    )
    return not fails, "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--arango-url", default=settings.ARANGO_URL)
    parser.add_argument("--arango-db", required=True)
    parser.add_argument(
        "--pg-url", default=os.environ.get("LAWGRAPH_DB_URL", settings.DB_URL)
    )
    parser.add_argument("--pg-db", required=True)
    parser.add_argument("--only", action="append", default=[], help="a collection")
    args = parser.parse_args()
    arango = ArangoClient(hosts=args.arango_url).db(
        args.arango_db, username=settings.ARANGO_USER, password=settings.ARANGO_PASSWORD
    )
    parts = []
    with psycopg.connect(f"{args.pg_url.rstrip('/')}/{args.pg_db}") as conn:
        conn.read_only = True
        for collection in NODE_COLLECTIONS:
            if args.only and collection not in args.only:
                continue
            parts.append(_nodes(arango, conn, collection))
            print(f"{collection}: {parts[-1].status}", flush=True)
        if not args.only or COLLECTION_EDGES in args.only:
            parts.extend(_edges(arango, conn))
    same, text = report(parts)
    print(text)
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()
