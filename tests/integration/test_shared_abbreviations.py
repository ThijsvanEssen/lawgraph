"""An abbreviation a regulation shares with its own variant (``Rv``: the Wetboek van
Burgerlijke Rechtsvordering and its "(geldt in geval van niet-digitaal procederen)" variant)
is the short title and abbreviation of the base only. The real ``normalize bwb`` runs on
both."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, RAW_KIND_BWB_WTI_GENERAL
from lawgraph.db import GraphStore
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BASE, VARIANT = "BWBR0001827", "BWBR0039872"
TITLE = "Wetboek van Burgerlijke Rechtsvordering"


def _wti(title: str, abbreviation: str = "Rv") -> str:
    return (
        f"<algemene-informatie><afkortingen><afkorting>{abbreviation}</afkorting></afkortingen>"
        f'<citeertitel status="officieel">{title}</citeertitel></algemene-informatie>'
    )


def test_the_base_regulation_gets_the_abbreviation_its_variant_shares(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    grondwet = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
    laws = {
        BASE: TITLE,
        VARIANT: f"{TITLE} (geldt in geval van niet-digitaal procederen)",
    }
    for bwb_id, title in laws.items():
        write_toestanden(
            store,
            [
                (
                    RAW_KIND_BWB_TOESTAND,
                    bwb_id,
                    grondwet.replace("BWBR0001840", bwb_id),
                    {"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}/x.xml"},
                ),
                (RAW_KIND_BWB_WTI_GENERAL, bwb_id, _wti(title), {"bwb_id": bwb_id}),
            ],
        )

    cli("normalize", "bwb")

    base = store.get_node("instruments", BASE.lower())
    variant = store.get_node("instruments", VARIANT.lower())
    assert base is not None and variant is not None
    assert base.props["short_title"] == "Rv"
    assert base.props["abbreviation"] == "Rv"
    assert not variant.props.get("short_title")
    assert not variant.props.get("abbreviation")
    assert variant.props["aliases"] == ["Rv"]


def _store_versions(store: GraphStore, laws: dict[str, tuple[str, str | None]]) -> None:
    """Store a toestand and a WTI (abbreviation ``BBB``) per ``id: (title, end date)``."""
    grondwet = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
    for bwb_id, (title, end_date) in laws.items():
        write_toestanden(
            store,
            [
                (
                    RAW_KIND_BWB_TOESTAND,
                    bwb_id,
                    grondwet.replace("BWBR0001840", bwb_id),
                    {
                        "bwb_id": bwb_id,
                        "state_url": f"https://repo/{bwb_id}/x.xml",
                        "end_date": end_date,
                    },
                ),
                (
                    RAW_KIND_BWB_WTI_GENERAL,
                    bwb_id,
                    _wti(title, "BBB"),
                    {"bwb_id": bwb_id},
                ),
            ],
        )


def _short_titles(store: GraphStore, ids: list[str]) -> dict[str, Any]:
    nodes = {i: store.get_node("instruments", i.lower()) for i in ids}
    missing = [i for i, node in nodes.items() if node is None]
    assert not missing, f"no instrument: {missing}"
    return {i: node.props.get("short_title") for i, node in nodes.items() if node}


def test_versions_of_one_regulation_give_the_abbreviation_to_the_one_in_force(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _store_versions(
        store,
        {
            "BWBR0000101": ("Besluit Boeten", "2012-12-31"),
            "BWBR0000102": ("besluit boeten", None),
        },
    )

    cli("normalize", "bwb")

    assert _short_titles(store, ["BWBR0000101", "BWBR0000102"]) == {
        "BWBR0000101": None,
        "BWBR0000102": "BBB",
    }


def test_regulations_with_other_titles_do_not_get_a_shared_abbreviation(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _store_versions(
        store,
        {
            "BWBR0000101": ("Besluit Boeten", None),
            "BWBR0000102": ("Besluit Anders", None),
        },
    )

    cli("normalize", "bwb")

    assert _short_titles(store, ["BWBR0000101", "BWBR0000102"]) == {
        "BWBR0000101": None,
        "BWBR0000102": None,
    }
