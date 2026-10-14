"""``retrieve staatsblad`` on a real PostgreSQL: a publication the source answered HTTP 404
for is remembered (``missing_record``, asked again after ``MISSING_FOR_DAYS``), so the next
run does not ask for it; one it could not serve (HTTP 500) is asked again."""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.fakes import http_error


class _Client:
    """The SRU lists three AMvBs: one without XML, one the source cannot serve, one."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def search(self) -> list[dict[str, str]]:
        return [
            {"identifier": i, "modified": "2020-01-01"}
            for i in ("stb-2020-404", "stb-2015-29246", "stb-2020-1")
        ]

    def fetch_publication_xml(self, identifier: str) -> str:
        self.asked.append(identifier)
        if identifier == "stb-2015-29246":
            raise http_error(500)
        if identifier.endswith("404"):
            raise http_error(404)
        return f"<xml>{identifier}</xml>"


def test_a_known_404_is_not_asked_again_and_a_500_is(store: GraphStore) -> None:
    client = _Client()
    first = StaatsbladRetrievePipeline(store, client).run_full()  # type: ignore[arg-type]
    assert first.errors == [] and first.created == 1
    client.asked.clear()
    second = StaatsbladRetrievePipeline(store, client).run_full()  # type: ignore[arg-type]
    assert second.errors == []
    assert client.asked == ["stb-2015-29246"]
