"""Declarative registry of all data sources and their pipeline entry points.

Adding a new source (e.g. senate documents, bilateral treaties) means:
  1. Write a retrieve CLI main function and a retrieve pipeline.
  2. Optionally write normalize and semantic pipeline CLIs.
  3. Add a SourceDescriptor here.

The ``retrieve_all``, ``normalize_all``, and ``semantic_all`` orchestrators
iterate ``SOURCES`` to build their step lists — no changes needed there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SourceDescriptor:
    """Declarative description of a data source and its pipeline entry points.

    Each phase (retrieve / normalize / semantic) is optional. When a phase
    has no CLI entry point, that step is simply skipped by the orchestrators.

    ``supports_full_load`` signals that the retrieve CLI accepts ``--mode=full``
    for a complete backfill without a date window.
    """

    id: str
    display_name: str

    # ── Retrieve phase ────────────────────────────────────────────────────────
    retrieve_main: Callable[..., None] | None = None
    retrieve_skip_env: str | None = None

    # ── Normalize phase ───────────────────────────────────────────────────────
    normalize_main: Callable[..., None] | None = None
    normalize_skip_env: str | None = None

    # ── Semantic phase ────────────────────────────────────────────────────────
    semantic_main: Callable[..., None] | None = None
    semantic_skip_env: str | None = None

    supports_full_load: bool = False


def _build_registry() -> list[SourceDescriptor]:
    # Imports are deferred so importing this module never triggers heavy
    # pipeline or client initialisation at import time.
    from lawgraph.cli.normalize_bwb import main as normalize_bwb_main
    from lawgraph.cli.normalize_echr import main as normalize_echr_main
    from lawgraph.cli.normalize_eerstekamer import main as normalize_eerstekamer_main
    from lawgraph.cli.normalize_eurlex import main as normalize_eurlex_main
    from lawgraph.cli.normalize_rechtspraak import main as normalize_rechtspraak_main
    from lawgraph.cli.normalize_staatsblad import main as normalize_staatsblad_main
    from lawgraph.cli.normalize_staatscourant import (
        main as normalize_staatscourant_main,
    )
    from lawgraph.cli.normalize_tk import main as normalize_tk_main
    from lawgraph.cli.normalize_tk_dossiers import main as normalize_tk_dossiers_main
    from lawgraph.cli.normalize_verdragenbank import (
        main as normalize_verdragenbank_main,
    )
    from lawgraph.cli.retrieve_bwb import main as retrieve_bwb_main
    from lawgraph.cli.retrieve_echr import main as retrieve_echr_main
    from lawgraph.cli.retrieve_eerstekamer import main as retrieve_eerstekamer_main
    from lawgraph.cli.retrieve_eurlex import main as retrieve_eurlex_main
    from lawgraph.cli.retrieve_rechtspraak import main as retrieve_rechtspraak_main
    from lawgraph.cli.retrieve_staatsblad import main as retrieve_staatsblad_main
    from lawgraph.cli.retrieve_staatscourant import main as retrieve_staatscourant_main
    from lawgraph.cli.retrieve_tk import main as retrieve_tk_main
    from lawgraph.cli.retrieve_tk_dossiers import main as retrieve_tk_dossiers_main
    from lawgraph.cli.retrieve_verdragenbank import main as retrieve_verdragenbank_main
    from lawgraph.cli.semantic_amendment_articles import (
        main as semantic_amendment_articles_main,
    )
    from lawgraph.cli.semantic_bwb_articles import main as semantic_bwb_main
    from lawgraph.cli.semantic_bwb_grondslagen import (
        main as semantic_bwb_grondslagen_main,
    )
    from lawgraph.cli.semantic_dossier_law_link import (
        main as semantic_dossier_law_link_main,
    )
    from lawgraph.cli.semantic_echr_citations import (
        main as semantic_echr_citations_main,
    )
    from lawgraph.cli.semantic_eerstekamer_dossier_link import (
        main as semantic_ek_dossier_link_main,
    )
    from lawgraph.cli.semantic_eu_articles import main as semantic_eu_main
    from lawgraph.cli.semantic_instrument_relations import (
        main as semantic_instrument_relations_main,
    )
    from lawgraph.cli.semantic_judgment_citations import (
        main as semantic_judgment_citations_main,
    )
    from lawgraph.cli.semantic_mvt_articles import main as semantic_mvt_articles_main
    from lawgraph.cli.semantic_rechtspraak_articles import (
        main as semantic_rechtspraak_main,
    )
    from lawgraph.cli.semantic_staatsblad_nvt import (
        main as semantic_staatsblad_nvt_main,
    )
    from lawgraph.cli.semantic_staatscourant_regeling import (
        main as semantic_staatscourant_regeling_main,
    )
    from lawgraph.cli.semantic_tk_articles import main as semantic_tk_main
    from lawgraph.cli.semantic_version_causes import (
        main as semantic_version_causes_main,
    )

    return [
        SourceDescriptor(
            id="tk",
            display_name="Tweede Kamer (zaken & documenten)",
            retrieve_main=retrieve_tk_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_TK",
            normalize_main=normalize_tk_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_TK",
            semantic_main=semantic_tk_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_TK",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="tk_dossiers",
            display_name="Tweede Kamer (dossiers, stemmingen, commissies)",
            retrieve_main=retrieve_tk_dossiers_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_TK_DOSSIERS",
            normalize_main=normalize_tk_dossiers_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS",
            supports_full_load=False,
        ),
        SourceDescriptor(
            id="rechtspraak",
            display_name="Rechtspraak (uitspraken)",
            retrieve_main=retrieve_rechtspraak_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_RECHTSPRAAK",
            normalize_main=normalize_rechtspraak_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_RECHTSPRAAK",
            semantic_main=semantic_rechtspraak_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="eurlex",
            display_name="EUR-Lex (EU-wetgeving)",
            retrieve_main=retrieve_eurlex_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_EURLEX",
            normalize_main=normalize_eurlex_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_EURLEX",
            semantic_main=semantic_eu_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_EU",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="bwb",
            display_name="BWB (Nederlandse wetgeving)",
            retrieve_main=retrieve_bwb_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_BWB",
            normalize_main=normalize_bwb_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_BWB",
            semantic_main=semantic_bwb_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_BWB",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="staatsblad",
            display_name="Staatsblad (NvT voor AMvBs)",
            retrieve_main=retrieve_staatsblad_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_STAATSBLAD",
            normalize_main=normalize_staatsblad_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_STAATSBLAD",
            semantic_main=semantic_staatsblad_nvt_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_STAATSBLAD",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="staatscourant",
            display_name="Staatscourant (ministeriele regelingen)",
            retrieve_main=retrieve_staatscourant_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_STAATSCOURANT",
            normalize_main=normalize_staatscourant_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_STAATSCOURANT",
            semantic_main=semantic_staatscourant_regeling_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_STAATSCOURANT_REGELING",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="eerstekamer",
            display_name="Eerste Kamer (kamerstukken & stemmingen)",
            retrieve_main=retrieve_eerstekamer_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_EERSTEKAMER",
            normalize_main=normalize_eerstekamer_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_EERSTEKAMER",
            semantic_main=semantic_ek_dossier_link_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_EK_DOSSIER_LINK",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="echr",
            display_name="ECHR HUDOC (Europees Hof voor de Rechten van de Mens)",
            retrieve_main=retrieve_echr_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_ECHR",
            normalize_main=normalize_echr_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_ECHR",
            semantic_main=semantic_echr_citations_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_ECHR_CITATIONS",
            supports_full_load=True,
        ),
        SourceDescriptor(
            id="verdragenbank",
            display_name="Verdragenbank (Nederlandse verdragen)",
            retrieve_main=retrieve_verdragenbank_main,
            retrieve_skip_env="LAWGRAPH_RETRIEVE_SKIP_VERDRAGENBANK",
            normalize_main=normalize_verdragenbank_main,
            normalize_skip_env="LAWGRAPH_NORMALIZE_SKIP_VERDRAGENBANK",
            supports_full_load=True,
        ),
        # ── Cross-source semantic steps ────────────────────────────────────
        # These don't retrieve/normalize their own documents but enrich edges
        # across multiple sources. They live in the registry so new source
        # authors can see them and understand the semantic step model.
        SourceDescriptor(
            id="judgment_citations",
            display_name="Rechtspraak citaatanalyse (CITES_JUDGMENT)",
            semantic_main=semantic_judgment_citations_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS",
        ),
        SourceDescriptor(
            id="instrument_relations",
            display_name="Instrumentrelaties (AMENDS / IMPLEMENTS)",
            semantic_main=semantic_instrument_relations_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS",
        ),
        SourceDescriptor(
            id="amendment_articles",
            display_name="Amendement-artikel koppeling (semantisch)",
            semantic_main=semantic_amendment_articles_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_AMENDMENT_ARTICLES",
        ),
        SourceDescriptor(
            id="mvt_articles",
            display_name="MvT-artikel koppeling (LICHT_TOE)",
            semantic_main=semantic_mvt_articles_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_MVT_ARTICLES",
        ),
        SourceDescriptor(
            id="bwb_grondslagen",
            display_name="BWB grondslagen (DELEGATED_BY)",
            semantic_main=semantic_bwb_grondslagen_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_BWB_GRONDSLAGEN",
        ),
        SourceDescriptor(
            id="dossier_law_link",
            display_name="Dossier → wet koppeling (RESULTED_IN)",
            semantic_main=semantic_dossier_law_link_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_DOSSIER_LAW_LINK",
        ),
        SourceDescriptor(
            id="version_causes",
            display_name="Versie-oorzaken (CAUSED_VERSION)",
            semantic_main=semantic_version_causes_main,
            semantic_skip_env="LAWGRAPH_SEMANTIC_SKIP_VERSION_CAUSES",
        ),
    ]


# Eagerly built once on first import, then cached here.
# The deferred imports inside _build_registry() mean the registry itself is
# cheap to import even if the underlying CLI modules are not yet loaded.
SOURCES: list[SourceDescriptor] = _build_registry()
