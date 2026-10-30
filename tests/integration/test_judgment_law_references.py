"""What names an article a judgment cites: its text, its metadata (``Wetsverwijzing``) or
both, from ``semantic rechtspraak`` to ``origin`` in the API.

``normalize rechtspraak`` and ``semantic rechtspraak`` run as processes of their own on the
test server, on three judgments that link article 1 of the Grondwet each another way.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import judgment_xml, seed, write_judgments

GRONDWET = "BWBR0001840"
ARTICLE = "articles/bwbr0001840_1"
JCI = f"jci1.31:c:{GRONDWET}&artikel=1"
LAW = "artikel 1 van de Grondwet"

TEXT = "ECLI:NL:HR:2020:1"
BOTH = "ECLI:NL:HR:2015:2"
METADATA = "ECLI:NL:HR:2016:3"

JUDGMENTS = {
    TEXT: judgment_xml(TEXT, "2020-03-01", [("1.1", f"Volgens {LAW} geldt dit.")]),
    BOTH: judgment_xml(
        BOTH, "2015-03-01", [("2.1", f"Op grond van {LAW}.")], law_references=(JCI,)
    ),
    # a cassation judgment that does not name the article its metadata lists
    METADATA: judgment_xml(
        METADATA, "2016-03-01", [("3.1", "Het beroep faalt.")], law_references=(JCI,)
    ),
}

pytestmark = pytest.mark.xdist_group("judgment_law_references")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    with module_store(tmp_path_factory) as (store, cli):
        seed(store, documents=0, judgments=0, regulations=1)
        write_judgments(store, JUDGMENTS)
        cli("normalize", "bwb")
        cli("normalize", "rechtspraak")
        cli("semantic", "rechtspraak")
        yield store


def _cited(api: Api, ecli: str) -> dict[str, Any]:
    body = api.get_json(f"/api/judgments/{ecli}")
    (cited,) = [c for c in body["cited_articles"] if c["article"]["id"] == ARTICLE]
    return cited


def test_a_cited_article_says_whether_the_text_or_the_metadata_names_it(
    api: Api,
) -> None:
    text = _cited(api, TEXT)
    assert text["origin"] == ["text"] and text["mention_count"] == 1

    both = _cited(api, BOTH)
    assert both["origin"] == ["text", "metadata"]
    assert both["paragraph_ids"] == ["rov-2.1"] and both["confidence"] == 0.95

    metadata = _cited(api, METADATA)
    assert metadata["origin"] == ["metadata"]
    assert metadata["paragraph_ids"] == [] and metadata["mention_count"] == 0
    assert metadata["confidence"] == 1.0


def test_a_passage_that_cites_the_article_carries_the_origin_of_its_edge(
    api: Api,
) -> None:
    body = api.get_json(f"/api/articles/{GRONDWET}/1/cited-by")

    origins = {i["judgment"]["ecli"]: i["origin"] for i in body["items"]}
    assert origins == {TEXT: ["text"], BOTH: ["text", "metadata"]}
    # a judgment only the metadata links has no passage to list
    assert (body["total"], body["judgment_total"]) == (2, 2)


def test_the_canvas_edge_of_a_citing_judgment_keeps_its_origin(api: Api) -> None:
    body = api.get_json(f"/api/nodes/{ARTICLE}", relations="REFERS_TO", props="canvas")

    origins = {
        item["id"]: item["meta"]["origin"]
        for bucket in body["neighbors"]["buckets"]
        for item in bucket["items"]
    }
    assert origins == {
        "judgments/ecli_nl_hr_2020_1": ["text"],
        "judgments/ecli_nl_hr_2015_2": ["text", "metadata"],
        "judgments/ecli_nl_hr_2016_3": ["metadata"],
    }
