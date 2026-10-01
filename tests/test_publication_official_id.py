"""The id of officielebekendmakingen.nl on a publication: as the BWB gives it, never made."""

from __future__ import annotations

from lawgraph.core.bwb_xml import publication_props


def test_the_official_id_is_the_urlidentifier_of_the_bwb() -> None:
    given = {"id": "stb-2016-288", "url_identifier": "stb-2016-288", "kind": "Stb"}
    assert publication_props(given)["official_id"] == "stb-2016-288"


def test_without_a_urlidentifier_there_is_none() -> None:
    made = {"id": "stb-2016-288", "url_identifier": None, "kind": "Stb", "year": 2016}
    assert "official_id" not in publication_props(made)
