"""The hits of a word searched often, kept ready (``queries/search_candidates.py``): a search
that takes them finds what it finds without them, and reads few pages of the table."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core import search_stats
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import search as search_queries
from lawgraph.db.queries import search_candidates

TYPES = ["judgments", "articles", "documents"]
WORDS = ["belasting", "belastingen", "inkomstenbelasting", "pacht", "rechtbank",
         "ecli:nl:hr:2026:30", "xyzzy"]  # fmt: skip


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _seed(store: GraphStore, rows: int = 300) -> None:
    """Judgments, articles and papers of which one in three holds "belasting" in a field
    the search ranks by, others in a name or title as a part of a word; citations and
    dates spread, ties among them."""
    word = ["belasting", "pacht", "huur"]
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(f"j_{n}", "judgment", ecli=f"ECLI:NL:HR:2026:{n}", source="rechtspraak",
                  display_name=f"Rechtbank Den Haag 2026-01-{n % 28 + 1:02d} / {n}",
                  names=["Belastingdienst/X"] if n % 17 == 0 else [],
                  summary=f"Een geschil over {word[n % 3]} en {word[n % 2]}.",
                  inbound_citation_count=n % 7, date_eff=f"20{n % 25:02d}-01-01")
            for n in range(rows)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(f"bwbr0002629_{n}", "article", bwb_id="BWBR0002629",
                  article_number=str(n),
                  display_name=f"Artikel {n} Wet "
                  + ("inkomstenbelasting 2001" if n % 5 == 0 else "op de huurtoeslag"),
                  heading="Belastbaar inkomen" if n % 11 == 0 else None,
                  text=f"De {word[n % 3]} wordt geheven.",
                  inbound_citation_count=n % 4)
            for n in range(rows)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {**_node(f"d_{n}", "document",
                     title=f"Brief over de {['belasting', 'inkomstenbelasting', 'pacht'][n % 3]}",
                     date=f"2026-01-{n % 9 + 1:02d}"), "labels": ["TK"]}
            for n in range(rows)
        ],
    )  # fmt: skip
    # the articles their case law calls by a word (``lg_article_terms``)
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms)"
        " SELECT 'articles/bwbr0002629_' || n, lg_tokens('belasting')"
        " FROM generate_series(1, 30, 3) AS n"
    )
    for table in TYPES:
        store.execute(f"ANALYZE {table}")


def _search(store: GraphStore, word: str) -> dict[str, list[dict[str, Any]]]:
    version_cache.clear()
    return search_queries.search_all(store, q=word, types=TYPES)


def _kept(store: GraphStore, table: str, word: str) -> bool:
    """Whether a search of *word* in *table* takes the hits kept of it."""
    termed = search_queries._termed(store, [word]) if table == "articles" else None
    clause, clause_params = search_queries.build_search_clause(
        table, [word], search_queries.CANDIDATE_FIELDS[table], termed=termed
    )
    gate, params = search_queries.kept_candidates(
        store, table, word, clause, clause_params
    )
    return bool(next(store.query(f"SELECT {gate}", params)))


@pytest.fixture()
def seeded(store: GraphStore, monkeypatch: pytest.MonkeyPatch) -> GraphStore:
    # fewer candidates than hits: the common words rank only their first
    monkeypatch.setattr(search_queries, "RANK_CANDIDATES", 25)
    monkeypatch.setattr(search_candidates, "RANK_CANDIDATES", 25)
    _seed(store)
    return store


def test_the_hits_kept_rank_as_the_hits_found(seeded: GraphStore) -> None:
    """Every word, every type: the same hits in the same order, with or without them kept;
    and with them kept the search takes them."""
    found = {word: _search(seeded, word) for word in WORDS}
    assert len(found["belasting"]["judgments"]) == 20  # a common word, ranked
    result = search_candidates.write(seeded, WORDS)
    assert result.written["judgments"]["belasting"] > 25  # more hits than it ranks
    assert {w: _search(seeded, w) for w in WORDS} == found
    assert all(_kept(seeded, table, word) for table in TYPES for word in WORDS)


def test_a_write_to_the_table_is_found_until_the_hits_are_read_again(
    seeded: GraphStore,
) -> None:
    """A row written after the hits were kept (a poll) is found: the search finds them
    itself until they are read again, at the version of now."""
    search_candidates.write(seeded, ["belasting"])
    seeded.bulk_insert_or_update_nodes(
        "judgments",
        [_node("j_new", "judgment", ecli="ECLI:NL:HR:2026:9999", source="rechtspraak",
               summary="Belasting.", inbound_citation_count=100, date_eff="2026-10-11")],
    )  # fmt: skip
    assert not _kept(seeded, "judgments", "belasting")
    assert _kept(seeded, "articles", "belasting")  # its table did not change
    keys = [h["key"] for h in _search(seeded, "belasting")["judgments"]]
    assert "j_new" in keys
    result = search_candidates.write(seeded, ["belasting"])
    assert list(result.written["judgments"]) == ["belasting"]
    assert result.current == {"judgments": 0, "articles": 1, "documents": 1}
    assert _kept(seeded, "judgments", "belasting")
    assert [h["key"] for h in _search(seeded, "belasting")["judgments"]] == keys


def test_hits_kept_for_another_search_are_left(
    seeded: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hits read for a search of another shape (another number of candidates) are not
    taken, and read again by the next run."""
    search_candidates.write(seeded, ["belasting"])
    monkeypatch.setattr(search_queries, "RANK_CANDIDATES", 30)
    monkeypatch.setattr(search_candidates, "RANK_CANDIDATES", 30)
    assert not _kept(seeded, "judgments", "belasting")
    result = search_candidates.write(seeded, ["belasting"])
    assert set(result.written["judgments"]) == {"belasting"}
    assert _kept(seeded, "judgments", "belasting")


def test_a_word_no_longer_asked_goes(seeded: GraphStore) -> None:
    search_candidates.write(seeded, ["belasting", "pacht"])
    result = search_candidates.write(seeded, ["pacht"])
    assert result.dropped == 3  # one state row per type
    assert set(seeded.query("SELECT word FROM lg_search_candidates")) == {"pacht"}
    assert not _kept(seeded, "judgments", "belasting")
    again = search_candidates.write(seeded, ["pacht"], every=True)
    assert all(set(w) == {"pacht"} for w in again.written.values())


def _buffers(node: Any, table: str) -> tuple[int, list[str]]:
    """The pages a plan read of *table* (hit or read), and the nodes that scanned it."""
    pages, scans = 0, []
    if isinstance(node, dict):
        if node.get("Relation Name") == table and node.get("Actual Loops", 0) > 0:
            pages += node.get("Shared Hit Blocks", 0) + node.get(
                "Shared Read Blocks", 0
            )
            scans.append(f"{node['Node Type']} {node.get('Index Name', '')}".strip())
        for value in node.values():
            more, found = _buffers(value, table)
            pages, scans = pages + more, scans + found
    elif isinstance(node, list):
        for value in node:
            more, found = _buffers(value, table)
            pages, scans = pages + more, scans + found
    return pages, scans


@pytest.mark.parametrize("table", TYPES)
def test_a_common_word_kept_reads_only_the_hits_it_answers(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, table: str
) -> None:
    """With its hits kept a common word reads of its table only the hits it answers (by
    their key), not every hit from the indexes of the word and the large columns of those it
    ranks: on prod "belasting" read 18,440 pages of the judgments cold (3.4 s, 11 Oct)."""
    monkeypatch.setattr(search_queries, "RANK_CANDIDATES", 100)
    monkeypatch.setattr(search_candidates, "RANK_CANDIDATES", 100)
    _seed(store, rows=3000)
    seen: list[tuple[Any, Any]] = []
    query = store.query

    def spy(statement: Any, params: Any = None, *args: Any, **kwargs: Any) -> Any:
        seen.append((statement, params))
        return query(statement, params, *args, **kwargs)

    def plan() -> tuple[int, list[str]]:
        seen.clear()
        monkeypatch.setattr(store, "query", spy)
        _search(store, "belasting")
        monkeypatch.setattr(store, "query", query)
        (statement, params), *_ = [
            s for s in seen if f"JOIN {table} doc ON doc.id = top.id" in str(s[0])
        ]
        with store.pool.connection() as conn, conn.transaction():
            conn.execute("SET LOCAL enable_seqscan = off")  # as ``indexes_only``
            row = conn.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params
            ).fetchone()
        assert row is not None
        return _buffers(row[0], table)

    found_pages, found_scans = plan()
    assert any(scan.startswith("Bitmap Heap Scan") for scan in found_scans)
    search_candidates.write(store, ["belasting"])
    kept_pages, kept_scans = plan()
    # the 20 hits it answers, by their key, and nothing else of the table
    assert kept_scans == [f"Index Scan {table}_pkey"], kept_scans
    assert kept_pages <= 4 * 20, kept_pages
    assert kept_pages * 5 < found_pages, (kept_pages, found_pages)


def test_the_words_are_those_searched_most(tmp_path: Path) -> None:
    """One-word terms asked ``MIN_COUNT`` times or more in the days kept, most asked first;
    a term of more words, or asked less, is not one."""
    today = dt.date(2026, 10, 11)
    counts = {"belasting": 9, "huur": 6, "onrechtmatige daad": 40,
              "jansen": 2, "pacht": 9, "a": 50}  # fmt: skip
    day = tmp_path / f"search-{today.isoformat()}.json"
    day.write_text(
        json.dumps({search_stats.normalise(k): v for k, v in counts.items()})
    )
    assert search_candidates.searched_words(tmp_path, today) == [
        "belasting",
        "pacht",
        "huur",
    ]
    assert search_candidates.searched_words(tmp_path, today, most=1) == ["belasting"]
