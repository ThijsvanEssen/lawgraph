from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import ArticleAddress, ListLimit, PageLimit, Tier
from lawgraph.api.schemas.articles import (
    ArticleCitedByItem,
    ArticleCitedByResponse,
    ArticleDelegatedResponse,
    ArticleDetailResponse,
    ArticleExplanationDTO,
    ArticleExplanationsResponse,
    ArticleHistoryResponse,
    ArticleLegislativeHistoryResponse,
    ArticlePassagesDTO,
    ArticlePassagesResponse,
    ArticleRelationshipWithType,
    ArticleSuccessionDTO,
    ArticleSummaryDTO,
    ArticleVersionDTO,
    DelegatedClauseDTO,
    DelegatedRegulationDTO,
    DelegationClauseDTO,
    LegislativeHistoryEntry,
    ScopeArticleReference,
    listed_versions,
    references_from_props,
)
from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    DefinitionDTO,
    EnrichmentDTO,
    InstrumentSummaryDTO,
    TermSpanDTO,
    in_regulation_order,
)
from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core.delegations import (
    delegation_clauses,
    fills,
)
from lawgraph.core.dossier_names import dossier_name
from lawgraph.core.models import (
    make_node_key,
    node_id,
)
from lawgraph.core.reference_targets import reference_targets
from lawgraph.db import GraphStore
from lawgraph.db.queries.articles import (
    get_article_citations,
    get_article_cited_by,
    get_article_explanation_passages,
    get_article_explanations,
    get_article_history,
    get_article_legislative_history,
    get_article_version,
    get_article_with_relations,
    present_targets,
)
from lawgraph.db.queries.definitions import article_terms
from lawgraph.db.queries.delegations import get_delegated_regulations
from lawgraph.db.queries.not_found import NotFound, require_node
from lawgraph.db.queries.relationships import get_article_relationship_data

router = APIRouter()


@router.get(
    "/{bwb_id}/{article_number}",
    response_model=ArticleDetailResponse,
    summary="One article with its references",
    description=(
        "Looks up an article by `bwb_id` and `article_number`, adds its parent "
        "instrument, the number of judgments that cite it (`metadata.judgment_count`; "
        "`/cited-by` pages them), and the article references recorded on the article "
        "itself; `successors` and `predecessors` give its place in a recodification "
        "(`TRANSPOSED_TO`) both ways."
    ),
    tags=["articles"],
)
def get_article_detail(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticleDetailResponse:
    """Return an article plus its instrument and the number of judgments citing it."""
    data = get_article_with_relations(store, article.bwb_id, article.number)

    instrument = (
        InstrumentSummaryDTO.from_document(data.instrument)
        if data.instrument is not None
        else None
    )

    citation_entries = get_article_citations(store, data.article)
    term_spans, citation_refs, used = _defined_terms(store, data, citation_entries)
    citations = [
        ArticleCitationSpan.from_entry(entry, citation_refs.get(index))
        for index, entry in enumerate(citation_entries)
    ]

    relationship_data = get_article_relationship_data(store, data.article["id"])
    upstream, downstream, scope = _build_relationship_dtos(relationship_data)
    props = data.article.get("props") or {}

    return ArticleDetailResponse(
        article=ArticleSummaryDTO.from_document(data.article),
        instrument=instrument,
        enrichment=(
            EnrichmentDTO.of(props, data.instrument.get("props") or {})
            if data.instrument is not None
            else None
        ),
        citations=citations,
        term_spans=[TermSpanDTO(**span) for span in term_spans],
        definitions=[DefinitionDTO.from_definition(d) for d in used],
        references=references_from_props(
            props,
            present_targets(store, reference_targets(props.get("references"))),
        ),
        delegations=[
            DelegationClauseDTO.from_clause(clause)
            for clause in delegation_clauses(props.get("text"), props.get("parts"))
        ],
        metadata=data.metadata or None,
        upstream_dependencies=upstream,
        downstream_implications=downstream,
        scope_articles=scope,
        successors=[
            ArticleSuccessionDTO.from_row(r)
            for r in relationship_data.get("successors", [])
        ],
        predecessors=[
            ArticleSuccessionDTO.from_row(r)
            for r in relationship_data.get("predecessors", [])
        ],
    )


def _defined_terms(
    store: GraphStore, data: Any, entries: list[Any]
) -> tuple[list[dict[str, Any]], dict[int, str], list[dict[str, Any]]]:
    """The terms of the article its regulation defines (``definitions.article_terms``):
    of its instrument, or the one its BWB id names; none without either."""
    props = data.article.get("props") or {}
    if data.instrument is not None:
        instrument_id = data.instrument["id"]
    elif props.get("bwb_id"):
        instrument_id = node_id(COLLECTION_INSTRUMENTS, make_node_key(props["bwb_id"]))
    else:
        return [], {}, []
    # one per entry, in its order, so a ref lands on its citation; one without a place
    # (-1, -1) holds no term
    citations = [
        (
            e.start if e.start is not None else -1,
            e.end if e.end is not None else -1,
            (e.target.get("props") or {}).get("bwb_id"),
        )
        for e in entries
    ]
    return article_terms(store, instrument_id, props, citations)


def _build_relationship_dtos(
    relationship_data: dict[str, list[dict[str, Any]]],
) -> tuple[
    list[ArticleRelationshipWithType],
    list[ArticleRelationshipWithType],
    list[ScopeArticleReference],
]:
    upstream = [
        ArticleRelationshipWithType.from_row(row)
        for row in relationship_data.get("upstream", [])
    ]
    downstream = [
        ArticleRelationshipWithType.from_row(row)
        for row in relationship_data.get("downstream", [])
    ]
    scope = [
        ScopeArticleReference.from_row(row)
        for row in relationship_data.get("scope", [])
    ]
    return upstream, downstream, scope


@router.get(
    "/{bwb_id}/{article_number}/cited-by",
    response_model=ArticleCitedByResponse,
    summary="Passages of judgments that cite an article",
    description=(
        "One row per passage: a judgment and the paragraph in it that cites the article, "
        "with the lid, onderdeel or aanhef it names, a snippet and the confidence of the "
        "detection. Newest judgment first. `court` (ECLI court code), `tier` and `lid` "
        "(a lid number the passage names) filter; `total` counts all passages that match, "
        "`judgment_total` the judgments they are in, `echr_judgment_total` the ECHR "
        "judgments that cite the article (no passage: HUDOC names the article). "
        "404 when the article is unknown."
    ),
    tags=["articles"],
)
def get_article_cited_by_passages(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    court: Annotated[
        str | None, Query(description="ECLI court code, e.g. 'HR', 'RBAMS'")
    ] = None,
    tier: Annotated[
        Tier | None,
        Query(
            description="The tier: `hoge_raad`, `gerechtshof`, `andere_instantie`, …"
        ),
    ] = None,
    lid: Annotated[
        str | None,
        Query(
            pattern=r"^\d+[A-Za-z]{0,3}$",
            description="A lid number the passage names: '3', '2a'",
        ),
    ] = None,
    sort: Annotated[
        Literal["date_desc", "citation_count"],
        Query(
            description="`date_desc`: the newest judgment first; `citation_count`: the "
            "most cited judgment first (a standard judgment), then the newest."
        ),
    ] = "date_desc",
) -> ArticleCitedByResponse:
    if not store.has_node(COLLECTION_ARTICLES, article.key):
        raise NotFound("Article", article.key)
    cited_by = get_article_cited_by(
        store,
        article.id,
        court=court,
        tier=tier.value if tier else None,
        lid=lid,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [
        item for row in cited_by.rows if (item := ArticleCitedByItem.from_row(row))
    ]
    return ArticleCitedByResponse(
        article_id=article.id,
        items=items,
        total=cited_by.total,
        judgment_total=cited_by.judgment_total,
        echr_judgment_total=cited_by.echr_judgment_total,
    )


@router.get(
    "/{bwb_id}/{article_number}/history",
    response_model=ArticleHistoryResponse,
    summary="Version history of an article",
    description=(
        "Every version of one article, identified by the stable BWB `stam_id` so "
        "renumbering does not break the chain, oldest first, without their text. Each "
        "version carries its validity period, the kind of change (`change`: "
        "introduces / amends / repeals), the amending publication (`amended_by`) and "
        "the commencement publication (`commencement`) with their dossiers, whether "
        "its text differs from the version before it (`text_changed`) and which parts "
        "it changed (`changes`). The text of a version is at `history/{key}`. "
        "An article of a law of the Staatsblad the BWB does not hold has one version: "
        "its text as enacted, without a validity, made (`amended_by`) by the "
        "publication its text comes from. 404 when the article is unknown."
    ),
    tags=["articles"],
)
def get_article_version_history(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticleHistoryResponse:
    data = get_article_history(store, article.bwb_id, article.number)
    props = data.article.get("props") or {}
    return ArticleHistoryResponse(
        bwb_id=props.get("bwb_id") or article.bwb_id,
        article_number=article.number,
        stam_id=props.get("stam_id"),
        versions=listed_versions(data.versions, data.dossier_titles),
    )


@router.get(
    "/{bwb_id}/{article_number}/history/{version_key}",
    response_model=ArticleVersionDTO,
    summary="One version of an article with its text",
    description=(
        "The version `version_key` (a `key` of `history`) with its text, its parts "
        "and tables as spans of the text, and the publications that made it. "
        "Two of them side by side are the difference between two versions. "
        "404 when the article is unknown or the version is not one of it."
    ),
    tags=["articles"],
)
def get_article_version_text(
    article: ArticleAddress,
    version_key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticleVersionDTO:
    data = get_article_version(store, article.bwb_id, article.number, version_key)
    return ArticleVersionDTO.from_document(data.versions[0], data.dossier_titles)


@router.get(
    "/{bwb_id}/{article_number}/legislative-history",
    response_model=ArticleLegislativeHistoryResponse,
    summary="Legislative history of an article",
    description=(
        "The dossiers that established (enacted its regulation), introduced, amended or "
        "repealed this article, or propose to: one entry per change and dossier, with "
        "the publication "
        "(enacted, `canoniek`) or the bill (proposed, `voorgesteld`) that carries "
        "it; proposed first, then newest first. What only cites the article "
        "(a judgment, another article) is not history. The explanatory documents "
        "are at `explained-by`. Returns an empty list when there is no history — "
        "never a 404."
    ),
    tags=["articles"],
)
def get_legislative_history(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticleLegislativeHistoryResponse:
    raw_entries = get_article_legislative_history(
        store, article.bwb_id, article.number, article_id=article.id
    )
    entries = [
        LegislativeHistoryEntry(
            **e, dossier_short_title=dossier_name({"title": e.get("dossier_title")})[0]
        )
        for e in raw_entries
    ]
    return ArticleLegislativeHistoryResponse(
        article_id=article.id,
        entries=entries,
        total=len(entries),
    )


@router.get(
    "/{bwb_id}/{article_number}/explained-by",
    response_model=ArticleExplanationsResponse,
    summary="Explanatory documents of an article",
    description=(
        "The documents that explain this article: every EXPLAINS edge that points "
        "at the article (`target` `article`) or at one of its versions (`target` "
        "`article_version`); an explanation of the law as a whole is no evidence "
        "about this article and is not listed. Newest first. An explanation of "
        "`scope` `dossier` is written per dossier: the memorandum explains all "
        "the changes of the dossier; of `scope` `article` the memorandum names "
        "the section about this article in `section_anchor` (the `id` of a "
        "section of the document; `GET /api/documents/{key}/passages` gives its "
        "text). One document appears once per level. `total` counts all "
        "explanations, independent of `limit` and `offset`. Returns an empty list "
        "for an unknown article — never a 404."
    ),
    tags=["articles"],
)
def get_explained_by(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArticleExplanationsResponse:
    page = get_article_explanations(
        store, article.bwb_id, article.number, limit=limit, offset=offset
    )
    return ArticleExplanationsResponse(
        article_id=article.id,
        total=page["total"],
        items=[ArticleExplanationDTO.from_row(row) for row in page["items"]],
    )


@router.get(
    "/{bwb_id}/{article_number}/explanations",
    response_model=ArticlePassagesResponse,
    summary="Passages that explain an article",
    description=(
        "The papers that explain this article in a passage, each with the text of "
        "its passages: the sections `semantic tk-mvt-articles` linked to the article "
        "or to one of its versions (of `scope` `article` in `explained-by`). Per "
        "paper the version it explains; the newest version first, the article itself "
        "(no version) last; of one version the memoranda before the amendments. A "
        "section is listed once, with its surest match, in the order of the paper. "
        "An explanation of a whole dossier has no passage and is not listed "
        "(`explained-by` lists it). Empty for an unknown article — never a 404."
    ),
    tags=["articles"],
)
def get_explanations(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticlePassagesResponse:
    rows = get_article_explanation_passages(store, article.bwb_id, article.number)
    return ArticlePassagesResponse(
        article_id=article.id,
        total=len(rows),
        items=[ArticlePassagesDTO.from_row(row) for row in rows],
    )


@router.get(
    "/{bwb_id}/{article_number}/delegated",
    response_model=ArticleDelegatedResponse,
    summary="Regulations issued under an article",
    description=(
        'The regulations in force whose preamble ("Gelet op") names this article as '
        "their legal basis (`BASED_ON`; a repealed regulation is left out), each with "
        "the leden it names and its articles that "
        'refer to this one; and the delegation formulas of the article ("bij of '
        'krachtens algemene maatregel van bestuur"), each with the regulations that '
        "fill it, or none yet. 404 when the article is unknown."
    ),
    tags=["articles"],
)
def get_delegated(
    article: ArticleAddress,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ArticleDelegatedResponse:
    node = require_node(store, COLLECTION_ARTICLES, article.key, "Article")
    items = in_regulation_order(
        DelegatedRegulationDTO.from_row(row)
        for row in get_delegated_regulations(store, article.id)
    )
    props = node.get("props") or {}
    clauses = [
        DelegatedClauseDTO(
            **DelegationClauseDTO.fields_of(clause),
            instruments=[
                item.instrument.key
                for item in items
                if fills(clause, item.kind, item.leden)
            ],
        )
        for clause in delegation_clauses(props.get("text"), props.get("parts"))
    ]
    return ArticleDelegatedResponse(
        article_id=article.id, clauses=clauses, items=items, total=len(items)
    )
