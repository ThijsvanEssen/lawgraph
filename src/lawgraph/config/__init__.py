from __future__ import annotations

from pathlib import Path
from typing import Any

from config.config import CONFIG_DIR, list_domain_configs, load_domain_config

STAFRECHT_CONFIG_PATH = CONFIG_DIR / "strafrecht.yml"


def load_strafrecht_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load the strafrecht domain profile using the shared config helper."""
    return load_domain_config("strafrecht", path)


def list_domain_profiles() -> list[str]:
    """Return the available domain profile names stored under src/config."""
    return list_domain_configs()
