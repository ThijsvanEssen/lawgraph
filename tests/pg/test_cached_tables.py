"""An answer kept per table (``version_cache.cached(tables=...)``) and a part of the warm-up
left out while its tables stand still (``warm.PART_TABLES``) must read those tables alone:
one that reads a table it does not name keeps an old answer after that table changed, and
nothing says so. So every statement they run is planned here (``EXPLAIN``), and every
table its plan reads, or a function of ours it calls reads, must be named; a table a trigger
keeps from a table of the graph counts as that table (``_kept_by``)."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from lawgraph.api import warm
from lawgraph.db import GraphStore, version_cache

# imported before ``kept`` patches the modules that hold ``cached``: run alone, this file
# would otherwise import the nodes queries only after, unpatched
from lawgraph.db.queries import _bm25, articles, nodes, seo
from lawgraph.db.schema import SEARCH_FIELDS
from lawgraph.db.store import _text

SRC = Path(__file__).resolve().parents[2] / "src" / "lawgraph"
# What a statement may read besides the tables it names: the versions themselves and the
# catalogues of PostgreSQL (the planner's estimates).
FREE = re.compile(r"^(lg_data_version|pg_\w+)$")


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": [], "props": props}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("bwbr1", bwb_id="BWBR0001", title="Wet beroep", short_title="Wb",
               kind="wet", article_count=3, legal_areas=[{"main": "Bestuursrecht"}])],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("j1", source="rechtspraak", summary="beroep ongegrond",
               subjects=["Bestuursrecht"], date="2025-01-01")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("d1", title="Motie over beroep", kind="Motie", date="2025-01-02")],
    )
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [_node("schoof", name="kabinet-Schoof", from_date="2024-07-02")],
    )


@contextmanager
def _statements(store: GraphStore) -> Iterator[list[tuple[str, Any]]]:
    """Every statement *store* runs while open (also in the threads of the cache)."""
    seen: list[tuple[str, Any]] = []
    stream, execute = store._stream, store.execute

    def recorded_stream(statement: Any, params: Any, *a: Any, **k: Any) -> Any:
        seen.append((_text(statement), params))
        return stream(statement, params, *a, **k)

    store._stream = recorded_stream  # type: ignore[method-assign]
    try:
        yield seen
    finally:
        store._stream = stream  # type: ignore[method-assign]
        store.execute = execute  # type: ignore[method-assign]


def _functions(store: GraphStore) -> dict[str, str]:
    """Our SQL functions and their bodies."""
    return {
        row["proname"]: row["prosrc"]
        for row in store.query(
            "SELECT proname, prosrc FROM pg_proc"
            " WHERE pronamespace = 'public'::regnamespace"
        )
    }


def _tables(store: GraphStore) -> set[str]:
    return set(
        store.query(
            "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
            " AND relkind IN ('r', 'v', 'm')"
        )
    )


def _kept_by(store: GraphStore) -> dict[str, str]:
    """Each table a trigger keeps from a table of the graph (``lg_judgment_light``,
    ``lg_instrument_names``, …) to that table: by the bodies of the functions the triggers
    run, the ``lg_`` tables they write. Such a table is that table's rows, light: reading
    it is reading the table it is kept from, and changes with it."""
    found: dict[str, str] = {}
    for row in store.query(
        "SELECT DISTINCT c.relname AS base, p.prosrc AS body"
        " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
        " JOIN pg_proc p ON p.oid = t.tgfoid"
        " WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace"
    ):
        for light in re.findall(
            r"\b(?:INSERT INTO|DELETE FROM)\s+(?:public\.)?(lg_\w+)", row["body"]
        ):
            if not FREE.match(light):
                found[light] = row["base"]
    return found


def _plan_relations(plan: Any, found: set[str]) -> None:
    if isinstance(plan, dict):
        if "Relation Name" in plan:
            found.add(plan["Relation Name"])
        for value in plan.values():
            _plan_relations(value, found)
    elif isinstance(plan, list):
        for value in plan:
            _plan_relations(value, found)


def _read(store: GraphStore, statements: list[tuple[str, Any]]) -> set[str]:
    """The tables *statements* read: by their plans, and by the bodies of the functions of
    ours they call."""
    functions, tables = _functions(store), _tables(store)
    found: set[str] = set()
    with store.pool.connection() as conn:
        for text, params in statements:
            plan = conn.execute("EXPLAIN (FORMAT JSON) " + text, params).fetchone()[0]
            _plan_relations(plan, found)
            for name in set(re.findall(r"\b(lg_\w+)\s*\(", text)) & set(functions):
                found |= {t for t in tables if re.search(rf"\b{t}\b", functions[name])}
    kept_by = _kept_by(store)
    return {kept_by.get(table, table) for table in found if not FREE.match(table)}


@pytest.fixture
def kept(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, tuple[str, ...], Callable[[], Any]]]:
    """Every ``cached`` call with tables: where it was made, its tables, its computation."""
    calls: list[tuple[str, tuple[str, ...], Callable[[], Any]]] = []
    original = version_cache.cached

    def cached(store_: Any, key: Any, compute: Any, *, tables: Any = None) -> Any:
        if tables is not None:
            calls.append((_caller(), tables, compute))
        return original(store_, key, compute, tables=tables)

    monkeypatch.setattr(version_cache, "cached", cached)
    for module in list(sys.modules.values()):
        if getattr(module, "cached", None) is original:
            monkeypatch.setattr(module, "cached", cached)
    _seed(store)
    version_cache.clear()
    return calls


def _caller() -> str:
    """``<file>:<function>`` of the code that asked, outside ``version_cache``."""
    frame = sys._getframe(2)
    while frame.f_code.co_filename.endswith("version_cache.py"):
        frame = frame.f_back  # type: ignore[assignment]
    path = Path(frame.f_code.co_filename).resolve().relative_to(SRC)
    return f"{path}:{frame.f_code.co_qualname.split('.<locals>')[0]}"


def _exercise(store: GraphStore) -> None:
    """Everything that keeps an answer per table: the warm-up, the search counts, the
    lids an article's edges cite, the judgments that cite it on its page, the papers
    on the page of a member, what a publication changes and the passages that explain
    an article."""
    warm.forget()
    warm.warm_up(store)
    for table, fields in SEARCH_FIELDS.items():
        _bm25.bm25_sql(store, table, {"w": "beroep"}, list(fields), {})
    store.bulk_insert_or_update_nodes("articles", [_node("a1", article_number="1")])
    nodes.get_node_with_neighbors(store, "articles", "a1")
    seo.cited(store, "articles/a1")
    seo.authored(store, "members/m1")
    seo.changed(store, ("instruments/stb_2025_1",))
    store.bulk_insert_or_update_nodes(
        "articles", [_node("bwbr0001_1", bwb_id="BWBR0001", article_number="1")]
    )
    articles.get_article_explanation_passages(store, "BWBR0001", "1")


def test_every_answer_kept_per_table_reads_only_its_tables(
    store: GraphStore, kept: list[tuple[str, tuple[str, ...], Callable[[], Any]]]
) -> None:
    _exercise(store)
    assert kept
    for where, tables, compute in kept:
        with _statements(store) as statements:
            compute()
        unnamed = _read(store, statements) - set(tables)
        assert not unnamed, f"{where} reads {sorted(unnamed)} and names {tables}"


def test_every_part_left_out_by_its_tables_reads_only_them(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)
    version_cache.clear()
    read: dict[str, list[tuple[str, Any]]] = {}
    run = warm._run

    def recorded(name: str, part: Callable[[], object]) -> bool:
        with _statements(store) as statements:
            done = run(name, part)
        read[name] = statements
        return done

    monkeypatch.setattr(warm, "_run", recorded)
    warm.warm_up(store)
    assert set(warm.PART_TABLES) <= set(read), "a part named in PART_TABLES never ran"
    for name, tables in warm.PART_TABLES.items():
        unnamed = _read(store, read[name]) - set(tables)
        assert not unnamed, (
            f"warm-up part {name} reads {sorted(unnamed)}, names {tables}"
        )


def _declared() -> set[str]:
    """``<file>:<function>`` of every call in src that keeps an answer per table."""
    found = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for top in ast.walk(tree):
            if not isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(top):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", None))
                    in ("cached", "cached_rows")
                    and any(k.arg == "tables" for k in node.keywords)
                ):
                    found.add(f"{path.relative_to(SRC)}:{top.name}")
    return found


def test_every_call_that_names_tables_is_checked(
    store: GraphStore, kept: list[tuple[str, tuple[str, ...], Callable[[], Any]]]
) -> None:
    """A new ``cached(..., tables=...)`` is planned above, or this fails."""
    _exercise(store)
    callers = {where for where, _, _ in kept}
    # cached_rows names its tables for its caller: the call checked is that of the caller
    declared = {d for d in _declared() if not d.startswith("db/version_cache.py:")}
    assert declared <= callers, sorted(declared - callers)
