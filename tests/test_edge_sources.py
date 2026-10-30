"""The source a pipeline writes on its edges, by which it removes its own stale ones.

The labels are stored on the edges of the database, so a change of one leaves the edges of
the old label behind: ``LABELS`` holds each as stored, and a label derived from the name of
the pipeline (``sources.addresses.edge_source``) must give the same.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import lawgraph.pipelines.normalize as normalize
import lawgraph.pipelines.semantic as semantic
from lawgraph.config.constants import EDGE_SOURCE_BWB_IMPLEMENTS
from lawgraph.pipelines.normalize._tk_cases import LinkRecordsPipelineBase
from lawgraph.sources.addresses import edge_source

# Per pipeline module, the edge sources it names, as stored.
LABELS: dict[str, dict[str, str]] = {
    "normalize.bwb": {"EDGE_SOURCE": "bwb-normalize"},
    "normalize.bwb_history": {"EDGE_SOURCE": "bwb-history-normalize"},
    "normalize.eerstekamer_agenda": {"EDGE_SOURCE": "eerstekamer-agenda"},
    "normalize.eerstekamer_composition": {"EDGE_SOURCE": "eerstekamer-composition"},
    "normalize.eerstekamer_motions": {"EDGE_SOURCE": "eerstekamer-motions"},
    "normalize.eerstekamer_votes": {"EDGE_SOURCE": "eerstekamer-votes"},
    "normalize.eurlex": {"EDGE_SOURCE": "eu-normalize"},
    "normalize.staatsblad_laws": {"EDGE_SOURCE": "staatsblad-laws"},
    "normalize.tk_case_actors": {"EDGE_SOURCE": "tk-case-actors"},
    "normalize.tk_document_links": {"EDGE_SOURCE": "tk-document-links"},
    "normalize.tk_dossiers": {"EDGE_SOURCE": "tk-dossiers"},
    "semantic.bwb": {"EDGE_SOURCE": "bwb-article-references"},
    "semantic.bwb_amendments": {"EDGE_SOURCE": "bwb-amendments"},
    "semantic.bwb_annexes": {"EDGE_SOURCE": "bwb-annex-links"},
    "semantic.bwb_grondslagen": {"EDGE_SOURCE": "bwb-grondslagen-linker"},
    "semantic.bwb_implements": {"EDGE_SOURCE": "bwb-implements"},
    "semantic.bwb_publications": {"EDGE_SOURCE": "bwb-publication-linker"},
    "semantic.echr": {"EDGE_SOURCE": "echr-citation-linker"},
    "semantic.echr_versions": {"EDGE_SOURCE": "echr-version-linker"},
    "semantic.eerstekamer": {"EDGE_SOURCE": "ek-dossier-linker"},
    "semantic.kst_sru": {"EDGE_SOURCE": "kst-sru"},
    "semantic.eurlex": {"EDGE_SOURCE": "eu-article-linker"},
    "semantic.eurlex_cjeu": {"EDGE_SOURCE": "eurlex-cjeu"},
    "semantic.rechtspraak": {"EDGE_SOURCE": "rechtspraak-article-linker"},
    "semantic.staatsblad_law_references": {"EDGE_SOURCE": "staatsblad-law-references"},
    "semantic.rechtspraak_appeal": {"EDGE_SOURCE": "rechtspraak-appeal-linker"},
    "semantic.rechtspraak_citations": {"EDGE_SOURCE": "judgment-citation-linker"},
    "semantic.rechtspraak_conclusions": {
        "EDGE_SOURCE": "rechtspraak-conclusion-linker"
    },
    "semantic.rechtspraak_duplicates": {"EDGE_SOURCE": "rechtspraak-duplicate-linker"},
    "semantic.rechtspraak_referrals": {"EDGE_SOURCE": "rechtspraak-referral-linker"},
    "semantic.rechtspraak_related": {"EDGE_SOURCE": "rechtspraak-related-cases"},
    "semantic.staatsblad": {"EDGE_SOURCE": "staatsblad-nvt-linker"},
    "semantic.staatscourant": {"EDGE_SOURCE": "staatscourant-regeling-linker"},
    "semantic.tk": {"EDGE_SOURCE": "tk-article-linker"},
    "semantic.tk_amendment_articles": {"EDGE_SOURCE": "amendment-article-linker"},
    "semantic.tk_amends": {"EDGE_SOURCE": "tk-amends-instrument"},
    "semantic.tk_cited_papers": {"EDGE_SOURCE": "tk-cited-papers"},
    "semantic.tk_dossier_relations": {"EDGE_SOURCE": "tk-dossier-relations"},
    "semantic.tk_transposition_tables": {"EDGE_SOURCE": "tk-transposition-tables"},
    "semantic.tk_government": {"EDGE_SOURCE": "tk-government"},
    "semantic.tk_mvt": {
        "EDGE_SOURCE": "mvt-article-linker",
        "EDGE_SOURCE_SECTIONS": "mvt-section-linker",
    },
    # the sections of a memorandum, whose label ``semantic tk-mvt`` leaves alone
    "semantic.tk_mvt_articles": {
        "EDGE_SOURCE": "mvt-section-linker",
        "EDGE_SOURCE_DOSSIER": "mvt-article-linker",
        "EDGE_SOURCE_SECTIONS": "mvt-section-linker",
    },
    "semantic.tk_faction_succession": {"EDGE_SOURCE": "tk-faction-succession"},
    "semantic.tk_person_duplicates": {"EDGE_SOURCE": "tk-person-duplicates"},
    "semantic.tooi_ministries": {"EDGE_SOURCE": "tooi-ministries"},
    "semantic.verdragenbank": {"EDGE_SOURCE": "verdragenbank"},
}
# The pipelines whose label is not their name. It only shrinks: renaming a stored label
# needs the edges relabelled with it.
NOT_THEIR_NAME = {
    "normalize.bwb",
    "normalize.bwb_history",
    "normalize.eurlex",
    "semantic.bwb",
    "semantic.bwb_annexes",
    "semantic.bwb_grondslagen",
    "semantic.bwb_publications",
    "semantic.echr",
    "semantic.echr_versions",
    "semantic.eerstekamer",
    "semantic.eurlex",
    "semantic.rechtspraak",
    "semantic.rechtspraak_appeal",
    "semantic.rechtspraak_citations",
    "semantic.rechtspraak_conclusions",
    "semantic.rechtspraak_duplicates",
    "semantic.rechtspraak_referrals",
    "semantic.rechtspraak_related",
    "semantic.staatsblad",
    "semantic.staatscourant",
    "semantic.tk",
    "semantic.tk_amendment_articles",
    "semantic.tk_amends",
    "semantic.tk_mvt",
    "semantic.tk_mvt_articles",
}


def _modules() -> dict[str, ModuleType]:
    return {
        f"{package.__name__.rsplit('.', 1)[1]}.{info.name}": importlib.import_module(
            f"{package.__name__}.{info.name}"
        )
        for package in (normalize, semantic)
        for info in pkgutil.iter_modules(package.__path__)
        if not info.name.startswith("_") and info.name != "base"
    }


def _labels(module: ModuleType) -> dict[str, str]:
    """The edge sources *module* names: its ``EDGE_SOURCE*`` constants, and the label of a
    pipeline of linked records (``LinkRecordsPipelineBase``), which is its name."""
    found = {
        name: value
        for name, value in vars(module).items()
        if name.startswith("EDGE_SOURCE") and isinstance(value, str)
    }
    if module.__name__ == "lawgraph.pipelines.semantic.bwb_implements":
        found["EDGE_SOURCE"] = found.pop("EDGE_SOURCE_BWB_IMPLEMENTS")
    links = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, LinkRecordsPipelineBase)
        and value.__module__ == module.__name__
    ]
    if links:
        found["EDGE_SOURCE"] = edge_source(module.__name__)
    return found


def test_every_label_is_the_one_stored() -> None:
    found = {name: labels for name, m in _modules().items() if (labels := _labels(m))}
    assert found == LABELS


def test_each_pipeline_writes_a_label_of_its_own() -> None:
    owners: dict[str, list[str]] = {}
    for name, labels in LABELS.items():
        owners.setdefault(labels["EDGE_SOURCE"], []).append(name)
    shared = {label: names for label, names in owners.items() if len(names) > 1}
    assert shared == {}


def test_a_label_is_the_name_of_its_pipeline() -> None:
    modules = _modules()
    found = {
        name
        for name, labels in LABELS.items()
        if labels["EDGE_SOURCE"] != edge_source(modules[name].__name__)
    }
    assert found == NOT_THEIR_NAME
    assert EDGE_SOURCE_BWB_IMPLEMENTS == edge_source(
        "lawgraph.pipelines.semantic.bwb_implements"
    )
