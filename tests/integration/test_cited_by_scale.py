"""The passages that cite a much cited article, at the scale of Sr 287 and Awb 6:2.

The test server allows a query 256 MiB. 5,000 judgments of 60 KB are 300 MB: a query that
holds the judgments of an article in memory, or sorts them whole, stops here as it would on
the full database (thousands of judgments per article, each with its text and paragraphs).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from lawgraph.db import ArangoStore
from lawgraph.db.queries.articles import get_article_cited_by

JUDGMENTS = 5_000
MENTIONS = 3
PARAGRAPHS = 40
PARAGRAPH_SIZE = 1_500
ARTICLE = "articles/bwbr0001854_287"
MEMORY_LIMIT = 64 * 1024 * 1024
COURTS = (("HR", "hoge_raad"), ("GHAMS", "gerechtshof"), ("RBAMS", "rechtbank"))


def _snippet(number: int) -> str:
    return (
        f"…{number} " + "de rechtbank overweegt dat art. 287 Sr van toepassing is " * 10
    )


def _judgments() -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for number in range(JUDGMENTS):
        court, tier = COURTS[number % len(COURTS)]
        ecli = f"ECLI:NL:{court}:{2000 + number % 25}:{number}"
        batch.append(
            {
                "_key": f"ecli_nl_{court.lower()}_{2000 + number % 25}_{number}",
                "type": "judgment",
                "labels": ["Rechtspraak"],
                "props": {
                    "ecli": ecli,
                    "source": "rechtspraak",
                    "court_code": court,
                    "tier": tier,
                    "date_eff": f"{2000 + number % 25}-{1 + number % 12:02d}-15",
                    "display_name": f"{court} {number}",
                    "paragraphs": [
                        {
                            "id": f"rov-1.{i}",
                            "number": f"1.{i}",
                            "kind": "body",
                            "text": "x" * PARAGRAPH_SIZE,
                        }
                        for i in range(PARAGRAPHS)
                    ],
                },
            }
        )
        if len(batch) == 200:
            yield batch
            batch = []
    if batch:
        yield batch


def _edge(doc: dict[str, Any]) -> dict[str, Any]:
    number = int(doc["_key"].rsplit("_", 1)[1])
    return {
        "_key": f"e{number}",
        "_from": f"judgments/{doc['_key']}",
        "_to": ARTICLE,
        "relation": "REFERS_TO",
        "source": "rechtspraak-article-linker",
        "status": "canoniek",
        "confidence": 0.95,
        "meta": {
            "reason": "bwb_article",
            "mention_count": MENTIONS,
            "mentions": [
                {
                    "paragraph_id": f"rov-1.{i}",
                    "paragraph_number": f"1.{i}",
                    "start": 10,
                    "end": 21,
                    "raw_match": "art. 287 Sr",
                    "leden": [str(1 + i % 3)],
                    "onderdelen": [],
                    "aanhef": False,
                    "snippet": _snippet(number),
                    "confidence": 0.95,
                }
                for i in range(MENTIONS)
            ],
        },
    }


def _seed(store: ArangoStore) -> None:
    judgments = store.db.collection("judgments")
    edges = store.db.collection("edges")
    for batch in _judgments():
        judgments.import_bulk(batch)
        edges.import_bulk([_edge(doc) for doc in batch])
    # what else points at the article and must not be read: other relations, other articles
    edges.import_bulk(
        [
            {
                "_key": f"noise{n}",
                "_from": f"judgments/ecli_nl_hr_2000_{n}",
                "_to": f"articles/bwbr0001854_{n}",
                "relation": "REFERS_TO",
                "meta": {},
            }
            for n in range(2_000)
        ]
    )


def test_a_much_cited_article_lists_its_passages_within_the_memory_of_a_query(
    database: str,
) -> None:
    store = ArangoStore()
    _seed(store)
    asked: list[tuple[str, dict[str, Any]]] = []

    def limited(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        """Every query with a fraction of the memory the server allows: the 5,000
        judgments do not fit in it, so one that has them in memory fails."""
        asked.append((aql, bind_vars or {}))
        return store.db.aql.execute(
            aql, bind_vars=bind_vars or {}, memory_limit=MEMORY_LIMIT
        )

    store.query = limited  # type: ignore[method-assign]

    started = time.monotonic()
    rows, total = get_article_cited_by(store, ARTICLE, limit=50)
    took = time.monotonic() - started

    assert total == JUDGMENTS * MENTIONS and len(rows) == 50
    dates = [row["judgment"]["props"]["date_eff"] for row in rows]
    assert dates == sorted(dates, reverse=True) and dates[0].startswith("2024-")
    assert set(rows[0]["mention"]) >= {"paragraph_id", "snippet", "start", "end"}
    assert took < 10, f"{took:.1f}s"

    rows, total = get_article_cited_by(
        store, ARTICLE, court="hr", lid="2", limit=10, offset=100
    )
    assert total == (JUDGMENTS // 3 + 1) * 1 and len(rows) == 10
    assert {r["judgment"]["props"]["court_code"] for r in rows} == {"HR"}

    # The edges of the article are read through their index, each judgment through its own.
    for aql, bind_vars in asked:
        plan = store.db.aql.explain(aql, bind_vars=bind_vars)
        reads = [
            (node["collection"], node["type"])
            for node in plan["nodes"]
            if node["type"] in ("EnumerateCollectionNode", "IndexNode")
        ]
        assert reads and {kind for _, kind in reads} == {"IndexNode"}, (aql, reads)
        assert {"edges", "judgments"} <= {name for name, _ in reads}
