"""Citation detection shared by the linkers of running text (TK papers, judgments)."""

from __future__ import annotations

from typing import Callable

from lawgraph.core.aliases import InstrumentAliasMap
from lawgraph.core.citations import CitationHit, DutchCitationExtractor
from lawgraph.core.eu_citations import (
    ARTICLE_NUMBER_ANY_LETTERS,
    EUCitationConfidence,
    build_article_patterns,
    collect_article_hits,
    collect_bwb_id_hits,
    collect_celex_literal_hits,
    collect_year_number_hits,
)

CONFIDENCE = EUCitationConfidence(
    article_with_instrument=0.88,  # "artikel X van Richtlijn/Besluit/... YYYY/N"
    celex_literal=0.90,  # CELEX ID literal in text
    instrument_year_number=0.65,  # directive/regulation via year + number only
    bwb_id=0.75,  # bare BWB id in text
)

# Running text: any letters on the article number, "de"/"het" allowed before the
# instrument name, and decisions and framework decisions as well.
_EU_ARTICLE_PATTERNS = build_article_patterns(
    ARTICLE_NUMBER_ANY_LETTERS,
    kinds=("directive", "regulation", "decision", "framework_decision"),
    allow_determiner=True,
)


def build_extractor(
    code_aliases: dict[str, str], instrument_aliases: InstrumentAliasMap
) -> DutchCitationExtractor:
    """Extractor that resolves law codes and full law names ("artikel 5 van de Wegenwet")."""
    name_aliases = {
        name: bwb_id or celex
        for name, (bwb_id, celex) in instrument_aliases.items()
        if bwb_id or celex
    }
    return DutchCitationExtractor(code_aliases=code_aliases, name_aliases=name_aliases)


def collect_eu_hits(text: str, record: Callable[[CitationHit], None]) -> None:
    """EU and literal-identifier hits: articles of directives, CELEX and BWB ids, year/number."""
    collect_bwb_id_hits(text, CONFIDENCE.bwb_id, record)
    collect_celex_literal_hits(text, CONFIDENCE.celex_literal, record)
    collect_year_number_hits(text, CONFIDENCE.instrument_year_number, record)
    collect_article_hits(
        text, _EU_ARTICLE_PATTERNS, CONFIDENCE.article_with_instrument, record
    )


def hit_identity(hit: CitationHit) -> tuple[str, str | None, str | None, str | None]:
    return (hit.kind, hit.bwb_id, hit.celex, hit.article_number)


def detect_in_text(
    text: str,
    extractor: DutchCitationExtractor,
    *,
    extra: Callable[[str, Callable[[CitationHit], None]], None] | None = None,
) -> list[CitationHit]:
    """Article hits of *extractor* plus the EU hits (and *extra* ones), once per citation."""
    hits = extractor.extract(text)
    seen = {hit_identity(h) for h in hits}

    def record(hit: CitationHit) -> None:
        if hit_identity(hit) not in seen:
            seen.add(hit_identity(hit))
            hits.append(hit)

    if extra is not None:
        extra(text, record)
    collect_eu_hits(text, record)
    return hits
