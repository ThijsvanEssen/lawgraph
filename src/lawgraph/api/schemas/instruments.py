"""Instrument endpoints: articles, judgments, dossiers, related instruments, lists and
versions."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ARTICLE_ADDRESS,
    OFFICIAL_URL,
    VALID_UNTIL,
    DossierRefDTO,
    FacetCountDTO,
    JudgmentSummaryDTO,
    WithPath,
    address_of,
)
from lawgraph.config.constants import (
    RELATION_IMPLEMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.eurlex_nim import publication_citation
from lawgraph.core.official_urls import article_url, instrument_url
from lawgraph.core.verdragenbank_xml import reservations_url

TEXT_PREVIEW_CHARS = 160  # the default length of a ``text_preview``

# What `bwb_id` holds in the answer of an instrument route: the identifier of the request.
_REQUESTED = (
    "The instrument as requested: its BWB id, or its CELEX number for an EU act."
)


class InstrumentArticleBreadcrumbDTO(BaseModel):
    """One division an article stands in, outermost first: ``type`` is the element of the
    BWB XML (``boek``, ``titeldeel``, ``hoofdstuk``, ``afdeling``, ``paragraaf``, ...),
    ``label`` as printed ("Hoofdstuk 1"), ``title`` its heading."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    label: str | None = None
    title: str | None = None


def breadcrumb_dtos(raw: Any) -> list[InstrumentArticleBreadcrumbDTO]:
    """The stored ``breadcrumb`` of an article or an article version as DTOs."""
    return [
        InstrumentArticleBreadcrumbDTO(
            type=c.get("type"), label=c.get("label"), title=c.get("title")
        )
        for c in raw or []
        if isinstance(c, dict)
    ]


def breadcrumb_on(props: dict[str, Any], day: str) -> Any:
    """The stored breadcrumb of an article version on *day*: the last of its
    ``breadcrumb_changes`` from on or before *day*, else its ``breadcrumb``."""
    crumbs = props.get("breadcrumb")
    for change in props.get("breadcrumb_changes") or []:
        if (change.get("from") or "") <= day:
            crumbs = change.get("breadcrumb")
    return crumbs


class InstrumentArticleNodeDTO(WithPath):
    """Lightweight article shape for the graph-loader.

    No full ``text`` field — that would balloon the payload when loading
    hundreds of articles for a single instrument. ``text_preview`` carries
    the first few characters so the FE has something to render on the node;
    use /api/articles/{bwb_id}/{article_number} for full content.
    """

    model_config = ConfigDict(extra="forbid")
    path_collection = "articles"

    id: str
    key: str
    bwb_id: str | None
    celex: str | None = None
    article_number: str | None = Field(
        None,
        description="Null for an article with only a heading, and for a repealed one.",
    )
    label: str | None = Field(
        None,
        description="`Artikel 287`, or the heading of an article without a number "
        "(`Algemene bepaling`).",
    )
    heading: str | None = Field(
        None,
        description="The title of its kop (`Definities`); most articles have none.",
    )
    address: str = Field(..., description=ARTICLE_ADDRESS)
    display_name: str | None
    official_url: str | None = Field(
        None, description="The article in force on wetten.overheid.nl (its JCI)."
    )
    breadcrumb: list[InstrumentArticleBreadcrumbDTO] = []
    stub: bool = False
    repealed: bool = Field(
        False,
        description="The article is no longer in force: an identity whose number another "
        "article has now, or one its current version repeals.",
    )
    last_article_number: str | None = Field(
        None, description="The number a repealed identity last had."
    )
    text_preview: str | None = None

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, text_preview_chars: int = 160
    ) -> InstrumentArticleNodeDTO:
        props = doc.get("props") or {}
        text = props.get("text") or ""
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            article_number=props.get("article_number"),
            label=props.get("label"),
            heading=props.get("heading"),
            address=address_of(doc),
            display_name=props.get("display_name"),
            official_url=article_url(props.get("bwb_id"), props.get("article_number")),
            breadcrumb=breadcrumb_dtos(props.get("breadcrumb")),
            stub=bool(props.get("stub", False)),
            repealed=bool(props.get("repealed")),
            last_article_number=props.get("last_article_number"),
            text_preview=(text[:text_preview_chars] if text else None),
        )


class InstrumentArticlesResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/articles."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute count of articles matching the request, independent "
            "of ``limit`` — use to render a '+N more' badge."
        ),
    )
    items: list[InstrumentArticleNodeDTO]


# ── /api/instruments/{bwb_id}/judgments ───────────────────────────────────


class CitedArticleRef(BaseModel):
    """Reference to one cited article inside a judgment-citation list."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        description="ArangoDB document _id, e.g. ``articles/bwbr0001854_287``.",
    )
    key: str = Field(..., description="ArangoDB document _key.")
    article_number: str | None = None
    display_name: str | None = None


class InstrumentJudgmentItem(WithPath):
    """One judgment that cites this instrument."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "judgments"

    id: str = Field(
        ...,
        description="ArangoDB document _id, e.g. ``judgments/ecli_nl_hr_2014_1496``.",
    )
    key: str
    ecli: str | None = None
    display_name: str | None = None
    court: str | None = Field(
        default=None, description="ECLI court code, `HR`, `RBAMS`."
    )
    tier: str | None = Field(
        default=None,
        description="The tier, the Type of the court in the Instanties value list: "
        "`hoge_raad`, `raad_van_state`, `gerechtshof`, `rechtbank`, … (as in "
        "`/api/judgments`).",
    )
    court_kind: str | None = Field(
        default=None, description="The kind of court within the tier."
    )
    date: str | None = Field(
        default=None, description="Date of the judgment, YYYY-MM-DD."
    )
    advocate_general: str | None = Field(
        default=None,
        description="For a conclusion, the advocate-general who wrote it, as on "
        "`/api/judgments/{ecli}`. Null for a judgment.",
    )
    advocate_general_role: str | None = Field(
        default=None,
        description="For a conclusion, the role it is signed in (`advocaat-generaal`, "
        "`waarnemend advocaat-generaal`, ...), as on `/api/judgments/{ecli}`. Null for a "
        "judgment.",
    )
    cited_articles: list[CitedArticleRef] = Field(
        default_factory=list,
        description="Articles of the focal instrument that this judgment cites.",
    )


class InstrumentJudgmentFacets(BaseModel):
    """Every judgment that cites this instrument counted, not the page."""

    model_config = ConfigDict(extra="forbid")

    year: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per year of the judgment, the oldest first; `value` null counts "
        "those without a date.",
    )


class InstrumentJudgmentsResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/judgments."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of judgments citing this instrument "
            "(independent of ``limit``)."
        ),
    )
    year: str | None = Field(
        None, description="The year asked for (`year`), null for every year."
    )
    sort: Literal["date", "cited"] = Field(
        "date",
        description="The order of `items`: `date`, the newest first; `cited`, the most "
        "cited articles of this law first, then the newest. Ties by id.",
    )
    facets: InstrumentJudgmentFacets = Field(default_factory=InstrumentJudgmentFacets)
    items: list[InstrumentJudgmentItem]


# ── /api/instruments/{bwb_id}/dossiers ────────────────────────────────────


class InstrumentDossierItem(WithPath):
    """One parliamentary dossier touching this instrument."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "dossiers"

    id: str
    key: str
    dossier_number: str = Field(..., description="The dossier's label, e.g. 37020-XV.")
    title: str | None = None
    display_name: str | None = None
    current_phase: str | None = Field(
        None, description="The current phase of the dossier's bill (``phases``)."
    )
    opened_on: str | None = None
    closed: bool | None = None
    via: Literal["instrument", "amending_publication"] = Field(
        "instrument",
        description=(
            "How the dossier is linked: ``instrument`` = LEGISLATED_IN from the "
            "regulation itself, ``amending_publication`` = LEGISLATED_IN from a "
            "publication that amends, introduces or repeals one of its articles."
        ),
    )
    publication: str | None = Field(
        None,
        description=(
            "Identifier (e.g. ``stb-2019-33``) of the newest amending publication "
            "linking the dossier; only set when ``via`` is ``amending_publication``."
        ),
    )


class InstrumentDossiersResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/dossiers."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of dossiers touching this instrument "
            "(independent of ``limit``)."
        ),
    )
    items: list[InstrumentDossierItem]


# ── /api/instruments/{bwb_id}/amended-by ──────────────────────────────────


class AmendingInstrumentDTO(BaseModel):
    """An amending publication (Stb, Trb, ...) and what it did to a regulation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    identifier: str = Field(..., description="Publication id, e.g. ``stb-2019-33``.")
    display_name: str | None = None
    kind: str | None = None
    year: int | None = None
    number: str | None = None
    date_signed: str | None = None
    date_published: str | None = None
    official_url: str | None = Field(None, description=OFFICIAL_URL)
    dossiers: list[DossierRefDTO] = Field(default_factory=list)
    amends: int = Field(0, description="Number of AMENDS edges into the regulation.")
    introduces: int = Field(
        0, description="Number of INTRODUCES edges into the regulation."
    )
    repeals: int = Field(0, description="Number of REPEALS edges into the regulation.")
    articles_affected: int = Field(
        0, description="Distinct articles of the regulation touched."
    )
    first_effective_date: str | None = Field(
        None, description="Earliest effective date over the edges."
    )

    @classmethod
    def from_row(
        cls, row: dict[str, Any], titles: dict[str, str | None]
    ) -> AmendingInstrumentDTO:
        """Build from an ``{instrument, amends, introduces, ...}`` query row."""
        doc = row.get("instrument") or {}
        props = doc.get("props") or {}
        year = props.get("publication_year")
        number = props.get("publication_number")
        return cls(
            id=doc.get("_id") or "",
            key=doc.get("_key") or "",
            identifier=props.get("identifier") or doc.get("_key") or "",
            display_name=props.get("display_name"),
            kind=props.get("publication_kind"),
            year=year if isinstance(year, int) else None,
            number=str(number) if number is not None else None,
            date_signed=props.get("date_signed"),
            date_published=props.get("date_published"),
            official_url=instrument_url(props),
            dossiers=[
                DossierRefDTO.from_number(n, titles)
                for n in props.get("dossier_numbers") or []
                if n is not None and str(n).strip()
            ],
            amends=int(row.get("amends") or 0),
            introduces=int(row.get("introduces") or 0),
            repeals=int(row.get("repeals") or 0),
            articles_affected=int(row.get("articles_affected") or 0),
            first_effective_date=row.get("first_effective_date"),
        )


class AmendedByResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/amended-by."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of amending instruments (independent of "
            "``limit``/``offset``)."
        ),
    )
    items: list[AmendingInstrumentDTO]


# ── /api/instruments/{bwb_id}/related-instruments ─────────────────────────


class InstrumentRelatedItem(BaseModel):
    """One other instrument linked via cross-article REFERS_TO edges."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    celex: str | None = None
    display_name: str | None = None
    citation_title: str | None = None
    outbound_count: int = Field(
        ...,
        description=(
            "Number of REFERS_TO edges from articles of the focal "
            "instrument to articles of this related instrument."
        ),
    )
    inbound_count: int = Field(
        ...,
        description="Mirror of ``outbound_count`` in the opposite direction.",
    )


class InstrumentRelatedResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/related-instruments."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of related instruments (independent of ``limit``)."
        ),
    )
    items: list[InstrumentRelatedItem]


class InstrumentListItemDTO(WithPath):
    """Row in the paginated /api/instruments list."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "instruments"

    id: str
    key: str
    collection: str = "instruments"
    bwb_id: str | None
    celex: str | None
    title: str | None
    short_title: str | None
    citation_title: str | None
    display_name: str | None = None
    jurisdiction: str | None
    kind: str | None
    article_count: int
    inbound_citation_count: int = Field(
        0,
        description="How often the law and its articles are cited (REFERS_TO), as on the "
        "instrument's detail.",
    )
    next_version_from: str | None = Field(
        None,
        description="The date of the first coming change: the start of the first toestand "
        "of the law after today, as the BWB lists it. Null when none is known (and for an "
        "EU instrument).",
    )
    official_url: str | None = Field(None, description=OFFICIAL_URL)

    @classmethod
    def from_document(cls, row: dict[str, Any]) -> InstrumentListItemDTO:
        return cls(
            id=row["_id"],
            key=row["_key"],
            bwb_id=row.get("bwb_id"),
            celex=row.get("celex"),
            title=row.get("title"),
            short_title=row.get("short_title"),
            citation_title=row.get("citation_title"),
            display_name=row.get("display_name"),
            jurisdiction=row.get("jurisdiction") or None,
            kind=row.get("kind"),
            article_count=int(row.get("article_count") or 0),
            inbound_citation_count=int(row.get("inbound_citation_count") or 0),
            next_version_from=row.get("next_version_from"),
            official_url=instrument_url(row),
        )


class RegisterConceptDTO(BaseModel):
    """A concept of a register with the instruments under the filters filed under it."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        None, description="Its TOOI concept (`c_e49bce03`); null without the thesaurus."
    )
    slug: str | None = Field(
        None,
        description="Unique in its list (`familierecht`); the filter takes it too.",
    )
    label: str = Field(description="As the WTI writes it: `Familierecht`.")
    count: int


class LegalAreaFacetDTO(RegisterConceptDTO):
    """A main legal area and its specific areas."""

    narrower: list[RegisterConceptDTO] = Field(default_factory=list)


class InstrumentFacets(BaseModel):
    """The instruments under the filters, counted per register; each without its own
    filter, so the other areas stay in view when one is chosen."""

    model_config = ConfigDict(extra="forbid")

    legal_area: list[LegalAreaFacetDTO] = Field(
        default_factory=list,
        description="The legal areas of the TOOI thesaurus `scw_bwb_rechtsgebieden` as a "
        "tree: main areas, most first, each with its specific areas (`narrower`). An "
        "instrument counts once per area. Counted without the `legal_area` filter.",
    )
    policy_domain: list[RegisterConceptDTO] = Field(
        default_factory=list,
        description="The government themes of `scw_bwb_themas`, most first. Counted "
        "without the `policy_domain` filter.",
    )
    kind: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per kind (`wet`, `verdrag`, `multilateraalverdrag`, …), most first. "
        "Counted without the `kind` filter, over the list without a kind (no "
        "publications).",
    )


class InstrumentListResponse(BaseModel):
    """Paginated list envelope for instruments."""

    model_config = ConfigDict(extra="forbid")

    items: list[InstrumentListItemDTO]
    total: int
    facets: InstrumentFacets = Field(default_factory=InstrumentFacets)


class InstrumentVersionDTO(BaseModel):
    """One historical version (toestand) of a BWB instrument."""

    model_config = ConfigDict(extra="forbid")

    key: str
    bwb_id: str
    valid_from: str | None = None
    valid_until: str | None = Field(None, description=VALID_UNTIL)
    current: bool = False
    state_url: str | None = None
    official_url: str | None = Field(
        None,
        description="This version on wetten.overheid.nl (``/{BWB}/{valid_from}``).",
    )
    article_count: int | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> "InstrumentVersionDTO":
        props = doc.get("props") or {}
        return cls(
            key=doc["_key"],
            bwb_id=props.get("bwb_id", ""),
            valid_from=props.get("valid_from"),
            valid_until=props.get("valid_until"),
            current=bool(props.get("current", False)),
            state_url=props.get("state_url"),
            official_url=instrument_url(
                {"bwb_id": props.get("bwb_id")}, on=props.get("valid_from")
            ),
            article_count=props.get("article_count"),
        )


class InstrumentVersionsResponse(BaseModel):
    """Paginated list of historical versions for one instrument."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int
    items: list[InstrumentVersionDTO]


class InstrumentArticleVersionDTO(BaseModel):
    """One historical version of a single BWB article, in its place on the day asked for."""

    model_config = ConfigDict(extra="forbid")

    key: str
    bwb_id: str
    article_number: str
    label: str | None = Field(
        None,
        description="`Artikel 1:3`, or the heading of an article without a number.",
    )
    heading: str | None = Field(
        None,
        description="The title of its kop (`Definities`); most articles have none.",
    )
    breadcrumb: list[InstrumentArticleBreadcrumbDTO] = Field(
        [],
        description="The divisions the article stood in on the day asked for, outermost "
        "first: those of the toestand of that day.",
    )
    valid_from: str | None = None
    valid_until: str | None = Field(None, description=VALID_UNTIL)
    current: bool = False
    official_url: str | None = Field(
        None, description="This version on wetten.overheid.nl (JCI with ``g``)."
    )
    text: str | None = Field(
        None, description="The whole text; null when it was not asked for."
    )
    text_preview: str | None = Field(
        None, description="The first ``text_preview_chars`` characters of the text."
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        on: str,
        text_preview_chars: int = TEXT_PREVIEW_CHARS,
        include_text: bool = True,
    ) -> InstrumentArticleVersionDTO:
        """The version *doc* with its breadcrumb *on* that day."""
        props = doc.get("props") or {}
        text = props.get("text") or None
        return cls(
            key=doc["_key"],
            bwb_id=props.get("bwb_id", ""),
            article_number=props.get("article_number", ""),
            label=props.get("label"),
            heading=props.get("heading"),
            breadcrumb=breadcrumb_dtos(breadcrumb_on(props, on)),
            valid_from=props.get("valid_from"),
            valid_until=props.get("valid_until"),
            current=bool(props.get("current", False)),
            official_url=article_url(
                props.get("bwb_id"),
                props.get("article_number"),
                on=props.get("valid_from"),
            ),
            text=text if include_text else None,
            text_preview=text[:text_preview_chars] if text else None,
        )


class InstrumentArticlesAtResponse(BaseModel):
    """Articles of an instrument as-of a specific date."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    at_date: str
    total: int = Field(
        ...,
        description="Every article in force on ``at_date``, independent of ``limit`` "
        "and ``offset``.",
    )
    first_version_from: str | None = Field(
        None,
        description="The start of the first toestand of the law the source gives (the "
        "oldest ``valid_from`` of its versions). Before it the source gives no law: the "
        "route is empty, also where an article's own ``valid_from`` is older.",
    )
    items: list[InstrumentArticleVersionDTO]


# ── /api/instruments/{identifier} and /eu-links ───────────────────────────


class LegalAreaDTO(BaseModel):
    """A legal area of a regulation (WTI ``rechtsgebied``) and its TOOI concepts."""

    model_config = ConfigDict(extra="forbid")

    main: str = Field(description="The main area: `Staats- en bestuursrecht`.")
    main_id: str | None = Field(None, description="Its TOOI concept: `c_5d8350bb`.")
    main_uri: str | None = None
    main_slug: str | None = Field(
        None, description="Its slug, unique in the list: `staats-en-bestuursrecht`."
    )
    specific: str | None = Field(
        None, description="The specific area: `Bestuursrecht`."
    )
    specific_id: str | None = None
    specific_uri: str | None = None
    specific_slug: str | None = None


class PolicyDomainDTO(BaseModel):
    """A government theme of a regulation (WTI ``overheidsdomein``) and its TOOI concept."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="`Overheid, bestuur en koninkrijk`.")
    id: str | None = None
    uri: str | None = None
    slug: str | None = None


class TreatyPublicationDTO(BaseModel):
    """A Tractatenblad of a treaty, as the Verdragenbank lists it."""

    model_config = ConfigDict(extra="forbid")

    official_id: str | None = Field(
        None, description="Its id on officielebekendmakingen.nl: `trb-1951-154`."
    )
    text: str = Field(description='As the register writes it: "1951, 154".')
    description: str | None = Field(
        None, description='What it publishes: "goedkeuring, inwerkingtreding".'
    )


class TreatyPartyDTO(BaseModel):
    """A state party to a treaty, with its dates (YYYY-MM-DD) as the register gives them."""

    model_config = ConfigDict(extra="forbid")

    name: str
    signed: str | None = None
    ratified: str | None = None
    consent: str | None = Field(
        None, description="How it consented, the register's code (`R`, `T`, `A`, …)."
    )
    provisional: str | None = Field(None, description="Provisional application from.")
    in_force: str | None = None
    retroactive: str | None = None
    denounced: str | None = None
    terminated: str | None = None
    reservation: bool | None = Field(
        None,
        description="It made a reservation; the text is on the register's page "
        "(`reservations_url` of the treaty).",
    )
    objection: bool | None = None


class TreatyKingdomPartDTO(BaseModel):
    """A part of the Kingdom the treaty applies to, and from when."""

    model_config = ConfigDict(extra="forbid")

    part: str | None = None
    provisional: str | None = None
    in_force: str | None = None
    retroactive: str | None = None
    terminated: str | None = None


class TreatyDossierDTO(BaseModel):
    """A dossier of the approval of a treaty."""

    model_config = ConfigDict(extra="forbid")

    dossier: str
    rijks_number: str | None = None
    sub_number: str | None = None


class RelatedTreatyDTO(BaseModel):
    """A treaty a treaty belongs to (a Convention of its Protocol), or that belongs to it."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(None, description="Its Verdragenbank id: `005132`.")
    title: str | None = None
    date: str | None = None
    place: str | None = None


class TreatyRegisterDTO(BaseModel):
    """What the Verdragenbank registers of a treaty beyond its title and dates."""

    model_config = ConfigDict(extra="forbid")

    place_signed: str | None = None
    reservations_url: str | None = Field(
        None,
        description="The register's page with the texts of the reservations and objections "
        "of the parties; null when no party made one.",
    )
    tractatenblad: list[TreatyPublicationDTO] = Field(default_factory=list)
    parties: list[TreatyPartyDTO] = Field(default_factory=list)
    kingdom_parts: list[TreatyKingdomPartDTO] = Field(default_factory=list)
    kamerstukken: list[TreatyDossierDTO] = Field(default_factory=list)
    parent_treaties: list[RelatedTreatyDTO] = Field(default_factory=list)
    child_treaties: list[RelatedTreatyDTO] = Field(default_factory=list)

    @classmethod
    def from_props(cls, props: dict[str, Any]) -> TreatyRegisterDTO | None:
        """From the props of a treaty; None before its item XML was read."""
        fields = [name for name in cls.model_fields if props.get(name) is not None]
        if not fields:
            return None
        return cls(
            **{name: props[name] for name in fields},
            reservations_url=reservations_url(
                props.get("treaty_number"), props.get("parties") or []
            ),
        )


class InstrumentDetailDTO(WithPath):
    """One instrument: its identifiers, names, classification and dates."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "instruments"

    id: str
    key: str
    collection: str = "instruments"
    bwb_id: str | None = Field(
        None,
        description=(
            "BWB id of a Dutch regulation or treaty; `BWBV0001000` for the "
            "Convention of the ECHR."
        ),
    )
    celex: str | None = Field(None, description="CELEX number of an EU act.")
    title: str | None
    official_title: str | None
    citation_title: str | None
    short_title: str | None
    abbreviation: str | None = Field(
        None,
        description="The abbreviation it is cited by: its WTI short title (EVRM), else "
        "the one kept by hand for it (AVG); the same as `instrument_abbreviation` on its "
        "articles.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Every name it is cited by: the official abbreviations and, for a "
        "book of a code, `Boek 6 BW`, `6 BW`, `BW 6`, `BW6`, `BW`.",
    )
    display_name: str | None
    legal_areas: list[LegalAreaDTO] = Field(
        default_factory=list,
        description="The legal areas of a BWB regulation as its WTI files it (`main`, "
        "`specific`), each with the URI of its concept in the TOOI thesaurus "
        "`scw_bwb_rechtsgebieden` (null when the thesaurus lacks the label).",
    )
    policy_domains: list[PolicyDomainDTO] = Field(
        default_factory=list,
        description="The government themes of a BWB regulation as its WTI files it "
        "(`label`), with the URI of its concept in the TOOI thesaurus `scw_bwb_themas`.",
    )
    jurisdiction: str | None = Field(
        None, description="`nl`, `eu` or `int` (Verdragenbank treaties)."
    )
    kind: str | None = Field(
        None,
        description=(
            "BWB type (`wet`, `AMvB`, `verdrag`, ...), treaty kind or publication kind."
        ),
    )
    source: str | None = Field(
        None, description="The source that created the node (`bwb`, `eurlex`, ...)."
    )
    labels: list[str] = Field(default_factory=list)
    lang: str | None = None
    stub: bool = False
    article_count: int = 0
    inbound_citation_count: int = 0
    date_signed: str | None = Field(
        None,
        description="When the instrument itself was signed; for a BWB regulation that of "
        "the publication that enacted it, not of a later amendment.",
    )
    date_published: str | None = Field(
        None, description="When the instrument itself was published."
    )
    date_in_force: str | None = Field(
        None, description="When the instrument itself entered into force."
    )
    version_date_in_force: str | None = Field(
        None, description="BWB: the start of the version in force (its toestand)."
    )
    treaty_number: str | None = Field(
        None,
        description="A treaty: its Verdragenbank id (six digits), which the BWB text of the "
        "treaty names too (`wetgeving@verdragnummer`).",
    )
    in_force: bool | None = None
    dossier_numbers: list[str] = Field(default_factory=list)
    official_url: str | None = Field(None, description=OFFICIAL_URL)
    same_treaty: list[LinkedInstrumentDTO] = Field(
        default_factory=list,
        description="The other instruments with its treaty number: the Verdragenbank "
        "record of a BWB treaty, the BWB text of a Verdragenbank treaty.",
    )
    treaty: TreatyRegisterDTO | None = Field(
        None,
        description="Of a treaty of the Verdragenbank: where it was signed, its "
        "Tractatenblad publications, its parties with their dates, the parts of the Kingdom, "
        "the dossiers of its approval and the treaties it belongs to or that belong to it. "
        "Null for any other instrument.",
    )

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, same_treaty: list[dict[str, Any]] | None = None
    ) -> InstrumentDetailDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title"),
            official_title=props.get("official_title"),
            citation_title=props.get("citation_title"),
            short_title=props.get("short_title"),
            abbreviation=props.get("abbreviation"),
            aliases=list(props.get("aliases") or []),
            legal_areas=[LegalAreaDTO(**a) for a in props.get("legal_areas") or []],
            policy_domains=[
                PolicyDomainDTO(**d) for d in props.get("policy_domains") or []
            ],
            display_name=props.get("display_name"),
            jurisdiction=props.get("jurisdiction") or None,
            kind=props.get("kind"),
            source=props.get("source"),
            labels=list(doc.get("labels") or []),
            lang=props.get("lang"),
            stub=bool(props.get("stub")),
            article_count=int(props.get("article_count") or 0),
            inbound_citation_count=int(props.get("inbound_citation_count") or 0),
            date_signed=props.get("date_signed"),
            date_published=props.get("date_published"),
            date_in_force=props.get("date_in_force"),
            version_date_in_force=props.get("version_date_in_force"),
            treaty_number=props.get("treaty_number") or None,
            in_force=props.get("in_force"),
            dossier_numbers=[str(n) for n in props.get("dossier_numbers") or []],
            official_url=instrument_url(props),
            same_treaty=[
                LinkedInstrumentDTO.from_document(other) for other in same_treaty or []
            ],
            treaty=TreatyRegisterDTO.from_props(props),
        )


class LinkedInstrumentDTO(WithPath):
    """The instrument at the other end of a link."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "instruments"

    id: str
    key: str
    bwb_id: str | None
    celex: str | None
    title: str | None
    citation_title: str | None
    kind: str | None
    jurisdiction: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> LinkedInstrumentDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title") or props.get("display_name"),
            citation_title=props.get("citation_title"),
            kind=props.get("kind"),
            jurisdiction=props.get("jurisdiction") or None,
        )


# What an IMPLEMENTS edge rests on (`meta.bases`).
ImplementsBasis = Literal["national_implementing_measure", "considerans"]
IMPLEMENTS_BASES: tuple[ImplementsBasis, ...] = get_args(ImplementsBasis)


class ImplementingMeasureDTO(BaseModel):
    """A national implementing measure as EUR-Lex lists it for the EU act: the publication
    through which the instrument implements it (the law that changed the Awb to implement a
    directive)."""

    model_config = ConfigDict(extra="forbid")

    publication: str = Field(
        description="Its id on officielebekendmakingen.nl: `stb-2013-102`."
    )
    citation: str = Field(description="How it is cited: `Stb. 2013, 102`.")
    title: str | None = Field(None, description="Its title, as EUR-Lex gives it.")
    type: str | None = Field(
        None, description="The kind of act, as EUR-Lex gives it: `Wet`."
    )

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> list[ImplementingMeasureDTO]:
        """The measures of an edge (``meta.measures``); without them only its publications."""
        measures = meta.get("measures")
        if isinstance(measures, list):
            return [
                cls(**m)
                for m in measures
                if isinstance(m, dict) and m.get("publication")
            ]
        return [
            cls(publication=p, citation=publication_citation(p), title=None, type=None)
            for p in meta.get("publications") or []
            if isinstance(p, str)
        ]


class EuLinkDTO(BaseModel):
    """An `IMPLEMENTS` or `REFERS_TO` edge between a national instrument and an EU act.

    `IMPLEMENTS` rests on an implementation source (`bases`): EUR-Lex lists the publication
    as a national implementing measure of the act, or it enacted or changed the regulation
    (`national_implementing_measure`, `meta.publications`), or the considerans of the
    regulation says it implements the act (`considerans`). It links instruments: no source
    names the article that implements. `REFERS_TO`: the text of the regulation names the
    CELEX number of an act it does not implement.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: LinkedInstrumentDTO = Field(
        ...,
        description=(
            "The other end: the EU act for `implements`, the national regulation for "
            "`implemented_by`."
        ),
    )
    relation: str = RELATION_IMPLEMENTS
    confidence: float | None = None
    bases: list[ImplementsBasis] = Field(
        default_factory=list,
        description=(
            "What an `IMPLEMENTS` edge rests on: `national_implementing_measure` (EUR-Lex) "
            "and/or `considerans`; empty for `REFERS_TO`."
        ),
    )
    source: str | None = Field(
        None, description="The pipeline that wrote the edge (`bwb-implements`)."
    )
    via: list[ImplementingMeasureDTO] = Field(
        default_factory=list,
        description=(
            "The national implementing measures EUR-Lex lists for the act through which this "
            "instrument implements it (`national_implementing_measure`): a law that changed "
            "it to implement the act, or its own enacting publication. Empty for "
            "`considerans` alone and for `REFERS_TO`."
        ),
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge evidence as stored (`celex`, `bases`, `publications`, `measures`).",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> EuLinkDTO:
        """Build from an ``{instrument, edge}`` query row."""
        edge = row.get("edge") or {}
        meta = edge.get("meta") or {}
        return cls(
            instrument=LinkedInstrumentDTO.from_document(row["instrument"]),
            relation=edge.get("relation") or RELATION_IMPLEMENTS,
            confidence=edge.get("confidence"),
            bases=[b for b in meta.get("bases") or [] if b in IMPLEMENTS_BASES],
            source=edge.get("source"),
            via=ImplementingMeasureDTO.from_meta(meta),
            meta=meta,
        )


class InternationalLinkDTO(BaseModel):
    """A `REFERS_TO` edge between this instrument and an international counterpart.

    `treaty`: an article of this instrument (`own_article`) refers to a treaty
    (`instrument`), and to a treaty article (`counterpart_article`) when the reference names
    one. `echr_judgment`: an ECHR judgment (`judgment`) refers to an article of this
    instrument (`own_article`) or, without an article, to the instrument as a whole.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["treaty", "echr_judgment"]
    instrument: LinkedInstrumentDTO | None = Field(
        None, description="The treaty; set for `treaty`."
    )
    judgment: JudgmentSummaryDTO | None = Field(
        None, description="The ECHR judgment; set for `echr_judgment`."
    )
    own_article: CitedArticleRef | None = Field(
        None, description="The article of this instrument at the edge, when it has one."
    )
    counterpart_article: CitedArticleRef | None = Field(
        None, description="The article of the treaty the reference names."
    )
    relation: str = RELATION_REFERS_TO
    confidence: float | None = None
    source: str | None = Field(None, description="The pipeline that wrote the edge.")
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge evidence as stored (`raw_match`, `snippet`, `qualifier`, ...).",
    )


class InstrumentEuLinksResponse(BaseModel):
    """Response for GET /api/instruments/{identifier}/eu-links."""

    model_config = ConfigDict(extra="forbid")

    instrument: LinkedInstrumentDTO
    implements: list[EuLinkDTO] = Field(
        default_factory=list, description="EU acts this instrument implements."
    )
    implements_total: int = Field(
        ..., description="Absolute number of `implements`, independent of `limit`."
    )
    implemented_by: list[EuLinkDTO] = Field(
        default_factory=list,
        description="National publications and regulations that implement this act.",
    )
    implemented_by_total: int = Field(
        ..., description="Absolute number of `implemented_by`, independent of `limit`."
    )
    mentions: list[EuLinkDTO] = Field(
        default_factory=list,
        description=(
            "EU acts whose CELEX number the text of this regulation names and that it "
            "does not implement (`REFERS_TO`)."
        ),
    )
    mentions_total: int = Field(
        ..., description="Absolute number of `mentions`, independent of `limit`."
    )
    mentioned_by: list[EuLinkDTO] = Field(
        default_factory=list,
        description="Regulations that name this act and do not implement it.",
    )
    mentioned_by_total: int = Field(
        ..., description="Absolute number of `mentioned_by`, independent of `limit`."
    )
    international: list[InternationalLinkDTO] = Field(
        default_factory=list,
        description=(
            "Treaties that articles of this instrument refer to and ECHR judgments that "
            "refer to it, at most `limit`, treaties first."
        ),
    )
    international_total: int = Field(
        ..., description="Absolute number of `international`, independent of `limit`."
    )
