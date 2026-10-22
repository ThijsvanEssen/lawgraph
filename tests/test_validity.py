"""``core.validity``: whether a law or an article holds on a day, from its dates."""

from __future__ import annotations

import pytest

from lawgraph.core.validity import (
    Validity,
    ValidityState,
    article_validity,
    instrument_validity,
)

TODAY = "2026-10-22"
IN_FORCE, EXPIRED, NOT_YET = (
    ValidityState.IN_FORCE,
    ValidityState.EXPIRED,
    ValidityState.NOT_IN_FORCE_YET,
)


@pytest.mark.parametrize(
    ("props", "expected"),
    [
        (
            {"bwb_id": "B", "date_expired": "2024-01-01"},
            Validity(EXPIRED, "2024-01-01"),
        ),
        ({"bwb_id": "B", "date_expired": TODAY}, Validity(EXPIRED, TODAY)),
        (
            {"bwb_id": "B", "date_expired": "2027-01-01"},
            Validity(IN_FORCE, "2027-01-01"),
        ),
        (
            {"bwb_id": "B", "date_in_force": "2027-01-01"},
            Validity(NOT_YET, "2027-01-01"),
        ),
        ({"bwb_id": "B", "date_in_force": "2012-04-01"}, Validity(IN_FORCE)),
        ({"in_force": False, "status": "vastgesteld"}, Validity(NOT_YET)),
        ({"in_force": True, "status": "inwerkinggetreden"}, Validity(IN_FORCE)),
        ({"in_force": False, "status": "beëindigd"}, None),
        ({"celex": "32016L0680"}, None),
        ({"bwb_id": "B", "stub": True}, None),
    ],
)
def test_a_law_holds_by_the_dates_its_source_gives(
    props: dict[str, object], expected: Validity | None
) -> None:
    assert instrument_validity(props, TODAY) == expected


LAW_EXPIRED = Validity(EXPIRED, "2024-01-01")


@pytest.mark.parametrize(
    ("law", "ended", "repealed", "expected"),
    [
        (Validity(IN_FORCE), None, False, Validity(IN_FORCE)),
        (Validity(IN_FORCE), "2007-01-01", False, Validity(EXPIRED, "2007-01-01")),
        (Validity(IN_FORCE), None, True, Validity(EXPIRED)),
        (
            Validity(IN_FORCE, "2028-01-01"),
            "2027-01-01",
            False,
            Validity(IN_FORCE, "2027-01-01"),
        ),
        (LAW_EXPIRED, None, False, LAW_EXPIRED),
        (LAW_EXPIRED, None, True, LAW_EXPIRED),
        (LAW_EXPIRED, "2007-01-01", False, Validity(EXPIRED, "2007-01-01")),
        (LAW_EXPIRED, "2025-01-01", False, LAW_EXPIRED),
        (Validity(NOT_YET), None, False, Validity(NOT_YET)),
        (None, None, False, None),
        (None, "2007-01-01", False, Validity(EXPIRED, "2007-01-01")),
    ],  # fmt: skip
)
def test_an_article_holds_as_long_as_its_law_and_until_its_own_end(
    law: Validity | None, ended: str | None, repealed: bool, expected: Validity | None
) -> None:
    assert article_validity(law, ended, repealed, TODAY) == expected
