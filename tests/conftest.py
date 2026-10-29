from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator

import pytest

# The suite is offline unless asked otherwise; a developer's .env must not switch that on.
os.environ.setdefault("ALLOW_NETWORK_TESTS", "0")
# Every TestClient request comes from one address, and a suite asks the API far more than
# the 200 a minute a visitor may: the limit itself is tested on an instance of its own.
os.environ["LAWGRAPH_RATE_LIMIT_CALLS"] = "1000000"
# The API warms its answers up in the background at its start; the tests ask themselves.
os.environ["LAWGRAPH_API_WARM_UP"] = "false"
# A test that runs the scheduled scripts or the deploy's lock sets the wait it relies on;
# one set where the suite runs (the deploy sets half an hour) is no test's.
os.environ.pop("LAWGRAPH_LOCK_WAIT", None)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Close the stores still open while the output of the run is: a pool closed at exit
    finds it closed, and logs every connection it could not make there."""
    store = sys.modules.get("lawgraph.db.store")
    if store is not None:
        store.close_stores()


@pytest.fixture(autouse=True)
def _fresh_version_cache(monkeypatch) -> Iterator[None]:
    """Every test reads the data version at every call and starts with nothing kept: a test
    writes and reads again within the seconds the API keeps an answer."""
    from lawgraph.api import warm
    from lawgraph.db import version_cache

    monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)
    version_cache.clear()
    warm.forget()
    yield
    version_cache.clear()
    warm.forget()


@pytest.fixture(autouse=True)
def _own_search_stats(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """The counts of the terms searched in a directory of the test run: a test that runs
    the API's start and stop flushes them, and the machine's files are no test's."""
    from lawgraph.api import search_terms

    monkeypatch.setattr(
        search_terms, "SEARCH_STATS_DIR", tmp_path_factory.mktemp("search-stats")
    )


@pytest.fixture(autouse=True)
def _own_pacer_locks(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """The host locks of the pacer in a directory of the test run, not the machine's.

    A ``lawgraph retrieve`` running next to the suite holds the real locks, and the tests
    would find every host "taken" and paced at half speed.
    """
    from lawgraph.clients import pacing

    lock_dir = tmp_path_factory.getbasetemp() / "pacer-locks"
    lock_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(pacing, "_lock_dir", lambda: lock_dir)


@pytest.fixture(scope="session", autouse=True)
def _edge_meta_found() -> Iterator[list[str]]:
    """The run holds the meta of every edge made to the whole model of its relation
    (``strict_meta``): what does not fit, until a test claims it."""
    from lawgraph.db.edges import strict_meta

    with strict_meta() as found:
        yield found


@pytest.fixture(autouse=True)
def _edge_meta_fits_its_model(_edge_meta_found: list[str]) -> Iterator[None]:
    """A test fails on the meta of an edge its model (``core/relations.py``) does not
    allow: made by the test, or by a fixture of a wider scope set up for it."""
    yield
    found = sorted(set(_edge_meta_found))
    _edge_meta_found.clear()
    if found:
        pytest.fail("edge meta outside the model of its relation:\n" + "\n".join(found))


@pytest.fixture()
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The waits of a client between its attempts, kept instead of slept."""
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    return waits


@pytest.fixture()
def raw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared reads of raw_sources, answered from the ``raw`` of an ``InMemoryStore``."""
    from tests.fakes import patch_raw_reads

    patch_raw_reads(monkeypatch)


@pytest.fixture()
def ek_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Kamerstukken ``normalize eerstekamer`` wrote before, from the documents of an
    ``InMemoryStore``."""
    from tests.fakes import patch_ek_documents

    patch_ek_documents(monkeypatch)


@pytest.fixture()
def edge_removals(monkeypatch: pytest.MonkeyPatch) -> None:
    """The edge removals of the semantic phase, on the ``edges`` of an ``InMemoryStore``."""
    from tests.fakes import patch_edge_removals

    patch_edge_removals(monkeypatch)
