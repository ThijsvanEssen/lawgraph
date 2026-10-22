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


def _wti(title: str) -> str:
    return (
        "<algemene-informatie><afkortingen><afkorting>Rv</afkorting></afkortingen>"
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
