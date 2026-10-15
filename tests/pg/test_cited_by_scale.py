"""The passages that cite a much cited article, at the scale of Sr 287 and Awb 6:2.

5,000 judgments of 60 KB are 300 MB: a query that reads the judgments of an article whole,
or sorts them whole, is slow here as it would be on the full database (thousands of
judgments per article, each with its text and paragraphs).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries.articles import get_article_cited_by
from tests.fakes import assert_fast

JUDGMENTS = 5_000
MENTIONS = 3
PARAGRAPHS = 40
PARAGRAPH_SIZE = 1_500
ARTICLE = "articles/bwbr0001854_287"
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
                "key": f"ecli_nl_{court.lower()}_{2000 + number % 25}_{number}",
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
    number = int(doc["key"].rsplit("_", 1)[1])
    return {
        "key": f"e{number}",
        "from_id": f"judgments/{doc['key']}",
        "to_id": ARTICLE,
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


def _seed(store: GraphStore) -> None:
    for batch in _judgments():
        store.bulk_insert_or_update_nodes("judgments", batch)
        store.bulk_insert_or_update_edges([_edge(doc) for doc in batch])
    # what else points at the article and must not be read: other relations, other articles
    store.bulk_insert_or_update_edges(
        [
            {
                "key": f"noise{n}",
                "from_id": f"judgments/ecli_nl_hr_2000_{n}",
                "to_id": f"articles/bwbr0001854_{n}",
                "relation": "REFERS_TO",
                "meta": {},
            }
            for n in range(2_000)
        ]
    )


def test_a_much_cited_article_lists_its_passages_in_time(store: GraphStore) -> None:
    _seed(store)

    cited_by = assert_fast(lambda: get_article_cited_by(store, ARTICLE, limit=50))
    rows = cited_by.rows

    assert cited_by.total == JUDGMENTS * MENTIONS and len(rows) == 50
    assert cited_by.judgment_total == JUDGMENTS
    dates = [row["judgment"]["props"]["date_eff"] for row in rows]
    assert dates == sorted(dates, reverse=True) and dates[0].startswith("2024-")
    assert set(rows[0]["mention"]) >= {"paragraph_id", "snippet", "start", "end"}

    cited_by = get_article_cited_by(
        store, ARTICLE, court="hr", lid="2", limit=10, offset=100
    )
    rows = cited_by.rows
    assert cited_by.total == (JUDGMENTS // 3 + 1) * 1 and len(rows) == 10
    assert {r["judgment"]["props"]["court_code"] for r in rows} == {"HR"}
