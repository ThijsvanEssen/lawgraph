"""What the search knows of a type (``SearchType``) and what a search is asked (``Asked``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.notation import Notation
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.clause import Period
from lawgraph.db.queries.search.signers import Signed, signed_sql

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
    """One search: the query and its words (``clause.query_words``), the citation it is
    (``parser.notation``), the kinds of documents and dossiers asked for, the most hits per
    type, the period, the factions it names (``signers.signed_for``), whether a hit holds
    one of its words at least (*any_word*) instead of every one, and the kinds of motion
    asked for (*motion_kinds*, ``core.motion_kinds``: of the papers and the votes)."""

    store: GraphStore
    q: str
    tokens: list[str]
    notation: Notation | None
    kinds: list[str] | None
    limit: int
    period: Period
    signed: Signed | None = None
    any_word: bool = False
    motion_kinds: list[str] | None = None

    def words(self, kind: SearchType) -> list[str]:
        """The tokens *kind* is searched by: of a type with signatures, without those that
        name a faction."""
        return self.signed.words if self.signed and kind.signatures else self.tokens

    def signed_where(
        self, kind: SearchType, row: str = "r"
    ) -> tuple[str, dict[str, Any]]:
        """``AND`` a row *row* of *kind* signed for each faction the query names, and its
        parameters; empty for a type without signatures or a query that names none."""
        if not self.signed or not kind.signatures:
            return "", {}
        return signed_sql(kind.signatures(row), self.signed)


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
    search takes long cold: it takes a thread of the pool first (``dispatch``). *names*
    are the fields of its names: a hit one of which starts with the query is a tier above
    those with every word of it in one of its *titles*, the fields of its own name and of
    the titles it stands in, which are a tier above the hits that only hold the words
    (``score_hit``, ``text.tier_sql``). *signatures* makes the SQL of the signatures of a
    row (a JSON array of ``actors``) of its alias: a query that names a faction keeps the
    hits signed for it (``signers``)."""

    table: str
    search: Callable[[SearchType, Asked, bool], list[Hit]]
    fields: list[str] = field(default_factory=list)
    boosts: dict[str, float] = field(default_factory=dict)
    live_order: str = ""
    candidate_order: str | None = None
    citations: str | None = None
    period_date: str | None = None
    heavy: bool = False
    names: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    signatures: Callable[[str], str] | None = None
