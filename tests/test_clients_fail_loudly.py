"""A dead or changed source must fail the step, not end as "completed, nothing to do"."""

from __future__ import annotations

import pathlib

import pytest

from lawgraph.clients.bwb import BWBClient
from tests.fakes import FakeResponse

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SRU_DIAGNOSTIC = (FIXTURES / "bwb_sru_diagnostic.xml").read_text()


# ── BWB toestanden ───────────────────────────────────────────────────────────


def _bwb(text: str) -> BWBClient:
    client = BWBClient.__new__(BWBClient)
    client._get_raw_absolute_with_retry = lambda url, **kw: FakeResponse(text)  # type: ignore[method-assign]
    return client


def test_an_sru_error_is_not_an_empty_list_of_toestanden() -> None:
    with pytest.raises(RuntimeError, match="record schema is known"):
        _bwb(SRU_DIAGNOSTIC).search_toestanden("BWBR0001840")


def test_an_unreadable_sru_response_raises() -> None:
    with pytest.raises(Exception, match="syntax error|not well-formed|no element"):
        _bwb("<html>Bad gateway").search_toestanden("BWBR0001840")
