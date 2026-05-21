"""Backward-compatibility shim — all logic now lives in lawgraph.config."""

from __future__ import annotations

from lawgraph.config import (  # noqa: F401
    CONFIG_DIR,
    list_domain_configs,
    list_domain_profiles,
    load_domain_config,
    load_strafrecht_config,
)
