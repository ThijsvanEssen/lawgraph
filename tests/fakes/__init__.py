"""The fakes the unit tests share: one store in memory, and the query functions it answers.

A read of ``db/queries/`` is no store method: a test patches the function, and the patches
here answer it from the store's data. Each kind of fake has a module of its own; this
package gives them all under ``tests.fakes``.
"""

from tests.fakes.clock import (
    FAST,
    PATIENCE,
    ManualClock,
    assert_fast,
    calls_made,
    until,
)
from tests.fakes.http import ScriptedSession, Sent, answer, http_error
from tests.fakes.queries import (
    patch_alias_rows,
    patch_document_kinds,
    patch_edge_removals,
    patch_ek_documents,
    patch_kept_state,
    patch_pipeline_state,
    patch_rijkswet_dossiers,
    patch_unlinked,
)
from tests.fakes.raw_reads import patch_raw_reads
from tests.fakes.store import (
    FakeStoreBase,
    InMemoryStore,
    PipelineStateFake,
    count_calls,
    external_ids,
    raw_record,
)

__all__ = [
    "FAST",
    "PATIENCE",
    "FakeStoreBase",
    "InMemoryStore",
    "ManualClock",
    "PipelineStateFake",
    "ScriptedSession",
    "Sent",
    "answer",
    "assert_fast",
    "calls_made",
    "count_calls",
    "external_ids",
    "http_error",
    "patch_alias_rows",
    "patch_document_kinds",
    "patch_edge_removals",
    "patch_ek_documents",
    "patch_kept_state",
    "patch_pipeline_state",
    "patch_rijkswet_dossiers",
    "patch_raw_reads",
    "patch_unlinked",
    "raw_record",
    "until",
]
