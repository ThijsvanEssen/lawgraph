"""An article is named as it is cited (``core.names.article_cite``): ``Art. 6:162 BW``, its
long name (``Artikel 162 Burgerlijk Wetboek Boek 6``) kept in its props."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.articles import ArticleSummaryDTO
from lawgraph.api.schemas.common import ArticleRelationDTO
from lawgraph.api.schemas.nodes import BaseNodeDTO
from lawgraph.core.names import article_cite

BW6_162: dict[str, Any] = {
    "bwb_id": "BWBR0005289",
    "article_number": "162",
    "label": "Artikel 162",
    "instrument_citation_title": "Burgerlijk Wetboek Boek 6",
    "display_name": "Artikel 162 Burgerlijk Wetboek Boek 6",
}
SR_287: dict[str, Any] = {
    "bwb_id": "BWBR0001854",
    "article_number": "287",
    "instrument_citation_title": "Wetboek van Strafrecht",
    "instrument_abbreviation": "Sr",
    "display_name": "Artikel 287 Wetboek van Strafrecht",
}


def test_an_article_is_named_as_it_is_cited() -> None:
    assert article_cite(BW6_162) == "Art. 6:162 BW"
    assert article_cite(SR_287) == "Art. 287 Sr"
    without_abbreviation = {
        k: v for k, v in SR_287.items() if k != "instrument_abbreviation"
    }
    assert article_cite(without_abbreviation) == "Art. 287 Wetboek van Strafrecht"
    # an article without a number by its own name; one without a law by its number
    assert (
        article_cite(
            {"label": "Algemene bepaling", "display_name": "Algemene bepaling Grondwet"}
        )
        == "Algemene bepaling Grondwet"
    )
    assert article_cite({"article_number": "3"}) == "Art. 3"


def _doc(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "articles/bwbr0005289_162",
        "key": "bwbr0005289_162",
        "type": "article",
        "props": props,
    }


def test_a_node_and_a_reference_carry_the_cited_name_and_keep_the_long_one() -> None:
    node = BaseNodeDTO.from_document(_doc(BW6_162)).model_dump()
    assert node["display_name"] == "Art. 6:162 BW"
    assert node["props"]["display_name"] == "Artikel 162 Burgerlijk Wetboek Boek 6"
    assert ArticleRelationDTO.from_documents(_doc(BW6_162), None).display_name == (
        "Art. 6:162 BW"
    )
    summary = ArticleSummaryDTO.from_document(_doc(BW6_162))
    assert summary.display_name == "Art. 6:162 BW"
