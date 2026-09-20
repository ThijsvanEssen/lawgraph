"""ECHR HUDOC retrieval against a real (recorded) results page."""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.echr import EchrClient
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from tests.fakes import RawSourcesFake

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
    return client


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    def insert_raw_source(self, **kw: Any) -> None:
        self.stored.append(kw)


def test_the_columns_of_each_result_are_the_judgment() -> None:
    judgments = _client([PAGE], []).search_judgments(respondent="NLD")
    assert [j["itemid"] for j in judgments] == ["001-252409", "001-252192"]
    assert judgments[1]["docname"] == "CASE OF A.A. v. THE NETHERLANDS"
    assert judgments[0]["kpdate"] == "2026-09-08T00:00:00"


def test_every_judgment_becomes_a_raw_record() -> None:
    store = _Store()
    pipeline = ECHRRetrievePipeline(store=store, client=_client([PAGE], []))
    result = pipeline.run_full()
    assert (result.created, result.errors) == (2, [])
    assert [r["external_id"] for r in store.stored] == ["001-252409", "001-252192"]
    assert store.stored[0]["payload_json"]["itemid"] == "001-252409"
    assert store.stored[0]["meta"]["appno"] == "7481/23"


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
    class Store(_Store):
        def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list:
            return []

    store = Store()
    unknown = "ECLI:CE:ECHR:1999:0101JUD000000199"
    pipeline = ECHRRetrievePipeline(store=store, client=_client([_versions("ENG")], []))
    result = pipeline.run(eclis=[SALDUZ, unknown])

    assert result.created == 1 and result.errors == []
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
