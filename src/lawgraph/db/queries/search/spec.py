"""What the search knows of a type (``SearchType``) and what a search is asked (``Asked``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.notation import Notation
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.clause import Period

Hit = dict[str, Any]

# SQL: of a judgment hit ``r`` (a row of ``judgments``) what its ``cite`` is made of
# (``core.judgment_cite.cite_of``), beside its ``extra``: the route makes it and leaves
# these out.
JUDGMENT_CITE_PROPS = """'cite_props', json_build_object(
            'date', r.props -> 'date', 'date_eff', to_json(r.date_eff),
            'court', r.props -> 'court',
            'advocate_general', r.props -> 'advocate_general',
            'advocate_general_role', r.props -> 'advocate_general_role',
            'case_number', r.props -> 'case_number'
        )"""


@dataclass(frozen=True)
class Asked:
    """One search: the query and its tokens (``tokenize_search_query``), the citation it is
    (``parser.notation``), the kinds of documents and dossiers asked for, the most hits per
    type and the period."""

    store: GraphStore
    q: str
    tokens: list[str]
    notation: Notation | None
    kinds: list[str] | None
    limit: int
    period: Period


@dataclass(frozen=True)
class SearchType:
    """One type ``/api/search`` searches, named as its collection (*table*).

    *search* finds its hits for an ``Asked`` (with ``live``: while typing, nothing ranked by
    its words), given this record. A type whose words are searched in ``SEARCH_FIELDS``
    (``text.text_query``) has its *fields*, the *boosts* of the fields its rank weighs more,
    and *live_order*, the order of its hits while typing, by its columns alone. Of a type
    whose common words rank only their first ``RANK_CANDIDATES`` hits, *candidate_order* is
    the order of those (its hits of the words searched most are kept ready,
    ``candidates.py``), and *citations* what its rank reads of a hit besides its words
    (``CITATION_PRIOR``). *period_date* is the SQL of its date of a row ``{row}``, which a
    period asks for; a type without one finds nothing with a period. A *heavy* type's full
    search takes long cold: it takes a thread of the pool first (``dispatch``)."""

    table: str
    search: Callable[[SearchType, Asked, bool], list[Hit]]
    fields: list[str] = field(default_factory=list)
    boosts: dict[str, float] = field(default_factory=dict)
    live_order: str = ""
    candidate_order: str | None = None
    citations: str | None = None
    period_date: str | None = None
    heavy: bool = False
