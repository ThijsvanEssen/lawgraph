"""ECHR HUDOC retrieval against a real (recorded) results page."""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.echr import EchrClient
from lawgraph.config.constants import RAW_KIND_ECHR_TEXT
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline, text_items
from tests.fakes import RawSourcesFake

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

PAGE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "hudoc_results_page.json").read_text()
)  # 2 real judgments, each wrapped as {"columns": {...}}
# The recorded page is cut to two judgments; the count it reports is cut with it, because the
# client compares what it read with what the service counts.
PAGE["resultcount"] = len(PAGE["results"])


def _client(responses: list[Any], calls: list[dict]) -> EchrClient:
    client = EchrClient.__new__(EchrClient)  # no HTTP session needed

    def fake_get(path, *, params=None, timeout=30, **_kw):
        calls.append(params)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(json=lambda: response)

    client._get_raw_with_retry = fake_get  # type: ignore[method-assign]
    client.fetch_document_xml = lambda item_id: f"<doc>{item_id}</doc>"  # type: ignore[method-assign]
    return client


class _Store(RawSourcesFake):
    """Nothing stored before the run: no judgments, texts or missing records."""

    items: list[
        dict[str, Any]
    ] = []  # {item_id, ecli, language} of the stored judgments
    texts: list[dict[str, Any]] = []  # {id, at} of the stored texts

    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    def insert_raw_source(self, **kw: Any) -> None:
        self.stored.append(kw)


@pytest.fixture(autouse=True)
def _raw_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the pipeline reads of raw_sources, from the ``_Store``."""
    monkeypatch.setattr(raw_queries, "echr_items", lambda store: iter(store.items))
    monkeypatch.setattr(
        raw_queries,
        "fetch_times",
        lambda store, *, source, kind: iter(
            store.texts if kind == RAW_KIND_ECHR_TEXT else []
        ),
    )
    monkeypatch.setattr(
        raw_queries, "ids_waiting_for_retry", lambda store, **kw: iter([])
    )


def test_the_columns_of_each_result_are_the_judgment() -> None:
    judgments = _client([PAGE], []).search_judgments(respondent="NLD")
    assert [j["itemid"] for j in judgments] == ["001-252409", "001-252192"]
    assert judgments[1]["docname"] == "CASE OF A.A. v. THE NETHERLANDS"
    assert judgments[0]["kpdate"] == "2026-09-08T00:00:00"


def test_every_judgment_becomes_a_raw_record() -> None:
    store = _Store()
    pipeline = ECHRRetrievePipeline(store=store, client=_client([PAGE], []))
    result = pipeline.run_full()
    # the records, then their texts: the recorded page has no ECLIs, so each record is a
    # judgment of its own
    assert (result.created, result.errors) == (4, [])
    assert [(r["kind"], r["external_id"]) for r in store.stored] == [
        ("echr-judgment-json", "001-252409"),
        ("echr-judgment-json", "001-252192"),
        ("echr-judgment-docx-xml", "001-252192"),
        ("echr-judgment-docx-xml", "001-252409"),
    ]
    assert store.stored[0]["payload_json"]["itemid"] == "001-252409"
    assert store.stored[0]["meta"]["appno"] == "7481/23"
    assert store.stored[2]["payload_text"] == "<doc>001-252192</doc>"
    assert store.stored[2]["meta"] == {"ecli": None, "language": "ENG"}


def test_a_failing_request_raises_instead_of_an_empty_result() -> None:
    client = _client([requests.ConnectionError("no route")], [])
    with pytest.raises(requests.ConnectionError):
        client.search_judgments()


def test_a_failing_request_is_an_error_of_the_run() -> None:
    pipeline = ECHRRetrievePipeline(
        store=_Store(), client=_client([requests.ConnectionError("no route")], [])
    )
    result = pipeline.run_full()
    assert result.created == 0
    assert result.errors and "no route" in result.errors[0]


def test_the_incremental_query_filters_on_the_date() -> None:
    calls: list[dict] = []
    _client([{"results": []}], calls).search_judgments(since_date="2026-01-01")
    # In quotes: without them HUDOC answers zero results and no error.
    assert 'kpdate>="2026-01-01T00:00:00.0Z"' in calls[0]["query"]


def test_fewer_judgments_than_the_service_counts_is_an_error() -> None:
    import pytest

    short = {**PAGE, "resultcount": 827}
    with pytest.raises(RuntimeError, match="2 judgments read, the service counts 827"):
        _client([short], []).search_judgments(respondent="NLD")


# ── cited judgments, by ECLI ─────────────────────────────────────────────────

SALDUZ = "ECLI:CE:ECHR:2008:1127JUD003639102"


def _versions(*languages: str) -> dict[str, Any]:
    return {
        "resultcount": len(languages),
        "results": [
            {
                "columns": {
                    "itemid": f"001-{n}",
                    "ecli": SALDUZ,
                    "languageisocode": language,
                    "docname": f"SALDUZ v. TURKEY ({language})",
                    "respondent": "TUR",
                }
            }
            for n, language in enumerate(languages)
        ],
    }


def test_a_cited_judgment_is_asked_for_by_ecli_and_the_english_text_is_kept() -> None:
    calls: list[dict] = []
    judgments = _client([_versions("FRE", "ENG", "FRE")], calls).fetch_by_ecli([SALDUZ])
    assert [j["docname"] for j in judgments] == ["SALDUZ v. TURKEY (ENG)"]
    assert (
        f'ecli:"{SALDUZ}"' in calls[0]["query"]
        and "respondent" not in calls[0]["query"]
    )


def test_a_cited_judgment_hudoc_does_not_have_is_remembered_as_missing() -> None:
    store = _Store()
    unknown = "ECLI:CE:ECHR:1999:0101JUD000000199"
    pipeline = ECHRRetrievePipeline(store=store, client=_client([_versions("ENG")], []))
    result = pipeline.run(eclis=[SALDUZ, unknown])

    assert result.created == 2 and result.errors == []  # the judgment and its text
    kinds = {(r["kind"], r["external_id"]) for r in store.stored}
    assert ("echr-judgment-json-missing", unknown) in kinds


def test_an_echr_judgment_is_the_node_its_ecli_names() -> None:
    """A Dutch judgment cites the ECLI; the stub it leaves and the judgment are one node."""
    from lawgraph.core.models import PipelineResult, make_node_key
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    class Nodes:
        def __init__(self) -> None:
            self.docs: dict[str, dict] = {}

        def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
            self.docs.update({d["_key"]: d for d in docs})
            return len(docs), 0

    store = Nodes()
    raw = [
        {"external_id": j["columns"]["itemid"], "payload_json": j["columns"]}
        for j in _versions("ENG", "FRE")["results"]
    ]
    result = PipelineResult()
    ECHRNormalizePipeline(store=store).normalize_nodes(raw, result)  # type: ignore[arg-type]

    assert list(store.docs) == [make_node_key(SALDUZ)]
    node = store.docs[make_node_key(SALDUZ)]
    assert node["props"]["ecli"] == SALDUZ and "(ENG)" in node["props"]["title"]
    assert node["props"]["stub"] is False and result.skipped == 1


# ── texts ────────────────────────────────────────────────────────────────────


def test_a_judgment_gets_the_text_of_its_english_record_else_the_french_one() -> None:
    items = text_items(
        [
            {"item_id": "001-1", "ecli": SALDUZ, "language": "FRE"},
            {"item_id": "001-2", "ecli": SALDUZ, "language": "ENG"},
            {"item_id": "001-3", "ecli": SALDUZ, "language": "RUS"},
            {"item_id": "001-4", "ecli": "ECLI:CE:ECHR:1999:1", "language": "FRE"},
            {"item_id": "001-5", "ecli": "ECLI:CE:ECHR:1999:2", "language": "GER"},
            {"item_id": "001-6", "ecli": None, "language": "ENG"},
        ]
    )
    assert items == {
        "001-2": {"ecli": SALDUZ, "language": "ENG"},
        "001-4": {"ecli": "ECLI:CE:ECHR:1999:1", "language": "FRE"},
        "001-6": {"ecli": None, "language": "ENG"},
    }


class _StoredBefore(_Store):
    """A judgment stored before the run, with the text of another one."""

    items = [
        {"item_id": "001-10", "ecli": "ECLI:CE:ECHR:2000:10", "language": "ENG"},
        {"item_id": "001-11", "ecli": "ECLI:CE:ECHR:2000:11", "language": "ENG"},
    ]
    texts = [{"id": "001-11", "at": "2026-09-01T00:00:00Z"}]


def _texts_of(store: _Store, client: EchrClient) -> list[tuple[str, str]]:
    ECHRRetrievePipeline(store=store, client=client).run(respondent="NLD")
    return [
        (r["kind"], r["external_id"])
        for r in store.stored
        if r["kind"].startswith("echr-judgment-docx-xml")
    ]


def test_a_run_fetches_the_texts_that_are_not_stored_also_of_older_judgments() -> None:
    texts = _texts_of(_StoredBefore(), _client([{"results": []}], []))
    assert texts == [("echr-judgment-docx-xml", "001-10")]


def test_a_text_hudoc_has_no_document_for_is_remembered_as_missing() -> None:
    client = _client([{"results": []}], [])

    def no_docx(item_id: str) -> str:
        raise ValueError(f"HUDOC {item_id}: no DOCX")

    client.fetch_document_xml = no_docx  # type: ignore[method-assign]
    texts = _texts_of(_StoredBefore(), client)
    assert texts == [("echr-judgment-docx-xml-missing", "001-10")]


def test_a_failing_text_request_is_counted_and_not_stored() -> None:
    client = _client([{"results": []}], [])

    def down(item_id: str) -> str:
        raise requests.ConnectionError("no route")

    client.fetch_document_xml = down  # type: ignore[method-assign]
    store = _StoredBefore()
    pipeline = ECHRRetrievePipeline(store=store, client=client)
    result = pipeline.run(respondent="NLD")
    assert store.stored == [] and result.errors


def test_the_text_of_a_judgment_is_merged_into_the_node_of_its_ecli() -> None:
    from lawgraph.core.models import PipelineResult, make_node_key
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    class Nodes:
        def __init__(self) -> None:
            self.docs: dict[str, dict] = {}

        def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
            for doc in docs:
                merged = self.docs.setdefault(doc["_key"], {"props": {}})
                merged["props"].update(doc["props"])
            return len(docs), 0

    xml = (FIXTURES / "hudoc_001_61254_document.xml").read_text()
    ecli = "ECLI:CE:ECHR:2003:0729JUD004808699"
    raw = [
        {
            "external_id": "001-61254",
            "payload_json": {
                "itemid": "001-61254",
                "ecli": ecli,
                "languageisocode": "ENG",
                "docname": "CASE OF BEUMER v. THE NETHERLANDS",
            },
        },
        {
            "kind": "echr-judgment-docx-xml",
            "external_id": "001-61254",
            "payload_text": xml,
            "meta": {"ecli": ecli, "language": "ENG"},
        },
    ]
    store = Nodes()
    result = PipelineResult()
    ECHRNormalizePipeline(store=store).normalize_nodes(raw, result)  # type: ignore[arg-type]

    props = store.docs[make_node_key(ecli)]["props"]
    assert props["title"] == "CASE OF BEUMER v. THE NETHERLANDS"
    assert props["text"].startswith("SECOND SECTION\n\nCASE OF BEUMER")
    assert props["paragraphs"][15]["id"] == "par-1"


def _http_error(status: int) -> requests.HTTPError:
    return requests.HTTPError(
        f"{status} Server Error", response=SimpleNamespace(status_code=status)
    )


def test_a_text_hudoc_answers_http_500_for_is_skipped_and_remembered() -> None:
    """HUDOC answers HTTP 500, run after run, for an item it cannot convert (001-208029):
    one such document is no failure of the run."""
    client = _client([{"results": []}], [])

    def cannot_convert(item_id: str) -> str:
        raise _http_error(500)

    client.fetch_document_xml = cannot_convert  # type: ignore[method-assign]
    store = _StoredBefore()
    result = ECHRRetrievePipeline(store=store, client=client).run(respondent="NLD")

    assert result.errors == [] and result.skipped == 1
    (missing,) = store.stored
    assert (missing["kind"], missing["external_id"]) == (
        "echr-judgment-docx-xml-missing",
        "001-10",
    )
    assert missing["meta"]["status"] == 500


def test_http_500_for_every_text_is_the_host_and_fails_the_run() -> None:
    class ManyStored(_Store):
        items = [
            {"item_id": f"001-{n}", "ecli": f"ECLI:CE:ECHR:2000:{n}", "language": "ENG"}
            for n in range(40)
        ]

    client = _client([{"results": []}], [])

    def down(item_id: str) -> str:
        raise _http_error(500)

    client.fetch_document_xml = down  # type: ignore[method-assign]
    result = ECHRRetrievePipeline(store=ManyStored(), client=client).run(
        respondent="NLD"
    )
    assert result.errors and "seems to be down" in result.errors[0]
