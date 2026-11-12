"""``semantic rechtspraak-conclusions --touched-since`` on a real PostgreSQL: for the
conclusions the judgments retrieved in the window can change it comes to the same as a run
over all, by each way a judgment reaches a conclusion (a shared case number, a judgment that
names it, a judgment that no longer does, a later decision of the court that advises itself);
what changed outside the window waits for that run."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import RAW_KIND_RECHTSPRAAK_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.core.models import make_node_key
from lawgraph.core.provenance import BASIS_CASE_NUMBER, BASIS_FORMAL
from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.pipelines.semantic.rechtspraak_conclusions import (
    EDGE_SOURCE,
    RechtspraakConclusionsSemanticPipeline,
)

NOW = dt.datetime.now(dt.UTC)
SINCE = NOW - dt.timedelta(hours=2)
OLD = (NOW - dt.timedelta(days=30)).isoformat()
NEW = (NOW - dt.timedelta(minutes=5)).isoformat()

P1 = "ECLI:NL:PHR:2026:1"  # its case number comes back in a new judgment
H1 = "ECLI:NL:HR:2026:11"
P2 = "ECLI:NL:PHR:2026:2"  # linked by its case number, then named by a new judgment
H2_OLD = "ECLI:NL:HR:2026:20"
H2 = "ECLI:NL:HR:2026:21"
P3 = "ECLI:NL:PHR:2026:3"  # named by a judgment that, retrieved again, no longer does
H3 = "ECLI:NL:HR:2026:31"
R1 = "ECLI:NL:RVS:2026:1"  # the staatsraad advocaat-generaal, and the later decision
R2 = "ECLI:NL:RVS:2026:2"
P4 = "ECLI:NL:PHR:2026:4"  # named outside the window: waits for the nightly run
H4 = "ECLI:NL:HR:2026:41"
CONCLUSIONS = (P1, P2, P3, R1)


def _id(ecli: str) -> str:
    return f"judgments/{make_node_key(ecli)}"


def _judgment(ecli: str, court: str, date: str, **props: Any) -> dict[str, Any]:
    return {
        "key": make_node_key(ecli),
        "type": "judgment",
        "labels": ["Judgment"],
        "props": {
            "ecli": ecli,
            "source": SOURCE_RECHTSPRAAK,
            "stub": False,
            "court_code": court,
            "date_eff": date,
            **props,
        },
    }


def _conclusion(ecli: str, court: str, date: str, **props: Any) -> dict[str, Any]:
    return _judgment(
        ecli,
        court,
        date,
        decision_kind="conclusie",
        judgment_metadata={"document_type": "Conclusie"},
        **props,
    )


def _number(number: str) -> dict[str, Any]:
    return {"case_number": number, "case_number_keys": [number.lower()]}


def _retrieved(store: GraphStore, at: str, *eclis: str) -> None:
    store.insert_raw_sources(
        [
            {
                **raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                    external_id=ecli,
                    payload_text=f'<xml retrieved="{at}"/>',
                ),
                "fetched_at": at.replace("+00:00", "Z"),
            }
            for ecli in eclis
        ]
    )


def _advice(store: GraphStore) -> set[tuple[str, str, str]]:
    rows = store.query(
        "SELECT json_build_object('f', from_id, 't', to_id, 'b', doc -> 'meta' ->> "
        "'basis') FROM edges WHERE relation = 'ADVISES_ON' AND source = %(source)s",
        {"source": EDGE_SOURCE},
    )
    return {(row["f"], row["t"], row["b"]) for row in rows}


def _of(edges: set[tuple[str, str, str]], *conclusions: str) -> set:
    ids = {_id(ecli) for ecli in conclusions}
    return {edge for edge in edges if edge[0] in ids}


def _seed(store: GraphStore) -> None:
    """Before the window: P2 linked to H2_OLD by its case number, P3 named by H3, and
    every judgment retrieved long ago."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _conclusion(P1, "PHR", "2026-01-05", **_number("24/00001")),
            _conclusion(P2, "PHR", "2026-01-06", **_number("24/00002")),
            _judgment(H2_OLD, "HR", "2026-02-01", **_number("24/00002")),
            _conclusion(P3, "PHR", "2026-01-07", **_number("24/00003")),
            _judgment(H3, "HR", "2026-02-02", conclusion_eclis=[P3]),
            _conclusion(R1, "RVS", "2026-01-10", **_number("202401234/2/A3")),
            _conclusion(P4, "PHR", "2026-01-08", **_number("24/00004")),
        ],
    )
    _retrieved(store, OLD, P1, P2, H2_OLD, P3, H3, R1, P4)
    RechtspraakConclusionsSemanticPipeline(store=store).run()


def _window(store: GraphStore) -> None:
    """The window: a judgment in P1's case, one that names P2, H3 retrieved again without
    its relation, and the later decision of the Raad van State in R1's case; outside it a
    judgment named P4."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment(H1, "HR", "2026-06-01", **_number("24/00001")),
            _judgment(H2, "HR", "2026-06-02", conclusion_eclis=[P2]),
            _judgment(H3, "HR", "2026-02-02", conclusion_eclis=[]),
            _judgment(R2, "RVS", "2026-06-03", **_number("202401234/1/A3")),
            _judgment(H4, "HR", "2026-06-04", conclusion_eclis=[P4]),
        ],
    )
    _retrieved(store, NEW, H1, H2, H3, R2)
    _retrieved(store, OLD, H4)


def test_the_touched_conclusions(store: GraphStore) -> None:
    _seed(store)
    _window(store)
    found = RechtspraakConclusionsSemanticPipeline(store=store).touched_conclusions(
        SINCE
    )
    assert set(CONCLUSIONS) <= found
    assert P4 not in found


def test_a_window_links_its_conclusions_as_a_run_over_all(store: GraphStore) -> None:
    _seed(store)
    before = _advice(store)
    assert _of(before, P2) == {(_id(P2), _id(H2_OLD), BASIS_CASE_NUMBER)}
    assert _of(before, P3) == {(_id(P3), _id(H3), BASIS_FORMAL)}
    _window(store)

    RechtspraakConclusionsSemanticPipeline(store=store).run(touched_since=SINCE)
    some = _advice(store)
    assert _of(some, P4) == _of(before, P4) == set()  # outside the window: as it was
    RechtspraakConclusionsSemanticPipeline(store=store).run()
    everything = _advice(store)
    assert _of(some, *CONCLUSIONS) == _of(everything, *CONCLUSIONS)
    assert _of(everything, *CONCLUSIONS) == {
        (_id(P1), _id(H1), BASIS_CASE_NUMBER),
        (_id(P2), _id(H2), BASIS_FORMAL),  # named now: no longer by its case number
        (_id(R1), _id(R2), BASIS_CASE_NUMBER),
    }
    assert _of(everything, P4) == {(_id(P4), _id(H4), BASIS_FORMAL)}
