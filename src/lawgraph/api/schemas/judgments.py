"""Judgment endpoints: detail (with inline citations) and lists."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
    QualifierFields,
)
from lawgraph.api.schemas.nodes import _DROP_PROPS_KEYS, BaseNodeDTO
from lawgraph.core.identifiers import ecli_source
from lawgraph.core.mentions import MAX_MENTIONS_PER_EDGE, Mention
from lawgraph.core.official_urls import judgment_url

# ``core.judgments.DECISION_KINDS``
DecisionKind = Literal[
    "arrest",
    "vonnis",
    "beschikking",
    "uitspraak",
    "beslissing",
    "conclusie",
    "prejudiciële beslissing",
]
_DECISION_KIND = (
    "What the decision is: `arrest`, `vonnis`, `beschikking`, `uitspraak`, `beslissing` "
    "(the kantonrechter on an appeal against a traffic fine), "
    "`conclusie` or `prejudiciële beslissing`. From the metadata and the kop where they "
    "tell, else from the court and the area of law; null when nothing does."
)
_NAMES = (
    "What lawyers call the judgment: `Haviltex`, `Urgenda`, "
    "`Lindenbaum/Cohen`. From a curated list of landmark cases; empty for most."
)


class JudgmentDTO(BaseNodeDTO):
    """Rich judgment DTO that hides raw XML but exposes metadata."""

    model_config = ConfigDict(extra="forbid")

    ecli: str | None
    source: str | None = None
    official_url: str | None = Field(
        default=None,
        description="The judgment on its official site: uitspraken.rechtspraak.nl by its "
        "ECLI, HUDOC by its item id for one of the ECHR; null for a stub of another court.",
    )
    summary: str | None = Field(
        description="The inhoudsindicatie, in Dutch. For an English translation the "
        "inhoudsindicatie of the judgment it translates; null while that is not loaded."
    )
    summary_en: str | None = Field(
        default=None,
        description="An English inhoudsindicatie: that of the judgment itself when it is "
        "an English translation, else that of its translation. Null when there is none.",
    )
    translation_of: str | None = Field(
        default=None,
        description="For an English translation, the ECLI of the Dutch judgment it "
        "translates (the authentic text); null otherwise.",
    )
    names: list[str] = Field(default_factory=list, description=_NAMES)
    decision_kind: DecisionKind | None = Field(default=None, description=_DECISION_KIND)
    series_id: str | None = Field(
        default=None,
        description="The series of parallel cases the judgment is one of (the same court, "
        "day and, nearly, text): the lowest ECLI in it. Null outside a series.",
    )
    series_size: int | None = Field(
        default=None, description="How many judgments the series has."
    )
    unresolved_appeal_targets: list["AppealTarget"] = Field(
        default_factory=list,
        description='The decisions an appeal says in its text it appeals ("tegen de '
        'uitspraak van de rechtbank Gelderland van 9 juli 2025 in zaak nr. 24/6811") that '
        "are not loaded; one that is loaded is its `APPEAL_OF` edge. Empty for most.",
    )
    unresolved_citations: list["UnresolvedCitation"] = Field(
        default_factory=list,
        description="The articles the judgment cites of laws that are not in the graph "
        '("art. 392 Rv"): mentioned, not in the network. One per law and article, in '
        "reading order. Empty when it cites none, or before `semantic rechtspraak` read it.",
    )
    paragraphs: list["JudgmentParagraph"] = Field(default_factory=list)
    parties: list["JudgmentParty"] | None = Field(
        default=None,
        description="The parties the kop of the judgment names, in its order. Null when "
        "the judgment was normalized before parties were read; empty when the kop names "
        "none.",
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> JudgmentDTO:
        base = BaseNodeDTO.from_document(doc, drop_props_keys=drop_props_keys)
        props = doc.get("props") or {}
        raw_paragraphs = props.get("paragraphs") or []
        kept = [p for p in raw_paragraphs if isinstance(p, dict) and p.get("text")]
        paragraphs = [
            JudgmentParagraph(
                # A paragraph normalized before `paragraph_id` existed has no "id"; fall
                # back to its position rather than 500 the whole judgment on one stale
                # record (`core.judgments.extract_sections` uses the same "p-<n>" shape
                # for a paragraph without a printed number).
                paragraph_id=p.get("id") or f"p-{position}",
                number=p.get("number"),
                kind=p.get("kind"),
                text=p.get("text") or "",
            )
            for position, p in enumerate(kept, start=1)
        ]
        ecli = props.get("ecli")
        source = props.get("source") or ecli_source(ecli)
        parties = props.get("parties")
        return cls(
            **base.model_dump(),
            ecli=ecli,
            source=source,
            official_url=judgment_url({**props, "source": source}),
            summary=props.get("summary"),
            summary_en=props.get("summary_en"),
            translation_of=props.get("translation_of"),
            names=props.get("names") or [],
            decision_kind=props.get("decision_kind"),
            series_id=props.get("series_id"),
            series_size=props.get("series_size"),
            unresolved_appeal_targets=[
                AppealTarget(**t) for t in props.get("unresolved_appeal_targets") or []
            ],
            unresolved_citations=[
                UnresolvedCitation(**c) for c in props.get("unresolved_citations") or []
            ],
            paragraphs=paragraphs,
            parties=None if parties is None else [JudgmentParty(**p) for p in parties],
        )


class AppealTarget(BaseModel):
    """A decision an appeal names in its text that is not loaded."""

    model_config = ConfigDict(extra="forbid")

    court: str = Field(description="As the text writes it: `rechtbank Gelderland`.")
    date: str = Field(description="ISO date of the decision.")
    case_number: str | None = Field(
        default=None,
        description="As the text writes it: `24/6811`; null when it gives none.",
    )


class UnresolvedCitation(QualifierFields):
    """An article a judgment cites of a law that is not in the graph."""

    law: str = Field(
        description="The law as the judgment writes it: `Rv`, `Sv`, `Vw 2000`, `Opiumwet`."
    )
    article_number: str = Field(description="As cited: `392`, `3.5`, `1:6p`.")
    raw_match: str = Field(
        description="The text of the first citation: `art. 392, eerste lid, Rv`."
    )
    qualifier: str | None = Field(
        default=None,
        description="The qualifier of the first citation as written: `eerste lid`. "
        "`leden`, `onderdelen` and `aanhef` are what it names.",
    )
    paragraph_ids: list[str] = Field(
        default_factory=list,
        description="The paragraphs that cite it (`JudgmentParagraph.paragraph_id`).",
    )
    mention_count: int = Field(description="How often the judgment cites it.")


class JudgmentRepresentative(BaseModel):
    """Who acts for a party, as the kop names them ("advocaat: mr. X")."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="As written: `mr. H.J.W. Alt`.")
    role: Literal["advocaat", "gemachtigde"]


class JudgmentParty(BaseModel):
    """A party of a judgment, read from its kop."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="As the judgment writes it, anonymised where the source is: "
        "`[eiser]`, `MAATSCHAP GRONINGEN`. Without its legal form, place or role."
    )
    role: str = Field(
        description="`Verdachte`, `Betrokkene`, `Klager`, `Veroordeelde`, `Eiser`, "
        "`Gedaagde`, `Verzoeker`, `Verweerder`, `Appellant`, `Geïntimeerde`, "
        "`Belanghebbende`, `Opposant`, `Wederpartij`; `Partij` when none applies."
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Every role the judgment names for the party, in its order: "
        "`Geïntimeerde` and `Appellant` for one that is geïntimeerde in principaal and "
        "appellante in incidenteel hoger beroep. `[role]` when it names none.",
    )
    role_stated: bool = Field(
        description="True when the judgment names the role (a role line, a role behind "
        "the name, an anonymised name that is a role: `[verdachte]`); false when it is "
        "derived from the area of law and the side."
    )
    side: Literal["first", "second", "other"] = Field(
        description="The side of the case: `first` before `tegen` or `en`, `second` after "
        "it, `other` for an interested party (belanghebbende)."
    )
    alias: str | None = Field(
        default=None,
        description='What the judgment calls the party: `EBN` for "hierna: EBN", `KLM` '
        'for "geïntimeerden worden hierna KLM respectievelijk VNV genoemd".',
    )
    representatives: list[JudgmentRepresentative] = Field(default_factory=list)


class JudgmentParagraph(BaseModel):
    """A single paragraph from a judgment, with the article citations in it."""

    model_config = ConfigDict(extra="forbid")

    paragraph_id: str = Field(
        description="Names the paragraph in the judgment, for a deep link: `rov-5.3` for "
        "the numbered consideration 5.3, `kop-5` for a numbered heading, `p-12` (its "
        "position) for a paragraph without a number. Unique in the judgment."
    )
    number: str | None = Field(
        default=None,
        description="The number as printed, without its closing dot (`5.3`); not part of "
        "`text`. Null for a paragraph without one.",
    )
    kind: str | None = Field(
        default=None, description="`heading`, `subheading` or `body`."
    )
    text: str
    citations: list[ArticleCitationSpan] = Field(
        default_factory=list,
        description="Every citation of an article in `text`, one per occurrence, with its "
        "span (`text[start:end]`).",
    )


class JudgmentCitedArticle(QualifierFields):
    """An article a judgment cites, with where and how: the strongest of its mentions."""

    article: ArticleRelationDTO
    qualifier: str | None = Field(
        default=None,
        description="The qualifier as the judgment wrote it, `derde lid`, of the strongest "
        "mention. `leden`, `onderdelen` and `aanhef` (this class) are what it names.",
    )
    paragraph_ids: list[str] = Field(
        default_factory=list,
        description="The paragraphs that cite the article, in reading order.",
    )
    paragraph_numbers: list[str] = Field(
        default_factory=list,
        description="Their printed numbers (`5.3`), those that have one.",
    )
    snippet: str | None = Field(
        default=None, description="The text around the strongest mention."
    )
    confidence: float | None = Field(
        default=None, description="The confidence of the strongest mention."
    )
    mention_count: int = Field(
        default=0,
        description="How often the judgment cites the article. The paragraphs cover the "
        f"first {MAX_MENTIONS_PER_EDGE}; a judgment that cites an article more often is "
        "counted in full.",
    )

    @classmethod
    def from_relation(
        cls,
        article: ArticleRelationDTO,
        meta: dict[str, Any],
        confidence: float | None,
    ) -> JudgmentCitedArticle:
        mentions = mentions_of(meta)
        strongest = max(mentions, key=lambda m: m.confidence, default=None)
        numbers = [m.paragraph_number for m in mentions if m.paragraph_number]
        return cls(
            article=article,
            qualifier=strongest.qualifier if strongest else None,
            **(strongest.parts.to_dict() if strongest else {}),
            paragraph_ids=list(dict.fromkeys(m.paragraph_id for m in mentions)),
            paragraph_numbers=list(dict.fromkeys(numbers)),
            snippet=strongest.snippet if strongest else None,
            confidence=strongest.confidence if strongest else confidence,
            mention_count=_count(meta, mentions),
        )


def mentions_of(meta: dict[str, Any]) -> list[Mention]:
    """The stored mentions of a REFERS_TO edge from a judgment, in reading order."""
    stored = meta.get("mentions")
    if not isinstance(stored, list):
        return []
    return [m for m in map(Mention.from_dict, stored) if m is not None]


def _count(meta: dict[str, Any], mentions: list[Mention]) -> int:
    count = meta.get("mention_count")
    return count if isinstance(count, int) and count >= len(mentions) else len(mentions)


class JudgmentDetailResponse(BaseModel):
    """Response for GET /api/judgments/{ecli}."""

    model_config = ConfigDict(extra="forbid")

    judgment: JudgmentDTO
    articles: list[ArticleRelationDTO]
    cited_articles: list[JudgmentCitedArticle] = Field(
        default_factory=list,
        description="The same articles, each with the passages of the judgment that cite "
        "it: paragraphs, the lid or onderdeel named, a snippet.",
    )
    cited_judgments: list[JudgmentSummaryDTO] = Field(default_factory=list)
    series: list[JudgmentSummaryDTO] = Field(
        default_factory=list,
        description="The other judgments of its series (`judgment.series_id`), in the "
        "order of their ECLI numbers; empty outside a series.",
    )
    metadata: dict[str, Any] | None


_TIER = (
    "The coarse tier: the Type of the court in the Instanties value list of the "
    "Rechtspraak (`hoge_raad`, `gerechtshof`, `rechtbank`, `tuchtcollege`, "
    "`andere_instantie`, `koninkrijksinstantie`, …), or `kroon`, `hvj_eu`, `ehrm`."
)
_COURT_KIND = (
    "The kind of court within the tier, from its official name (`ambtenarengerecht`, "
    "`raad_van_beroep`, `gerecht_in_eerste_aanleg`, …); a tier of one kind of court "
    "is its own kind (`hoge_raad`)."
)


class JudgmentListItemDTO(BaseModel):
    """Row in the paginated /api/judgments list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str = "judgments"
    ecli: str | None
    display_name: str | None
    court: str | None
    tier: str | None = Field(default=None, description=_TIER)
    court_kind: str | None = Field(default=None, description=_COURT_KIND)
    date: str | None
    summary: str | None
    names: list[str] = Field(default_factory=list, description=_NAMES)
    decision_kind: DecisionKind | None = Field(default=None, description=_DECISION_KIND)
    source: str | None = None
    subjects: list[str] = Field(
        default_factory=list,
        description="The areas of law the source gives it (Rechtspraak `dcterms:subject`), "
        "as written: `Strafrecht`, `Bestuursrecht; Belastingrecht`. Empty when it gives "
        "none.",
    )
    inbound_citation_count: int | None
    outbound_citation_count: int | None = None
    series_id: str | None = None
    series_size: int | None = None

    @classmethod
    def from_document(cls, row: dict[str, Any]) -> JudgmentListItemDTO:
        inbound = row.get("inbound_citation_count")
        ecli = row.get("ecli")
        source = row.get("source") or ecli_source(ecli)
        return cls(
            id=row["_id"],
            key=row["_key"],
            ecli=ecli,
            display_name=row.get("display_name") or ecli,
            court=row.get("court_code"),
            tier=row.get("tier"),
            court_kind=row.get("court_kind"),
            date=row.get("date"),
            summary=row.get("summary"),
            names=row.get("names") or [],
            decision_kind=row.get("decision_kind"),
            source=source,
            subjects=row.get("subjects") or [],
            inbound_citation_count=int(inbound) if inbound is not None else None,
            series_id=row.get("series_id"),
            series_size=row.get("series_size"),
        )


class JudgmentFacetCount(BaseModel):
    """How many of the judgments have one value."""

    model_config = ConfigDict(extra="forbid")

    value: str | None
    count: int


class JudgmentFacets(BaseModel):
    """The judgments under the filters, counted; each without its own filter."""

    model_config = ConfigDict(extra="forbid")

    tier: list[JudgmentFacetCount] = Field(
        default_factory=list,
        description="Per tier, most first; counted without the `tier` and "
        "`court_kind` filters.",
    )
    court_kind: list[JudgmentFacetCount] = Field(
        default_factory=list,
        description="Per kind of court, most first; counted without the `court_kind` "
        "filter (within a chosen `tier`).",
    )
    source: list[JudgmentFacetCount] = Field(
        default_factory=list,
        description="Per source (`rechtspraak`, `echr`), most first; counted without "
        "the `source` filter.",
    )
    year: list[JudgmentFacetCount] = Field(
        default_factory=list,
        description="Per year of `date` (`2024`), oldest first after null (no date); "
        "counted without `from` and `to`.",
    )


class JudgmentListResponse(BaseModel):
    """Paginated list envelope for judgments."""

    model_config = ConfigDict(extra="forbid")

    items: list[JudgmentListItemDTO]
    total: int
    facets: JudgmentFacets = Field(default_factory=JudgmentFacets)
