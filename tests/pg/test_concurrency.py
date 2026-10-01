"""Requests side by side on a pool smaller than the queries they run together.

A route may run its independent queries side by side (``run_together``, and the types of a
search). Those run on two executors of four threads in ``db/queries``, and every query
borrows a connection from the pool only while it reads: a request that waits for its
queries holds none. So any number of requests finish on any pool, however small; they
only queue for a connection.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from lawgraph.db import ArangoStore
from lawgraph.db import store as store_module
from lawgraph.db.queries.articles import get_article_with_relations
from lawgraph.db.queries.judgments import get_judgments_list
from lawgraph.db.queries.relationships import get_article_relationship_data
from lawgraph.db.queries.search import search_all

REQUESTS = 24  # three times the default pool, as many as the API runs at once
POOL = 2  # fewer connections than the queries one request runs together


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": None,
        "meta": {},
    }


@pytest.fixture()
def small_pool(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ArangoStore]:
    server, name = database_url.rsplit("/", 1)
    monkeypatch.setattr(store_module, "DB_URL", server)
    monkeypatch.setattr(store_module, "DB_NAME", name)
    monkeypatch.setattr(store_module, "DB_POOL_SIZE", POOL)
    monkeypatch.setattr(
        store_module, "PAYLOAD_STORE", f"file://{tmp_path / 'payloads'}"
    )
    opened = ArangoStore()
    # A request starved of a connection fails within seconds, not after a minute.
    opened.pool.timeout = 5
    try:
        yield opened
    finally:
        opened.close()


def _seed(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_node("bwbr0002", "instrument", bwb_id="BWBR0002")]
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(f"bwbr0002_{n}", "article", bwb_id="BWBR0002", article_number=str(n))
            for n in (1, 2)
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "ecli_nl_hr_2020_1",
                "judgment",
                ecli="ECLI:NL:HR:2020:1",
                date_eff="2020-01-01",
                display_name="HR 1 januari 2020",
            )
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("p1", "articles/bwbr0002_1", "instruments/bwbr0002", "PART_OF"),
            _edge("p2", "articles/bwbr0002_2", "instruments/bwbr0002", "PART_OF"),
            _edge("r1", "articles/bwbr0002_1", "articles/bwbr0002_2", "REFERS_TO"),
            _edge(
                "r2", "judgments/ecli_nl_hr_2020_1", "articles/bwbr0002_1", "REFERS_TO"
            ),
        ]
    )


def test_requests_finish_on_a_pool_smaller_than_their_queries(
    small_pool: ArangoStore,
) -> None:
    _seed(small_pool)
    routes: list[Callable[[], Any]] = [
        lambda: get_article_with_relations(small_pool, "BWBR0002", "1"),
        lambda: get_article_relationship_data(small_pool, "articles/bwbr0002_1"),
        lambda: get_judgments_list(small_pool),
        lambda: search_all(
            small_pool, q="januari", types=["articles", "instruments", "judgments"]
        ),
    ]
    alone = [route() for route in routes]

    with ThreadPoolExecutor(max_workers=REQUESTS) as requests:
        futures = [
            requests.submit(routes[n % len(routes)]) for n in range(REQUESTS * 2)
        ]
        # A request that held a connection while it waited would starve the others: they
        # fail with PoolTimeout.
        answers = [future.result() for future in futures]

    for n, answer in enumerate(answers):
        assert answer == alone[n % len(routes)]
    assert small_pool.pool.get_stats()["pool_max"] == POOL
