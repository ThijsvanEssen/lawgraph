"""BWBClient.enumerate_all_ids against real (recorded) SRU responses."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from lawgraph.clients.bwb import SRU_PAGE_SIZE, BWBClient
from lawgraph.config.constants import BWB_INSTRUMENT_TYPES

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "bwb_sru_grondwet_page.xml").read_text()  # 3 toestanden, 1 BWBR id
DIAGNOSTIC = (FIXTURES / "bwb_sru_diagnostic.xml").read_text()


def _client(responses: list[str], calls: list[dict]) -> BWBClient:
    client = BWBClient.__new__(BWBClient)  # no HTTP session needed

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append(params)
        return SimpleNamespace(text=responses.pop(0))

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def test_deduplicates_ids_across_toestand_records() -> None:
    calls: list[dict] = []

    ids = _client([PAGE], calls).enumerate_all_ids(types=("wet",))

    assert ids == ["BWBR0001840"]  # 3 records, one law


def test_queries_use_exact_type_values_and_no_record_schema() -> None:
    calls: list[dict] = []

    _client([PAGE] * len(BWB_INSTRUMENT_TYPES), calls).enumerate_all_ids()

    assert [c["query"] for c in calls] == [
        f'dcterms.type=="{t}"' for t in BWB_INSTRUMENT_TYPES
    ]
    assert all("recordSchema" not in c for c in calls)
    assert {"AMvB", "ministeriele-regeling", "verdrag"} <= set(BWB_INSTRUMENT_TYPES)


def _full_page() -> str:
    """A page of exactly SRU_PAGE_SIZE records, built from real ones."""
    start = PAGE.index("<record>")
    end = PAGE.rindex("</record>") + len("</record>")
    record = PAGE[start : PAGE.index("</record>") + len("</record>")]
    return PAGE[:start] + record * SRU_PAGE_SIZE + PAGE[end:]


def test_pages_until_a_short_page() -> None:
    calls: list[dict] = []

    ids = _client([_full_page(), PAGE], calls).enumerate_all_ids(types=("wet",))

    assert ids == ["BWBR0001840"]
    assert [c["startRecord"] for c in calls] == ["1", str(SRU_PAGE_SIZE + 1)]


def test_service_error_raises_instead_of_returning_nothing() -> None:
    calls: list[dict] = []

    with pytest.raises(RuntimeError, match="record schema is known"):
        _client([DIAGNOSTIC], calls).enumerate_all_ids(types=("wet",))
