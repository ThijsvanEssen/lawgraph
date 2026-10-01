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


VALID_UNTIL = (
    "The first day the version is no longer in force, exclusive: the start of the next "
    "one. `2021-07-01` is in force up to and including 2021-06-30 (wetten.overheid.nl: "
    '"t/m 30-06-2021"). Null while it is in force.'
)


SEMANTIC_CONFIDENCE = (
    "How sure `semantic_type` is: the share of classifications by the same trigger "
    "phrase, in the same place, that a hand check found right (0.25 to 0.9). Null when "
    "the reference has no type."
)
SEMANTIC_PATTERN = (
    "The pattern that gave `semantic_type` and where its phrase stood: "
    "`limiting_exception_adjacent`, `definitional_reference_window`, "
    "`cross_reference_fallback`, …"
)


def semantic_fields(edge: dict[str, Any]) -> dict[str, Any]:
    """``semantic_confidence`` and ``semantic_pattern`` of a classified reference edge
    (``semantic bwb-relation-types`` keeps them in its ``meta``)."""
    meta = edge.get("meta") or {}
    confidence = meta.get("semantic_confidence")
    pattern = meta.get("semantic_pattern")
    return {
        "semantic_confidence": (
            float(confidence) if isinstance(confidence, (int, float)) else None
        ),
        "semantic_pattern": pattern if isinstance(pattern, str) else None,
    }


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
    bwb_id: str | None = None
    celex: str | None = Field(None, description="CELEX number of an EU act.")
    title: str | None = None
    citation_title: str | None = None
    short_title: str | None = None
    abbreviation: str | None = Field(
        None,
        description="The abbreviation it is cited by: its WTI short title (EVRM), else "
        "the one kept by hand for it (AVG); the same as `instrument_abbreviation` on its "
        "articles.",
    )
    display_name: str | None
    official_url: str | None = Field(None, description=OFFICIAL_URL)
    article_count: int = Field(0, description="The articles of the instrument.")
    inbound_citation_count: int = Field(
        0, description="What refers to the instrument and to its articles."
    )
    judgment_count: int | None = Field(
        None, description="Not counted here: see `GET /api/instruments/{identifier}`."
    )
    outbound_citation_count: int | None = Field(
        None, description="Not counted here: see `GET /api/instruments/{identifier}`."
    )

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> InstrumentSummaryDTO:
        """Build from an ArangoDB document, with the counts ``graph-list-stats`` stores."""
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title"),
            citation_title=props.get("citation_title"),
            short_title=props.get("short_title"),
            abbreviation=props.get("abbreviation"),
            display_name=props.get("display_name"),
            official_url=instrument_url(props),
            article_count=int(props.get("article_count") or 0),
            inbound_citation_count=int(props.get("inbound_citation_count") or 0),
            judgment_count=None,
            outbound_citation_count=None,
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


# How the end of a post, a cabinet or a phase of it is dated, as Rijksoverheid dates it: the
# day of the change, on which the successor takes office. A period is ``from_date`` up to,
# not including, ``to_date`` (half-open, as the validity of an article version).
END_OF_OFFICE = (
    "The day it ended, as Rijksoverheid gives it: the day of the change, on which the next "
    "cabinet (holder, phase) takes office; so the period runs from ``from_date`` up to, not "
    "including, ``to_date``, and ``to_date`` is the ``from_date`` of what follows. Null "
    "while it lasts."
)
