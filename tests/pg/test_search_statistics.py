"""The statistics of the search: counted on a small table, taken from a sample of the
same pages every time on a large one (``_bm25._stats``)."""

from __future__ import annotations

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries import _bm25


def _instrument(n: int) -> dict[str, object]:
    return {
        "_key": f"i{n}",
        "type": "instrument",
        "labels": [],
        "props": {
            "title": "wet op de " + " ".join(["regel"] * (n % 5 + 1)),
            # a field few have, as the names of a judgment
            **({"aliases": ["WA", "WB", "WC"]} if n % 500 == 0 else {}),
        },
    }


def _fill(store: GraphStore, rows: int) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument(n) for n in range(rows)]
    )
    store.execute("ANALYZE instruments")


def test_a_small_table_is_counted(store: GraphStore) -> None:
    _fill(store, 40)
    stats = _bm25._stats(store, "instruments")
    assert stats["N"] == 40
    assert stats["title/text"] > 1


def test_a_large_table_is_sampled_the_same_every_time(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_bm25, "STATS_MAX_AGE", 0.0)  # computed again on every call
    _fill(store, 2000)
    counted = _bm25._stats(store, "instruments")
    monkeypatch.setattr(_bm25, "SAMPLE_ROWS", 100)
    monkeypatch.setattr(_bm25, "MIN_SAMPLED", 10)
    statements: list[str] = []
    query = store.query

    def recording(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(str(statement))
        return query(statement, *args, **kwargs)

    monkeypatch.setattr(store, "query", recording)
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument(2000)]
    )  # a new version
    sampled = _bm25._stats(store, "instruments")
    store.bulk_insert_or_update_nodes("instruments", [_instrument(2001)])
    again = _bm25._stats(store, "instruments")

    assert any("TABLESAMPLE SYSTEM" in s for s in statements)
    assert sampled["N"] == pytest.approx(2000, rel=0.05)  # the planner's count
    assert sampled["title/text"] == pytest.approx(counted["title/text"], rel=0.25)
    # too rare for the sample: measured over the whole table
    assert counted["aliases/identity"] == 3
    assert sampled["aliases/identity"] == 3
    assert again["N"] == pytest.approx(sampled["N"], rel=0.01)
    assert again["title/text"] == pytest.approx(sampled["title/text"], rel=0.05)


def test_the_statistics_are_kept_when_the_data_changes(store: GraphStore) -> None:
    """A run of the pipelines hardly moves them: kept ``STATS_MAX_AGE``, not per version."""
    _fill(store, 40)
    first = _bm25._stats(store, "instruments")
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument(n) for n in range(40, 80)]
    )
    assert _bm25._stats(store, "instruments") == first


def _judgments_with_words(store: GraphStore, rows: int) -> None:
    """Judgments whose summaries mix words of every frequency, as the real ones do: a word
    of the first ones in most summaries, of the last ones in a few."""
    words = [
        "beroep", "bestuursrecht", "huurovereenkomst", "ontbinding", "verblijfsvergunning",
        "asiel", "onrechtmatige", "daad", "schadevergoeding", "aansprakelijkheid",
        "zeldzaamheid",
    ]  # fmt: skip
    store.execute(
        "INSERT INTO judgments (id, type, props)"
        " SELECT 'judgments/w_' || n, 'judgment', json_build_object("
        " 'source', 'rechtspraak', 'ecli', 'ECLI:NL:RBAMS:2020:' || n,"
        " 'date_eff', '2020-01-01', 'display_name', 'Rechtbank ' || n,"
        " 'summary', array_to_string(ARRAY("
        "   SELECT w FROM unnest(%(words)s::text[]) WITH ORDINALITY AS x(w, i)"
        "   WHERE (n * 7 + i * 13) %% (i + 1) = 0 OR (n %% (i * i + 1)) = 0), ' '))"
        f" FROM generate_series(1, {rows}) n",
        {"words": words},
    )
    store.execute("ANALYZE judgments")


def test_common_words_take_their_frequency_from_the_statistics_alike(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The top 10 with the frequencies of the planner's statistics is the top 10 with the
    counted ones; a word the statistics do not know is counted."""
    from lawgraph.db import version_cache
    from lawgraph.db.queries.search import search_all

    _judgments_with_words(store, 4000)
    queries = [
        "beroep bestuursrecht",
        "huurovereenkomst ontbinding",
        "onrechtmatige daad",
        "asiel",
        "zeldzaamheid",
    ]

    def top(estimated: bool) -> dict[str, list[str]]:
        version_cache.clear()
        if not estimated:
            monkeypatch.setattr(_bm25, "_common_elements", lambda *a: {})
        found = {
            q: [
                h["key"]
                for h in search_all(store, q=q, types=["judgments"], limit=10)[
                    "judgments"
                ]
            ]
            for q in queries
        }
        monkeypatch.undo()
        return found

    counted = top(estimated=False)
    assert top(estimated=True) == counted
    assert all(counted[q] for q in queries)

    version_cache.clear()
    common = _bm25._common_elements(store, "judgments", "s_summary_t")
    assert "beroep" in common
    statements: list[str] = []
    query = store.query

    def recording(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(str(statement))
        return query(statement, *args, **kwargs)

    monkeypatch.setattr(store, "query", recording)
    search_all(store, q="beroep", types=["judgments"], limit=10)
    counts = [s for s in statements if s.startswith("SELECT 1 AS one")]
    # the summaries are not counted for a common word: the statistics give its frequency
    assert counts and not any("s_summary_t &&" in s for s in counts)
    statements.clear()
    version_cache.clear()
    search_all(store, q="voorbeeldloos", types=["judgments"], limit=10)
    counts = [s for s in statements if s.startswith("SELECT 1 AS one")]
    # a word outside the statistics is counted
    assert counts and any("s_summary_t &&" in s for s in counts)


def test_many_searches_at_once_on_a_small_pool_do_not_stand_still(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twelve searchers of every type at once on a cache of one worker, the statistics
    computed again on every call: before ``_frequencies`` read them outside its computation
    of the cache, this stood still for ever (as a search did on 2026-10-08)."""
    import concurrent.futures
    import threading

    from lawgraph.api.schemas.search import SEARCH_TYPES
    from lawgraph.db import version_cache
    from lawgraph.db.queries.search import search_all

    _judgments_with_words(store, 1500)
    monkeypatch.setattr(
        version_cache,
        "_pool",
        concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lawgraph-cache"),
    )
    monkeypatch.setattr(_bm25, "STATS_MAX_AGE", 0.0)
    queries = [
        "beroep",
        "asiel",
        "beroep asiel",
        "onrechtmatige daad",
        "huurovereenkomst",
    ]
    done: list[int] = []

    def search(n: int) -> None:
        for r in range(4):
            if n == 0:
                version_cache.clear()
            q = queries[(n + r) % len(queries)]
            search_all(store, q=q, types=sorted(SEARCH_TYPES), limit=10)
        done.append(n)

    searchers = [
        threading.Thread(target=search, args=(n,), daemon=True) for n in range(12)
    ]
    for searcher in searchers:
        searcher.start()
    for searcher in searchers:
        searcher.join(timeout=60)
    assert len(done) == 12, f"{12 - len(done)} of 12 searchers stood still"


def test_the_start_of_a_value_is_matched_from_three_characters(
    store: GraphStore,
) -> None:
    """Two characters (``hu``) start the values of a large share of the rows, which the
    trigrams cannot narrow: a start of a value counts from three."""
    from lawgraph.db.queries.search import _INSTRUMENT_FIELDS, build_search_clause

    law = {
        "_key": "bwbr0002",
        "type": "instrument",
        "labels": [],
        "props": {"citation_title": "huurwet", "bwb_id": "BWBR0002"},
    }
    store.bulk_insert_or_update_nodes("instruments", [law])

    def matching(token: str) -> int:
        clause, params = build_search_clause("instruments", [token], _INSTRUMENT_FIELDS)
        return int(
            next(
                store.query(
                    f"SELECT count(*) FROM instruments doc WHERE {clause}", params
                )
            )
        )

    assert matching("hu") == 0
    assert matching("huu") == 1


def test_frequencies_that_take_too_long_weigh_nothing_and_are_kept(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A count past ``DF_TIMEOUT`` takes every row as the frequency of its terms: the search
    still finds what holds them, and the next one does not count again."""
    from lawgraph.db import version_cache
    from lawgraph.db.queries.search import search_all

    _judgments_with_words(store, 300)
    version_cache.clear()
    monkeypatch.setattr(_bm25, "DF_TIMEOUT", 0.0)
    monkeypatch.setattr(_bm25, "_common_elements", lambda *a: {})  # every word counted
    counts: list[str] = []
    query = store.query

    def recording(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(statement).startswith("SELECT 1 AS one"):
            counts.append(str(statement))
        return query(statement, *args, **kwargs)

    monkeypatch.setattr(store, "query", recording)
    with caplog.at_level("INFO"):
        first = search_all(store, q="asiel", types=["judgments"], limit=10)["judgments"]
        again = search_all(store, q="asiel", types=["judgments"], limit=10)["judgments"]
    assert first and [h["key"] for h in again] == [h["key"] for h in first]
    assert any("took over" in r.message for r in caplog.records)
    assert len(counts) <= 1  # kept: the second search counts nothing


def test_the_start_of_a_value_is_matched_in_any_case_and_without_accents(
    store: GraphStore,
) -> None:
    """A value starts with a word whatever its case, and without its accents where the
    field is folded for a part of its value as well (``start_of_value_sql``); a word
    later in a value is no start of it."""
    from lawgraph.db.schema import start_of_value_sql

    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": "a",
                "type": "instrument",
                "labels": [],
                "props": {
                    "citation_title": "Réglement op de huur",
                    "short_title": "Huurwet",
                },
            },
            {
                "_key": "b",
                "type": "instrument",
                "labels": [],
                "props": {"citation_title": "Algemene huurwet", "short_title": "AHW"},
            },
        ],
    )

    def starting(field: str, word: str) -> list[str]:
        condition = start_of_value_sql("instruments", field, "%(w)s")
        return list(
            store.query(
                f"SELECT doc.key FROM instruments doc WHERE {condition} ORDER BY doc.key",
                {"w": word},
            )
        )

    assert starting("citation_title", "reglement") == ["a"]  # folded: case and accent
    assert starting("citation_title", "Régl") == ["a"]
    assert starting("citation_title", "huur") == []  # later in a value: no start of it
    assert starting("short_title", "huur") == ["a"]  # in any case, as it is
    assert starting("short_title", "ahw") == ["b"]
