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
