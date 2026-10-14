"""What a client sees of HTTP: an error for a status, and a response body."""

from __future__ import annotations

import requests


def http_error(status: int) -> requests.HTTPError:
    """What a client raises for an answer with HTTP *status*, after its retries."""
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


class FakeResponse:
    """What a client reads of a ``requests.Response``: the body as text and as bytes."""

    def __init__(
        self, text: str, content_type: str = "text/xml", url: str = "https://fake"
    ) -> None:
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status_code = 200
