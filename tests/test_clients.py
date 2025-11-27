# tests/test_clients.py

from __future__ import annotations

import datetime as dt
from typing import Any

import requests

from lawgraph.clients.eu import EUClient
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.tk import TKClient


class DummyResponse(requests.Response):
    def __init__(
        self,
        *,
        json_data: dict | None = None,
        text: str = "",
        status: int = 200,
    ) -> None:
        super().__init__()
        self._json_data = json_data
        self._text_override = text
        self.status_code = status
        self.reason = "OK" if status < 400 else "Error"

    @property  # type: ignore[override]
    def text(self) -> str:
        return self._text_override

    @text.setter
    def text(self, value: str) -> None:
        self._text_override = value

    def json(self, **kwargs: Any) -> Any:  # type: ignore[override]
        if self._json_data is not None:
            return self._json_data
        return super().json(**kwargs)


class DummySession(requests.Session):
    def __init__(self, response: DummyResponse) -> None:
        super().__init__()
        self.response = response
        self.last_url: str | None = None
        self.last_params: dict | None = None
        self.calls: int = 0

    # type: ignore[override]
    def get(self, url: str | bytes, **kwargs: Any) -> requests.Response:
        params = kwargs.get("params")
        self.last_url = str(url)
        self.last_params = params or {}
        self.calls += 1
        return self.response


# --------------------------------------------------------------------
# TKClient tests
# --------------------------------------------------------------------


def test_tkclient_zaken_modified_since_builds_correct_url_and_params() -> None:
    # Arrange
    dummy_json = {"value": [{"Id": 1, "Titel": "Testzaak"}]}
    session = DummySession(DummyResponse(json_data=dummy_json))
    client = TKClient(session=session)

    # Forceer base_url zodat test niet afhankelijk is van .env
    client.base_url = "https://example.org/OData/v4/2.0/"

    since = dt.datetime(2025, 1, 1, 12, 0, 0)

    # Act
    result = client.zaken_modified_since(since, top=10)

    # Assert
    assert session.calls == 1
    assert session.last_url == "https://example.org/OData/v4/2.0/Zaak"
    assert session.last_params is not None
    assert session.last_params.get("$top") == 10

    flt = session.last_params.get("$filter", "")
    assert "ApiGewijzigdOp ge " in flt
    assert "2025-01-01T12:00:00" in flt  # tijdstip moet erin zitten

    assert isinstance(result, list)
    assert result[0]["Id"] == 1


# --------------------------------------------------------------------
# RechtspraakClient tests
# --------------------------------------------------------------------


def test_rechtspraak_search_ecli_index_uses_correct_path_and_params() -> None:
    # Arrange
    xml_body = "<index>ok</index>"
    session = DummySession(DummyResponse(text=xml_body))
    client = RechtspraakClient(session=session)
    client.base_url = "https://data.example.org/"

    since = dt.datetime(2025, 1, 1, 12, 0, 0)

    # Act
    result = client.search_ecli_index(
        modified_since=since,
        extra_params={"rechtsgebied": "bestuursrecht"},
    )

    # Assert
    assert session.calls == 1
    assert session.last_url == "https://data.example.org/uitspraken/zoeken"
    assert session.last_params is not None
    assert session.last_params["rechtsgebied"] == "bestuursrecht"
    assert "modifiedsince" in session.last_params
    assert "2025-01-01T12:00:00" in session.last_params["modifiedsince"]
    assert result == xml_body


def test_rechtspraak_fetch_ecli_content_uses_correct_path_and_param() -> None:
    # Arrange
    xml_body = "<uitspraak>ECLI content</uitspraak>"
    session = DummySession(DummyResponse(text=xml_body))
    client = RechtspraakClient(session=session)
    client.base_url = "https://data.example.org/"

    # Act
    result = client.fetch_ecli_content("ECLI:NL:HR:2024:1234")

    # Assert
    assert session.calls == 1
    assert session.last_url == "https://data.example.org/uitspraken/content"
    assert session.last_params is not None
    assert session.last_params.get("id") == "ECLI:NL:HR:2024:1234"
    assert result == xml_body


# --------------------------------------------------------------------
# EUClient tests
# --------------------------------------------------------------------


def test_euclient_fetch_celex_html_builds_correct_url() -> None:
    # Arrange
    html_body = "<html>CELEX</html>"
    session = DummySession(DummyResponse(text=html_body))
    client = EUClient(session=session)
    client.base_url = "https://eur-lex.example.org/"

    # Act
    result = client.fetch_celex_html("32019L1158", lang="NL")

    # Assert
    assert session.calls == 1
    assert session.last_url == "https://eur-lex.example.org/legal-content/NL/TXT/"
    assert session.last_params is not None
    assert session.last_params.get("uri") == "CELEX:32019L1158"
    assert result == html_body
