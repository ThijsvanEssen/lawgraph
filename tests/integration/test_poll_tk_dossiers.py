"""A poll of the Tweede Kamer links the cases of its window to their dossiers, and the
cases that name a dossier it brought, not every case of the Kamer again: on the server that
was 200,000 edges written as they were, 6 of the 8 minutes of a poll. It comes to the same
edges as linking every case."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    RELATION_PART_OF,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.tk import TKNormalizePipeline
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from tests.integration.seed import seed, uid


def _write(store: GraphStore, *records: tuple[str, dict[str, Any]]) -> None:
    with RawSourceWriter(store) as writer:
        for kind, payload in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )


def _zaak(salt: int, number: int) -> dict[str, Any]:
    return {
        "Id": uid(9000 + salt, 2),
        "Nummer": f"2026Z{salt:05d}",
        "Soort": "Motie",
        "Titel": "Een zaak",
        "Onderwerp": "Een zaak",
        "Kamerstukdossier": [{"Id": uid(number, 3), "Nummer": number}],
    }


def _case_links(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = %(r)s"
            " AND from_collection = 'cases' AND to_collection = 'dossiers'",
            {"r": RELATION_PART_OF},
        )
    }


def test_a_window_links_its_cases_and_those_of_the_dossiers_it_brought(
    database: str,
) -> None:
    store = GraphStore()
    seed(store, documents=60, judgments=0, regulations=0)
    # a case that names a dossier the graph does not hold yet
    _write(store, (RAW_KIND_TK_ZAAK, _zaak(1, 37000)))
    TKNormalizePipeline(store=store).run()
    TKDossiersNormalizePipeline(store=store).run()
    before = _case_links(store)
    old_case = f"cases/{uid(9001, 2).replace('-', '_')}"
    assert not any(case == old_case for case, _ in before)

    time.sleep(1.1)  # fetched_at has a precision of a second
    since = dt.datetime.now(dt.timezone.utc)
    time.sleep(1.1)
    new_dossier = {
        "Id": uid(37000, 3),
        "Nummer": 37000,
        "Toevoeging": None,
        "Titel": "Een nieuw dossier",
        "Afgesloten": False,
    }
    _write(
        store, (RAW_KIND_TK_DOSSIER, new_dossier), (RAW_KIND_TK_ZAAK, _zaak(2, 36001))
    )
    TKNormalizePipeline(store=store).run(since=since)
    TKDossiersNormalizePipeline(store=store).run(since=since)

    windowed = _case_links(store)
    new_case = f"cases/{uid(9002, 2).replace('-', '_')}"
    assert windowed - before == {
        (old_case, "dossiers/37000"),
        (new_case, "dossiers/36001"),
    }
    # linking every case again adds nothing: the window missed none
    tk_cases.link_cases_to_dossiers(store, source="tk-dossiers")
    assert _case_links(store) == windowed


def test_a_window_without_cases_reads_none(database: str, monkeypatch) -> None:
    """The fixed cost of a poll: an empty window links no case at all."""
    store = GraphStore()
    seed(store, documents=60, judgments=0, regulations=0)
    TKNormalizePipeline(store=store).run()
    TKDossiersNormalizePipeline(store=store).run()
    linked: list[int] = []
    queue = tk_cases._queue_existing

    def counted(store_, pairs, relation, writer, *, source):  # type: ignore[no-untyped-def]
        if relation == RELATION_PART_OF:
            linked.append(len(pairs))
        return queue(store_, pairs, relation, writer, source=source)

    monkeypatch.setattr(tk_cases, "_queue_existing", counted)
    since = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)
    TKDossiersNormalizePipeline(store=store).run(since=since)
    assert linked and linked[0] == 0
