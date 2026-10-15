"""Ministry responses."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.ministries import Ministry, Source


class MinistryPeriodDTO(StrictModel):
    """A stretch in which the ministry had its name, and where that is known from."""

    from_date: str | None = Field(None, description="Null where no source dates it.")
    until: str | None = Field(
        None, description="The last day; null while it has the name, or where unknown."
    )
    successor: MinistryKey | None = None
    basis: str | None = Field(
        None, description="The Staatscourant decree the end rests on (from TOOI)."
    )
    source: Source = Field(
        ...,
        description="``tooi`` (the TOOI value list, since about 2010) or "
        "``rijksoverheid`` (the first post and a handover on the cabinet pages).",
    )
    successor_source: Source | None = Field(
        None,
        description="``curated`` for a succession no source gives (before 2010; "
        "``data/curated/ministries.json``).",
    )


class MinistryDTO(StrictModel):
    """A ministry name of ``data/ministries.json``: a name that came back (Economische
    Zaken) has a period for each time; a former one names its successor and the last day
    it had its name (``successor`` and ``until`` of its last period)."""

    key: MinistryKey
    name: str
    abbreviation: str | None = None
    tooi: str | None = Field(None, description="The TOOI code: ``mnre1045``.")
    successor: MinistryKey | None = None
    until: str | None = None
    periods: list[MinistryPeriodDTO] = Field(default_factory=list)

    @classmethod
    def from_ministry(cls, ministry: Ministry) -> MinistryDTO:
        return cls(
            key=MinistryKey(ministry.key),
            name=ministry.name,
            abbreviation=ministry.abbreviation,
            tooi=ministry.tooi,
            successor=MinistryKey(ministry.successor) if ministry.successor else None,
            until=ministry.until,
            periods=[
                MinistryPeriodDTO(
                    from_date=p.from_date,
                    until=p.until,
                    successor=MinistryKey(p.successor) if p.successor else None,
                    basis=p.basis,
                    source=p.source,
                    successor_source=p.successor_source,
                )
                for p in ministry.periods
            ],
        )
