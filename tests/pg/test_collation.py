"""The collation of the database: lawgraph refuses one that does not sort by the schema's
ICU collation, and the feed and the dossier prefix answer alike under glibc's en_US.utf8
(the collation of a database the postgres image makes at its first start, ``POSTGRES_DB``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries.dossiers import DossierFilters, get_dossiers
from lawgraph.db.queries.feed import get_feed
from lawgraph.db.queries.feed_sql import FeedFilters
from lawgraph.db.schema import (
    COLLATION,
    CollationMismatch,
    collation_of,
    ensure_schema,
)
from tests.databases import (
    TEST_URL,
    new_database_name,
    opened_store,
    point_at,
    url_of,
)
from tests.pg.dossier_graph import DOSSIERS
from tests.pg.feed_graph import seed_feed as seed_feed

GLIBC = "libc en_US.utf8"


@pytest.fixture()
def glibc_database() -> Iterator[str]:
    """The name of a fresh database that sorts by glibc's en_US.utf8, dropped afterwards."""
    name = new_database_name()
    with psycopg.connect(TEST_URL, autocommit=True) as admin:
        admin.execute(
            f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING UTF8'
            " LOCALE_PROVIDER libc LOCALE 'en_US.utf8'".encode()
        )
        try:
            yield name
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)'.encode())


@pytest.fixture()
def glibc_url(glibc_database: str) -> str:
    """The URL of ``glibc_database``."""
    return url_of(glibc_database)


@pytest.fixture()
def glibc_store(
    store: GraphStore,  # first: it points the store module at its own database
    glibc_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[GraphStore]:
    """The store on the glibc database, let through as for a dump and restore."""
    point_at(
        monkeypatch, glibc_database, tmp_path / "glibc-payloads", ALLOW_COLLATION=GLIBC
    )
    with opened_store() as opened:
        yield opened


# ── the guard ────────────────────────────────────────────────────────────────


def test_a_database_lawgraph_makes_has_the_schemas_collation(
    conn: psycopg.Connection,
) -> None:
    assert collation_of(conn) == f"icu {COLLATION}"


def test_a_database_of_another_collation_is_refused(glibc_url: str) -> None:
    with psycopg.connect(glibc_url, autocommit=True) as conn:
        assert collation_of(conn) == GLIBC
        with pytest.raises(CollationMismatch) as refused:
            ensure_schema(conn)
        assert f"LAWGRAPH_ALLOW_COLLATION='{GLIBC}'" in str(refused.value)
        # nothing was made, and the connection is usable
        tables = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()
        assert tables == (0,)


def test_only_the_collation_let_through_passes(glibc_url: str) -> None:
    with psycopg.connect(glibc_url, autocommit=True) as conn:
        with pytest.raises(CollationMismatch):
            ensure_schema(conn, allowed_collation="libc de_DE.utf8")
        ensure_schema(conn, allowed_collation=GLIBC)
        assert conn.execute("SELECT count(*) FROM dossiers").fetchone() == (0,)


def test_the_store_refuses_it_too(
    glibc_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, glibc_database, tmp_path, ALLOW_COLLATION="")
    with pytest.raises(CollationMismatch, match="sorts strings by libc en_US.utf8"):
        GraphStore()


# ── the same answers under glibc ─────────────────────────────────────────────


# The kinds whose rows no range of ``Document.Soort`` selects (``feed_sql._kind_parts``).
WITHOUT_RANGES = ("toezegging", "stemming", "publicatie", "inwerkingtreding")


def test_the_feed_without_an_end_has_its_events_under_glibc(
    store: GraphStore, glibc_store: GraphStore
) -> None:
    """Without ``until`` the feed has no upper bound: one that sorts after every date
    under ICU (U+FFFF) sorts before them under glibc, and the feed was empty."""
    for each in (store, glibc_store):
        seed_feed(each)
    for filters in (
        FeedFilters(kinds=WITHOUT_RANGES),
        FeedFilters(kinds=WITHOUT_RANGES, since="2020-01-01"),
        FeedFilters(kinds=WITHOUT_RANGES, cabinet="jetten"),  # the cabinet in office
    ):
        icu, glibc = get_feed(store, filters), get_feed(glibc_store, filters)
        assert glibc["total"] == icu["total"] > 0, filters
        assert {i["id"] for i in glibc["items"]} == {i["id"] for i in icu["items"]}
    # a page without facets reads up to the cursor's day, without a bound past it
    unfaceted = get_feed(glibc_store, FeedFilters(kinds=WITHOUT_RANGES), facets=False)
    assert (
        len(unfaceted["items"])
        == get_feed(store, FeedFilters(kinds=WITHOUT_RANGES))["total"]
    )


def test_the_variants_of_a_paper_kind_need_the_schemas_collation(
    store: GraphStore, glibc_store: GraphStore
) -> None:
    """``Motie (gewijzigd/nader)`` is a ``Motie`` by a range on the index, which holds under
    ICU alone: why a database of another collation is refused, not only warned about."""
    for each in (store, glibc_store):
        seed_feed(each)
    motions = FeedFilters(kinds=("Motie",))
    assert [i["id"] for i in get_feed(store, motions)["items"]] == [
        "documents/motion_005"
    ]
    assert get_feed(glibc_store, motions)["total"] == 0


def test_a_dossier_prefix_finds_the_same_under_glibc(
    store: GraphStore, glibc_store: GraphStore
) -> None:
    for each in (store, glibc_store):
        with NodeWriter(each) as writer:
            writer.add_all(DOSSIERS)
    for prefix in ("37020", "37020-", "3626", "36264"):
        icu = {
            d["key"]
            for d in get_dossiers(store, DossierFilters(number=prefix))["items"]
        }
        glibc = {
            d["key"]
            for d in get_dossiers(glibc_store, DossierFilters(number=prefix))["items"]
        }
        assert icu == glibc, prefix
        assert icu, prefix
