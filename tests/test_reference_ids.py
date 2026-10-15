"""A reference to another source carries its node id and its readable address, so a client
builds neither (``path`` and ``id`` beside the identifier)."""

from __future__ import annotations

from lawgraph.api.schemas.common import DossierRefDTO
from lawgraph.api.schemas.feed import FeedNodeDTO
from lawgraph.api.schemas.instruments import ImplementingMeasureDTO
from lawgraph.api.schemas.judgments import JudgmentConclusionDTO, JudgmentDTO
from lawgraph.api.schemas.resolve import ResolveMatch

DOTTED = "ECLI:BE:CASS:2020:ARR.20201015.1F.6"
DOTTED_ID = "judgments/ecli_be_cass_2020_arr_20201015_1f_6"


def test_a_conclusion_in_the_graph_has_its_id_and_path() -> None:
    found = JudgmentConclusionDTO(id=DOTTED_ID, ecli=DOTTED)
    assert found.model_dump()["path"] == f"/uitspraken/{DOTTED}"


def test_a_conclusion_the_graph_lacks_has_neither() -> None:
    lacking = JudgmentConclusionDTO(ecli="ECLI:NL:PHR:2020:1").model_dump()
    assert (lacking["id"], lacking["path"]) == (None, None)


def test_a_judgment_names_the_ids_of_its_original_and_its_replacement() -> None:
    judgment = JudgmentDTO.from_document(
        {
            "id": "judgments/ecli_nl_hr_2020_1",
            "key": "ecli_nl_hr_2020_1",
            "type": "judgment",
            "props": {
                "ecli": "ECLI:NL:HR:2020:1",
                "summary": None,
                "translation_of": DOTTED,
                "replaced_by": "ECLI:NL:HR:2020:2",
            },
        }
    ).model_dump()
    assert judgment["translation_of_id"] == DOTTED_ID
    assert judgment["replaced_by_id"] == "judgments/ecli_nl_hr_2020_2"


def test_a_dossier_reference_has_its_id() -> None:
    assert DossierRefDTO.from_number("36600-VIII").model_dump()["id"] == (
        "dossiers/36600_viii"
    )


def test_an_implementing_measure_has_the_id_and_path_of_its_publication() -> None:
    measure = ImplementingMeasureDTO(
        publication="stb-2013-102", citation="Stb. 2013, 102"
    ).model_dump()
    assert (measure["id"], measure["path"]) == (
        "instruments/stb_2013_102",
        "/stb/2013/102",
    )


def test_a_feed_node_has_its_id_and_path() -> None:
    node = FeedNodeDTO(collection="instruments", key="bwbr0005289").model_dump()
    assert (node["id"], node["path"]) == (
        "instruments/bwbr0005289",
        "/wetten/BWBR0005289",
    )


def test_a_resolve_match_has_its_path_from_its_props() -> None:
    match = ResolveMatch(
        id="articles/bwbr0005289_162",
        key="bwbr0005289_162",
        collection="articles",
        kind="article",
        display_name="Artikel 6:162",
        confidence=0.95,
        path_props={"bwb_id": "BWBR0005289", "article_number": "162"},
    ).model_dump()
    assert match["path"] == "/wetten/BWBR0005289/artikel/6:162"
    assert "path_props" not in match
