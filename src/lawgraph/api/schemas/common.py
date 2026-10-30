"""Building blocks shared by several API domains: instrument / article / judgment
summaries, citation spans and article relations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, computed_field

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_JUDGMENTS,
    SCOPE_TYPE_FIXED,
    Collection,
    as_collection,
)
from lawgraph.core.bwb_definitions import definition_ref
from lawgraph.core.bwb_xml import article_address
from lawgraph.core.delegations import regulation_order
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.echr_findings import EchrAspect, EchrFinding
from lawgraph.core.judgment_cite import cite_of
from lawgraph.core.judgment_outcome import ConclusionOutcome, JudgmentOutcome
from lawgraph.core.models import make_node_key, node_id, parse_node_id
from lawgraph.core.names import article_cite
from lawgraph.core.official_urls import instrument_url, publication_url
from lawgraph.core.readable_paths import path_of
from lawgraph.core.tk_records.kinds import KindGroup, kind_group

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
        return str(props.get("article_number") or doc["key"])
    return article_address(law_id, doc["key"], props.get("article_number"))


OFFICIAL_ID = (
    "Of an article of a law the BWB does not hold (yet): the id of the Staatsblad "
    "publication that enacted its law (`stb-2026-56`), which names the law in the article "
    "routes (`/api/articles/STB-2026-56/2.8.6`) and in its address."
)

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


def scope_type_of(meta: dict[str, Any]) -> str:
    """How an annex scopes an article: an edge's `meta.scope_type`, else fixed."""
    return meta.get("scope_type") or SCOPE_TYPE_FIXED


PARTIAL_COUNTS = (
    "The page is whole, but ``total`` and ``facets`` were not counted in time (a filter not "
    "counted since the data last changed: a request waits 3 s for them): ``total`` null and "
    "empty facets now, ask again for them; they are counted on. The next page does not "
    "depend on them."
)


class StrictModel(BaseModel):
    """The base of every DTO: an unknown field is an error, so a change of the contract
    shows at once. Every field is in every answer (none is left out for its default), so
    the schema of an answer requires a field with a default as well; one that may be null
    says so in its type."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )


# The fields a readable address is built from (``core.readable_paths.path_of``), under the
# names the props of a node have them.
PATH_FIELDS = (
    "ecli",
    "bwb_id",
    "celex",
    "article_number",
    "dossier_number",
    "dossier_suffix",
    "sequence",
    "number",
    "slug",
    "official_id",
)


@dataclass(frozen=True)
class PathSource:
    """Where the readable address of a ``WithPath`` is read from, besides its fields under
    the names of ``PATH_FIELDS``."""

    # the collection of a source whose fields have no id and no ``collection``
    collection: str | None = None
    # the fields that hold the id and the key, when they are named otherwise
    id_field: str = "id"
    key_field: str = "key"
    # whether ``dossier_number`` is the whole label of the dossier (``37020-XV``), its
    # suffix in it: then the address of a paper needs no ``dossier_suffix``
    dossier_is_label: bool = False


class WithPath(StrictModel):
    """A source with its readable address (``path``), from its id (or its collection and
    key) and the fields it has under the names of ``PATH_FIELDS``, or its ``props`` (a
    search hit: its ``extra``). Null where they do not make one, where ``exists`` says the
    data does not hold the source, and for a paper also where the fields cannot say its
    dossier's suffix (``36600-VIII``), rather than a wrong one.
    One function for the API, the server HTML and the front end (``readable-paths.json``)."""

    path_source: ClassVar[PathSource] = PathSource()
    # what the address is built from when the fields of the answer do not say it (the own
    # dossier number and suffix of a paper whose answer names its dossier by label, the
    # slug of a member named by key): not part of the answer
    path_props: dict[str, Any] | None = Field(default=None, exclude=True)

    @computed_field(  # type: ignore[prop-decorator]
        description="Its readable address (``/wetten/BWBR0005289/artikel/6:162``); null "
        "for a source without one, or when the answer lacks what makes it."
    )
    @property
    def path(self) -> str | None:
        return readable_path(self)


def readable_path(model: WithPath) -> str | None:
    """The readable address of the source *model* describes."""
    values = model.__dict__
    source = type(model).path_source
    target = _target(values, source)
    if target is None or values.get("exists") is False:
        return None
    if isinstance(values.get("path_props"), dict):
        return path_of(target, values["path_props"])
    props: dict[str, Any] = {}
    for bag in ("props", "extra"):
        if isinstance(values.get(bag), dict):
            props.update(values[bag])
    props.update({f: values[f] for f in PATH_FIELDS if values.get(f) is not None})
    if _suffix_unknown(target, values, props, source):
        return None
    return path_of(target, props)


def _target(values: dict[str, Any], source: PathSource) -> str | None:
    """The node id of the source: its id, else its collection and key. A judgment's address
    is its ECLI, so a judgment needs no key."""
    raw_id = values.get(source.id_field)
    if isinstance(raw_id, str) and "/" in raw_id:
        return raw_id
    collection = values.get("collection") or source.collection
    key = values.get(source.key_field) or (
        "_" if collection == COLLECTION_JUDGMENTS else None
    )
    return node_id(collection, key) if collection and key else None


def _suffix_unknown(
    target: str, values: dict[str, Any], props: dict[str, Any], source: PathSource
) -> bool:
    """Whether the source is a paper whose fields cannot say its dossier's suffix: no
    ``dossier_suffix`` and no props, and its ``dossier_number`` not the whole label."""
    return parse_node_id(target)[0] == COLLECTION_DOCUMENTS and not (
        "dossier_suffix" in values
        or "dossier_suffix" in props
        or "props" in values
        or source.dossier_is_label
    )


KIND_GROUP = (
    "What the paper or case is, by its Soort (`kind`): `motie` or `amendement` (also a "
    "changed one), `wetsvoorstel`, `brief` (a Soort beginning with Brief), `overig`; null "
    "without a Soort."
)


class WithKindGroup(StrictModel):
    """A paper or case of the Kamer with ``kind_group`` beside its ``kind``."""

    @computed_field(description=KIND_GROUP)  # type: ignore[prop-decorator]
    @property
    def kind_group(self) -> KindGroup | None:
        return kind_group(getattr(self, "kind", None))


class QualifierFields(StrictModel):
    """Which parts of the cited article a reference names: "eerste lid, onder a"."""

    leden: list[str] = Field(
        default_factory=list,
        description="Numbers of the leden named (`['1', '2']`), ranges written out.",
    )
    onderdelen: list[str] = Field(
        default_factory=list,
        description="Letters or numbers of the onderdelen named (`['a']`, `['2']`).",
    )
    aanhef: bool = Field(default=False, description="Whether the aanhef is named.")


class WithSeries(StrictModel):
    """A regulation that is renewed under one name (`Mandaatbesluit DT&V 2020`, `2022`, …):
    each year has a regulation of its own, and these fields bundle them."""

    series_id: str | None = Field(
        None,
        description="The same for every regulation of the series; null for one with no "
        "sibling. A heuristic, not a relation of the BWB (it names no predecessor): "
        "regulations of one kind whose citation titles are equal once their years are "
        "taken out (`series_basis`).",
    )
    series_position: int | None = Field(
        None,
        description="Its place in the series, from 1, by the day it came into force.",
    )
    series_size: int | None = Field(
        None, description="How many regulations the series holds."
    )
    series_basis: str | None = Field(
        None, description="How the series was found: `title_year`."
    )


def series_fields(props: dict[str, Any]) -> dict[str, Any]:
    """The ``WithSeries`` fields of the props of an instrument."""
    return {
        name: props.get(name)
        for name in ("series_id", "series_position", "series_size", "series_basis")
    }


class InstrumentSummaryDTO(WithSeries, WithPath):
    """Short representation of an instrument."""

    path_source = PathSource("instruments")

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
    signed_on: str | None = Field(
        None,
        description="The day the instrument itself was signed (`props.date_signed`): of a "
        "BWB regulation that of the publication that enacted it, of an EU act the day its "
        "title names.",
    )
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
        """Build from a node row, with the counts ``graph-list-stats`` stores."""
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title"),
            citation_title=props.get("citation_title"),
            short_title=props.get("short_title"),
            abbreviation=props.get("abbreviation"),
            display_name=props.get("display_name"),
            signed_on=props.get("date_signed"),
            official_url=instrument_url(props),
            article_count=int(props.get("article_count") or 0),
            inbound_citation_count=int(props.get("inbound_citation_count") or 0),
            judgment_count=None,
            outbound_citation_count=None,
            **series_fields(props),
        )


class ArticleCitationTarget(StrictModel):
    """Minimal metadata describing the referenced article (or judgment)."""

    id: str
    key: str
    collection: Collection
    bwb_id: str | None
    official_id: str | None = Field(None, description=OFFICIAL_ID)
    article_number: str | None
    display_name: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArticleCitationTarget:
        """From the cited article or judgment (a judgment is named by its ECLI when it
        has no display name)."""
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            collection=as_collection(parse_node_id(doc["id"])[0]),
            bwb_id=props.get("bwb_id"),
            official_id=props.get("official_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name") or props.get("ecli"),
        )


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
    definition_ref: str | None = Field(
        default=None,
        description="The definition the regulation gives of a term in the citation's text "
        'that is the regulation cited ("van de wet": its `wet`), as `definitions[].ref`.',
    )

    @classmethod
    def from_entry(
        cls, entry: Any, definition_ref: str | None = None
    ) -> ArticleCitationSpan:
        """Build from an ``ArticleCitationEntry`` (``queries.articles``)."""
        return cls(
            start=entry.start,
            end=entry.end,
            text=entry.text,
            target=ArticleCitationTarget.from_document(entry.target),
            reference_kind=entry.reference_kind,
            confidence=entry.confidence,
            definition_ref=definition_ref,
            **entry.qualifier.to_dict(),
        )


class DefinitionGiverDTO(WithPath):
    """The regulation that gives a definition another regulation takes (it is issued under
    it)."""

    path_source = PathSource("instruments")

    key: str
    bwb_id: str | None = None
    citation_title: str | None = None
    short_title: str | None = None
    abbreviation: str | None = None


class DefinitionDTO(StrictModel):
    """A definition a regulation gives (its begripsbepalingen), as its text has it: its own,
    or one of a regulation it is issued under (``given_by``)."""

    ref: str = Field(
        ..., description="What a span names it by: article, letter and term."
    )
    term: str
    text: str
    article_key: str
    article_number: str | None = None
    place: str | None = Field(
        None,
        description="The letter of its onderdeel: `a`; none in an unmarked list.",
    )
    jci: str | None = None
    scope: dict[str, str] = Field(
        default_factory=dict,
        description="Where it holds: `kind` (`wet`, `besluit`, `hoofdstuk`, …), `path` "
        "(that part, empty for the whole regulation) and `reach`: `own_and_based` where it "
        'holds in the regulations issued under it too ("In deze wet en de daarop berustende '
        'bepalingen"), else `own`.',
    )
    refers_to: str | None = Field(
        None,
        description="The BWB id of the regulation the definition is (`wet`: de "
        "Zorgverzekeringswet).",
    )
    given_by: DefinitionGiverDTO | None = Field(
        None,
        description="The regulation that gives it, where that is not the article's own: a "
        "law or AMvB the regulation is issued under (`BASED_ON`, two levels), whose "
        "definition reaches it (`scope.reach`). Null for its own.",
    )

    @classmethod
    def from_definition(cls, definition: dict[str, Any]) -> DefinitionDTO:
        return cls(ref=definition_ref(definition), **definition)


class TermSpanDTO(StrictModel):
    """Where the text of an article uses a term its regulation defines."""

    start: int
    end: int
    term: str
    definition_ref: str


# What a change does to an article: the relations of a law to a bill or publication, and
# the ``effect`` of an article version that set it (``establishes``).
ArticleChange = Literal["amends", "introduces", "repeals"]
ChangeEffect = Literal["establishes", ArticleChange]


class EchrFindingDTO(StrictModel):
    """What the ECHR found on one article (``core/echr_findings.py``)."""

    article: str = Field(description="The article of the Convention: `8`.")
    protocol: str | None = Field(
        None, description="Of an article of a protocol, its number (`1`); else null."
    )
    combined_with: str | None = Field(
        None, description="The article it is taken together with (`8` of `13+8`)."
    )
    finding: EchrFinding
    aspect: EchrAspect | None = Field(
        None, description="The aspect, when HUDOC names one."
    )
    text: str = Field(
        description='As HUDOC writes it: "No violation of Article 8 - …".'
    )


class JudgmentOutcomeFields(StrictModel):
    """How a judgment ended, what a conclusion proposes and what the ECHR found per article,
    as the decision says it (``core/judgment_outcome.py``, ``core/echr_findings.py``)."""

    outcome: JudgmentOutcome | None = Field(
        None,
        description="How it ended, from the first clause of its decision (Beslissing, "
        "Dictum): `verworpen` (verwerpt het beroep), `vernietigd`, `gedeeltelijk "
        "vernietigd`, `vernietigd en verwezen`, `bekrachtigd`, `bevestigd`, `gegrond`, "
        "`ongegrond`, `niet-ontvankelijk`, `afgewezen`, `toegewezen`, `tussenuitspraak` "
        "(an order to repair a defect, the case is not decided); of the ECHR `schending` "
        "(a violation found) or `geen schending`. Null for a conclusion, and when the "
        "decision does not say one of them first (a conviction).",
    )
    outcome_text: str | None = Field(
        None,
        description='The clause that says it, as the decision writes it: "verwerpt het '
        'beroep", "vernietigt de aangevallen uitspraak"; of the ECHR the finding.',
    )
    conclusion_outcome: ConclusionOutcome | None = Field(
        None,
        description="Of a conclusion of the A-G or P-G, what it proposes (its strekking): "
        "`verwerping`, `vernietiging`, `vernietiging en verwijzing`, "
        "`niet-ontvankelijkverklaring`, `gegrondverklaring`, `ongegrondverklaring`, "
        "`beantwoording` (of preliminary questions); null for a judgment and when the "
        "conclusion does not say it.",
    )
    conclusion_outcome_text: str | None = Field(
        None,
        description='The sentence that says it: "De conclusie strekt tot verwerping van '
        'het cassatieberoep."',
    )
    echr_findings: list[EchrFindingDTO] = Field(
        default_factory=list,
        description="Of the ECHR, what it found per article, in the order of HUDOC; empty "
        "for any other judgment.",
    )


def judgment_outcome_fields(values: dict[str, Any]) -> dict[str, Any]:
    """The ``JudgmentOutcomeFields`` of a judgment with these props (or light props)."""
    return {
        "outcome": values.get("outcome"),
        "outcome_text": values.get("outcome_text"),
        "conclusion_outcome": values.get("conclusion_outcome"),
        "conclusion_outcome_text": values.get("conclusion_outcome_text"),
        "echr_findings": [
            EchrFindingDTO(**finding) for finding in values.get("echr_findings") or []
        ],
    }


def regulation_kind(props: dict[str, Any]) -> str | None:
    """The BWB type of a regulation, lower case: ``amvb``, ``ministeriele-regeling``."""
    kind = props.get("kind")
    return kind.lower() if isinstance(kind, str) else None


class _Regulation(Protocol):
    @property
    def kind(self) -> str | None: ...

    @property
    def instrument(self) -> InstrumentSummaryDTO: ...


def in_regulation_order[Regulation: _Regulation](
    items: Iterable[Regulation],
) -> list[Regulation]:
    """Regulations issued under a law or an article in their order
    (``core.delegations.regulation_order``)."""
    return sorted(
        items,
        key=lambda item: regulation_order(
            item.kind,
            item.instrument.citation_title or item.instrument.title,
            item.instrument.key,
        ),
    )


CITE = (
    "The judgment as a lawyer cites it: `short` `HR 20 december 2019`, `Rb. Den Haag 6 "
    "december 2019`, `Conclusie A-G Hartlief 20 december 2019` (`P-G` where a "
    "procureur-generaal signed it), `HvJ EU 22 juni 2023, C-160/20` (a court of the "
    "Union with its case number); `full` with its ECLI. Null without an ECLI."
)


class JudgmentCiteDTO(StrictModel):
    """A judgment as a lawyer cites it (``core.judgment_cite``)."""

    short: str = Field(
        description="The court, the author of a conclusion and the day: "
        "`HR 20 december 2019`."
    )
    full: str = Field(
        description="`short` with the ECLI: `HR 20 december 2019, ECLI:NL:HR:2019:2006`."
    )


def judgment_cite_dto(props: dict[str, Any]) -> JudgmentCiteDTO | None:
    """``CITE`` of a judgment from its props (``core.judgment_cite.cite_of``)."""
    cite = cite_of(props)
    return JudgmentCiteDTO(short=cite.short, full=cite.full) if cite else None


class WithCite(StrictModel):
    """A judgment with ``cite``."""

    cite: JudgmentCiteDTO | None = Field(default=None, description=CITE)


class JudgmentSummaryDTO(WithCite, WithPath):
    """Lightweight judgment summary for listing matches."""

    path_source = PathSource("judgments")

    id: str
    key: str
    display_name: str | None
    ecli: str | None

    @classmethod
    def fields_of(cls, doc: dict[str, Any]) -> dict[str, Any]:
        props = doc.get("props") or {}
        return {
            "id": doc["id"],
            "key": doc["key"],
            "display_name": props.get("display_name"),
            "ecli": props.get("ecli"),
            "cite": judgment_cite_dto(props),
        }

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentSummaryDTO:
        return cls(**JudgmentSummaryDTO.fields_of(doc))


class ArticleRelationDTO(WithPath):
    """Article reference plus optional parent instrument used in judgment responses."""

    path_source = PathSource("articles")

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
            id=article_doc["id"],
            key=article_doc["key"],
            display_name=article_cite(props) or None,
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            article_number=props.get("article_number"),
            instrument=instrument,
        )


class DossierNameDTO(StrictModel):
    """The names of a dossier next to its bare number, as ``/api/dossiers`` gives them;
    null when no dossier has the number."""

    number: str
    short_title: str | None = Field(
        None,
        description="The name it goes by: ``Begroting Defensie 2027``, the short title of "
        "a bill (``Wet betaalbare huur``).",
    )
    title: str | None = None


def dossier_names_of(
    numbers: Iterable[Any], names: dict[str, dict[str, Any]]
) -> list[DossierNameDTO]:
    """The ``DossierNameDTO`` of each of *numbers* in their order, once each, from *names*
    (``load_dossier_names``)."""
    seen: dict[str, DossierNameDTO] = {}
    for number in numbers:
        text = str(number or "").strip()
        if text and text not in seen:
            seen[text] = DossierNameDTO(**(names.get(text) or {"number": text}))
    return list(seen.values())


class DossierRefDTO(WithPath):
    """Reference to a Kamerstukdossier by number; ``title`` is null when unknown."""

    path_source = PathSource("dossiers")

    number: str
    key: str
    title: str | None = None
    short_title: str | None = Field(
        None, description="The name it goes by, as ``/api/dossiers`` gives it."
    )
    exists: bool = Field(
        ...,
        description="Whether the data holds the dossier. A publication can name one "
        "it does not (an old dossier, before the Tweede Kamer's open data): then "
        "``id`` and ``path`` are null.",
    )

    @computed_field(  # type: ignore[prop-decorator]
        description="Its node id (``dossiers/36600_viii``); null when the data does "
        "not hold it."
    )
    @property
    def id(self) -> str | None:
        return node_id(COLLECTION_DOSSIERS, self.key) if self.exists else None

    @classmethod
    def from_number(cls, number: Any, titles: dict[str, str | None]) -> DossierRefDTO:
        """Build from a dossier number and the ``key -> title`` of the dossiers the
        data holds (``get_dossier_titles``)."""
        text = str(number)
        key = make_node_key(text)
        title = titles.get(key)
        return cls(
            number=text,
            key=key,
            title=title,
            short_title=short_title(title),
            exists=key in titles,
        )


class PublicationDTO(StrictModel):
    """An amending publication (Staatsblad, Tractatenblad, ...) as recorded on a version."""

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
        titles: dict[str, str | None],
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


class FacetCountDTO(StrictModel):
    """One value of a facet and how many items have it under the current filters."""

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
