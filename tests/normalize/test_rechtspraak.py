"""``normalize rechtspraak``: judgments are streamed, not loaded."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from tests.fakes import InMemoryStore


def test_the_rechtspraak_normalizer_streams_its_raw_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def iter_raw_records(store, *, batch_size, **kw):
        calls.append({"batch_size": batch_size})
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    monkeypatch.setattr(
        raw_queries,
        "count_raw_records",  # the total for the progress line
        lambda *a, **kw: calls.append({"count": True}),
    )

    raw = RechtspraakNormalizePipeline(store=InMemoryStore()).fetch_raw()  # type: ignore[arg-type]
    assert not isinstance(raw, list)  # a generator: nothing is read yet
    assert calls == []
    list(raw)
    # small batches: a judgment is tens of KB
    assert calls[-1]["batch_size"] <= 200


def test_the_normalizer_keeps_no_nodes_after_writing_them() -> None:
    xml = "<open-rechtspraak><uitspraak><para>Tekst.</para></uitspraak></open-rechtspraak>"
    rows = iter(
        [
            {
                "external_id": f"ECLI:NL:HR:2025:{n}",
                "kind": "rs-content",
                "payload_text": xml,
                "meta": {"ecli": f"ECLI:NL:HR:2025:{n}"},
            }
            for n in range(3)
        ]
    )
    store = InMemoryStore()
    RechtspraakNormalizePipeline(store=store).write(rows, PipelineResult())
    assert len(store.nodes[COLLECTION_JUDGMENTS]) == 3
