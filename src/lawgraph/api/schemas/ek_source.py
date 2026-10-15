"""Where something of the Eerste Kamer was read: eerstekamer.nl, the day it was read and
the first snapshot the graph holds."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.config.settings import EK_ATTRIBUTION

OBSERVED_FROM = (
    "Of the Eerste Kamer: the day a snapshot of eerstekamer.nl first showed it (not the day "
    "it began: the site gives no start as data); null for the Tweede Kamer."
)

OBSERVED_UNTIL = (
    "Of the Eerste Kamer: the day of the first snapshot that no longer showed it (not the "
    "day it ended); null while it is shown."
)


class EkSourceDTO(StrictModel):
    """Where something of the Eerste Kamer was taken over from, to name with it."""

    url: str | None = Field(None, description="Its page on eerstekamer.nl.")
    retrieved_on: str | None = Field(None, description="The day it was read.")
    composition_date: str | None = Field(
        None,
        description="The day of the composition shown: the snapshot it was last seen in "
        "(``stand``).",
    )
    data_since: str | None = Field(
        None,
        description="The day of the first snapshot the graph holds: nothing before it is "
        "known.",
    )
    attribution: str = Field(
        ..., description="The source to name (``EK_ATTRIBUTION``)."
    )

    @classmethod
    def from_props(cls, props: dict[str, Any]) -> EkSourceDTO:
        """From what was read of eerstekamer.nl: its page, the day it was read (that of
        the composition shown) and the first snapshot the graph holds."""
        return cls(
            url=props.get("url"),
            retrieved_on=props.get("retrieved_on"),
            composition_date=props.get("retrieved_on"),
            data_since=props.get("data_since"),
            attribution=EK_ATTRIBUTION,
        )


def ek_source(props: dict[str, Any]) -> EkSourceDTO | None:
    """The source of something of the Eerste Kamer; None for the Tweede Kamer."""
    if props.get("chamber") != "EK":
        return None
    return EkSourceDTO.from_props(props)
