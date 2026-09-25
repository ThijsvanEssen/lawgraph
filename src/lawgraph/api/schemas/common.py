"""Building blocks shared by several API domains: instrument / article / judgment
summaries, citation spans and article relations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.core.bwb_xml import article_address
from lawgraph.core.models import make_node_key
from lawgraph.core.official_urls import instrument_url, publication_url

# The description of every ``official_url`` of an instrument.
OFFICIAL_URL = (
    "The official text: wetten.overheid.nl for a BWB regulation, EUR-Lex for an EU act, "
    "the Verdragenbank for a treaty, zoek.officielebekendmakingen.nl for a publication "
    "from 1995; null for none."
)

ARTICLE_ADDRESS = (
    "The `{article_number}` segment of the article routes: the number (`287`, `8:54`), or "
    "for an article without one the rest of its key (`stam_16464063` of the Algemene "
    "bepaling of the Grondwet; a repealed identity `2_10_stam_2866303`). It stays the "
    "same across versions."
)


def address_of(doc: dict[str, Any]) -> str:
    """``ARTICLE_ADDRESS`` of an article document."""
    props = doc.get("props") or {}
    law_id = props.get("bwb_id") or props.get("celex")
    if not law_id:
        return str(props.get("article_number") or doc["_key"])
    return article_address(law_id, doc["_key"], props.get("article_number"))


class QualifierFields(BaseModel):
    """Which parts of the cited article a reference names: "eerste lid, onder a"."""

    model_config = ConfigDict(extra="forbid")

    leden: list[str] = Field(
        default_factory=list,
        description="Numbers of the leden named (`['1', '2']`), ranges written out.",
    )
    onderdelen: list[str] = Field(
        default_factory=list,
        description="Letters or numbers of the onderdelen named (`['a']`, `['2']`).",
    )
    aanhef: bool = Field(default=False, description="Whether the aanhef is named.")


class InstrumentSummaryDTO(BaseModel):
    """Short representation of an instrument."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    official_url: str | None = Field(None, description=OFFICIAL_URL)
    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        stats: Any = None,
    ) -> InstrumentSummaryDTO:
        """Build from an ArangoDB document and an optional InstrumentStats dataclass."""
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            official_url=instrument_url(props),
            article_count=int(getattr(stats, "article_count", 0) or 0),
            judgment_count=int(getattr(stats, "judgment_count", 0) or 0),
            inbound_citation_count=int(
                getattr(stats, "inbound_citation_count", 0) or 0
            ),
            outbound_citation_count=int(
                getattr(stats, "outbound_citation_count", 0) or 0
            ),
        )


class ArticleCitationTarget(BaseModel):
    """Minimal metadata describing the referenced article."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    bwb_id: str | None
    article_number: str | None
    display_name: str | None


class ArticleCitationSpan(QualifierFields):
    """Character span for an internal citation inside the source article."""

    start: int | None
    end: int | None
    text: str | None
    target: ArticleCitationTarget
    kind: str = "article"
    reference_kind: str | None = Field(
        default=None,
        description="`intref` or `extref`: how the regulation's XML wrote a reference "
        "from one article to another; null for other citations.",
    )
    confidence: float | None = None


class JudgmentSummaryDTO(BaseModel):
    """Lightweight judgment summary for listing matches."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    ecli: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            ecli=props.get("ecli"),
        )


class ArticleRelationDTO(BaseModel):
    """Article reference plus optional parent instrument used in judgment responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    bwb_id: str | None
    celex: str | None = None
    article_number: str | None
    instrument: InstrumentSummaryDTO | None

    @classmethod
    def from_documents(
        cls,
        article_doc: dict[str, Any],
        instrument_doc: dict[str, Any] | None,
    ) -> ArticleRelationDTO:
        props = article_doc.get("props") or {}
        instrument = (
            InstrumentSummaryDTO.from_document(instrument_doc)
            if instrument_doc
            else None
        )
        return cls(
            id=article_doc["_id"],
            key=article_doc["_key"],
            display_name=props.get("display_name"),
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            article_number=props.get("article_number"),
            instrument=instrument,
        )


class DossierRefDTO(BaseModel):
    """Reference to a Kamerstukdossier by number; ``title`` is null when unknown."""

    model_config = ConfigDict(extra="forbid")

    number: str
    key: str
    title: str | None = None

    @classmethod
    def from_number(
        cls, number: Any, titles: dict[str, str | None] | None = None
    ) -> DossierRefDTO:
        """Build from a dossier number and an optional ``key -> title`` lookup."""
        text = str(number)
        key = make_node_key(text)
        return cls(number=text, key=key, title=(titles or {}).get(key))


class PublicationDTO(BaseModel):
    """An amending publication (Staatsblad, Tractatenblad, ...) as recorded on a version."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    kind: str | None = None
    year: int | None = None
    number: str | None = None
    signed: str | None = None
    published: str | None = None
    official_url: str | None = Field(
        None,
        description="The publication on zoek.officielebekendmakingen.nl; null before 1995.",
    )
    dossiers: list[DossierRefDTO] = Field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        titles: dict[str, str | None] | None = None,
    ) -> PublicationDTO | None:
        """Build from a ``Publication.to_dict()`` prop; None when there is none."""
        if not isinstance(data, dict) or not data:
            return None
        year = data.get("year")
        number = data.get("number")
        return cls(
            id=data.get("id"),
            kind=data.get("kind"),
            year=year if isinstance(year, int) else None,
            number=str(number) if number is not None else None,
            signed=data.get("signed"),
            published=data.get("published"),
            official_url=publication_url(data),
            dossiers=[
                DossierRefDTO.from_number(n, titles)
                for n in (data.get("dossiers") or [])
                if n is not None and str(n).strip()
            ],
        )


class FacetCountDTO(BaseModel):
    """One value of a facet and how many items have it under the current filters."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(None, description="Null counts the items without one.")
    count: int
