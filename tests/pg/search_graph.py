"""Judgments to search: summaries that mix words of every frequency."""

from __future__ import annotations

from lawgraph.db import GraphStore


def judgments_with_words(store: GraphStore, rows: int) -> None:
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
