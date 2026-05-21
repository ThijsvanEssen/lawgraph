from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Domain profile YAML files live alongside this package under profiles/.
CONFIG_DIR = Path(__file__).resolve().parent / "profiles"


def _resolve_domain_path(domain: str, path: Path | str | None = None) -> Path:
    if path:
        return Path(path)
    return CONFIG_DIR / f"{domain}.yml"


def _load_yaml(yaml_path: Path) -> dict[str, Any]:
    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path.name} must contain a mapping at top level")
    return data


def load_domain_config(domain: str, path: Path | str | None = None) -> dict[str, Any]:
    """Load a domain-specific profile such as strafrecht from the profiles directory."""
    return _load_yaml(_resolve_domain_path(domain, path))


def list_domain_profiles() -> list[str]:
    """Return the available domain profile names (without extension)."""
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yml") if p.is_file())


# Keep these for any code that imports from lawgraph.config directly.
list_domain_configs = list_domain_profiles


def load_strafrecht_config(path: Path | str | None = None) -> dict[str, Any]:
    """Convenience wrapper for the strafrecht profile."""
    return load_domain_config("strafrecht", path)
