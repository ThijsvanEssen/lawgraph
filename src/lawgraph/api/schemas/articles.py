"""Article endpoints: detail with its relationships, legislative history, explanatory
documents and version history."""

from __future__ import annotations

from typing import Any, Literal, NamedTuple

from pydantic import Field, computed_field

from lawgraph.api.schemas.common import (
    ARTICLE_ADDRESS,
    OFFICIAL_ID,
    SEMANTIC_CONFIDENCE,
    SEMANTIC_PATTERN,
    VALID_UNTIL,
    ArticleCitationSpan,
    ArticleRelationDTO,
    ChangeEffect,
    DefinitionDTO,
    InstrumentSummaryDTO,
    JudgmentOutcomeFields,
    PathSource,
    PublicationDTO,
    QualifierFields,
    StrictModel,
    TermSpanDTO,
    WithCite,
    WithKindGroup,
    WithPath,
    address_of,
    judgment_cite_dto,
    judgment_outcome_fields,
    regulation_kind,
    scope_type_of,
    semantic_fields,
)
from lawgraph.api.schemas.documents import (
    DocumentOrigin,
    PassageDTO,
    origin_fields,
    sender_of,
)
from lawgraph.api.schemas.dossiers import DocumentEntryDTO
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    SCOPE_TYPE_FIXED,
    Relation,
    as_relation,
)
from lawgraph.core.bwb_xml import effect_kind
from lawgraph.core.delegations import (
    BasisKind,
    DelegationClause,
    DelegationKind,
    basis_qualifier,
)
from lawgraph.core.display import shorten
from lawgraph.core.documents import number_in_dossier, numbered_in
from lawgraph.core.mentions import Mention
from lawgraph.core.models import node_id, parse_node_id
from lawgraph.core.names import article_cite
from lawgraph.core.official_urls import (
    OFFICIELE_BEKENDMAKINGEN,
    article_url,
    enacting_publication_url,
)
from lawgraph.core.qualifiers import Qualifier
from lawgraph.core.reference_targets import ReferenceCollection, reference_target
from lawgraph.core.time import strip_time_component
from lawgraph.core.tk_links import tk_url
from lawgraph.core.xml import collapse_ws

ExplanationTarget = Literal["article", "article_version"]
ExplanationScope = Literal["dossier", "article"]

_TARGET_OF_COLLECTION: dict[str, ExplanationTarget] = {
    COLLECTION_ARTICLES: "article",
    COLLECTION_ARTICLE_VERSIONS: "article_version",
}


class ArticlePartSpanDTO(StrictModel):
    """A lid, an onderdeel, an aanhef or a tekst of an article, as a span of its `text`.

    The parts and the printed numbers between them cover the whole text."""

    id: str = Field(
        description="Where the part sits: `aanhef`, `lid-2`, `lid-2-aanhef`, `lid-2-onder-a`, "
        "`onder-a` (an article without leden), `lid-2-onder-a-onder-1` (an onderdeel "
        "inside an onderdeel), `onder-_39-onder-a` (inside an unmarked onderdeel), `tekst-1` "
        "(a paragraph outside the other parts, such as a line between the lists of an "
        "article of a bijlage), `tekst-6-onder-a` (in the list a definition paragraph "
        "leads). Unique within the article."
    )
    kind: str = Field(description="`aanhef`, `lid`, `onderdeel` or `tekst`.")
    number: str | None = Field(
        description="The number as printed: `2`, `2a`, `a`, `1°`; null for an aanhef "
        "or an item without one."
    )
    start: int = Field(
        description="Offset of the part in the `text` of the article; a part with "
        "onderdelen spans them too."
    )
    end: int
    term: str | None = Field(
        None,
        description="The term a definition without a letter or digit defines (an unmarked "
        "onderdeel, a tekst), as its `<nadruk>` gives it; it is cited by it: `art. 1, "
        "definitie van 'netwerk- en informatiesysteem', onder a`. Null elsewhere.",
    )


class ArticlePartDTO(ArticlePartSpanDTO):
    """A part of an article with its content."""

    text: str = Field(
        description="The content without its number: `text[start:end]` of the article."
    )


def parts_from_props(props: dict[str, Any]) -> list[ArticlePartDTO]:
    """The parts stored on an article or version, with their text cut from `props.text`.

    Entries that do not fit the text are left out rather than failing the response.
    """
    text = props.get("text")
    stored = props.get("parts")
    if not isinstance(text, str) or not isinstance(stored, list):
        return []
    parts: list[ArticlePartDTO] = []
    for part in stored:
        if not isinstance(part, dict):
            continue
        start, end = part.get("start"), part.get("end")
        if not (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(text)
        ):
            continue
        parts.append(
            ArticlePartDTO(
                id=str(part.get("id") or ""),
                kind=str(part.get("kind") or ""),
                number=part.get("number"),
                term=part.get("term"),
                text=text[start:end],
                start=start,
                end=end,
            )
        )
    return parts


class ArticleCellSpanDTO(StrictModel):
    """A cell of a table that spans more than one column or row."""

    row: int = Field(description="Its row, counted from 0.")
    cell: int = Field(description="Its place among the cells of that row, from 0.")
    cols: int = Field(description="How many columns it covers.")
    rows: int = Field(description="How many rows it covers.")


class ArticleTableDTO(StrictModel):
    """A table in the text of an article, as a span of its `text`: a row a line, its cells
    separated by a tab (an empty cell an empty string)."""

    start: int = Field(
        description="Offset of its first row in the `text` of the article."
    )
    end: int
    head_rows: int = Field(description="How many of its first rows are its header.")
    columns: int = Field(
        description="How many columns it has; a row next to a cell that spans rows, or "
        "whose last cells are empty, has fewer cells."
    )
    spans: list[ArticleCellSpanDTO] = Field(
        default_factory=list, description="Its cells that span columns or rows."
    )


def tables_from_props(props: dict[str, Any]) -> list[ArticleTableDTO]:
    """The tables stored on an article or version; one that does not fit the text is left
    out rather than failing the response."""
    text = props.get("text")
    stored = props.get("tables")
    if not isinstance(text, str) or not isinstance(stored, list):
        return []
    return [
        ArticleTableDTO.model_validate(table)
        for table in stored
        if isinstance(table, dict)
        and isinstance(table.get("start"), int)
        and isinstance(table.get("end"), int)
        and 0 <= table["start"] < table["end"] <= len(text)
    ]


class ArticleHeadingDTO(StrictModel):
    """A heading in the text of an article on a line of its own (a `<tussenkop>`, the title
    of a table), as a span of its `text`."""

    start: int = Field(
        description="Offset of the heading in the `text` of the article."
    )
    end: int


def headings_from_props(props: dict[str, Any]) -> list[ArticleHeadingDTO]:
    """The headings stored on an article or version; one that does not fit the text is left
    out rather than failing the response."""
    text = props.get("text")
    stored = props.get("headings")
    if not isinstance(text, str) or not isinstance(stored, list):
        return []
    return [
        ArticleHeadingDTO.model_validate(heading)
        for heading in stored
        if isinstance(heading, dict)
        and isinstance(heading.get("start"), int)
        and isinstance(heading.get("end"), int)
        and 0 <= heading["start"] < heading["end"] <= len(text)
    ]


class DelegationClauseDTO(StrictModel):
    """A delegation formula in the text of an article ("bij of krachtens algemene maatregel
    van bestuur"), as a span of its `text`."""

    start: int = Field(
        description="Offset of the formula in the `text` of the article."
    )
    end: int
    text: str
    kind: DelegationKind = Field(
        description="`amvb` (bij algemene maatregel van bestuur) or "
        "`ministeriele_regeling` (bij ministeriële regeling, bij regeling van Onze "
        "Minister)."
    )
    krachtens: bool = Field(
        description="`bij of krachtens`: the regulation may delegate further."
    )
    part: str | None = Field(
        description="The `id` of the innermost part it stands in (`lid-1`, "
        "`lid-2-onder-a`); null for an article without parts."
    )
    lid: str | None = Field(description="The number of the lid it stands in.")

    @classmethod
    def fields_of(cls, clause: DelegationClause) -> dict[str, Any]:
        return {
            "start": clause.start,
            "end": clause.end,
            "text": clause.text,
            "kind": clause.kind,
            "krachtens": clause.krachtens,
            "part": clause.part,
            "lid": clause.lid,
        }

    @classmethod
    def from_clause(cls, clause: DelegationClause) -> DelegationClauseDTO:
        return cls(**DelegationClauseDTO.fields_of(clause))


class ReferenceTargetDTO(StrictModel):
    """The node a reference names, and whether the data holds it."""

    collection: ReferenceCollection
    key: str
    exists: bool = Field(
        description="Whether the data holds the node: a regulation, an EU act or an "
        "article that is not loaded is named all the same."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return node_id(self.collection, self.key)


class ArticleReferenceDTO(QualifierFields):
    """A reference the text of an article makes: a link of the BWB XML to an article or a
    division of a regulation, to an annex, or to an EU act."""

    kind: str = Field(
        description="`intref` (a link inside the regulation) or `extref` (to another)."
    )
    bwb_id: str | None = Field(
        description="The regulation linked to; null for an EU act."
    )
    article: str | None = Field(
        description="Number of the article referred to; null for a reference to a chapter, "
        "a title, an annex or an EU act."
    )
    celex: str | None = Field(None, description="The CELEX number of an EU act.")
    doc: str = Field(
        description="The JCI string or CELEX number of the link, as the XML has it; empty "
        "for a link to an annex."
    )
    text: str
    start: int = Field(description="Offset of `text` in the text of the article.")
    end: int
    target: ReferenceTargetDTO | None = Field(
        None,
        description="What the link names: the article; the regulation of a link to a "
        "chapter or a title; the annex; the EU act. Null when it names none of these.",
    )


def references_from_props(
    props: dict[str, Any], present: set[tuple[str, str]]
) -> list[ArticleReferenceDTO]:
    """The references stored on an article, in text order, each with its target and
    whether it is among the ``(collection, key)`` the data holds (*present*)."""
    stored = props.get("references")
    if not isinstance(stored, list):
        return []
    references = []
    for ref in stored:
        if not isinstance(ref, dict):
            continue
        target = reference_target(ref)
        references.append(
            ArticleReferenceDTO(
                kind=str(ref.get("kind") or ""),
                bwb_id=ref.get("bwb_id"),
                article=ref.get("article"),
                celex=ref.get("celex"),
                doc=str(ref.get("doc") or ""),
                text=str(ref.get("text") or ""),
                start=int(ref.get("start") or 0),
                end=int(ref.get("end") or 0),
                target=ReferenceTargetDTO(
                    collection=target[0], key=target[1], exists=target in present
                )
                if target
                else None,
                **Qualifier.from_dict(ref).to_dict(),
            )
        )
    return sorted(references, key=lambda ref: (ref.start, ref.end))


class ArticleSummaryDTO(WithPath):
    """Summary of an article: its identifiers and text."""

    path_source = PathSource("articles")

    id: str
    key: str
    bwb_id: str | None
    official_id: str | None = Field(None, description=OFFICIAL_ID)
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
    repealed: bool = False
    display_name: str | None
    official_url: str | None = Field(
        None,
        description="The article in force on wetten.overheid.nl (its JCI); the "
        "regulation for an article without a number the JCI can address.",
    )
    text: str | None
    parts: list[ArticlePartDTO] = Field(
        default_factory=list,
        description="Aanhef, leden and onderdelen as spans of `text`; empty when the "
        "article has no structure or was normalized before parts existed.",
    )
    tables: list[ArticleTableDTO] = Field(
        default_factory=list, description="The tables in `text`, as spans of it."
    )
    headings: list[ArticleHeadingDTO] = Field(
        default_factory=list, description="The headings in `text`, as spans of it."
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
    ) -> ArticleSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            official_id=props.get("official_id"),
            article_number=props.get("article_number"),
            label=props.get("label"),
            heading=props.get("heading"),
            address=address_of(doc),
            repealed=bool(props.get("repealed")),
            display_name=article_cite(props) or None,
            official_url=article_url(props.get("bwb_id"), props.get("article_number"))
            or enacting_publication_url(props.get("official_id")),
            text=props.get("text"),
            parts=parts_from_props(props),
            tables=tables_from_props(props),
            headings=headings_from_props(props),
        )


class ArticleRelationshipWithType(QualifierFields):
    """An article-to-article relationship enriched with its semantic layer."""

    edge_id: str
    relation: Relation
    target_article: ArticleRelationDTO
    semantic_type: str | None = None
    explanation: str | None = Field(
        default=None,
        description="What `semantic_type` rests on: the trigger phrase and where it stood.",
    )
    confidence: float | None = Field(
        default=None,
        description="That the reference exists: 1.0 for a link of the BWB XML.",
    )
    semantic_confidence: float | None = Field(
        default=None, description=SEMANTIC_CONFIDENCE
    )
    semantic_pattern: str | None = Field(default=None, description=SEMANTIC_PATTERN)
    start: int | None = Field(
        None,
        description="Offset of the reference in the text of the referring article.",
    )
    end: int | None = None
    text: str | None = Field(None, description="The text of the reference.")
    reference_kind: str | None = Field(
        default=None, description="`intref` or `extref`, as on the reference itself."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleRelationshipWithType:
        """Build from a {edge, target, instrument} query row."""
        edge = row.get("edge") or {}
        meta: dict[str, Any] = edge.get("meta") or {}
        start, end, text = meta.get("start"), meta.get("end"), meta.get("text")
        return cls(
            edge_id=edge.get("key") or "",
            relation=as_relation(edge["relation"]),
            target_article=ArticleRelationDTO.from_documents(
                row["target"], row.get("instrument")
            ),
            semantic_type=edge.get("semantic_type"),
            explanation=edge.get("explanation"),
            confidence=edge.get("confidence"),
            **semantic_fields(edge),
            start=start if isinstance(start, int) else None,
            end=end if isinstance(end, int) else None,
            text=text if isinstance(text, str) else None,
            reference_kind=meta.get("reference_kind"),
            **Qualifier.from_dict(meta).to_dict(),
        )


class SuccessionPartDTO(StrictModel):
    """A part of the old article and its place in the new law, as the source writes it."""

    old_part: str = Field(
        description="The part of the old article as the source writes it: `2`, `2 a`, "
        "`eerste lid`; empty for the whole article."
    )
    new_place: str = Field(
        description="Its place in the new law as the source writes it: `2.8.6, 1`, "
        "`algemene regeling 2.1.10`."
    )
    new_article: str | None = Field(
        None,
        description="The number of the article of the new law it is placed in (`2.8.6`): "
        "that of `article` of a successor, the article itself of a predecessor.",
    )
    new_leden: list[str] = Field(
        default_factory=list,
        description="The leden of that article `new_place` names (`2`); empty for the "
        "whole article.",
    )


class ArticleSuccessionDTO(StrictModel):
    """The other article of a recodification (``TRANSPOSED_TO``): the article of the new law
    that takes this one's place, or the article of the old law whose place this one takes."""

    article: ArticleRelationDTO
    in_force: bool | None = Field(
        None,
        description="Whether the law of `article` is in force: false for a new law that is "
        "enacted and not in force yet.",
    )
    status: str | None = Field(
        None, description="The status of the law of `article`: `vastgesteld`, …"
    )
    parts: list[SuccessionPartDTO] = Field(
        default_factory=list,
        description="Each part of the old article the source places in the new article.",
    )
    basis: str | None = Field(
        None, description="What the link rests on: `transposition_table`."
    )
    source: str | None = Field(
        None,
        description="The identifier of the source: `blg-1081574`, `kst-34986-3`.",
    )
    source_url: str | None = Field(
        None, description="The source on zoek.officielebekendmakingen.nl."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleSuccessionDTO:
        """Build from an {edge, target, instrument} query row."""
        meta: dict[str, Any] = (row.get("edge") or {}).get("meta") or {}
        law = (row.get("instrument") or {}).get("props") or {}
        source = meta.get("source")
        return cls(
            article=ArticleRelationDTO.from_documents(
                row["target"], row.get("instrument")
            ),
            in_force=law.get("in_force")
            if isinstance(law.get("in_force"), bool)
            else None,
            status=law.get("status"),
            parts=[
                SuccessionPartDTO(
                    old_part=str(p.get("from") or ""),
                    new_place=str(p.get("to") or ""),
                    new_article=p.get("article"),
                    new_leden=[str(n) for n in p.get("leden") or []],
                )
                for p in meta.get("parts") or []
                if isinstance(p, dict)
            ],
            basis=meta.get("basis"),
            source=source,
            source_url=OFFICIELE_BEKENDMAKINGEN.format(identifier=source)
            if source
            else None,
        )


class ScopeArticleReference(StrictModel):
    """Annex that scopes the applicability of an article."""

    annex_id: str
    annex_key: str
    display_name: str | None = None
    annex_entries: list[str] = Field(default_factory=list)
    scope_type: str = SCOPE_TYPE_FIXED
    explanation: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ScopeArticleReference:
        """Build from an {edge, annex} query row."""
        edge = row.get("edge") or {}
        meta = edge.get("meta") or {}
        annex = row.get("annex") or {}
        props = annex.get("props") or {}
        entries = [
            str(e.get("name"))
            for e in (props.get("entries") or [])
            if isinstance(e, dict) and e.get("name")
        ]
        return cls(
            annex_id=annex.get("id") or "",
            annex_key=annex.get("key") or "",
            display_name=props.get("display_name"),
            annex_entries=entries,
            scope_type=scope_type_of(meta),
            explanation=edge.get("explanation"),
        )


class ArticleDetailResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}."""

    article: ArticleSummaryDTO
    instrument: InstrumentSummaryDTO | None
    citations: list[ArticleCitationSpan] = Field(default_factory=list)
    term_spans: list[TermSpanDTO] = Field(
        default_factory=list,
        description="Every place the text uses a term its regulation defines (where that "
        "definition holds: its regulation, or its chapter or paragraph), or a law or AMvB "
        "it is issued under defines for the regulations based on it (its own first), as "
        "`definitions`; not inside a citation, which names the definition itself "
        "(`definition_ref`) when it is the regulation cited.",
    )
    definitions: list[DefinitionDTO] = Field(
        default_factory=list,
        description="The definitions `term_spans` and `citations` name, as the regulation "
        "gives them (`given_by` for one of another).",
    )
    references: list[ArticleReferenceDTO] = Field(
        default_factory=list,
        description="Every reference the text of the article makes, as stored on it, "
        "whether or not the target is in the graph. `citations` holds the resolved ones, "
        "one per target.",
    )
    delegations: list[DelegationClauseDTO] = Field(
        default_factory=list,
        description="The delegation formulas in the text, in text order; empty when the "
        "article delegates nothing. `.../delegated` lists the regulations issued under "
        "the article, per formula.",
    )
    metadata: dict[str, Any] | None
    upstream_dependencies: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    downstream_implications: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    scope_articles: list[ScopeArticleReference] = Field(default_factory=list)
    successors: list[ArticleSuccessionDTO] = Field(
        default_factory=list,
        description="In the new law: the articles that take this article's place in a "
        "recodification (`TRANSPOSED_TO`), as an official source gives them.",
    )
    predecessors: list[ArticleSuccessionDTO] = Field(
        default_factory=list,
        description="Formerly: the articles of the old law whose place this article takes "
        "(`TRANSPOSED_TO` read backwards).",
    )


BASIS_KIND = (
    "`delegates`: the leden named (none: the whole article) give the power the regulation "
    'is made under (a delegation formula, "bij besluit van", "kan regels stellen"); '
    "`mentioned`: the article is only named in the preamble (Awb 3:4 by a policy rule); "
    "null: not known (an article without text)."
)


def basis_kind_of(meta: dict[str, Any]) -> BasisKind | None:
    """The ``basis_kind`` of the meta of a ``BASED_ON`` edge."""
    kind = meta.get("basis_kind")
    if kind == "delegates":
        return "delegates"
    return "mentioned" if kind == "mentioned" else None


class DelegatedArticleDTO(QualifierFields):
    """An article of a regulation issued under the article that refers to it, with the
    leden and onderdelen of the article it names."""

    id: str
    key: str
    article_number: str | None
    display_name: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DelegatedArticleDTO:
        return cls(
            id=row["id"],
            key=row["key"],
            article_number=row.get("article_number"),
            display_name=row.get("display_name"),
            **Qualifier.from_dict(row.get("meta")).to_dict(),
        )


class DelegatedRegulationDTO(QualifierFields):
    """A regulation whose preamble ("Gelet op") names the article as its legal basis, with
    the leden and onderdelen of the article it names (none: the whole article)."""

    instrument: InstrumentSummaryDTO
    kind: str | None = Field(
        description="Its BWB type, lower case: `amvb`, `ministeriele-regeling`, `kb`, …"
    )
    date_in_force: str | None = Field(
        None, description="When the regulation itself entered into force."
    )
    text: str | None = Field(
        description="The reference in its preamble: `16, eerste en zevende lid`."
    )
    basis_kind: BasisKind | None = Field(None, description=BASIS_KIND)
    articles: list[DelegatedArticleDTO] = Field(
        default_factory=list,
        description="Its articles that refer to the article, in the order of the "
        "regulation.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DelegatedRegulationDTO:
        """From a row of ``get_delegated_regulations``."""
        instrument = row["instrument"]
        props = instrument.get("props") or {}
        meta = row.get("meta") or {}
        text = meta.get("text") if isinstance(meta.get("text"), str) else None
        return cls(
            instrument=InstrumentSummaryDTO.from_document(instrument),
            kind=regulation_kind(props),
            date_in_force=props.get("date_in_force"),
            text=text,
            basis_kind=basis_kind_of(meta),
            articles=[
                DelegatedArticleDTO.from_row(a) for a in row.get("articles") or []
            ],
            **basis_qualifier(text).to_dict(),
        )


class DelegatedClauseDTO(DelegationClauseDTO):
    """A delegation formula with the regulations that fill it."""

    instruments: list[str] = Field(
        default_factory=list,
        description="The `key` of every item that fills it: of a type the formula names "
        "(an AMvB; with `krachtens` also a ministerial regulation) and naming its lid or "
        "no lid. Empty: no regulation is issued under it yet.",
    )


class ArticleDelegatedResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/delegated."""

    article_id: str
    clauses: list[DelegatedClauseDTO] = Field(
        default_factory=list,
        description="The delegation formulas of the article (as `delegations` of the "
        "article), each with the regulations that fill it.",
    )
    items: list[DelegatedRegulationDTO] = Field(
        default_factory=list,
        description="Every regulation in force issued under the article: AMvBs first, then "
        "ministerial regulations, then the others; by title.",
    )
    total: int


class CitedByJudgment(JudgmentOutcomeFields, WithCite, WithPath):
    """The judgment of a passage that cites an article, with how it ended."""

    path_source = PathSource("judgments")

    id: str
    key: str
    ecli: str | None
    court: str | None = Field(description="ECLI court code, `HR`, `RBAMS`.")
    tier: str | None = Field(
        description="The tier, the Type of the court in the Instanties value list: "
        "`hoge_raad`, `raad_van_state`, `parket`, `gerechtshof`, `rechtbank`, "
        "`andere_instantie`, … (`/api/stats/coverage` lists those present).",
    )
    court_kind: str | None = Field(
        default=None,
        description="The kind of court within the tier (`ambtenarengerecht`; a tier of "
        "one kind of court is its own kind).",
    )
    date: str | None = Field(description="Date of the judgment, YYYY-MM-DD.")
    display_name: str | None
    inbound_citation_count: int | None = Field(
        default=None,
        description="The judgments that cite it, or another publication of the same "
        "decision, each once (as in `/api/judgments`): a standard judgment has many.",
    )


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


class ArticleCitedByItem(QualifierFields):
    """One passage of a judgment that cites the article. `leden`, `onderdelen` and
    `aanhef` say what the passage names of it."""

    judgment: CitedByJudgment
    paragraph_id: str = Field(
        description="The paragraph, as `paragraph_id` of `/api/judgments/{ecli}`."
    )
    paragraph_number: str | None = Field(
        description="Its printed number (`5.3`), null when it has none."
    )
    qualifier: str | None = Field(
        description="The qualifier as the judgment wrote it, `derde lid`."
    )
    start: int = Field(
        description="Offset of the citation in the text of the paragraph."
    )
    end: int
    text: str = Field(description="The citation as written: `text[start:end]`.")
    snippet: str = Field(description="The text of the paragraph around the citation.")
    confidence: float

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleCitedByItem | None:
        """Build from a `{judgment, mention}` row; None when the mention is malformed."""
        mention = Mention.from_dict(row.get("mention"))
        if mention is None:
            return None
        doc = row["judgment"]
        props = doc.get("props") or {}
        return cls(
            judgment=CitedByJudgment(
                id=doc["id"],
                key=doc["key"],
                ecli=props.get("ecli"),
                court=props.get("court_code"),
                tier=props.get("tier"),
                court_kind=props.get("court_kind"),
                date=props.get("date_eff"),
                display_name=props.get("display_name"),
                inbound_citation_count=_count(props.get("inbound_citation_count")),
                cite=judgment_cite_dto(props),
                **judgment_outcome_fields(props),
            ),
            paragraph_id=mention.paragraph_id,
            paragraph_number=mention.paragraph_number,
            qualifier=mention.qualifier,
            start=mention.start,
            end=mention.end,
            text=mention.raw_match,
            snippet=mention.snippet,
            confidence=mention.confidence,
            **mention.parts.to_dict(),
        )


class ArticleCitedByResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/cited-by."""

    article_id: str
    items: list[ArticleCitedByItem]
    total: int = Field(
        description="Every passage that matches the filters, independent of `limit`."
    )
    judgment_total: int = Field(
        description="The judgments those passages are in: a judgment that cites the "
        "article in three places is three passages and one judgment."
    )
    echr_judgment_total: int = Field(
        default=0,
        description="The ECHR judgments that cite the article, whatever the filters. "
        "HUDOC names the articles a judgment applies, not the passage, so they are no "
        "row of `items`; `GET /api/instruments/{identifier}/eu-links` lists them "
        "(`international`).",
    )


class LegislativeHistoryEntry(StrictModel):
    """One change of an article in one dossier: the dossier, and the amending publication
    (enacted) or the bill (proposed) that made or proposes the change."""

    dossier_id: str | None = Field(
        None,
        description="Node id (``collection/key``) of the dossier; null when the "
        "publication names a dossier that is not in the graph.",
    )
    dossier_number: str
    dossier_title: str | None = None
    dossier_short_title: str | None = Field(
        None,
        description="The name the dossier goes by (``Cyberbeveiligingswet``), as "
        "``/api/dossiers`` gives it; null without one.",
    )
    date: str | None = Field(
        None, description="Of the bill, or the publication date of the publication."
    )
    kind: str | None = Field(
        None,
        description="Document kind of a bill, publication kind (`Stb`) of a publication.",
    )
    change: ChangeEffect = Field(
        ...,
        description="`establishes`: the publication that enacted the regulation set the "
        "article; else the change it made or a bill proposes.",
    )
    status: str | None = Field(
        None, description="`canoniek` (enacted) or `voorgesteld` (proposed)."
    )
    summary: str | None = None
    document_id: str = Field(
        ..., description="Node id (``collection/key``) of the publication or the bill."
    )


class ArticleLegislativeHistoryResponse(StrictModel):
    """Legislative history for an article."""

    article_id: str
    entries: list[LegislativeHistoryEntry]
    total: int


class ExplainingDocumentDTO(WithKindGroup, DocumentOrigin, WithPath):
    """The explanatory document of an explanation."""

    path_source = PathSource("documents")

    id: str = Field(..., description="Node id (``collection/key``) of the document.")
    key: str
    kind: str | None = None
    title: str | None = None
    date: str | None = None
    dossier_number: str | None = Field(
        None,
        description="The dossier the document is PART_OF (the lowest, if several).",
    )
    sequence: int | None = Field(
        None, description="Its number in its own dossier (nr. 3); null for none."
    )


# The length an excerpt of a passage is cut to.
EXCERPT_CHARS = 300


def passage_excerpt(opening: Any, heading: str | None) -> str | None:
    """The opening of a passage without its heading, in one line of at most
    ``EXCERPT_CHARS`` characters, cut at a word with an ellipsis; None without text."""
    if not isinstance(opening, str):
        return None
    first, _, rest = opening.partition("\n")
    if heading and collapse_ws(first) == collapse_ws(heading):
        opening = rest
    return shorten(collapse_ws(opening), EXCERPT_CHARS) or None


class ArticleExplanationDTO(StrictModel):
    """One document that explains an article, and the node its EXPLAINS edge points at."""

    document: ExplainingDocumentDTO
    target: ExplanationTarget = Field(
        ...,
        description=(
            "What the edge points at: the 'article' or one of its versions "
            "('article_version'). An explanation of the article's law as a whole is "
            "none of this article, and is not listed."
        ),
    )
    target_id: str = Field(
        ..., description="Node id (``collection/key``) of the node the edge points at."
    )
    article_version_key: str | None = Field(
        None,
        description="Key of the article version; null unless target is 'article_version'.",
    )
    confidence: float | None = None
    scope: ExplanationScope = Field(
        ...,
        description=(
            "'dossier': the document explains the changes of a whole dossier, not "
            "this article in particular (the memorandum is not tied to a passage). "
            "'article': the edge names the section that explains the article, "
            "in ``section_anchor``."
        ),
    )
    section_anchor: str | None = Field(
        None,
        description="`id` of the section in `sections` of the document; set when scope "
        "is 'article'.",
    )
    heading: str | None = Field(
        None,
        description="The heading of that section: ``Artikel 21 (zorgplicht)``; null "
        "when scope is 'dossier'.",
    )
    char_start: int | None = Field(
        None, description="Where the section starts in the `text` of the document."
    )
    char_end: int | None = Field(
        None, description="Where it ends (exclusive): `text[char_start:char_end]`."
    )
    excerpt: str | None = Field(
        None,
        description="The opening of the section after its heading, about 300 "
        "characters cut at a word (`…` when it goes on); null without a section or "
        "without the text.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleExplanationDTO:
        """Build from a row of ``get_article_explanations``."""
        collection, key = parse_node_id(row["target_id"])
        target = _TARGET_OF_COLLECTION[collection]
        section_anchor = row.get("section_anchor") or None
        paper = row.get("paper") or {}
        sequence = paper.get("sequence")
        heading = row.get("heading") if isinstance(row.get("heading"), str) else None
        return cls(
            document=ExplainingDocumentDTO(
                id=row["document_id"],
                key=row["key"],
                kind=row.get("kind") or None,
                title=row.get("title") or None,
                date=strip_time_component(row.get("date")),
                dossier_number=row.get("dossier_number"),
                sequence=sequence if isinstance(sequence, int) else None,
                path_props=paper,
                **origin_fields(row.get("labels"), row.get("source"), row.get("kind")),
            ),
            heading=heading if section_anchor else None,
            char_start=row.get("char_start") if section_anchor else None,
            char_end=row.get("char_end") if section_anchor else None,
            excerpt=(
                passage_excerpt(row.get("opening"), heading) if section_anchor else None
            ),
            target=target,
            target_id=row["target_id"],
            article_version_key=key if target == "article_version" else None,
            confidence=row.get("confidence"),
            scope="article" if section_anchor else "dossier",
            section_anchor=section_anchor,
        )


class ArticleExplanationsResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/explained-by."""

    article_id: str
    total: int = Field(
        ..., description="All explanations, independent of ``limit`` and ``offset``."
    )
    items: list[ArticleExplanationDTO]


class ArticlePassagesDTO(StrictModel):
    """A paper that explains an article in a passage, and its passages."""

    document: DocumentEntryDTO
    target: ExplanationTarget = Field(
        ...,
        description="What the paper explains: one of the versions of the article "
        "('article_version'), or the article itself ('article').",
    )
    target_id: str
    article_version_key: str | None = Field(
        None, description="Null unless target is 'article_version'."
    )
    valid_from: str | None = Field(
        None, description="From when the version applies; null for the article."
    )
    passages: list[PassageDTO] = Field(
        ...,
        description="The sections that explain the article, in the order of the paper, "
        "each with its text.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticlePassagesDTO:
        """Build from a row of ``get_article_explanation_passages``."""
        collection, key = parse_node_id(row["target_id"])
        target = _TARGET_OF_COLLECTION[collection]
        return cls(
            document=_entry(row),
            target=target,
            target_id=row["target_id"],
            article_version_key=key if target == "article_version" else None,
            valid_from=row.get("valid_from"),
            passages=[
                PassageDTO(
                    section_id=p["section_anchor"],
                    heading=p["heading"],
                    level=p.get("level"),
                    char_start=p["char_start"],
                    char_end=p["char_end"],
                    text=p["text"],
                    confidence=p["confidence"],
                    match_type=p["match_type"],
                    changed=p.get("changed"),
                    explanation=p.get("explanation"),
                )
                for p in row["passages"]
            ],
        )


def _entry(row: dict[str, Any]) -> DocumentEntryDTO:
    """The paper of a row of ``get_article_explanation_passages``, as it is named."""
    props = row["props"]
    origin = origin_fields(row.get("labels"), row.get("source"), row.get("kind"))
    return DocumentEntryDTO(
        id=row["document_id"],
        key=row["key"],
        kind=row.get("kind"),
        title=props.get("title"),
        sequence=props.get("sequence"),
        number=number_in_dossier(origin["chamber"], props),
        dossier_number=numbered_in(
            props.get("dossier_number"), props.get("dossier_suffix")
        ),
        session_year=props.get("session_year"),
        date=strip_time_component(row.get("date")),
        tk_url=tk_url("document", props),
        sender=sender_of(props),
        **origin,
    )


class ArticlePassagesResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/explanations."""

    article_id: str
    total: int
    items: list[ArticlePassagesDTO]


class _ArticleVersionFields(StrictModel):
    """What every version of an article says of itself, its text aside."""

    key: str = Field(description="Names the version: its text is at `history/{key}`.")
    article_number: str | None = None
    label: str | None = Field(
        None,
        description="`Artikel 287`, or the heading of an article without a number.",
    )
    valid_from: str | None = None
    valid_until: str | None = Field(None, description=VALID_UNTIL)
    current: bool = False
    official_url: str | None = Field(
        None,
        description="This version on wetten.overheid.nl: the JCI with ``g`` its "
        "``valid_from``.",
    )
    effect: str | None = Field(None, description="Raw BWB effect of this version.")
    change: str | None = Field(
        None,
        description=(
            "Normalised effect: 'establishes' (the regulation as it was enacted), "
            "'introduces', 'amends', 'repeals', 'republishes' (the text placed again, "
            "unchanged: a republication, as of the Grondwet) or null."
        ),
    )
    source_publication: str | None = None
    amended_by: PublicationDTO | None = Field(
        None, description="Publication that created this version."
    )
    commencement: PublicationDTO | None = Field(
        None, description="Publication that brought this version into force."
    )

    @staticmethod
    def fields_of(doc: dict[str, Any], titles: dict[str, str | None]) -> dict[str, Any]:
        props = doc.get("props") or {}
        effect = props.get("effect")
        return {
            "key": doc["key"],
            "article_number": props.get("article_number"),
            "label": props.get("label"),
            "valid_from": props.get("valid_from"),
            "valid_until": props.get("valid_until"),
            "current": bool(props.get("current", False)),
            "official_url": article_url(
                props.get("bwb_id"),
                props.get("article_number"),
                on=props.get("valid_from"),
            ),
            "effect": effect,
            "change": effect_kind(effect) or props.get("change"),
            "source_publication": props.get("source_publication"),
            "amended_by": PublicationDTO.from_dict(
                props.get("origin_publication"), titles
            ),
            "commencement": PublicationDTO.from_dict(
                props.get("commencement_publication"), titles
            ),
        }


class ArticleVersionDTO(_ArticleVersionFields):
    """One dated version of an article with its text, and the publication that
    produced it."""

    text: str | None = None
    parts: list[ArticlePartDTO] = Field(
        default_factory=list, description="As on the article: spans of `text`."
    )
    tables: list[ArticleTableDTO] = Field(
        default_factory=list, description="As on the article: spans of `text`."
    )
    headings: list[ArticleHeadingDTO] = Field(
        default_factory=list, description="As on the article: spans of `text`."
    )

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], titles: dict[str, str | None]
    ) -> ArticleVersionDTO:
        props = doc.get("props") or {}
        return cls(
            **cls.fields_of(doc, titles),
            text=props.get("text"),
            parts=parts_from_props(props),
            tables=tables_from_props(props),
            headings=headings_from_props(props),
        )


PartChange = Literal["added", "removed", "changed"]


class VersionPartChangeDTO(StrictModel):
    """A part of the article that a version added, removed or worded otherwise than the
    version before it. Parts are the outermost ones (a lid, not its onderdelen), paired
    by their number, else the term they define, else their place (`aanhef`)."""

    change: PartChange
    kind: str = Field(description="As `kind` of the part: `lid`, `tekst`, `aanhef`.")
    number: str | None = Field(None, description="As printed: `2`, `2a`.")
    term: str | None = Field(None, description="The term a definition defines.")


class ArticleVersionListedDTO(_ArticleVersionFields):
    """One dated version of an article as the history lists it: without its text."""

    text_changed: bool = Field(
        description="Its text differs from that of the version before it (a "
        "non-breaking space counts as a space); true for the first. Versions that "
        "only moved the text in time have false."
    )
    changes: list[VersionPartChangeDTO] = Field(
        default_factory=list,
        description="The parts it changed against the version before it, in the order "
        "of its text, the removed ones last. Empty for the first version and where "
        "either version has no parts.",
    )


def _wording(text: str | None) -> str:
    """*text* as two versions are compared: a non-breaking space is a space."""
    return (text or "").replace("\u00a0", " ").replace("\u202f", " ").strip()


class _Part(NamedTuple):
    """A part as two versions compare it."""

    kind: str
    number: str | None
    term: str | None
    wording: str


def _outer_parts(props: dict[str, Any]) -> dict[tuple[str, str], _Part]:
    """The outermost parts of a version (not those inside another), by what pairs them
    with those of another version: number, else term, else id. Stored parts that do not
    fit the text are left out, as ``parts_from_props`` does."""
    text, stored = props.get("text"), props.get("parts")
    if not isinstance(text, str) or not isinstance(stored, list):
        return {}
    spans = [
        p
        for p in stored
        if isinstance(p, dict)
        and isinstance(p.get("start"), int)
        and isinstance(p.get("end"), int)
        and 0 <= p["start"] < p["end"] <= len(text)
    ]
    outer: dict[tuple[str, str], _Part] = {}
    end = 0
    for p in sorted(spans, key=lambda p: (p["start"], -p["end"])):
        if p["start"] < end:
            continue
        end = p["end"]
        part = _Part(
            str(p.get("kind") or ""),
            p.get("number"),
            p.get("term"),
            _wording(text[p["start"] : p["end"]]),
        )
        if part.number:
            pair = (part.kind, str(part.number))
        else:
            pair = ("term", part.term) if part.term else ("id", str(p.get("id") or ""))
        outer.setdefault(pair, part)
    return outer


def _part_changes(
    old: dict[tuple[str, str], _Part], new: dict[tuple[str, str], _Part]
) -> list[VersionPartChangeDTO]:
    """The parts of *new* that differ from those of *old*, then those it lost."""
    if not old or not new:
        return []

    def change(kind: PartChange, part: _Part) -> VersionPartChangeDTO:
        return VersionPartChangeDTO(
            change=kind, kind=part.kind, number=part.number, term=part.term
        )

    found = [
        change("added", part) if pair not in old else change("changed", part)
        for pair, part in new.items()
        if pair not in old or old[pair].wording != part.wording
    ]
    return found + [change("removed", p) for pair, p in old.items() if pair not in new]


def listed_versions(
    docs: list[dict[str, Any]], titles: dict[str, str | None]
) -> list[ArticleVersionListedDTO]:
    """The versions *docs* (oldest first) as the history lists them, each against the
    one before it."""
    listed: list[ArticleVersionListedDTO] = []
    before: tuple[str, dict[tuple[str, str], _Part]] | None = None
    for doc in docs:
        props = doc.get("props") or {}
        wording, parts = _wording(props.get("text")), _outer_parts(props)
        changed = before is None or before[0] != wording
        listed.append(
            ArticleVersionListedDTO(
                **ArticleVersionListedDTO.fields_of(doc, titles),
                text_changed=changed,
                changes=_part_changes(before[1], parts) if before and changed else [],
            )
        )
        before = (wording, parts)
    return listed


class ArticleHistoryResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/history."""

    bwb_id: str
    article_number: str
    stam_id: str | None = Field(
        None, description="Stable BWB identity of the article across versions."
    )
    versions: list[ArticleVersionListedDTO] = Field(
        default_factory=list, description="All versions, oldest first."
    )
