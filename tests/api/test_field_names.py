"""What the name of an answer field says (``api/schemas/__init__.py``), held for every
component of ``/openapi.json``. The fields that do not follow yet are listed: the list only
shrinks."""

from __future__ import annotations

from typing import Any

from lawgraph.api.app import app

SCHEMAS: dict[str, dict[str, Any]] = app.openapi()["components"]["schemas"]
FIELDS = [
    (name, field, spec)
    for name, schema in sorted(SCHEMAS.items())
    for field, spec in schema.get("properties", {}).items()
]

# A day is ``<verb>_on``: these still put ``date_`` in front.
DATE_PREFIXED = {
    ("AmendingInstrumentDTO", "date_published"),
    ("AmendingInstrumentDTO", "date_signed"),
    ("DelegatedRegulationDTO", "date_in_force"),
    ("InstrumentDelegatedItem", "date_in_force"),
    ("InstrumentDetailDTO", "date_in_force"),
    ("InstrumentDetailDTO", "date_published"),
    ("InstrumentDetailDTO", "date_signed"),
    ("InstrumentRelatedItem", "date_in_force"),
    ("SubDelegatedDTO", "date_in_force"),
}
# A period is ``from_date``/``to_date``: these end it with ``until``.
FROM_DATE_UNTIL = {"MinistryPeriodDTO"}


def test_a_day_is_named_by_what_happened_on_it() -> None:
    found = {(name, field) for name, field, _ in FIELDS if field.startswith("date_")}
    assert found == DATE_PREFIXED


def test_a_period_from_a_date_ends_at_a_date() -> None:
    found = {
        name
        for name, schema in SCHEMAS.items()
        if {"from_date", "until"} <= set(schema.get("properties", {}))
    }
    assert found == FROM_DATE_UNTIL
