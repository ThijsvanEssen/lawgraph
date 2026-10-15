"""Configuration has one home, so nothing in ``.env`` is ever ignored.

1. Only ``config/settings.py`` reads the environment (and loads ``.env`` on import).
2. ``.env.example`` lists exactly the variables that are read, each named after its setting.
"""

from __future__ import annotations

import importlib
import re

import pytest

from tests.paths import ROOT, SRC
from tests.source_scan import python_files

SETTINGS = SRC / "config" / "settings.py"

_ENVIRONMENT_ACCESS = re.compile(r"\bos\.(getenv|environ)\b|\bload_dotenv\b")


def test_only_settings_reads_the_environment() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in python_files()
        if path != SETTINGS and _ENVIRONMENT_ACCESS.search(path.read_text())
    ]
    assert offenders == []


_ENV_EXAMPLE = ROOT / ".env.example"
# A variable settings.py reads: the name a reader of it is called with.
_SETTINGS_READ = re.compile(
    r'\b(?:_flag|_int|_float|_choice|_list|os\.getenv)\(\s*"([A-Z][A-Z0-9_]+)"'
)
# One variable per pattern, the documented example of a family of names.
_FAMILIES = {
    "LAWGRAPH_CONFIDENCE_": re.compile(r"LAWGRAPH_CONFIDENCE_\w+"),
    "_SKIP_": re.compile(r"LAWGRAPH_(RETRIEVE|NORMALIZE|SEMANTIC)_SKIP_\w+"),
}


def _listed_in_env_example() -> list[str]:
    return re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", _ENV_EXAMPLE.read_text(), re.M)


def test_env_example_lists_only_variables_that_are_read() -> None:
    readers = SETTINGS.read_text() + (ROOT / "docker-compose.yml").read_text()
    listed = _listed_in_env_example()
    assert listed

    def is_read(variable: str) -> bool:
        for marker, family in _FAMILIES.items():
            if family.fullmatch(variable):
                return marker in readers
        return (
            f'"{variable}"' in readers
            or re.search(rf"\${{{variable}(:-[^}}]*)?}}", readers) is not None
        )

    assert [v for v in listed if not is_read(v)] == []


def test_every_variable_settings_reads_is_in_env_example() -> None:
    read = set(_SETTINGS_READ.findall(SETTINGS.read_text()))
    assert "LAWGRAPH_DB_URL" in read and "NO_COLOR" in read
    assert sorted(read - set(_listed_in_env_example())) == []


def test_every_setting_variable_is_named_after_its_setting() -> None:
    """``LAWGRAPH_<SETTING>`` sets ``settings.<SETTING>``: a grep for one finds the other.
    ``NO_COLOR`` is the common convention."""
    from lawgraph.config import settings

    for variable in _SETTINGS_READ.findall(SETTINGS.read_text()):
        if variable == "NO_COLOR":
            assert hasattr(settings, variable), variable
            continue
        assert variable.startswith("LAWGRAPH_"), variable
        assert hasattr(settings, variable.removeprefix("LAWGRAPH_")), variable


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " True "])
def test_a_flag_is_on(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from lawgraph.config import settings

    monkeypatch.setenv("LAWGRAPH_SOME_FLAG", raw)
    assert settings._flag("LAWGRAPH_SOME_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off"])
def test_a_flag_is_off(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from lawgraph.config import settings

    monkeypatch.setenv("LAWGRAPH_SOME_FLAG", raw)
    assert settings._flag("LAWGRAPH_SOME_FLAG", True) is False


def test_an_unset_or_empty_variable_is_its_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.config import settings

    monkeypatch.delenv("LAWGRAPH_SOME", raising=False)
    assert settings._flag("LAWGRAPH_SOME", True) is True
    assert settings._int("LAWGRAPH_SOME", 8) == 8
    assert settings._float("LAWGRAPH_SOME", 0.5) == 0.5
    assert settings._choice("LAWGRAPH_SOME", "text", ("text", "json")) == "text"
    monkeypatch.setenv("LAWGRAPH_SOME", " ")
    assert settings._flag("LAWGRAPH_SOME", False) is False
    assert settings._int("LAWGRAPH_SOME", 8) == 8


@pytest.mark.parametrize(
    ("read", "raw"),
    [
        (lambda s: s._flag("LAWGRAPH_SOME", False), "ja"),
        (lambda s: s._int("LAWGRAPH_SOME", 8), "acht"),
        (lambda s: s._int("LAWGRAPH_SOME", 8), "0"),
        (lambda s: s._int("LAWGRAPH_SOME", 8), "-1"),
        (lambda s: s._float("LAWGRAPH_SOME", 0.5), "half"),
        (lambda s: s._choice("LAWGRAPH_SOME", "text", ("text", "json")), "xml"),
    ],
)
def test_an_invalid_value_fails_with_the_name_of_the_variable(
    monkeypatch: pytest.MonkeyPatch, read, raw: str
) -> None:
    from lawgraph.config import settings

    monkeypatch.setenv("LAWGRAPH_SOME", raw)
    with pytest.raises(ValueError, match=f"LAWGRAPH_SOME={raw!r}"):
        read(settings)


def test_a_choice_ignores_case_and_gives_the_choice_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.config import settings

    monkeypatch.setenv("LAWGRAPH_SOME", "Json")
    assert settings._choice("LAWGRAPH_SOME", "text", ("text", "json")) == "json"


@pytest.mark.parametrize(
    ("variable", "raw"),
    [
        ("LAWGRAPH_LOG_LEVEL", "DEBG"),
        ("LAWGRAPH_LOG_FORMAT", "plain"),
        ("LAWGRAPH_DB_POOL_SIZE", "acht"),
        ("LAWGRAPH_API_WARM_UP", "nee"),
        ("LAWGRAPH_RATE_LIMIT_CALLS", "2OO"),
    ],
)
def test_an_invalid_setting_fails_the_start(
    monkeypatch: pytest.MonkeyPatch, variable: str, raw: str
) -> None:
    from lawgraph.config import settings

    try:
        monkeypatch.setenv(variable, raw)
        with pytest.raises(ValueError, match=variable):
            importlib.reload(settings)
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_the_log_level_is_one_of_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    from lawgraph.config import settings

    try:
        monkeypatch.setenv("LAWGRAPH_LOG_LEVEL", "debug")
        assert importlib.reload(settings).LOG_LEVEL == "DEBUG"
        monkeypatch.setenv("LAWGRAPH_LOG_LEVEL", "WARN")
        assert importlib.reload(settings).LOG_LEVEL == "WARN"
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


@pytest.mark.parametrize(
    ("old", "new"),
    [("BWB_IDS", "LAWGRAPH_BWB_IDS"), ("EK_ATTRIBUTION", "LAWGRAPH_EK_ATTRIBUTION")],
)
def test_a_variable_under_its_former_name_fails_the_start(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> None:
    """A renamed variable still set under its old name is no silent default."""
    from lawgraph.config import settings

    try:
        monkeypatch.setenv(old, "x")
        with pytest.raises(ValueError, match=f"{old}.*{new}"):
            importlib.reload(settings)
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_a_confidence_that_is_no_number_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from lawgraph.config import settings

    monkeypatch.setenv("LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION", "0.8")
    assert settings.confidence_override("scope_limitation", 0.5) == 0.8
    monkeypatch.setenv("LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION", "hoog")
    with pytest.raises(ValueError, match="LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION"):
        settings.confidence_override("scope_limitation", 0.5)


def test_the_default_database_url_carries_the_password_of_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without LAWGRAPH_DB_URL the store reaches the server of docker-compose.yml with the
    password compose gave it, quoted for a URL."""
    from lawgraph.config import settings

    monkeypatch.delenv("LAWGRAPH_DB_URL", raising=False)
    monkeypatch.setenv("LAWGRAPH_DB_PASSWORD", "p@ss/w")
    try:
        assert importlib.reload(settings).DB_URL == (
            "postgresql://lawgraph:p%40ss%2Fw@localhost:5432"
        )
        monkeypatch.setenv("LAWGRAPH_DB_URL", "postgresql://u:x@db:5433")
        assert importlib.reload(settings).DB_URL == "postgresql://u:x@db:5433"
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_the_write_timeout_is_a_ceiling_that_cannot_be_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LAWGRAPH_WRITE_TIMEOUT_MS`` raises the ceiling of a writing statement; 0 (no
    ceiling) or a negative number is refused at the start."""
    from lawgraph.config import settings

    try:
        monkeypatch.delenv("LAWGRAPH_WRITE_TIMEOUT_MS", raising=False)
        assert importlib.reload(settings).WRITE_TIMEOUT_MS == 600_000
        monkeypatch.setenv("LAWGRAPH_WRITE_TIMEOUT_MS", "14400000")
        assert importlib.reload(settings).WRITE_TIMEOUT_MS == 14_400_000
        for value in ("0", "-1"):
            monkeypatch.setenv("LAWGRAPH_WRITE_TIMEOUT_MS", value)
            with pytest.raises(ValueError, match="LAWGRAPH_WRITE_TIMEOUT_MS"):
                importlib.reload(settings)
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


@pytest.mark.parametrize(
    ("variable", "default"),
    [
        ("LAWGRAPH_READ_TIMEOUT_MS", 10_800_000),
        ("LAWGRAPH_WATCHDOG_MINUTES", 10),
        ("LAWGRAPH_API_REQUEST_TIMEOUT_MS", 30_000),
    ],
)
def test_the_read_ceiling_and_the_watchdog_are_positive_settings(
    monkeypatch: pytest.MonkeyPatch, variable: str, default: int
) -> None:
    from lawgraph.config import settings

    name = variable.removeprefix("LAWGRAPH_")
    try:
        monkeypatch.delenv(variable, raising=False)
        assert getattr(importlib.reload(settings), name) == default
        monkeypatch.setenv(variable, "0")
        with pytest.raises(ValueError, match=variable):
            importlib.reload(settings)
    finally:
        monkeypatch.undo()
        importlib.reload(settings)
