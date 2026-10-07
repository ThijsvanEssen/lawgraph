"""The credentials of the database URL never reach an error message."""

from __future__ import annotations

import psycopg
import pytest

from lawgraph.db import store
from lawgraph.db.store import GraphStore, redacted

_PASSWORD = "pa:ss@w/rd"  # characters that a URL has to quote
_URL = "postgresql://lawgraph:pa%3Ass%40w%2Frd@db.example:5433"


def test_a_failed_connection_names_the_server_without_its_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(conninfo: str, **_kw: object) -> None:
        raise psycopg.OperationalError(f"connection to {conninfo} failed ({_PASSWORD})")

    monkeypatch.setattr(store, "DB_URL", _URL)
    monkeypatch.setattr(store, "_create_database_if_missing", lambda: None)
    monkeypatch.setattr(store, "ConnectionPool", refuse)

    with pytest.raises(ConnectionError) as caught:
        GraphStore()

    message = str(caught.value)
    assert "postgresql://***@db.example:5433" in message
    assert _PASSWORD not in message
    assert "pa%3Ass%40w%2Frd" not in message
    assert "lawgraph:" not in message


def test_a_url_without_credentials_is_left_alone() -> None:
    text = "at postgresql://db.example:5432/lawgraph"
    assert redacted(text, "postgresql://db.example:5432") == text


def test_a_user_without_password_is_masked_too() -> None:
    url = "postgresql://lawgraph@localhost:5432"
    assert redacted(f"at {url}/x", url) == "at postgresql://***@localhost:5432/x"
