"""Instrument list endpoint — paginated catalogue of laws and regulations."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import (
    After,
    DateSort,
    ListLimit,
    LongListLimit,
    MinistryKey,
    OpenedSort,
    PageLimit,
    Tier,
    not_both,
)
from lawgraph.api.schemas.common import (
    DefinitionDTO,
    FacetCountDTO,
    in_regulation_order,
)
from lawgraph.api.schemas.instruments import (
    TEXT_PREVIEW_CHARS,
    AmendedByResponse,
    AmendingInstrumentDTO,
    AmendingProposalDTO,
    EuLinkDTO,
    InstrumentAnnexDTO,
    InstrumentArticleNodeDTO,
    InstrumentArticlesAtResponse,
    InstrumentArticlesResponse,
    InstrumentArticleVersionDTO,
    InstrumentBasisItem,
    InstrumentBasisResponse,
    InstrumentDefinitionsResponse,
    InstrumentDelegatedItem,
    InstrumentDelegatedResponse,
    InstrumentDelegatedSummaryItem,
    InstrumentDetailDTO,
    InstrumentDivisionDTO,
    InstrumentDossierItem,
    InstrumentDossiersResponse,
    InstrumentEuLinksResponse,
    InstrumentFacets,
    InstrumentJudgmentFacets,
    InstrumentJudgmentItem,
    InstrumentJudgmentsResponse,
    InstrumentListItemDTO,
    InstrumentListResponse,
    InstrumentPreambleDTO,
    InstrumentReferenceDTO,
    InstrumentReferencesResponse,
    InstrumentRelatedItem,
    InstrumentRelatedResponse,
    InstrumentVersionDTO,
    InstrumentVersionsResponse,
    InternationalLinkDTO,
    JudgmentSort,
    LinkedInstrumentDTO,
)
from lawgraph.api.validity import instrument_validity_dto
from lawgraph.core.division_anchor import as_anchor
from lawgraph.core.reference_targets import reference_targets
from lawgraph.core.staatsblad_laws import is_law
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.annexes import get_law_annexes
from lawgraph.db.queries.articles import get_current_references, present_targets
from lawgraph.db.queries.definitions import definitions_of
from lawgraph.db.queries.delegations import (
    count_expired_delegated,
    get_basis,
    get_delegated_by_law,
)
from lawgraph.db.queries.instrument_links import (
    get_eu_links,
    get_international_links,
)
from lawgraph.db.queries.instrument_scope import (
    resolve_instrument,
    same_treaty,
    scope_of,
    scope_of_node,
)
from lawgraph.db.queries.instruments import (
    INSTRUMENT_SORTS,
    LawOnADate,
    get_articles,
    get_articles_at,
    get_citing_judgments,
    get_division_articles,
    get_division_articles_at,
    get_instrument_amended_by,
    get_instrument_dossiers,
    get_instrument_references,
    get_instrument_related_instruments,
    get_instrument_versions,
    get_instruments_list,
)
from lawgraph.db.queries.not_found import NotFound, require
from lawgraph.db.queries.unlinked_references import law_reference_counts

Validity = Literal["in_force", "expired", "all"]

router = APIRouter()


@router.get(
    "",
    response_model=InstrumentListResponse,
    summary="Paginated list of instruments",
    description=(
        "A paginated list of statutes, regulations and EU instruments. Supports "
        "free-text search (`q`), a jurisdiction filter (`nl`/`eu`), a kind "
        "filter, a minimum article count, and the registers of the BWB: a legal area "
        "(`legal_area`, a main area includes its specific areas) and a government theme "
        "(`policy_domain`), each by TOOI id or slug; an unknown value finds nothing; and "
        "the ministry first responsible for a BWB regulation (`ministry`, its WTI). "
        "`facets` counts the instruments under the filters per legal area (a tree) and per "
        "theme, each without its own filter. The regulations that change other "
        "regulations (`amending` on an item) are hidden from the list without a search "
        "and shown with one; `amending` says otherwise (`hide`, `show`, `only`), and the "
        "facet `amending` counts both. The same holds for the instruments no longer in "
        "force (`validity`: `in_force`, `expired` or `all`; left out, `in_force` without `q` and "
        "`all` with it; `expired_on` on an item, as the BWB gives it, read on the Dutch "
        "day). "
        "`facets=false` leaves them out (null): the pages after the first need none."
    ),
    tags=["instruments"],
)
def list_instruments(
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    facets: Annotated[
        bool, Query(description="Count per legal area, theme and kind.")
    ] = True,
    q: Annotated[str | None, Query(description="Free-text match")] = None,
    jurisdiction: Annotated[
        Literal["nl", "eu", "int"] | None,
        Query(
            description="``nl``, ``eu``, or ``int``: the treaties of the Verdragenbank "
            "(``Internationaal``)."
        ),
    ] = None,
    kind: Annotated[str | None, Query()] = None,
    article_count_min: Annotated[int | None, Query(ge=0)] = None,
    legal_area: Annotated[
        str | None,
        Query(
            max_length=200,
            description="A legal area by TOOI id (`c_e49bce03`) or slug (`familierecht`).",
        ),
    ] = None,
    policy_domain: Annotated[
        str | None,
        Query(max_length=200, description="A government theme by TOOI id or slug."),
    ] = None,
    sort: Annotated[Literal["title", "article_count"], Query()] = "title",
    date_from: Annotated[
        dt.date | None,
        Query(
            alias="from",
            description="Came into force on or after this day, YYYY-MM-DD.",
        ),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(
            alias="to", description="Came into force on or before this day, YYYY-MM-DD."
        ),
    ] = None,
    published_from: Annotated[
        dt.date | None,
        Query(description="Published on or after this day, YYYY-MM-DD."),
    ] = None,
    published_to: Annotated[
        dt.date | None,
        Query(description="Published on or before this day, YYYY-MM-DD."),
    ] = None,
    amending: Annotated[
        Literal["hide", "show", "only"] | None,
        Query(
            description="The regulations that change others: `hide` them, `show` them "
            "with the rest, or `only` them. Left out: `hide` without `q`, `show` with it."
        ),
    ] = None,
    validity: Annotated[
        Validity | None,
        Query(
            description="The instruments in force today (`in_force`), those no longer in "
            "force (`expired`), or `all`. Left out: `in_force` without `q`, `all` with it."
        ),
    ] = None,
    ministry: Annotated[
        MinistryKey | None,
        Query(description="The ministry first responsible (``GET /api/ministries``)."),
    ] = None,
    after: After = None,
) -> InstrumentListResponse:
    not_both(after, offset)
    if sort not in INSTRUMENT_SORTS:  # belt-and-braces; Literal already validates
        sort = "title"
    data = get_instruments_list(
        store,
        q=q,
        jurisdiction=jurisdiction,
        kind=kind,
        article_count_min=article_count_min,
        legal_area=legal_area,
        policy_domain=policy_domain,
        ministry=ministry.value if ministry else None,
        sort=sort,
        limit=limit,
        offset=offset,
        after=after,
        in_force_from=iso_day(date_from),
        in_force_to=iso_day(date_to),
        published_from=iso_day(published_from),
        published_to=iso_day(published_to),
        amending=amending,
        validity=validity,
        facets=facets,
    )
    items = [InstrumentListItemDTO.from_document(row) for row in data.get("items", [])]
    return InstrumentListResponse(
        items=items,
        total=data.get("total"),
        facets=InstrumentFacets(**(data.get("facets") or {})) if facets else None,
        partial=bool(data.get("partial")),
        next_cursor=data.get("next_cursor"),
    )


@router.get(
    "/{identifier}",
    response_model=InstrumentDetailDTO,
    summary="One instrument",
    description=(
        "The instrument named by its BWB id (`BWBR0001854`), its CELEX number "
        "(`32016L0680`), the official number of a law of the Staatsblad (`STB-2026-56`: "
        "the law, `wet_stb_2026_56`; the publication is `stb_2026_56`) or its node key "
        "(`bwbv0001000`, `verdrag_012345`): "
        "identifiers, names, jurisdiction, kind, dates and article count, of a BWB "
        "regulation its aanhef (`preamble`), and for a treaty the other instruments with "
        "its treaty number (`same_treaty`). 404 for an unknown instrument."
    ),
    tags=["instruments"],
)
def get_instrument(
    identifier: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> InstrumentDetailDTO:
    doc = require(resolve_instrument(store, identifier), "Instrument", identifier)
    references = (
        law_reference_counts(store, doc["id"])
        if is_law(doc.get("props") or {})
        else None
    )
    return InstrumentDetailDTO.from_document(
        doc,
        same_treaty=same_treaty(store, doc),
        references=references,
        validity=instrument_validity_dto(store, doc),
        preamble=_preamble(store, doc.get("props") or {}),
    )


def _preamble(store: GraphStore, props: dict[str, Any]) -> InstrumentPreambleDTO | None:
    """The aanhef stored on an instrument, its links with whether the data holds what they
    name; None without one."""
    stored = props.get("preamble")
    if not isinstance(stored, dict):
        return None
    present = present_targets(store, reference_targets(stored.get("references")))
    return InstrumentPreambleDTO.from_props(stored, present)


@router.get(
    "/{identifier}/definitions",
    response_model=InstrumentDefinitionsResponse,
    summary="The definitions an instrument gives itself",
    description=(
        "Its begripsbepalingen, as its text gives them, in the order of the text: each "
        "`term` with its `text`, the article and letter it stands in, where it holds "
        "(`scope`: the whole regulation, or a chapter or paragraph of it, and whether in "
        "the regulations issued under it too) and the "
        "regulation a definition is (`refers_to`: `wet`, de Zorgverzekeringswet). Empty for "
        "one that defines nothing. 404 for an unknown instrument."
    ),
    tags=["instruments"],
)
def get_instrument_definitions(
    identifier: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> InstrumentDefinitionsResponse:
    doc = require(resolve_instrument(store, identifier), "Instrument", identifier)
    return InstrumentDefinitionsResponse(
        key=doc["key"],
        definitions=[
            DefinitionDTO.from_definition(d) for d in definitions_of(store, doc["id"])
        ],
    )


@router.get(
    "/{identifier}/eu-links",
    response_model=InstrumentEuLinksResponse,
    summary="EU and international links of an instrument",
    description=(
        "`implements`: EU acts this instrument implements; `implemented_by`: the national "
        "publications and regulations that implement this EU act. Both are `IMPLEMENTS` "
        "edges between instruments with what they rest on (`bases`): EUR-Lex lists the "
        "publication as a national implementing measure, or the considerans says so; not "
        "per article. `mentions` and `mentioned_by`: the same for an EU act a regulation "
        "names by CELEX number without implementing it (`REFERS_TO`). `international`: "
        "treaties (BWB treaties) that articles of this "
        "instrument refer to, and ECHR judgments that refer to it or to its articles, "
        "each with the evidence of its edge; the graph holds no other links to treaties "
        "or to the articles of the ECHR Convention from Dutch text. The instrument is "
        "named by BWB id, CELEX number or node key; 404 when unknown. `limit` bounds "
        "each list; the `*_total` fields are absolute. `sort`: `confidence` (default) puts the "
        "most certain link first; `importance` the one whose instrument (treaty, EU act, "
        "ECHR judgment) is cited most often (`inbound_citation_count`), then the most certain."
    ),
    tags=["instruments"],
)
def get_instrument_eu_links(
    identifier: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: LongListLimit = 500,
    sort: Annotated[Literal["confidence", "importance"], Query()] = "confidence",
) -> InstrumentEuLinksResponse:
    doc = require(resolve_instrument(store, identifier), "Instrument", identifier)
    importance = sort == "importance"
    eu = get_eu_links(store, doc["id"], limit=limit, importance=importance)
    cited = (doc.get("props") or {}).get("inbound_citation_count")
    international = get_international_links(
        store,
        doc["id"],
        scope_of_node(doc),
        limit=limit,
        cited=cited if isinstance(cited, int) else None,
        importance=importance,
    )
    links = [
        InternationalLinkDTO.from_row(r, "treaty") for r in international.treaties
    ] + [
        InternationalLinkDTO.from_row(r, "echr_judgment")
        for r in international.judgments
    ]
    return InstrumentEuLinksResponse(
        instrument=LinkedInstrumentDTO.from_document(doc),
        implements=[EuLinkDTO.from_row(r) for r in eu.implements],
        implements_total=eu.implements_total,
        implemented_by=[EuLinkDTO.from_row(r) for r in eu.implemented_by],
        implemented_by_total=eu.implemented_by_total,
        mentions=[EuLinkDTO.from_row(r) for r in eu.mentions],
        mentions_total=eu.mentions_total,
        mentioned_by=[EuLinkDTO.from_row(r) for r in eu.mentioned_by],
        mentioned_by_total=eu.mentioned_by_total,
        international=links[:limit],
        international_total=international.treaties_total
        + international.judgments_total,
    )


_DIVISION_HELP = (
    "One division alone, by its anchor: the path of its labels "
    "(`deel-hoofdstuk-10-titel-10.2-afdeling-10.2.2`; `deel-` may be left out)."
)


@router.get(
    "/{bwb_id}/articles",
    response_model=InstrumentArticlesResponse,
    summary="All articles of an instrument",
    description=(
        "The articles in force of this instrument (BWB id or CELEX number), in the order "
        "of the document: an article with only a heading (the Algemene bepaling of the "
        "Grondwet) where it stands, an article of an annex after the regulation; the "
        "annexes themselves in ``annexes``. `include_repealed` "
        "adds the repealed identities (last). The text is a short preview; "
        "/api/articles/{bwb_id}/{address} has the full content. ``division`` cuts the "
        "list to the articles of one division (``total`` and the pages count those), "
        "with the division itself in ``division``; 404 when no article stands in it."
    ),
    tags=["instruments"],
)
def list_articles(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    include_stubs: Annotated[
        bool,
        Query(description="Include placeholder/stub articles (default: false)"),
    ] = False,
    include_repealed: Annotated[
        bool,
        Query(
            description="Include the articles no longer in force: identities whose "
            "number another article has now, and articles their current version repeals."
        ),
    ] = False,
    text_preview_chars: Annotated[
        int, Query(ge=0, le=600, description="Chars of text to inline as preview")
    ] = 160,
    limit: LongListLimit = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
    division: Annotated[
        str | None, Query(max_length=300, description=_DIVISION_HELP)
    ] = None,
) -> InstrumentArticlesResponse:
    filters = {"include_stubs": include_stubs, "include_repealed": include_repealed}
    shown: InstrumentDivisionDTO | None = None
    if division is None:
        docs, total = get_articles(store, bwb_id, **filters, limit=limit, offset=offset)
    else:
        anchor = as_anchor(division)
        part = get_division_articles(
            store, bwb_id, anchor, **filters, limit=limit, offset=offset
        )
        if part is None:
            raise NotFound("Division", division)
        docs, total = part.items, part.total
        shown = InstrumentDivisionDTO.from_path(anchor, part.path, part.start)
    scope = scope_of(bwb_id)
    annexes = (
        get_law_annexes(store, scope.value, text_chars=text_preview_chars)
        if scope.prop == "bwb_id"
        else []
    )
    return InstrumentArticlesResponse(
        bwb_id=bwb_id,
        total=total,
        division=shown,
        items=[
            InstrumentArticleNodeDTO.from_document(
                d, text_preview_chars=text_preview_chars
            )
            for d in docs
        ],
        annexes=[InstrumentAnnexDTO.from_document(doc) for doc in annexes],
    )


@router.get(
    "/{bwb_id}/judgments",
    response_model=InstrumentJudgmentsResponse,
    summary="Every judgment citing this instrument",
    description=(
        "Per judgment: light metadata plus the specific articles it refers to. "
        "Meant for the case-law layer of the graph. ``total`` is the absolute "
        "count, independent of ``limit``. ``sort``: ``date`` (default), the newest "
        "first; ``cited``, the most cited articles of the law first; ``citation_count``, "
        "the most cited judgment first (a standard judgment); each then the newest. "
        "``year``, ``tier`` (repeated: any of them) and ``subject_area`` (a main area of "
        "law of the judgment's source: ``Strafrecht``) filter ``total`` and the page. "
        "``facets`` counts the judgments, not the page: per ``year`` without the "
        "``year`` filter, per ``tier`` (most first) without the ``tier`` filter, per "
        "``subject_area`` (most first) without the ``subject_area`` filter, each "
        "under the other filters."
    ),
    tags=["instruments"],
)
def get_instrument_judgments_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: LongListLimit = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[JudgmentSort, Query()] = "date",
    year: Annotated[
        str | None,
        Query(
            pattern=r"^\d{4}$",
            description="The judgments of this year (of their date) alone; "
            "``facets.year`` still counts every year.",
        ),
    ] = None,
    tier: Annotated[
        list[Tier] | None,
        Query(
            description="The tier: `hoge_raad`, `gerechtshof`, `andere_instantie`, …; "
            "repeated, the judgments of any of them; ``facets.tier`` still counts every "
            "tier."
        ),
    ] = None,
    subject_area: Annotated[
        str | None,
        Query(
            description="A main area of law of the judgment's source, as "
            "``facets.subject_area`` writes it: `Strafrecht`, `Civiel recht`, "
            "`Bestuursrecht`; ``facets.subject_area`` still counts every area."
        ),
    ] = None,
) -> InstrumentJudgmentsResponse:
    found = get_citing_judgments(
        store,
        bwb_id,
        sort=sort,
        limit=limit,
        offset=offset,
        year=year,
        tiers=tuple(t.value for t in tier or ()),
        area=(subject_area or "").strip() or None,
    )
    return InstrumentJudgmentsResponse(
        bwb_id=bwb_id,
        total=found.total,
        year=year,
        sort=sort,
        facets=InstrumentJudgmentFacets(
            year=[FacetCountDTO(**row) for row in found.years],
            tier=[FacetCountDTO(**row) for row in found.tiers],
            subject_area=[FacetCountDTO(**row) for row in found.areas],
        ),
        items=[InstrumentJudgmentItem.from_row(row) for row in found.items],
    )


@router.get(
    "/{bwb_id}/dossiers",
    response_model=InstrumentDossiersResponse,
    summary="Parliamentary dossiers touching this law",
    description=(
        "Dossiers reached through LEGISLATED_IN from (a) the regulation itself "
        "and (b) the amending publications (Stb/Trb) that change, introduce or "
        "repeal one of its articles. ``via`` says how the dossier is linked "
        "(``instrument`` or ``amending_publication``; in the latter case "
        "``publication`` names the newest publication). ``total`` is the "
        "absolute count, independent of ``limit``. ``sort`` ``opened`` (default): newest "
        "opened first; ``importance``: the dossiers of the regulation itself first, then "
        "those with the most amending publications, then the newest opened."
    ),
    tags=["instruments"],
)
def get_instrument_dossiers_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: LongListLimit = 500,
    sort: Annotated[OpenedSort, Query()] = "opened",
) -> InstrumentDossiersResponse:
    rows, total = get_instrument_dossiers(store, bwb_id, limit=limit, sort=sort)
    items = [InstrumentDossierItem.from_row(row) for row in rows]
    return InstrumentDossiersResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/amended-by",
    response_model=AmendedByResponse,
    summary="Amending publications of a regulation",
    description=(
        "The publications (Staatsblad, Staatscourant, Tractatenblad, ...) that enacted "
        "this regulation (ESTABLISHES its articles) or change, introduce or repeal "
        "articles of it (AMENDS / INTRODUCES / REPEALS), newest first. Per publication: "
        "the edge count per "
        "kind, the number of articles affected, the first effective date and the "
        "dossiers. ``total`` is the absolute count, independent of ``limit`` "
        "and ``offset``. Apart from them, in ``proposals``, the papers of the "
        "Tweede Kamer that propose to change it and are pending. ``sort`` ``date`` "
        "(default) is newest first; ``importance`` puts the publication that affected the "
        "most articles first (``articles_affected``), then the newest."
    ),
    tags=["instruments"],
)
def get_instrument_amended_by_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[DateSort, Query()] = "date",
) -> AmendedByResponse:
    data = get_instrument_amended_by(
        store, bwb_id, limit=limit, offset=offset, sort=sort
    )
    titles = data.dossier_titles
    return AmendedByResponse(
        bwb_id=bwb_id,
        total=data.total,
        items=[AmendingInstrumentDTO.from_row(r, titles) for r in data.items],
        proposals_total=data.proposals_total,
        proposals=[AmendingProposalDTO.from_row(r, titles) for r in data.proposals],
    )


@router.get(
    "/{bwb_id}/related-instruments",
    response_model=InstrumentRelatedResponse,
    summary="Instruments referring to this one, or referred to by it",
    description=(
        "The other laws in force whose articles in force refer to articles in force of "
        "this law, or the other way (`REFERS_TO` between articles), the most articles "
        "first; an expired law (`date_expired` passed) is left out. Each "
        "carries its `kind` and `date_in_force`, the `direction`, the articles at both "
        "ends (`outbound_count` articles of this law refer to `outbound_cited_count` of "
        "it; `inbound_count` of its articles refer to `inbound_cited_count` of this law) "
        "and `basis`: whether one is issued under the other as well (`BASED_ON`), with "
        "the articles its preamble names. ``total`` is the absolute count, independent of "
        "``limit``; ``based_on_total`` how many of those have a `basis`. The articles "
        "between the two: `.../references/{other}`."
    ),
    tags=["instruments"],
)
def get_instrument_related_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 100,
) -> InstrumentRelatedResponse:
    rows, total, based_on = get_instrument_related_instruments(
        store, bwb_id, limit=limit
    )
    items = [InstrumentRelatedItem.from_row(r) for r in rows]
    return InstrumentRelatedResponse(
        bwb_id=bwb_id, total=total, based_on_total=based_on, items=items
    )


@router.get(
    "/{bwb_id}/references/{other}",
    response_model=InstrumentReferencesResponse,
    summary="The references between the articles of two instruments",
    description=(
        "Every reference (`REFERS_TO`) from an article in force of this instrument to an "
        "article in force of `other`, then the other way (`direction` `outbound`, "
        "`inbound`), in the order of the referring and the referred article: the `source` "
        "and `target` articles, the words of the reference (`text`), the parts of the "
        "target it names and its `semantic_type`. Both are a BWB id or a CELEX number; "
        "empty for an unknown one or the same one twice."
    ),
    tags=["instruments"],
)
def get_instrument_references_route(
    bwb_id: str,
    other: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> InstrumentReferencesResponse:
    items = [
        InstrumentReferenceDTO.from_row(row)
        for row in get_instrument_references(store, bwb_id, other)
    ]
    return InstrumentReferencesResponse(
        bwb_id=bwb_id, other=other, total=len(items), items=items
    )


_VALIDITY = Query(
    description="Those in force today (`in_force`), those no longer in force (`expired`) or "
    "`all`, as on the list of instruments."
)


@router.get(
    "/{bwb_id}/delegated",
    response_model=InstrumentDelegatedResponse,
    summary="Regulations issued under a law",
    description=(
        'The regulations whose preamble ("Gelet op") names an article in force of this '
        "law as their legal basis (`BASED_ON`), one per regulation with the "
        "articles it names, whether those give the power it is made under (`basis_kind`), "
        "its articles that work each out (`referring`), the other laws it names "
        "(`also_based_on`) and the regulations issued under it in turn (`sub_delegated`): "
        "AMvBs first, then ministerial regulations, then the others; by title. By "
        "`validity` those in force (the default), those no longer in force (`expired_on` "
        "today or before) or all, each with its `expired_on`; `expired_total` counts the "
        "ones no longer in force whatever was asked for and `by_kind` the items per kind. "
        "A repealed article is left out. `detail=summary`: the light form, per regulation "
        "only the articles of the law it names, without `referring` and `also_based_on`, with "
        "`sub_delegated` (its articles without `referring`). Empty for an unknown instrument."
    ),
    tags=["instruments"],
)
def get_instrument_delegated_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    validity: Annotated[Validity, _VALIDITY] = "in_force",
    detail: Annotated[
        Literal["full", "summary"],
        Query(description="`summary`: the light form, see the description."),
    ] = "full",
) -> InstrumentDelegatedResponse:
    rows = get_delegated_by_law(store, bwb_id, validity, detail == "summary")
    items: list[InstrumentDelegatedItem] | list[InstrumentDelegatedSummaryItem]
    if detail == "summary":
        items = in_regulation_order(
            InstrumentDelegatedSummaryItem.from_row(row) for row in rows
        )
    else:
        items = in_regulation_order(
            InstrumentDelegatedItem.from_row(row) for row in rows
        )
    return InstrumentDelegatedResponse(
        bwb_id=bwb_id,
        total=len(items),
        expired_total=count_expired_delegated(store, bwb_id),
        by_kind=dict(Counter(item.kind or "unknown" for item in items)),
        items=items,
    )


@router.get(
    "/{bwb_id}/basis",
    response_model=InstrumentBasisResponse,
    summary="The laws a regulation is issued under",
    description=(
        'The legal basis of a regulation: per law its preamble ("Gelet op") names an '
        "article in force of (`BASED_ON`), by title, the articles it names with the leden "
        "and onderdelen, whether they give the power it is made under (`basis_kind`) and "
        "the articles of the regulation that refer to each (`referring`). By `validity` "
        "the laws in force (the default), those no longer in force or all, each with its "
        "`expired_on`; `expired_total` counts the ones no longer in force whatever was "
        "asked for. Empty for a law without a preamble basis and for an unknown "
        "instrument. The other way: `.../delegated`."
    ),
    tags=["instruments"],
)
def get_instrument_basis_route(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
    validity: Annotated[Validity, _VALIDITY] = "in_force",
) -> InstrumentBasisResponse:
    instrument = resolve_instrument(store, bwb_id)
    rows = get_basis(store, instrument["id"]) if instrument else []
    kept = [
        r for r in rows if validity == "all" or r["expired"] == (validity == "expired")
    ]
    items = [InstrumentBasisItem.from_row(row) for row in kept]
    return InstrumentBasisResponse(
        bwb_id=bwb_id,
        total=len(items),
        expired_total=sum(1 for r in rows if r["expired"]),
        items=items,
    )


@router.get(
    "/{bwb_id}/versions",
    response_model=InstrumentVersionsResponse,
    summary="Historical versions of an instrument",
    description=(
        "Every historical toestand (version) of a BWB law, newest first. Each "
        "version carries a validity period (valid_from, valid_until); the "
        "current one has ``current=true``."
    ),
    tags=["instruments"],
)
def list_instrument_versions(
    bwb_id: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> InstrumentVersionsResponse:
    docs = get_instrument_versions(store, bwb_id)
    items = [InstrumentVersionDTO.from_document(d) for d in docs]
    return InstrumentVersionsResponse(bwb_id=bwb_id, total=len(items), items=items)


@router.get(
    "/{bwb_id}/articles/at/{at_date}",
    response_model=InstrumentArticlesAtResponse,
    summary="Articles as they stood on a given date",
    description=(
        "The articles of a BWB instrument as they applied on ``at_date`` "
        "(YYYY-MM-DD), read from the article versions, in the order of that day's "
        "toestand, each with the divisions it stood in that day (``breadcrumb``). Empty "
        "before the first toestand of the law (``first_version_from``) and when no "
        "version covers that date. ``text_preview`` is the start of the text; with "
        "``text_preview_chars`` the whole ``text`` is left out unless "
        "``include_text=true``; with the text come its ``parts`` (spans, nested by id). "
        "``limit`` and ``offset`` page, ``total`` counts every "
        "article. ``division`` cuts the list to the articles that stood in one division "
        "that day, with the division itself in ``division``; 404 when none did. "
        "``include=references`` adds the references and citations of each article in "
        "its current version, so a reader of the whole law asks for no article apart."
    ),
    tags=["instruments"],
)
def list_articles_at(
    bwb_id: str,
    at_date: dt.date,
    store: Annotated[GraphStore, Depends(get_store)],
    text_preview_chars: Annotated[
        int | None,
        Query(
            ge=0,
            le=600,
            description=f"Chars of text to inline as preview (default "
            f"{TEXT_PREVIEW_CHARS}); given, the "
            "whole text is left out unless include_text=true",
        ),
    ] = None,
    include_text: Annotated[
        bool | None,
        Query(
            description="Give the whole text; default: true unless text_preview_chars "
            "is given"
        ),
    ] = None,
    limit: LongListLimit = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
    division: Annotated[
        str | None, Query(max_length=300, description=_DIVISION_HELP)
    ] = None,
    include: Annotated[
        Literal["references"] | None,
        Query(
            description="``references``: each article that stands in its current "
            "version gets its ``references`` and ``citations``, as the article gives them."
        ),
    ] = None,
) -> InstrumentArticlesAtResponse:
    on = at_date.isoformat()
    shown: InstrumentDivisionDTO | None = None
    if division is None:
        law = get_articles_at(store, bwb_id, on, limit=limit, offset=offset)
    else:
        anchor = as_anchor(division)
        part = get_division_articles_at(
            store, bwb_id, on, anchor, limit=limit, offset=offset
        )
        if part is None:
            raise NotFound("Division", division)
        law = LawOnADate(part.items, part.total, part.first_version_from)
        shown = InstrumentDivisionDTO.from_path(anchor, part.path, part.start)
    whole = text_preview_chars is None if include_text is None else include_text
    current = get_current_references(store, law.items) if include else None
    return InstrumentArticlesAtResponse(
        bwb_id=bwb_id,
        at_date=on,
        total=law.total,
        first_version_from=law.first_version_from,
        division=shown,
        items=[
            InstrumentArticleVersionDTO.from_document(
                d,
                on=on,
                text_preview_chars=(
                    TEXT_PREVIEW_CHARS
                    if text_preview_chars is None
                    else text_preview_chars
                ),
                include_text=whole,
                current=current,
            )
            for d in law.items
        ],
    )
