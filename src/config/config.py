from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent


def _resolve_domain_path(domain: str, path: Path | str | None = None) -> Path:
    if path:
        return Path(path)
    return CONFIG_DIR / f"{domain}.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError("%s must contain a mapping at top level" % path.name)

    return data


def load_domain_config(domain: str, path: Path | str | None = None) -> dict[str, Any]:
    """
    Load a domain-specific profile such as strafrecht from the config directory.
    """
    config_path = _resolve_domain_path(domain, path)
    return _load_yaml(config_path)


def list_domain_configs() -> list[str]:
    """Return the set of available domain profiles (sans extension)."""
    names: list[str] = []
    for path in CONFIG_DIR.glob("*.yml"):
        if path.is_file():
            names.append(path.stem)
    return sorted(names)


def load_strafrecht_config(path: Path | str | None = None) -> dict[str, Any]:
    """Convenience wrapper for the strafrecht profile."""
    return load_domain_config("strafrecht", path)
