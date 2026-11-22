"""What a dossier says of the EU (``semantic tk-dossier-eu``): the COM document it is about and
the EU acts it implements."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.config.constants import ImplementsBasis


class EuRefDTO(StrictModel):
    """A document of the European Commission the dossier is about, by the COM number its
    title names (the Tweede Kamer gives no field for it)."""

    com: str = Field(
        ...,
        description="As EUR-Lex writes it: ``COM(2025) 80``.",
        examples=["COM(2025) 80"],
    )
    celex: str | None = Field(
        None,
        description="The CELEX number of that document (``52025PC0080`` a proposal, "
        "``52025DC0080`` another document) when the graph holds it "
        "(``GET /api/instruments/{identifier}``); null when it does not.",
    )


class DossierImplementsDTO(StrictModel):
    """An EU act the dossier implements."""

    celex: str = Field(..., examples=["32024L2811"])
    bases: list[Literal["title"] | ImplementsBasis] = Field(
        ...,
        description="What says so: ``title`` the dossier's title (\"ter implementatie van "
        'Richtlijn (EU) 2024/2811"); ``national_implementing_measure`` and ``considerans`` '
        "the ``IMPLEMENTS`` of a law the dossier legislated "
        "(``GET /api/instruments/{identifier}/eu-links``).",
    )


class WithEu(StrictModel):
    """What a dossier says of the EU (``semantic tk-dossier-eu``)."""

    eu_ref: list[EuRefDTO] = Field(
        default_factory=list,
        description="The COM documents its title names (an EU proposal); empty for none.",
    )
    implements: list[DossierImplementsDTO] = Field(
        default_factory=list,
        description="The EU acts it implements, by CELEX; empty for none known.",
    )
