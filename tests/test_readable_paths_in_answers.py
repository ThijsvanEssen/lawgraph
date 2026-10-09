"""The readable address (``path``) of a source in the answers of the API: from the fields
an answer has, by the same function as the server HTML (``WithPath``); null where they do
not make one, never a wrong one."""

from __future__ import annotations

from lawgraph.api.schemas.common import DossierRefDTO, JudgmentSummaryDTO
from lawgraph.api.schemas.decisions import VoteDTO
from lawgraph.api.schemas.documents import SubmitterDTO
from lawgraph.api.schemas.feed import FeedFactionDTO, FeedJudgmentDTO
from lawgraph.api.schemas.nodes import BaseNodeDTO
from lawgraph.api.schemas.search import SearchResultItem


def _node(node_id: str, **props: object) -> BaseNodeDTO:
    return BaseNodeDTO.from_document(
        {"_id": node_id, "_key": node_id.split("/")[1], "type": "x", "props": props}
    )


def test_a_node_has_the_address_its_props_make() -> None:
    assert (
        _node(
            "articles/bwbr0005289_162", bwb_id="BWBR0005289", article_number="162"
        ).path
        == "/wetten/BWBR0005289/artikel/6:162"
    )
    paper = _node(
        "documents/p", dossier_number="36600", dossier_suffix="VIII", sequence=5
    )
    assert paper.path == "/kamerstukken/36600-VIII/5"
    assert _node("decisions/decision_1").path == "/stemmingen/decision_1"
    assert _node("activities/a1").path is None
    # in the answer, and in its schema
    assert paper.model_dump()["path"] == "/kamerstukken/36600-VIII/5"
    assert "path" in BaseNodeDTO.model_json_schema(mode="serialization")["properties"]


def test_a_reference_without_an_id_by_its_collection() -> None:
    judgment = JudgmentSummaryDTO(
        id="judgments/ecli_nl_hr_2019_2006", key="ecli_nl_hr_2019_2006",
        ecli="ECLI:NL:HR:2019:2006", display_name="Hoge Raad 20-12-2019",
    )  # fmt: skip
    assert judgment.path == "/uitspraken/ECLI:NL:HR:2019:2006"
    assert FeedJudgmentDTO(ecli="ECLI:NL:HR:2019:2006").path == judgment.path
    assert FeedFactionDTO(key="d66").path == "/fracties/d66"
    assert DossierRefDTO.from_number("36600-VIII").path == "/dossiers/36600-VIII"


def test_a_paper_without_its_dossier_suffix_has_no_address() -> None:
    """A search hit of a paper names its dossier by its label, not its suffix: no address
    rather than a wrong one (36600-VIII is no 36600)."""
    hit = SearchResultItem(
        id="documents/p", key="p", collection="documents", type="document",
        display_name="Motie", score=0.1, extra={"dossier_number": "36600", "sequence": 5},
    )  # fmt: skip
    assert hit.path is None
    article = SearchResultItem(
        id="articles/a", key="a", collection="articles", type="article",
        display_name="Artikel 1", score=0.1, extra={"bwb_id": "BWBR0001854", "article_number": "1"},
    )  # fmt: skip
    assert article.path == "/wetten/BWBR0001854/artikel/1"


def test_given_props_make_the_address() -> None:
    """A member by its slug, a paper of a search hit by its dossier suffix: the props a
    query gives along (``path_props``), not in the answer itself."""
    vote = VoteDTO(
        voter_id="members/m_bakker", voter_key="m_bakker", choice="Voor",
        path_props={"slug": "bram-bakker"},
    )  # fmt: skip
    assert vote.path == "/leden/bram-bakker"
    assert "path_props" not in vote.model_dump()
    faction = VoteDTO(voter_id="factions/vvd", voter_key="vvd", choice="Voor")
    assert faction.path == "/fracties/vvd"
    assert SubmitterDTO(name="B. Bakker", member_key="m_bakker", role="indiener",
                        path_props={"slug": None}).path is None  # fmt: skip
    hit = SearchResultItem(
        id="documents/p", key="p", collection="documents", type="document",
        display_name="Motie", score=0.1, extra={"dossier_number": "36600", "sequence": 5},
        path_props={"dossier_number": "36600", "dossier_suffix": "VIII", "sequence": 5},
    )  # fmt: skip
    assert hit.path == "/kamerstukken/36600-VIII/5"


def test_a_path_given_back_is_left_out() -> None:
    """``path`` is computed: an answer built on another one's ``model_dump`` keeps its own."""
    ref = DossierRefDTO.from_number("36600")
    again = DossierRefDTO(**ref.model_dump())
    assert again.path == "/dossiers/36600"
