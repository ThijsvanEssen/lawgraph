"""Dossiers of the Tweede Kamer as ``normalize tk-dossiers`` writes them: a bill, a budget
with its chapters, and the outcomes of each."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.models import Node

TITLE = (
    "Wijziging van de Uitvoeringswet Algemene verordening gegevensbescherming "
    "(Verzamelwet gegevensbescherming)"
)


def dossier_node(number: str, suffix: str, **props: Any) -> Node:
    label = f"{number}-{suffix}" if suffix else number
    return Node(
        collection=COLLECTION_DOSSIERS,
        key=label.lower().replace("-", "_"),
        labels=["TK"],
        props={
            "number": number,
            "suffix": suffix,
            "label": label,
            "order": dossier_order(number, suffix),
            **props,
        },
    )


DOSSIERS = [
    dossier_node(
        "36264",
        "",
        title=TITLE,
        kind="Wetgeving",
        opened_on="2023-01-10",
        closed=True,
        closed_on="2026-06-26",
        outcome="aangenomen",
    ),
    dossier_node("37020", "", title="Miljoenennota", kind=None, opened_on="2026-09-15"),
    dossier_node(
        "37020",
        "XV",
        title="Begroting SZW",
        kind="Begroting",
        opened_on="2026-09-15",
    ),
    dossier_node(
        "37020",
        "IIA",
        title="Begroting Staten-Generaal",
        kind="Begroting",
        opened_on="2026-09-15",
    ),
    dossier_node(
        "35000",
        "",
        title="Verworpen wet",
        kind="Wetgeving",
        opened_on="2018-01-01",
        closed=True,
        closed_on="2019-01-01",
        outcome="verworpen",
    ),
]
