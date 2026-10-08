"""The votes of the Eerste Kamer on bills, read from pages of eerstekamer.nl as they were
served on 2026-09-30 (``<main>`` only)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from lawgraph.config.constants import RAW_KIND_EK_REJECTED, RAW_KIND_EK_VOTES_DAY
from lawgraph.core import eerstekamer_votes as ev
from lawgraph.core.dossier_stages import derive_outcome, ek_outcome
from lawgraph.pipelines.normalize.eerstekamer_votes import faction_of, observed_on
from lawgraph.pipelines.retrieve.eerstekamer_votes import (
    EerstekamerVotesRetrievePipeline,
)
from tests.fakes import RawSourcesFake

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_1 = (FIXTURES / "ek_votes_page_1.html").read_text()
PAGE_2 = (FIXTURES / "ek_votes_page_2.html").read_text()
REJECTED = (FIXTURES / "ek_rejected_page_1.html").read_text()
# the list of every vote, on bills and on motions, as served on 2026-10-09
ALL = (FIXTURES / "ek_votes_alles_page_1.html").read_text()


@pytest.mark.parametrize(
    ("number", "label"),
    [
        ("36.791", "36791"),
        ("36.600 VII", "36600-VII"),
        ("36.600 B", "36600-B"),
        ("36.455 (R2188)", "36455-(R2188)"),
        ("6.791", "6791"),
        ("Wet 36791", None),
    ],
)
def test_the_number_of_the_eerste_kamer_is_the_label_of_the_tweede_kamer(
    number: str, label: str | None
) -> None:
    assert ev.dossier_label(number) == label


def test_a_page_holds_its_days_and_links_the_page_before() -> None:
    days = ev.days(PAGE_1)
    assert [(day, continued) for day, continued, _ in days] == [
        ("2026-09-29", False),
        ("2026-09-22", False),
    ]
    assert [(d, c) for d, c, _ in ev.days(PAGE_2)][0] == ("2026-09-22", True)
    assert ev.earlier_page(PAGE_1) == (
        "/stemmingen_per_vergaderdag?filter=wetsvoorstellen&start_006=25"
        "&dlastinprev=2026-09-22"
    )


def test_a_vote_is_read_as_the_kamer_writes_it() -> None:
    day, _, fragment = ev.days(PAGE_1)[0]
    votes = {vote.label: vote for vote in ev.votes(day or "", fragment)}
    assert len(votes) == 5
    rent = votes["36791"]
    assert (rent.date, rent.number, rent.title, rent.result) == (
        "2026-09-29",
        "36.791",
        "Wet toekomstbestendige huurcommissie",
        "Aangenomen",
    )
    assert rent.method == "Stemming bij zitten en opstaan, aangenomen"
    assert rent.report_path == "/verslagdeel/20260929/wet_toekomstbestendige"
    assert rent.bill_path == "/wetsvoorstel/36791_wet_toekomstbestendige"
    assert rent.factions["tegen"] == ["BBB", "FVD"]
    assert "Fractie-Van de Sanden" in rent.factions["voor"]
    # a rijkswet by its R-number, as the Tweede Kamer labels it
    assert votes["36455-(R2188)"].factions["tegen"] == ["PVV"]
    # a hamerstuk, with and without factions that ask to have their vote recorded
    assert votes["36880"].method == "Hamerstuk" and votes["36880"].factions == {}
    assert votes["36745"].factions == {"aantekening gevraagd": ["SGP", "FVD", "JA21"]}


def test_a_vote_on_a_motion_is_read_by_its_letter() -> None:
    """The list of every vote names a motion by the number of its dossier and its letter
    (``37.020, M``), a bill by its number; the list of bills alone shows a vote on a motion
    as one on its bill."""
    assert ev.VOTES_PATH.endswith("filter=alles")
    day, _, fragment = ev.days(ALL)[0]
    assert day == "2026-10-06"
    found = ev.votes(day, fragment)
    motions = [v for v in found if v.letter]
    bills = [v for v in found if not v.letter]
    assert (len(bills), len(motions)) == (5, 9)
    beukering = next(v for v in motions if v.letter == "M")
    assert (beukering.number, beukering.label, beukering.result) == (
        "37.020",
        "37020",
        "Verworpen",
    )
    assert beukering.title.startswith("Motie-Beukering (Fractie-Beukering) c.s. over ")
    assert beukering.motion_path == "/motiedossier/37020_m_motie_beukering_fractie"
    assert beukering.bill_path is None
    assert beukering.method == "Stemming bij zitten en opstaan, verworpen"
    assert (
        beukering.factions["voor"][0] == "BBB" and "VVD" in beukering.factions["tegen"]
    )
    assert all(v.bill_path and v.motion_path is None for v in bills)


def test_the_rejected_bills_are_read_with_their_day_and_number() -> None:
    rejected = ev.rejected(REJECTED)
    assert len(rejected) == 49
    first = rejected[0]
    assert (first.date, first.label, first.result, first.method) == (
        "2026-04-21",
        "36855",
        "Verworpen",
        None,
    )
    assert first.title == "Novelle aanpassing strafbaarstelling illegaal verblijf"
    assert rejected[-1].date == "1996-03-05"
    assert ev.next_rejected_page(REJECTED, set()) == (
        "/verworpen_in_de_eerste_kamer?start_002=50"
    )
    assert (
        ev.next_rejected_page(REJECTED, {ev.next_rejected_page(REJECTED, set()) or ""})
        is None
    )


class _Client:
    def url(self, path: str) -> str:
        return "https://www.eerstekamer.nl" + path

    def vote_pages(self):
        yield self.url("/1"), PAGE_1
        yield self.url("/2"), PAGE_2

    def rejected_pages(self):
        return [(self.url(ev.REJECTED_PATH), REJECTED)]


def test_a_day_over_two_pages_is_one_record_and_the_window_stops_the_list() -> None:
    pipeline = EerstekamerVotesRetrievePipeline(RawSourcesFake(), client=_Client())  # type: ignore[arg-type]
    records = list(pipeline.fetch(since=dt.date(2026, 9, 1)))
    days = [r for r in records if r.kind == RAW_KIND_EK_VOTES_DAY]
    assert [r.external_id for r in days] == ["2026-09-29", "2026-09-22"]
    assert len(ev.votes("2026-09-22", days[1].payload_text or "")) == 20 + 11
    assert days[1].meta["url"] == "https://www.eerstekamer.nl/1"
    rejected = [r for r in records if r.kind == RAW_KIND_EK_REJECTED]
    assert [r.external_id for r in rejected] == ["verworpen_in_de_eerste_kamer"]


def _vote(id_: str, date: str, result: str, **more: str) -> dict:
    return {"id": f"decisions/{id_}", "date": date, "result": result, **more}


def test_only_the_list_of_rejected_bills_rejects_a_bill() -> None:
    # the vote list names the vote on a motion by its bill: Wet natuurbescherming 2015
    adopted = _vote(
        "a",
        "2015-12-15",
        "Aangenomen",
        method="Stemming bij zitten en opstaan, aangenomen",
    )
    motion = _vote("m", "2015-12-15", "Verworpen")
    outcome = ek_outcome([motion, adopted], None)
    assert outcome is not None
    assert (outcome["outcome"], outcome["date"], outcome["decision"]) == (
        "Aangenomen",
        "2015-12-15",
        "decisions/a",
    )
    # a motion voted down alone decides nothing
    assert ek_outcome([motion], None) is None


def test_a_rejected_bill_takes_the_vote_of_that_day_or_the_list() -> None:
    rejected = {
        "date": "2026-04-21",
        "source_url": "list",
        "retrieved_on": "2026-09-30",
    }
    vote = _vote(
        "v",
        "2026-04-21",
        "Verworpen",
        method="Hoofdelijke stemming, verworpen",
        source_url="report",
        retrieved_on="2026-09-30",
    )
    outcome = ek_outcome([vote], rejected)
    assert outcome == {
        "outcome": "Verworpen",
        "date": "2026-04-21",
        "method": "Hoofdelijke stemming, verworpen",
        "source_url": "report",
        "retrieved_on": "2026-09-30",
        "decision": "decisions/v",
    }
    old = ek_outcome([], {**rejected, "date": "1996-03-05"})
    assert old is not None
    assert (old["method"], old["source_url"], old["decision"]) == (None, "list", None)


def test_the_eerste_kamer_closes_a_dossier() -> None:
    adopted = ek_outcome([_vote("a", "2026-09-29", "Aangenomen")], None)
    outcome = derive_outcome([], [], adopted)
    assert (outcome.closed, outcome.outcome, outcome.closed_on) == (
        True,
        "aangenomen",
        "2026-09-29",
    )
    assert outcome.ek_outcome is not None and "decision" not in outcome.ek_outcome
    rejected = ek_outcome([], {"date": "2026-04-21"})
    assert derive_outcome([], [], rejected).outcome == "verworpen"
    # the Staatsblad dates an adopted law
    published = derive_outcome([{"date_published": "2026-10-15"}], [], adopted)
    assert (published.outcome, published.closed_on) == ("aangenomen", "2026-10-15")


def test_a_name_on_the_list_of_votes_is_the_faction_observed_that_day() -> None:
    def faction(id_: str, since: str | None, until: str | None) -> dict:
        return {"id": id_, "observed_from": since, "observed_until": until, "seats": 3}

    old = faction("factions/ek_a_old", "2019-06-11", "2023-06-13")
    new = faction("factions/ek_a_new", "2023-06-13", None)
    factions = {"A": [old, new]}
    assert faction_of(factions, "A", "2020-01-01") is old
    assert faction_of(factions, "A", "2026-10-06") is new
    # before either was observed: none of two, the only one of one
    assert faction_of(factions, "A", "2016-01-01") is None
    assert faction_of({"A": [new]}, "A", "2016-01-01") is new
    assert faction_of(factions, "B", "2026-10-06") is None
    # its seats count only in the period it was observed
    assert observed_on(new, "2026-10-06") and not observed_on(new, "2016-01-01")
