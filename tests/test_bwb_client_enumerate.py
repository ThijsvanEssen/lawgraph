"""BWBClient.enumerate_all_ids against real (recorded) SRU responses."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from lawgraph.clients.bwb import EMPTY_PAGE_SIZES, SRU_PAGE_SIZE, BWBClient
from lawgraph.config.constants import BWB_INSTRUMENT_TYPES

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "bwb_sru_grondwet_page.xml").read_text()  # 3 toestanden, 1 BWBR id
DIAGNOSTIC = (FIXTURES / "bwb_sru_diagnostic.xml").read_text()


def _client(responses: list[str], calls: list[dict]) -> BWBClient:
    client = BWBClient.__new__(BWBClient)  # no HTTP session needed

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append(dict(params))
        return SimpleNamespace(text=responses.pop(0))

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def _page(records: int, total: int) -> str:
    """A result page of *records* real records that says the query matched *total*."""
    start = PAGE.index("<record>")
    end = PAGE.rindex("</record>") + len("</record>")
    record = PAGE[start : PAGE.index("</record>") + len("</record>")]
    text = PAGE[:start] + record * records + PAGE[end:]
    return text.replace("<numberOfRecords>11<", f"<numberOfRecords>{total}<")


def _empty_page(total: int) -> str:
    """What the service sometimes answers: valid, the total and a next position, no record."""
    return _page(0, total).replace("<recordData>", "<recordData>")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    from lawgraph.clients import bwb

    monkeypatch.setattr(bwb.time, "sleep", lambda seconds: None)


def test_deduplicates_ids_across_toestand_records() -> None:
    calls: list[dict] = []

    ids = _client([_page(3, 3)], calls).enumerate_all_ids(types=("wet",))

    assert ids == ["BWBR0001840"]  # 3 records, one law


def test_queries_use_exact_type_values_and_no_record_schema() -> None:
    calls: list[dict] = []

    _client([_page(3, 3)] * len(BWB_INSTRUMENT_TYPES), calls).enumerate_all_ids()

    assert [c["query"] for c in calls] == [
        f'dcterms.type=="{t}"' for t in BWB_INSTRUMENT_TYPES
    ]
    assert all("recordSchema" not in c for c in calls)
    assert {"AMvB", "ministeriele-regeling", "verdrag"} <= set(BWB_INSTRUMENT_TYPES)


def test_pages_until_the_reported_total_is_read() -> None:
    calls: list[dict] = []
    total = SRU_PAGE_SIZE + 3

    ids = _client(
        [_page(SRU_PAGE_SIZE, total), _page(3, total)], calls
    ).enumerate_all_ids(types=("wet",))

    assert ids == ["BWBR0001840"]
    assert [c["startRecord"] for c in calls] == ["1", str(SRU_PAGE_SIZE + 1)]


def test_an_empty_page_in_the_middle_is_not_the_end_of_the_list() -> None:
    """The service answered a valid page without records at startRecord 2001 and 4001; the
    list was taken for finished, and the Awb and the Burgerlijk Wetboek were never loaded."""
    calls: list[dict] = []
    total = SRU_PAGE_SIZE + 3
    responses = [_page(SRU_PAGE_SIZE, total), _empty_page(total), _page(3, total)]

    ids = _client(responses, calls).enumerate_all_ids(types=("wet",))

    assert ids == ["BWBR0001840"]
    assert [c["startRecord"] for c in calls] == [
        "1",
        str(SRU_PAGE_SIZE + 1),
        str(SRU_PAGE_SIZE + 1),  # the same page, asked again
    ]


def test_an_empty_page_that_stays_empty_raises() -> None:
    total = SRU_PAGE_SIZE + 3
    responses = [_page(SRU_PAGE_SIZE, total)] + [_empty_page(total)] * len(
        EMPTY_PAGE_SIZES
    )
    with pytest.raises(RuntimeError, match="empty page at startRecord=1001"):
        _client(responses, []).enumerate_all_ids(types=("wet",))


def test_an_empty_page_is_asked_again_with_a_smaller_page() -> None:
    calls: list[dict] = []
    total = SRU_PAGE_SIZE + 3
    responses = [
        _page(SRU_PAGE_SIZE, total),
        _empty_page(total),
        _empty_page(total),
        _empty_page(total),  # 500 records asked: empty too
        _page(3, total),  # 250 records asked: the service answers
    ]
    _client(responses, calls).enumerate_all_ids(types=("wet",))
    assert [c["maximumRecords"] for c in calls] == [
        str(SRU_PAGE_SIZE),
        str(SRU_PAGE_SIZE),
        str(SRU_PAGE_SIZE),
        "500",
        "250",
    ]


def test_fewer_records_than_the_service_reports_raises() -> None:
    """The list stopped before the total: something was lost."""
    total = SRU_PAGE_SIZE + 3

    responses = [_page(SRU_PAGE_SIZE, total), _page(1, total)]
    # after 1001 records the next page (start 1002) is empty for good
    responses += [_empty_page(total)] * len(EMPTY_PAGE_SIZES)
    with pytest.raises(RuntimeError, match="empty page at startRecord=1002"):
        _client(responses, []).enumerate_all_ids(types=("wet",))


def test_more_records_than_the_reported_total_is_only_a_warning(caplog) -> None:
    """The toestanden change while they are listed, and a page can overlap."""
    with caplog.at_level("WARNING"):
        ids = _client([_page(5, 3)], []).enumerate_all_ids(types=("wet",))
    assert ids == ["BWBR0001840"]
    assert any("5 records read for a reported total of 3" in m for m in caplog.messages)


def test_a_type_without_records_is_fine() -> None:
    assert _client([_empty_page(0)], []).enumerate_all_ids(types=("verdrag",)) == []


def test_service_error_raises_instead_of_returning_nothing() -> None:
    calls: list[dict] = []

    with pytest.raises(RuntimeError, match="record schema is known"):
        _client([DIAGNOSTIC], calls).enumerate_all_ids(types=("wet",))
