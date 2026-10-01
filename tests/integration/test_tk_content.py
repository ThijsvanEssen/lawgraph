"""The XML of Kamerstukken through the chain, on a real database.

``retrieve tk-content`` (with its HTTP client replaced) stores the XML in raw_sources,
``normalize tk-content`` (the real command, as a process) writes text and sections on the
Documents, and a second run writes nothing.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from psycopg.types.json import Json

from lawgraph.commands.check import check
from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, raw_key
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from tests.integration.seed import FIXTURES, seed

# The seed makes two memoranda: papers 0 and 25 of the dossiers 36000 and 36025.
MVT_36000 = "kst-36000-1"
MVT_36025 = "kst-36025-26"
# The seed's other papers are moties: these tests ask for the memoranda alone.
MEMORANDA = ["toelichting"]


class _Repository:
    """The KOOP repository: the XML of a few papers, HTTP 404 for the rest."""

    def __init__(self, papers: dict[str, str | None]) -> None:
        self.papers = papers
        self.fetched: list[str] = []

    def fetch_kamerstuk_xml(self, identifier: str) -> str | None:
        self.fetched.append(identifier)
        return self.papers.get(identifier)


def _xml(name: str) -> str:
    return (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")


def _mvt_documents(store: GraphStore) -> dict[str, dict[str, Any]]:
    statement = (
        "SELECT key AS _key, props FROM documents"
        " WHERE lg_num(props -> 'sequence') IN (1, 26)"
    )
    return {d["props"]["sequence"]: d for d in store.query(statement)}


def _revisions(store: GraphStore) -> dict[str, str]:
    """The row version of every document: an upsert that changes nothing does not write."""
    rows = store.query("SELECT key, xmin::text AS rev FROM documents")
    return {row["key"]: row["rev"] for row in rows}


def _raw(store: GraphStore, key: str) -> dict[str, Any]:
    return next(
        store.query("SELECT doc FROM raw_sources WHERE key = %(key)s", {"key": key})
    )


def _seeded(cli: Any) -> GraphStore:
    store = GraphStore()
    seed(store, documents=50, judgments=2, regulations=1)
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    return store


def test_gaps_are_the_memoranda_without_xml_and_a_missing_record_waits(
    database: str, cli: Any
) -> None:
    store = _seeded(cli)
    gaps = _gaps.kamerstuk_gaps(store, MEMORANDA)
    assert sorted(p["identifier"] for p in gaps) == [MVT_36000, MVT_36025]
    assert all(p["key"] and p["date"] == "2025-03-04" for p in gaps)

    repository = _Repository({MVT_36000: _xml("kst_36750_3"), MVT_36025: None})
    pipeline = TKContentRetrievePipeline(store=store, client=repository)  # type: ignore[arg-type]
    result = pipeline.run(kinds=MEMORANDA)
    assert (result.created, result.skipped, result.errors) == (1, 1, [])

    # One paper has its XML, the other a record that says the repository has none.
    xml_key = raw_key(SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, MVT_36000)
    missing_key = raw_key(
        SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX, MVT_36025
    )
    stored = _raw(store, xml_key)
    (read,) = store.with_payloads([stored])
    assert read["payload_text"] == _xml("kst_36750_3")
    assert stored["meta"] == {"document": _mvt_documents(store)[1]["_key"]}
    waiting = _raw(store, missing_key)
    assert "payload_ref" not in waiting and waiting["meta"]["status"] == 404
    # this paper is from March 2025: not a week old, so a month
    retry = dt.datetime.fromisoformat(
        waiting["meta"]["retry_after"].replace("Z", "+00:00")
    )
    assert retry > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=29)

    assert _gaps.kamerstuk_gaps(store, MEMORANDA) == []
    again = TKContentRetrievePipeline(store=store, client=repository)  # type: ignore[arg-type]
    assert again.run(kinds=MEMORANDA).created == 0
    assert repository.fetched == [MVT_36000, MVT_36025]  # nothing was asked twice

    # A wait that is over asks again.
    store.execute(
        "UPDATE raw_sources SET doc = %(doc)s WHERE key = %(key)s",
        {
            "key": missing_key,
            "doc": Json(
                {
                    **waiting,
                    "meta": {**waiting["meta"], "retry_after": "2000-01-01T00:00:00Z"},
                }
            ),
        },
    )
    assert [p["identifier"] for p in _gaps.kamerstuk_gaps(store, MEMORANDA)] == [
        MVT_36025
    ]


def test_the_text_and_the_sections_reach_the_documents_and_a_second_run_writes_nothing(
    database: str, cli: Any
) -> None:
    store = _seeded(cli)
    repository = _Repository(
        {MVT_36000: _xml("kst_36750_3"), MVT_36025: _xml("kst_25823_3")}
    )
    TKContentRetrievePipeline(store=store, client=repository).run(kinds=MEMORANDA)  # type: ignore[arg-type]

    # before the step, the check says that it is behind
    assert any("normalize is behind" in p for p in check(store, edges=False).problems)

    first = cli("normalize", "tk-content")
    assert "2 updated" in first.stderr
    documents = _mvt_documents(store)
    modern, legacy = documents[1]["props"], documents[26]["props"]

    assert modern["xml_dialect"] == "officiele-publicatie"
    assert legacy["xml_dialect"] == "kamerwrk"
    for props in (modern, legacy):
        assert props["text_source"] == "kst-xml" and props["text_truncated"] is False
        assert props["structure_quality"] == "explicit" and props["budget"] is False
        assert props["text"].startswith("MEMORIE VAN TOELICHTING\n")
    articles = [s for s in modern["sections"] if s["kind"] == "article"]
    assert [a["number"] for a in articles] == ["I", "II"]
    article = articles[0]
    assert modern["text"][article["char_start"] : article["char_end"]].startswith(
        "Artikel I\n"
    )
    assert [
        s["number"] for s in legacy["sections"] if s["kind"] == "onderdeel"
    ] == list("ABCDEF")
    assert len(modern["footnotes"]) == 19
    # what normalize tk-dossiers wrote stays
    assert documents[1]["props"]["kind"] == "Memorie van toelichting"
    assert documents[1]["props"]["source"] == "tk"

    assert not [p for p in check(store, edges=False).problems if "tk:" in p]

    # normalize tk-dossiers again does not take the text away, and writes nothing
    before = _revisions(store)
    cli("normalize", "tk-dossiers")
    assert _revisions(store) == before
    assert _mvt_documents(store)[1]["props"]["sections"] == modern["sections"]

    # The same records again: not a document is written.
    second = cli("normalize", "tk-content")
    assert _revisions(store) == before
    assert re.search(r"Done in \S+: [\d,]+ unchanged\.", second.stderr), second.stderr[
        -500:
    ]

    # The rest of the chain reads a paper with sections without trouble.
    cli("semantic", "tk")
    assert _revisions(store).keys() == before.keys()


def test_a_paper_whose_document_does_not_exist_yet_is_left_alone(
    database: str, cli: Any
) -> None:
    store = _seeded(cli)
    TKContentRetrievePipeline(  # type: ignore[arg-type]
        store=store,
        client=_Repository(
            {MVT_36000: _xml("kst_36750_3"), MVT_36025: _xml("kst_25823_3")}
        ),
    ).run(kinds=MEMORANDA)
    victim = _mvt_documents(store)[26]["_key"]
    store.execute("DELETE FROM documents WHERE key = %(key)s", {"key": victim})

    result = cli("normalize", "tk-content")
    assert not (
        store.get_document("documents", victim) is not None
    )  # no bare node was made
    assert "1 updated, 1 skipped" in result.stderr
    assert _mvt_documents(store)[1]["props"]["structure_quality"] == "explicit"
