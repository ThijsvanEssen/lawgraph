"""Ministry responses: a ministry, its bewindspersonen per cabinet, and the ministry a
law, a dossier or a commitment names."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, computed_field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.common import END_OF_OFFICE, StrictModel
from lawgraph.api.schemas.members import PersonRefDTO
from lawgraph.core.ministries import MINISTRIES, MINISTRY_BY_KEY, Ministry, Source


class WithMinistry(StrictModel):
    """A source that names a ministry by its key (its own field ``ministry``), and so by
    its name."""

    if TYPE_CHECKING:
        ministry: MinistryKey | None

    @computed_field(  # type: ignore[prop-decorator]
        description="The name of ``ministry`` (``GET /api/ministries/{key}``): "
        "``Financiën``; null without one."
    )
    @property
    def ministry_name(self) -> str | None:
        found = MINISTRY_BY_KEY.get(str(self.ministry)) if self.ministry else None
        return found.name if found else None


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
            until=ministry.to_date,
            periods=[
                MinistryPeriodDTO(
                    from_date=p.from_date,
                    until=p.to_date,
                    successor=MinistryKey(p.successor) if p.successor else None,
                    basis=p.basis,
                    source=p.source,
                    successor_source=p.successor_source,
                )
                for p in ministry.periods
            ],
        )


class MinistryPostDTO(StrictModel):
    """A post under the ministry, as the cabinet lists it (``GET /api/cabinets/{key}``)."""

    member: PersonRefDTO
    post: Post | None = None
    function: str | None = Field(None, description="As Rijksoverheid names the post.")
    portfolio: str | None = None
    from_date: str | None = Field(None, description="The day it began.")
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    acting: bool = Field(False, description="A stand-in (ad interim).")


class MinistryCabinetDTO(StrictModel):
    """A cabinet with the posts held under the ministry in it, in order of start."""

    key: str
    name: str | None = None
    from_date: str | None = None
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    posts: list[MinistryPostDTO]


class MinistryDetailDTO(MinistryDTO):
    """A ministry with its bewindspersonen per cabinet, and how many laws, open dossiers
    and open commitments are its own: each the ``total`` of a list with ``ministry``."""

    predecessors: list[MinistryKey] = Field(
        default_factory=list,
        description="The names it followed (``Veiligheid en Justitie`` for ``Justitie en "
        "Veiligheid``), each a ministry of its own.",
    )
    cabinets: list[MinistryCabinetDTO] = Field(
        default_factory=list,
        description="The cabinets with a post under it, newest first: a post is under "
        "the ministry it had on its day (``government_functions[].ministry``).",
    )
    laws: int = Field(
        0,
        description="The BWB regulations it is first responsible for (the WTI's "
        "``eerstverantwoordelijke``), as ``GET /api/instruments?ministry=`` lists them: "
        "those in force, without the ones that change others.",
    )
    open_dossiers: int = Field(
        0,
        description="Its open dossiers: ``GET /api/dossiers?status=open&ministry=`` (a "
        "dossier's ministry is that of the bewindspersoon who signed it first).",
    )
    open_commitments: int = Field(
        0,
        description="Its open commitments: ``GET /api/commitments?status=Openstaand"
        "&ministry=``.",
    )

    @classmethod
    def from_detail(
        cls, ministry: Ministry, posts: list[dict[str, Any]], counts: dict[str, int]
    ) -> MinistryDetailDTO:
        """From the ministry, its posts (``ministry_posts``) and its counts."""
        cabinets: dict[str, MinistryCabinetDTO] = {}
        for row in posts:
            post = row.get("post") or {}
            cabinet = cabinets.setdefault(
                row["cabinet_key"],
                MinistryCabinetDTO(
                    key=row["cabinet_key"],
                    name=row.get("cabinet"),
                    from_date=row.get("from_date"),
                    to_date=row.get("to_date"),
                    posts=[],
                ),
            )
            cabinet.posts.append(
                MinistryPostDTO(
                    member=PersonRefDTO.from_row(row["member"]),
                    post=post.get("post"),
                    function=post.get("function"),
                    portfolio=post.get("portfolio"),
                    from_date=post.get("from_date"),
                    to_date=post.get("to_date"),
                    acting=bool(post.get("acting")),
                )
            )
        for cabinet in cabinets.values():
            cabinet.posts.sort(key=lambda p: (p.from_date or "", p.member.name or ""))
        return cls(
            **MinistryDTO.from_ministry(ministry).model_dump(),
            predecessors=[
                MinistryKey(m.key)
                for m in MINISTRIES
                if any(p.successor == ministry.key for p in m.periods)
            ],
            cabinets=sorted(
                cabinets.values(), key=lambda c: c.from_date or "", reverse=True
            ),
            **counts,
        )
