from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from config.config import load_domain_config


def load_profile_config(profile: str | None) -> dict[str, Any]:
    """Return the domain config for the given profile, if available."""
    if not profile:
        return {}

    try:
        return load_domain_config(profile)
    except FileNotFoundError:
        return {}


def tk_filters(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("filters", {}).get("tk", {})


def rechtspraak_filters(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("filters", {}).get("rechtspraak", {})


def eurlex_filters(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("filters", {}).get("eurlex", {})


def seed_examples(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("seed_examples", {})


def make_tk_filter(filters: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
    title_keywords = [
        keyword.strip().lower()
        for keyword in filters.get("title_contains", [])
        if isinstance(keyword, str) and keyword.strip()
    ]
    dossier_keywords = [
        keyword.strip().lower()
        for keyword in filters.get("dossier_keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    ]

    def matcher(record: dict[str, Any]) -> bool:
        candidates = [
            record.get("Titel"),
            record.get("ZaakTitel"),
            record.get("Omschrijving"),
            record.get("TitelMetBijlagen"),
            record.get("ZaakNummer"),
        ]
        for candidate in candidates:
            text = str(candidate) if candidate is not None else None
            if _text_contains_keywords(text, title_keywords):
                return True

        if dossier_keywords:
            record_text = json.dumps(record, default=str)
            if _text_contains_keywords(record_text, dossier_keywords):
                return True

        return False

    return matcher


def build_rechtspraak_params(filters: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    rechtsgebieden = [
        str(item).strip() for item in filters.get("rechtsgebieden", []) if item
    ]
    if rechtsgebieden:
        params["rechtsgebieden"] = ",".join(rechtsgebieden)

    search_terms = [
        str(term).strip() for term in filters.get("search_terms", []) if term
    ]
    if search_terms:
        joined = " ".join(search_terms)
        params["zoekterm"] = joined
        params["searchterm"] = joined

    return params


def merge_celex_ids(
    eurlex_filters: dict[str, Any],
    seed_examples: dict[str, Any],
) -> list[str]:
    candidate_ids: list[str] = []
    candidate_ids.extend(
        str(item) for item in eurlex_filters.get("celex_ids", []) if item
    )
    candidate_ids.extend(
        str(item) for item in seed_examples.get("extra_celex_candidates", []) if item
    )

    return list(dict.fromkeys(candidate_ids))


def _text_contains_keywords(value: str | None, keywords: list[str]) -> bool:
    if not value:
        return False

    lowered = value.lower()
    for keyword in keywords:
        if keyword and keyword in lowered:
            return True
    return False
