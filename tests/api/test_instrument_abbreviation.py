"""BE-8: the law and the instrument of an article serve the same ``abbreviation``."""

from __future__ import annotations

from lawgraph.api.schemas.common import InstrumentSummaryDTO
from lawgraph.api.schemas.instruments import InstrumentDetailDTO

EVRM = {
    "_id": "instruments/bwbv0001000",
    "_key": "bwbv0001000",
    "props": {
        "bwb_id": "BWBV0001000",
        "citation_title": "Verdrag tot bescherming van de rechten van de mens",
        "short_title": "EVRM",
        "abbreviation": "EVRM",
    },
}
AVG = {
    "_id": "instruments/32016r0679",
    "_key": "32016r0679",
    "props": {
        "celex": "32016R0679",
        "short_title": "algemene verordening gegevensbescherming",
        "abbreviation": "AVG",
    },
}


def test_the_law_and_the_instrument_of_an_article_carry_its_abbreviation() -> None:
    for doc, abbreviation in ((EVRM, "EVRM"), (AVG, "AVG")):
        assert InstrumentDetailDTO.from_document(doc).abbreviation == abbreviation
        assert InstrumentSummaryDTO.from_document(doc).abbreviation == abbreviation


def test_without_one_it_is_null() -> None:
    doc = {"_id": "instruments/x", "_key": "x", "props": {"bwb_id": "BWBR0000001"}}
    assert InstrumentDetailDTO.from_document(doc).abbreviation is None
