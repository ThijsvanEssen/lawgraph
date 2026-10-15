"""The nested props fit their strict submodels (``core.props``): each fixture is what a
pipeline writes, and a key the submodel does not name is refused."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
)
from lawgraph.core import ek_bills as bills
from lawgraph.core import ek_composition as ec
from lawgraph.core import ek_motions, ek_persons, props
from lawgraph.core.bwb_wti import with_concepts
from lawgraph.core.dossier_stages import (
    derive_outcome,
    ek_outcome,
    outcome_props,
    phase_props,
)
from lawgraph.core.models import Node
from lawgraph.core.props import (
    DocumentProps,
    DossierProps,
    FactionProps,
    InstrumentProps,
    MemberProps,
)
from lawgraph.core.tk_records import actors, seats
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import eerstekamer_composition as composition
from lawgraph.pipelines.normalize.eerstekamer_agenda import committee_activities
from lawgraph.pipelines.normalize.eerstekamer_bills import ek_bill
from lawgraph.pipelines.normalize.eerstekamer_motions import _document_node
from lawgraph.pipelines.normalize.eerstekamer_persons import _period
from tests.fakes import InMemoryStore
from tests.paths import fixture_text

_CONCEPT = {"id": "c1", "uri": "https://identifier.overheid.nl/tooi/c1", "slug": "s"}


def _legal_areas() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return with_concepts(
        [{"main": "Strafrecht", "specific": "Strafprocesrecht"}, {"main": "Belasting"}],
        ["Justitie"],
        {"strafrecht": _CONCEPT},
        {"justitie": _CONCEPT},
    )


def test_the_legal_areas_and_themes_of_a_regulation_fit() -> None:
    areas, domains = _legal_areas()

    found = InstrumentProps.model_validate(
        {"legal_areas": areas, "policy_domains": domains}
    )

    assert found.legal_areas and found.legal_areas[0].main_slug == "s"


@pytest.mark.parametrize("field", ["legal_areas", "policy_domains"])
def test_an_unknown_key_in_a_legal_area_or_theme_is_refused(field: str) -> None:
    areas, domains = _legal_areas()
    found = {"legal_areas": areas, "policy_domains": domains}[field]

    with pytest.raises(ValueError, match="mian"):
        Node(collection="instruments", props={field: [{**found[0], "mian": "x"}]})


def test_the_signatories_of_a_paper_fit() -> None:
    signed = actors.document_actors(
        {
            "DocumentActor": [
                {
                    "Persoon_Id": "p1",
                    "Fractie_Id": "f1",
                    "ActorNaam": "J. Jansen",
                    "ActorFractie": "VVD",
                    "Relatie": "Eerste ondertekenaar",
                    "Functie": "Tweede Kamerlid",
                },
                {"ActorNaam": "De minister", "Functie": "minister van Financiën"},
            ]
        }
    )

    assert DocumentProps.model_validate({"actors": signed}).actors


def test_the_signers_of_a_motion_of_the_eerste_kamer_fit() -> None:
    page = ek_motions.motion_page(fixture_text("ek_motion_37020_m.html"))
    assert page is not None

    node = _document_node("documents/kst-37020-m", "/motiedossier/37020_m", page, {})

    assert len(node.props["actors"]) == len(page.signers)


def _decision(**props: Any) -> dict[str, Any]:
    return {"date": "2026-03-01", "case_kind": "Wetgeving", **props}


def test_the_phases_and_outcomes_of_a_bill_fit() -> None:
    decisions = [
        _decision(decision_kind="Stemmen - aangenomen", decision_text="Aangenomen.")
    ]
    phases = phase_props(
        ["Wetgeving"],
        [{"kind": "Voorstel van wet", "date": "2025-01-01"}],
        [],
        decisions,
    )
    rejected = {
        "date": "2026-06-01",
        "source_url": "https://www.eerstekamer.nl/verworpen_wetsvoorstellen",
        "retrieved_on": "2026-06-02",
    }
    vote = {
        "id": "decisions/ek_1",
        "result": "Verworpen",
        "date": "2026-06-01",
        "method": "Stemming bij zitten en opstaan",
        "source_url": "https://www.eerstekamer.nl/stemmingen",
        "retrieved_on": "2026-06-02",
    }
    outcome = derive_outcome([], decisions, ek_outcome([vote], rejected))

    found = DossierProps.model_validate(
        {**phases, **outcome_props(outcome), "ek_rejected": rejected}
    )

    assert found.phases and found.tk_decision and found.ek_outcome
    assert found.ek_outcome.outcome == "Verworpen"


def test_the_page_of_a_bill_of_the_eerste_kamer_fits() -> None:
    bill = bills.bill(fixture_text("ek_bill_36791.html"))
    meta = {"url": "https://www.eerstekamer.nl/wetsvoorstel/36791", "read_on": "x"}

    found = DossierProps.model_validate({"ek_bill": ek_bill(bill, meta)})

    assert found.ek_bill and found.ek_bill.progress


def test_the_decision_points_of_a_committee_meeting_fit() -> None:
    nodes = committee_activities(
        fixture_text("ek_committee_day_20260929.html"), {"read_on": "2026-09-29"}
    )

    assert any(node.props.get("decision_points") for node in nodes)
    assert all(node.collection == COLLECTION_ACTIVITIES for node in nodes)


def test_a_period_in_a_faction_of_the_eerste_kamer_fits() -> None:
    known = {"id": "factions/ek_d66", "key": "ek_d66", "abbreviation": "D66"}
    periods = [
        _period(ek_persons.Period("D66", "2019-06-11", None), known),
        _period(ek_persons.Period("Fractie-Otten", "2019-06-11", "2019-07-27"), None),
    ]

    assert MemberProps.model_validate({"ek_faction_memberships": periods})


def test_the_vacancies_of_a_faction_fit() -> None:
    vacancy = seats.seat_vacancy(
        {"FractieZetel": {"Fractie_Id": "f1"}, "Van": "2024-01-01", "TotEnMet": None}
    )
    assert vacancy is not None
    periods = seats.vacant_periods(
        vacancy[1], [{"from_date": "2024-03-01", "to_date": None}]
    )

    assert FactionProps.model_validate({"vacancies": periods}).vacancies


def test_the_seats_and_boards_of_the_eerste_kamer_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member's ``ek`` and a faction's ``board`` as the composition writes them, and the
    stored ``ek`` written again when the member is no longer listed."""
    state: dict[str, list[Any]] = {
        "factions": [],
        "committees": [],
        "members": [],
        "edges": [],
    }
    monkeypatch.setattr(normalize_tk, "ek_composition", lambda _s: state)
    monkeypatch.setattr(normalize_tk, "members_born_on", lambda *_a: [])
    monkeypatch.setattr(composition, "assign_member_slugs", lambda _s: None)
    store = InMemoryStore()
    pipeline = composition.EerstekamerCompositionNormalizePipeline(store=store)
    pages = {
        ec.FACTIONS_PATH: fixture_text("ek_factions.html"),
        "/fractie/democraten_1966": fixture_text("ek_faction_d66.html"),
        ec.HALL_PATH: fixture_text("ek_wie_zit_waar.html"),
    }

    written = pipeline._write_nodes(
        [{"external_id": path, "payload_text": text} for path, text in pages.items()]
    )

    members = store.nodes[COLLECTION_MEMBERS]
    assert any(doc["props"]["ek"].get("seat") for doc in members.values())
    assert store.nodes[COLLECTION_FACTIONS]["ek_democraten_1966"]["props"]["board"]
    stored = [{"key": key, "ek": doc["props"]["ek"]} for key, doc in members.items()]
    assert written is not None
    departed = pipeline._departed(written.shot, {"members": stored}, {})
    assert len(departed) == len(stored)


def _bare(annotation: Any) -> bool:
    """Whether *annotation* is or holds a ``list`` or ``dict`` without its item types."""
    if annotation in (list, dict):
        return True
    return any(_bare(arg) for arg in get_args(annotation))


def test_every_props_model_is_strict_and_types_its_lists() -> None:
    models = [
        model
        for model in vars(props).values()
        if isinstance(model, type)
        and issubclass(model, BaseModel)
        and model is not BaseModel
    ]

    assert [m.__name__ for m in models if m.model_config.get("extra") != "forbid"] == []
    assert [
        f"{model.__name__}.{name}"
        for model in models
        for name, info in model.model_fields.items()
        if _bare(info.annotation)
    ] == []
