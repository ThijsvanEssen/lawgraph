"""The description of a law's page opens with the abbreviation lawyers search it by; its
title stays the one of the API."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.api.seo.pages.laws import law_page


def _page(key: str, **props: Any) -> tuple[str, str]:
    page = law_page(
        {"id": f"instruments/{key}", "key": key, "props": props, "articles": []}
    )
    return page.title, page.description


@pytest.mark.parametrize(
    ("key", "props", "name"),
    [
        (
            "bwbr0005290",
            {"bwb_id": "BWBR0005290", "citation_title": "Burgerlijk Wetboek Boek 7",
             "short_title": "BW 7"},
            "Burgerlijk Wetboek Boek 7 (BW 7)",
        ),
        (
            "bwbr0049999",
            {"bwb_id": "BWBR0049999", "citation_title": "Cyberbeveiligingswet",
             "short_title": "Cbw", "abbreviation": "Cbw"},
            "Cyberbeveiligingswet (Cbw)",
        ),
        (
            "bwbr0001840",
            {"bwb_id": "BWBR0001840", "citation_title": "Grondwet"},
            "Grondwet",
        ),
    ],
)  # fmt: skip
def test_a_law_described_by_its_name_and_abbreviation(
    key: str, props: dict[str, Any], name: str
) -> None:
    _, description = _page(key, **props)
    assert description.startswith(name)


def test_an_eu_act_by_the_abbreviation_kept_for_it() -> None:
    _, description = _page(
        "32016r0679",
        celex="32016R0679",
        citation_title="Algemene verordening gegevensbescherming",
        abbreviation="AVG",
    )
    assert description.startswith("Algemene verordening gegevensbescherming (AVG)")
