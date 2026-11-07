"""The commitments of the Eerste Kamer: its register and the page of a commitment as served on
2026-11-07 (``<main>`` only), the commitment written of a page, who made it, and which pages a
run of ``retrieve eerstekamer-commitments`` fetches."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import CHAMBER_EK, LABEL_EERSTE_KAMER
from lawgraph.core import ek_commitments
from lawgraph.core.official_urls import ek_url
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.eerstekamer_commitments import commitment_node
from lawgraph.pipelines.retrieve import eerstekamer_commitments as retrieve
from lawgraph.pipelines.semantic.eerstekamer_government import ek_commitment_props
from tests.paths import fixture_text


def _page(name: str) -> ek_commitments.CommitmentPage:
    page = ek_commitments.commitment_page(fixture_text(name, sub="eerstekamer"))
    assert page is not None
    return page


LIST = fixture_text("ek_commitments_list.html", sub="eerstekamer")
FORM = fixture_text("ek_commitments_form.html", sub="eerstekamer")


def test_the_register_lists_fifty_a_page_with_their_status() -> None:
    entries, following = ek_commitments.listed(LIST)
    assert len(entries) == 50
    assert entries[0] == ek_commitments.ListedCommitment(
        path="/toezegging/brief_over_cijfers_over_vrijwillig",
        number="T04274",
        made_on="2026-07-07",
        status="openstaand",
    )
    assert {e.status for e in entries} == {"openstaand", "voldaan", "deels voldaan"}
    assert following == (
        "/toezeggingen_2?dlgid=n2fglptsmol4y&_charset_=utf-8&u=%E2%9C%93&m=1"
        "&start_00c=50"
    )


def test_the_form_gives_the_first_page_of_every_commitment() -> None:
    form = ek_commitments.form_id(FORM)
    assert form == "n2fglptsmol4y"
    assert ek_commitments.list_path(form) == (
        "/toezeggingen_2?dlgid=n2fglptsmol4y&_charset_=utf-8&u=%E2%9C%93&m=1"
    )
    # the form's own page lists the latest five, with a next page of its own kind
    assert len(ek_commitments.listed(FORM)[0]) == 5


def test_a_commitment_page_is_read_as_the_kamer_writes_it() -> None:
    page = _page("ek_commitment_t04275.html")
    assert page.number == "T04275"
    assert page.text is not None
    assert page.text.startswith("De minister van Sociale Zaken en Werkgelegenheid zegt")
    assert (page.status, page.made_on, page.deadline) == (
        "openstaand",
        "2026-07-07",
        "2027-01-01",
    )
    assert page.responsible == ["Minister van Sociale Zaken en Werkgelegenheid"]
    assert page.responsible_now == []
    assert page.members == ["I.M. Lagas MDR (BBB)"]
    assert page.activity_kind == "Plenaire vergadering"
    assert page.category == "lagere regelgeving"
    assert page.subjects == ["flexwerkers", "PGB-sector"]
    assert page.papers == ["Wet meer zekerheid flexwerkers (36.746)"]
    assert page.dossiers == ["36746"]
    assert page.citation == "Handelingen I, 2025/2026, nr.39, item 18, p. 10."
    assert page.speakers == [ek_commitments.Speaker("Minister", "Vijlbrief")]
    assert ek_commitments.maker(page) == "Vijlbrief"


def test_an_office_since_renamed_is_the_one_of_that_day() -> None:
    page = _page("ek_commitment_t00012.html")
    assert page.responsible == [
        "Minister voor Bestuurlijke Vernieuwing en Koninkrijksrelaties"
    ]
    assert page.responsible_now == [
        "Minister van Binnenlandse Zaken en Koninkrijksrelaties"
    ]
    assert page.former_number == "tr_BIZA_2004_23"
    assert page.dossiers == ["28831"]
    assert ek_commitments.maker(page) == "De Graaf"


def test_every_dossier_of_the_kamerstukken_with_its_addition() -> None:
    page = _page("ek_commitment_t04236.html")
    assert page.dossiers == ["36915-XII", "36915-A", "36800-XII", "36800-A"]
    # the member who asked speaks first; the minister is the one who made it
    assert ek_commitments.maker(page) == "Karremans"


def test_a_page_without_a_number_is_none() -> None:
    assert ek_commitments.commitment_page("<main><p>Niet gevonden</p></main>") is None


def test_the_years_of_a_later_name_are_left_out_of_the_office() -> None:
    page = ek_commitments.commitment_page(
        '<th scope="row">Nummer</th><td>T00100</td>'
        '<th scope="row">Verantwoordelijke(n)</th>'
        "<td>Minister van Landbouw, Natuur en Voedselkwaliteit (2003-2010)<br />"
        "Staatssecretaris van Financiën<br /></td>"
    )
    assert page is not None
    assert page.responsible == [
        "Minister van Landbouw, Natuur en Voedselkwaliteit",
        "Staatssecretaris van Financiën",
    ]
    # no one spoke: no name
    assert ek_commitments.maker(page) is None


def test_the_commitment_of_a_page() -> None:
    node = commitment_node(
        "/toezegging/uitzondering_pgb_sector_voor_2030",
        _page("ek_commitment_t04275.html"),
        {
            "url": ek_url("/toezegging/uitzondering_pgb_sector_voor_2030"),
            "read_on": "2026-11-07",
        },
    )
    assert node.key == "ek_t04275"
    assert node.labels == [LABEL_EERSTE_KAMER, CHAMBER_EK]
    props = node.props
    assert props["status"] == "Openstaand"
    assert props["number"] == "T04275"
    assert props["minister_role"] == "Minister van Sociale Zaken en Werkgelegenheid"
    assert props["minister_name"] == "Vijlbrief"
    assert props["expected_resolution"] == "2027-01-01"
    assert props["dossier_labels"] == ["36746"]
    assert props["read_on"] == "2026-11-07"


_SZW = "minister van Sociale Zaken en Werkgelegenheid"
_PEOPLE = [
    {
        "id": "vijlbrief",
        "name": "S.P.R.A. Vijlbrief",
        "posts": [
            {"function": _SZW, "ministry": "szw", "from_date": "2026-02-23"},
        ],
    },
    {
        "id": "other",
        "name": "A. Ander",
        "posts": [
            {
                "function": _SZW,
                "ministry": "szw",
                "from_date": "2020-01-01",
                "to_date": "2026-02-22",
            }
        ],
    },
]
_CABINETS = [{"key": "jetten", "from_date": "2026-02-23", "to_date": None}]


def _row(**changes: Any) -> dict[str, Any]:
    return {
        "key": "ek_t04275",
        "name": "Vijlbrief",
        "role": "Minister van Sociale Zaken en Werkgelegenheid",
        "ministry_name": None,
        "text": "De minister van Sociale Zaken en Werkgelegenheid zegt de Kamer toe …",
        "date": "2026-07-07",
        "props": {},
        **changes,
    }


def test_who_made_it_is_the_holder_of_that_day_with_that_name() -> None:
    assert ek_commitment_props(_row(), _PEOPLE, _CABINETS) == {
        "member_key": "vijlbrief",
        "post": "minister",
        "ministry": "szw",
        "cabinet": "jetten",
        "member_missing": None,
        "ministry_held": None,
    }


@pytest.mark.parametrize(
    ("name", "date", "missing"),
    [
        (None, "2026-07-07", ek_commitments.NO_NAME),
        ("Vijlbrief", "2025-07-07", ek_commitments.UNMATCHED),  # not his post yet
        ("Onbekend", "2026-07-07", ek_commitments.UNMATCHED),
    ],
)
def test_a_gap_says_why(name: str | None, date: str, missing: str) -> None:
    props = ek_commitment_props(_row(name=name, date=date), _PEOPLE, _CABINETS)
    assert props["member_key"] is None
    assert props["member_missing"] == missing
    # the ministry of the office stays
    assert props["ministry"] == "szw"


def test_a_ministry_the_member_did_not_hold_is_marked_not_corrected() -> None:
    row = _row(
        role="Minister van Financiën",
        text="De minister van Financiën zegt de Kamer toe …",
    )
    props = ek_commitment_props(row, _PEOPLE, _CABINETS)
    assert (props["member_key"], props["ministry"]) == ("vijlbrief", "fin")
    assert props["ministry_held"] == "szw"


class _Client(EerstekamerSiteClient):
    """The register, answered with the entries given; a commitment's page by its path."""

    def __init__(self, entries: list[ek_commitments.ListedCommitment]) -> None:
        super().__init__()
        self.entries = entries
        self.read: list[str] = []

    def listed_commitments(self) -> Iterator[ek_commitments.ListedCommitment]:
        yield from self.entries

    def page(self, path: str) -> tuple[str, str]:
        self.read.append(path)
        return ek_url(path), "<main></main>"


ENTRIES, _ = ek_commitments.listed(LIST)


def _fetched(
    monkeypatch: pytest.MonkeyPatch,
    stored: dict[str, str],
    **options: Any,
) -> list[str]:
    def meta_values(store: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        assert kwargs["field"] == "status"
        return iter({"id": k, "value": v} for k, v in stored.items())

    monkeypatch.setattr(raw_queries, "meta_values", meta_values)
    client = _Client(ENTRIES)
    pipeline = retrieve.EerstekamerCommitmentsRetrievePipeline(
        object(),  # type: ignore[arg-type]
        client,
        **options,
    )
    records = list(pipeline.fetch())
    assert [r.external_id for r in records] == client.read
    assert all(r.meta and r.meta["status"] for r in records)
    return client.read


def test_a_page_is_fetched_when_new_or_its_status_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    every = [e.path for e in ENTRIES]
    assert _fetched(monkeypatch, {}) == every
    stored = {e.path: e.status for e in ENTRIES}
    assert _fetched(monkeypatch, stored) == []
    stored[ENTRIES[3].path] = "openstaand" if ENTRIES[3].status != "openstaand" else "x"
    assert _fetched(monkeypatch, stored) == [ENTRIES[3].path]


def test_since_and_limit_bound_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime as dt

    recent = [e.path for e in ENTRIES if (e.made_on or "") >= "2026-07-01"]
    assert len(recent) == 13
    since = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    assert _fetched(monkeypatch, {}, since=since) == recent
    assert _fetched(monkeypatch, {}, limit=2) == [e.path for e in ENTRIES[:2]]
