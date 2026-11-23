"""``normalize rechtspraak``: judgments are streamed, not loaded."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from tests.fakes import InMemoryStore
from tests.paths import fixture_text


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

    raw = RechtspraakNormalizePipeline(store=InMemoryStore()).fetch_raw()
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


def test_a_judgment_without_a_document_is_a_node_of_its_metadata() -> None:
    """ECLI:NL:GHAMS:2002:AR8277, the referring decision of ECLI:EU:C:2005:255: the
    Rechtspraak has it without a document, its content (real) is the RDF only.
    ``semantic eurlex-cjeu`` finds it by its date, tier and case number."""
    ecli = "ECLI:NL:GHAMS:2002:AR8277"
    row = {
        "external_id": ecli,
        "kind": "rs-content",
        "payload_text": fixture_text("rs_ghams_2002_ar8277_no_document.xml"),
        "meta": {"ecli": ecli},
    }
    store = InMemoryStore()
    RechtspraakNormalizePipeline(store=store).write(iter([row]), PipelineResult())
    [props] = [node["props"] for node in store.nodes[COLLECTION_JUDGMENTS].values()]
    assert {k: props.get(k) for k in ("date_eff", "case_number", "tier", "text")} == {
        "date_eff": "2002-12-12",
        "case_number": "658/2002",
        "tier": "gerechtshof",
        "text": None,
    }
