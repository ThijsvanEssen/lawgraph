"""The server HTML says an outcome, a vote, a due day and the official page of a judgment
alike everywhere (pure, on fixed rows)."""

from __future__ import annotations

from lawgraph.api.seo.pages.government import commitment_page
from lawgraph.api.seo.pages.judgments import judgment_page
from lawgraph.api.seo.pages.parliament import document_page
from lawgraph.core.names import decision_outcome

_COMMITMENT = {
    "id": "commitments/tz202609_124",
    "key": "tz202609_124",
    "props": {"number": "TZ202609-124", "text": "De minister stuurt een brief."},
}


def test_a_commitment_without_a_due_day_shows_none() -> None:
    page = commitment_page(
        {
            **_COMMITMENT,
            "props": {**_COMMITMENT["props"], "expected_resolution": "0001-01-01"},
        }
    )
    assert "Verwachte afdoening" not in page.body


def test_a_commitment_with_a_due_day_shows_it() -> None:
    page = commitment_page(
        {
            **_COMMITMENT,
            "props": {**_COMMITMENT["props"], "expected_resolution": "2026-12-01"},
        }
    )
    assert "Verwachte afdoening: 1 december 2026" in page.body


def test_a_decision_says_its_outcome() -> None:
    assert decision_outcome({"passed": True}) == "aangenomen"
    assert decision_outcome({"passed": False}) == "verworpen"
    assert decision_outcome({"result": "Aangenomen"}) == "Aangenomen"
    assert decision_outcome({"decision_kind": "Stemmen - uitstellen"}) == "uitstellen"


def _judgment(ecli: str, **light: object) -> dict[str, object]:
    key = ecli.lower().replace(":", "_")
    return {"id": f"judgments/{key}", "key": key, "light": {"ecli": ecli, **light}}


def test_a_dutch_judgment_links_rechtspraak() -> None:
    page = judgment_page(_judgment("ECLI:NL:HR:2019:2006", date="2019-12-20"))
    assert (
        '<a href="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2019:2006">'
        "De uitspraak op rechtspraak.nl</a>" in page.body
    )


def test_a_judgment_of_the_echr_links_hudoc_by_its_item_id() -> None:
    row = _judgment(
        "ECLI:CE:ECHR:2020:0101JUD000100018", source="echr", jurisdiction="ECHR"
    )
    page = judgment_page({**row, "external_id": "001-200001"})
    assert (
        '<a href="https://hudoc.echr.coe.int/eng?i=001-200001">'
        "De uitspraak op HUDOC</a>" in page.body
    )
    assert "rechtspraak.nl" not in page.body
    # without its item id it links nothing
    assert "<a " not in judgment_page(row).body


def test_a_paper_says_the_outcome_and_the_votes_of_its_last_vote() -> None:
    row = {
        "id": "documents/d1",
        "key": "d1",
        "props": {"kind": "Motie", "subject": "Motie van het lid A over B"},
        "decisions": [
            {
                "props": {"passed": False, "date": "2026-04-01"},
                "votes": [
                    {"name": "VVD", "choice": "Voor"},
                    {"name": "SP", "choice": "Tegen"},
                ],
            },
            {
                "props": {"passed": True, "date": "2026-04-15"},
                "votes": [
                    {"name": "GL-PvdA", "choice": "Voor"},
                    {"name": "PVV", "choice": "Tegen"},
                ],
            },
        ],
    }
    body = document_page(row).body
    assert "aangenomen" in body
    assert "GL-PvdA" in body and "PVV" in body
