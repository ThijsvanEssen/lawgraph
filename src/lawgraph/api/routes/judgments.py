from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import CourtKind, PageLimit, Tier
from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
    judgment_cite_dto,
)
from lawgraph.api.schemas.judgments import (
    JudgmentCitedArticle,
    JudgmentCitedJudgment,
    JudgmentConclusionDTO,
    JudgmentDetailResponse,
    JudgmentDTO,
    JudgmentFacets,
    JudgmentListItemDTO,
    JudgmentListResponse,
    RelatedJudgmentDTO,
    conclusion_props,
    mentions_of,
)
from lawgraph.core.mentions import mention_texts
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.judgments import (
    JudgmentArticleRelation,
    JudgmentFilters,
    get_judgment_with_relations,
    get_judgments_list,
)

router = APIRouter()


@router.get(
    "",
    response_model=JudgmentListResponse,
    summary="Paginated list of judgments",
    description=(
        "A paginated list of judgments with filters on court (the ECLI court "
        "code), tier (the Type of the court in the Instanties value list of the "
        "Rechtspraak: hoge_raad, raad_van_state, gerechtshof, rechtbank, tuchtcollege, "
        "andere_instantie, koninkrijksinstantie, …), court_kind (the kind of court "
        "within the tier: ambtenarengerecht, raad_van_beroep, gerecht_in_eerste_aanleg, "
        "…), area of law (`subject`), source, date range and a minimum citation count. "
        "`facets` counts the judgments under the filters per `tier` (without the tier "
        "and court_kind filters), per `court_kind` (without its own filter), per "
        "`source` (without the source filter), per year of `date` (without `from` "
        "and `to`), per area of law (`subjects`, without `subject`) and per `procedure` "
        "(without its filter). `facets=false` leaves them out (null): the pages after the "
        "first need none."
        "\n\n"
        "paged list, without the judgments known only because something cites them "
        "(stubs: no date, court or text) unless `include_stubs=true`, and without a "
        "publication of a decision that another publication replaces (`same_as`; `q` "
        "its exact ECLI finds it); `q` (a query that is the whole of an ECLI or of a "
        "case number, `18/04298`, gives the judgments with it and only those; other "
        "text is searched), `court` (ECLI code), `tier` (the `Type` of the court in "
        "the Instanties list, one of `core.courts.TIERS`: `hoge_raad`, "
        "`raad_van_state`, `centrale_raad_van_beroep`, "
        "`college_van_beroep_bedrijfsleven`, `parket` (the conclusions of the Parket "
        "bij de Hoge Raad), `gerechtshof`, `rechtbank`, `kantongerecht`, "
        "`tuchtcollege`, `andere_instantie`, `koninkrijksinstantie`, `kroon`, "
        "`buitenlandse_instantie`, `hvj_eu`, `ehrm`), `court_kind` (the kind of court "
        "within the tier, one of `core.courts.COURT_KINDS`: `ambtenarengerecht`, "
        "`raad_van_beroep`, `gerecht_in_eerste_aanleg`, …; a tier of one kind of court "
        "is its own; see pipelines (docs/pipelines.md#courts)), `source`, `subject` "
        "(an area of law, one of `subjects` as written: `Strafrecht`, `Bestuursrecht; "
        "Belastingrecht`), `subject_area` (a main area of law, the part of a subject "
        "before its first `;`: `Bestuursrecht` holds `Bestuursrecht` and "
        "`Bestuursrecht; Belastingrecht` alike), `from`, `to`, `cited_by_min`, `sort` "
        "(`date_desc`, `date_asc`, `citation_count`); each item has `tier`, "
        "`court_kind`, `subjects` (the areas of law of the source, empty when it gives "
        "none), `names` (what lawyers call it, `Haviltex`; empty for most), "
        "`decision_kind` (`arrest`, `vonnis`, `beschikking`, `uitspraak`, `conclusie`, "
        "`prejudiciële beslissing`, or null; see pipelines "
        "(docs/pipelines.md#rechtspraak)), `series_id` and `series_size`, "
        "`inbound_citation_count` (the judgments that cite it or a publication "
        "`SAME_AS` it) and `outbound_citation_count` (the judgments it cites); `q` "
        "also matches `names`. `facets` counts the judgments under the filters, each "
        "without its own: `tier` (`value`, `count`, most first; without the `tier` and "
        "`court_kind` filters), `court_kind` (the same, without the `court_kind` "
        "filter), `source` (`value` `rechtspraak`, `echr`, `count`, most first; "
        "without the `source` filter) `year` (`value` the year of `date`, `count`, "
        "oldest first after null, no date; without `from` and `to`), `subjects` (per "
        "area of law as written, `Strafrecht`, `Bestuursrecht; Belastingrecht`, most "
        "first; a judgment counts for each of its areas; without the `subject` "
        "filter), `subject_area` (per main area of law, most first; a judgment counts "
        "once for each of its main areas; with `narrower`, the subjects of the source "
        "under it, `value` as written for the `subject` filter, `label` the part after "
        "its first `;`, `count`; the whole tree without the `subject_area` and "
        "`subject` filters) and `procedure` (per Rechtspraak `psi:procedure` as "
        "written, `Hoger beroep`, `Cassatie`, null for none, most first; without the "
        "`procedure` filter, which filters on that value); the counts of `tier`, "
        "`court_kind`, `source` and `year` read an index, not the judgments; the "
        "facets and `total` are kept an hour whatever the data does "
        "(`db/version_cache.py`), the page itself is read fresh; `facets=false` gives "
        "`facets` null and counts nothing but `total`, the choice for the pages after "
        "the first"
    ),
    tags=["judgments"],
)
def list_judgments(
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    facets: Annotated[
        bool, Query(description="Count per tier, court kind, source, year, area.")
    ] = True,
    q: Annotated[
        str | None, Query(description="Free-text over display_name/ecli/summary")
    ] = None,
    court: Annotated[
        str | None,
        Query(description="ECLI court code, e.g. 'HR', 'RBAMS', 'GHARL'"),
    ] = None,
    tier: Annotated[
        Tier | None,
        Query(
            description="The tier: `hoge_raad`, `gerechtshof`, `andere_instantie`, …"
        ),
    ] = None,
    court_kind: Annotated[
        CourtKind | None,
        Query(
            description="The kind of court: `ambtenarengerecht`, `raad_van_beroep`, "
            "`hoge_raad`, …"
        ),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="The source, e.g. 'rechtspraak', 'echr'."),
    ] = None,
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Lower bound on judgment date, YYYY-MM-DD"),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Upper bound on judgment date, YYYY-MM-DD"),
    ] = None,
    subject: Annotated[
        str | None,
        Query(
            description="An area of law, one of `subjects` as written: `Strafrecht`, "
            "`Bestuursrecht; Belastingrecht`."
        ),
    ] = None,
    subject_area: Annotated[
        str | None,
        Query(
            description="A main area of law: the judgments with a subject in it, "
            "`Bestuursrecht` for `Bestuursrecht` and `Bestuursrecht; Belastingrecht` alike "
            "(the part of a subject before its first `;`)."
        ),
    ] = None,
    procedure: Annotated[
        str | None,
        Query(
            description="The procedure, as the source writes it (Rechtspraak "
            "`psi:procedure`): `Hoger beroep`, `Cassatie`, `Eerste aanleg - meervoudig`."
        ),
    ] = None,
    cited_by_min: Annotated[int | None, Query(ge=0)] = None,
    include_stubs: Annotated[
        bool,
        Query(
            description="Also the judgments known only because something cites them "
            "(no date, court or text)."
        ),
    ] = False,
    sort: Annotated[
        Literal["date_desc", "date_asc", "citation_count"], Query()
    ] = "date_desc",
) -> JudgmentListResponse:
    filters = JudgmentFilters(
        q=q,
        court=court,
        tier=tier.value if tier else None,
        court_kind=court_kind.value if court_kind else None,
        source=source,
        subject=(subject or "").strip() or None,
        subject_area=(subject_area or "").strip() or None,
        procedure=(procedure or "").strip() or None,
        from_date=iso_day(date_from),
        to_date=iso_day(date_to),
        cited_by_min=cited_by_min,
        include_stubs=include_stubs,
    )
    data = get_judgments_list(
        store, filters, sort=sort, limit=limit, offset=offset, facets=facets
    )
    items = [JudgmentListItemDTO.from_document(row) for row in data.get("items", [])]
    return JudgmentListResponse(
        items=items,
        total=int(data.get("total", 0)),
        facets=JudgmentFacets(**(data.get("facets") or {})) if facets else None,
    )


@router.get(
    "/{ecli}",
    response_model=JudgmentDetailResponse,
    summary="One judgment with the articles it cites",
    description=(
        "Looks a judgment up by ECLI, follows its REFERS_TO edges to articles "
        "and adds each article with its parent instrument."
        "\n\n"
        "the judgment with its `official_url` (uitspraken.rechtspraak.nl by ECLI; "
        "HUDOC by item id, `external_id`, for an ECHR judgment; null for a stub of "
        "another court), its `paragraphs` (each with a `paragraph_id` for deep links, "
        "its printed `number`, its `kind` (`heading`, `subheading`, `body`, `toc`: a "
        "line of a table of contents, `signature`: the closing lines that sign a "
        "conclusion), of a paragraph without a number that goes on with a numbered "
        "consideration `continues` (its `paragraph_id`), and the `citations` in it of "
        "an article or a judgment, one per occurrence with `start` and `end`, `kind` "
        "`article` or `judgment` and `target.collection` to match; the first is the "
        "kop when the judgment has one), its `footnotes` (`label` as printed, "
        "`paragraph_id` the paragraph whose marker points to it, null when none does, "
        "`at` where that marker stands in the paragraph's `text`, null when not known, "
        "`text`, and the `citations` in that text as a paragraph has them), its "
        "`parties` (`name`, `role`, `roles` (every role the kop names, in its order: "
        "geïntimeerde and appellant in incidenteel hoger beroep), `role_stated` (a "
        "derived role is never the other side's for a public authority: the "
        "prosecution is `Officier van justitie`), `side` `first`/`second`/`other`, "
        '`alias` ("(hierna: X)", and "Partijen worden hierna A, B en C genoemd"), '
        "`representatives` (`name`, `role` `advocaat`, `gemachtigde` or, in a criminal "
        "case, `raadsman`, `place`, `capacity`: from the kop and the account of the "
        "procedure, data model (docs/data-model.md#judgment)); a party the procedure "
        'hears "als partij" that the kop does not name comes last, `side` `other`; '
        "null when the judgment was normalized before parties were read, empty when "
        "none are named), the articles its `REFERS_TO` edges point at with their "
        "parent instrument (`articles`), and the same articles as `cited_articles` "
        "with the paragraphs that cite them, the lid or onderdeel named and the "
        "snippet of the strongest mention: `snippet_paragraph_id` the paragraph it is "
        "from (of a citation in a footnote, the paragraph that refers to it, and "
        "`footnote` the footnote's `label`; null for a paragraph's own text), `text` "
        "the citation as written and `start`/`end` where the linker found it in the "
        "snippet (null when the judgment was normalized again since it was linked). "
        "Citations are read from the stored edges; nothing is detected per request. "
        "`judgment.names` and `decision_kind` as in the list; `summary` is the Dutch "
        "inhoudsindicatie and `summary_en` an English one: an English translation (its "
        "own ECLI, `translation_of` the ECLI of the Dutch judgment) has the Dutch "
        "`summary` of that judgment, and that judgment the English `summary_en` (see "
        "data-model (docs/data-model.md#judgment)). `judgment.series_id` and "
        "`series_size` name the series of parallel cases it is one of (the same court, "
        "day and text), `series` the other judgments of it. `conclusions` are the "
        "conclusions its metadata names (`conclusion_eclis`), in that order: `ecli`, "
        "`author` (the A-G or P-G), `role` and `date` as the conclusion's light node "
        "gives them (`lg_judgment_light`), so they read as the conclusion's own page; "
        "one the graph lacks is its `ecli` alone. `cited_judgments` are the judgments "
        "its text cites (`REFERS_TO`: by ECLI, LJN or application number), newest "
        "first, each with the places that cite it as `cited_articles` has them "
        "(`paragraph_ids`, `paragraph_numbers`, `snippet`, `snippet_paragraph_id`, "
        "`footnote`, `text`, `start`, `end`, `confidence`, `mention_count`; empty for "
        "an edge linked before places were kept); `judgment.same_as` is, for a "
        "replaced publication, the ECLI of the one kept (for a language version of an "
        "ECHR decision without an ECLI, the HUDOC item id of the version kept), and "
        "`same_as` the other publications of the decision (`SAME_AS`, either way); "
        "`related_to` the connected cases (`RELATED_TO`, as between dossiers, either "
        'way: those its summary names, "Samenhang met 24/03860 E", "Zie ook: ECLI:…", '
        "and those whose summary names it), each once with its `links`: per edge its "
        "`direction` (`outbound`: this judgment's summary names it, `inbound`: its "
        "summary names this one, outbound first), `basis` (`summary_text`) and `text`, "
        "the sentence that names it; `judgment.replaced_by` the ECLI "
        "`dcterms:isReplacedBy` names, loaded or not. `judgment.advocate_general` and "
        "`advocate_general_role` (the role it is signed in: `advocaat-generaal`, "
        "`waarnemend advocaat-generaal`, `plaatsvervangend procureur-generaal`, "
        "`plaatsvervangend advocaat-generaal`; null when not clear) is, for a "
        "conclusion, who wrote it (`T. Hartlief`; null for a judgment); "
        '`published_on`, the "Datum publicatie" of uitspraken.rechtspraak.nl (null for '
        "another source or without a published document). How it ended (data model "
        "(docs/data-model.md#judgment)): `judgment.outcome` (`verworpen`, "
        "`vernietigd`, `gedeeltelijk vernietigd`, `vernietigd en verwezen`, "
        "`bekrachtigd`, `bevestigd`, `gegrond`, `ongegrond`, `niet-ontvankelijk`, "
        "`afgewezen`, `toegewezen`; of the ECHR `schending` or `geen schending`) with "
        '`outcome_text`, the clause of the decision that says it ("verwerpt het '
        'beroep"), and `outcome_paragraph_id`; of a conclusion `conclusion_outcome` '
        "(`verwerping`, `vernietiging`, `vernietiging en verwijzing`, "
        "`niet-ontvankelijkverklaring`, `gegrondverklaring`, `ongegrondverklaring`, "
        "`beantwoording`) with `conclusion_outcome_text` and "
        "`conclusion_outcome_paragraph_id`; of the ECHR `echr_findings`, per article "
        "`{article, protocol, combined_with, finding, aspect, text}`; null (empty) "
        "when the text does not say it. Each of `conclusions` has the `outcome` and "
        "`outcome_text` of that conclusion (what it proposes)"
    ),
    tags=["judgments"],
)
def get_judgment_detail(
    ecli: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> JudgmentDetailResponse:
    """Return a judgment plus the articles it mentions."""
    data = get_judgment_with_relations(store, ecli)

    articles = [
        ArticleRelationDTO.from_documents(rel.article, rel.instrument)
        for rel in data.articles
    ]
    props = data.judgment.get("props") or {}
    texts = mention_texts(props.get("paragraphs") or [], props.get("footnotes") or [])
    cited_articles = [
        JudgmentCitedArticle.from_relation(article, rel.meta, rel.confidence, texts)
        for article, rel in zip(articles, data.articles, strict=True)
    ]

    judgment = JudgmentDTO.from_document(data.judgment)
    spans = _citation_spans(data.articles, data.cited_judgments)
    judgment = judgment.model_copy(
        update={
            "paragraphs": [
                paragraph.model_copy(
                    update={"citations": spans.get((paragraph.paragraph_id, None), [])}
                )
                for paragraph in judgment.paragraphs
            ],
            "footnotes": [
                note.model_copy(
                    update={
                        "citations": spans.get(
                            (note.paragraph_id or f"fn-{note.label}", note.label), []
                        )
                    }
                )
                for note in judgment.footnotes
            ],
        }
    )

    cited_judgments = [
        JudgmentCitedJudgment.from_citation(doc, texts) for doc in data.cited_judgments
    ]

    return JudgmentDetailResponse(
        judgment=judgment,
        articles=articles,
        cited_articles=cited_articles,
        cited_judgments=cited_judgments,
        same_as=[JudgmentSummaryDTO.from_document(doc) for doc in data.same_as],
        related_to=[RelatedJudgmentDTO.from_document(doc) for doc in data.related_to],
        series=[JudgmentSummaryDTO.from_document(doc) for doc in data.series],
        conclusions=[
            JudgmentConclusionDTO(**c, cite=judgment_cite_dto(conclusion_props(c)))
            for c in data.conclusions
        ],
        metadata=data.metadata or None,
    )


def _citation_spans(
    relations: list[JudgmentArticleRelation], cited: list[dict[str, Any]]
) -> dict[tuple[str, str | None], list[ArticleCitationSpan]]:
    """The stored mentions of every cited article and judgment, as citation spans, by
    ``(paragraph_id, footnote)``: a paragraph's own under ``None``, a footnote's under its
    label (``core.mentions.mention_texts``).

    Detected when the judgment was linked (``semantic rechtspraak``, ``semantic
    rechtspraak-citations``), so serving one costs no detection.
    """
    spans: dict[tuple[str, str | None], list[ArticleCitationSpan]] = {}

    def add(target: ArticleCitationTarget, meta: dict[str, Any], kind: str) -> None:
        for mention in mentions_of(meta):
            spans.setdefault((mention.paragraph_id, mention.footnote), []).append(
                ArticleCitationSpan(
                    start=mention.start,
                    end=mention.end,
                    text=mention.raw_match,
                    target=target,
                    kind=kind,
                    confidence=mention.confidence,
                    **mention.parts.to_dict(),
                )
            )

    for relation in relations:
        add(
            ArticleCitationTarget.from_document(relation.article),
            relation.meta,
            "article",
        )
    for doc in cited:
        add(ArticleCitationTarget.from_document(doc), doc.get("meta") or {}, "judgment")
    for found in spans.values():
        found.sort(key=lambda span: span.start or 0)
    return spans
