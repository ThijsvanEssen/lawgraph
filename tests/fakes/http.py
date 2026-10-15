"""What a client sees of HTTP: a session that answers from a script, a response, and an
error for a status."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import requests
from requests.structures import CaseInsensitiveDict

from lawgraph.clients.pacing import PacedSession


def http_error(status: int) -> requests.HTTPError:
    """What a client raises for an answer with HTTP *status*, after its retries."""
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def answer(
    body: str | bytes | dict | list = "",
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    url: str | None = None,
) -> requests.Response:
    """A response with *body* (a dict or a list as JSON) and *status*; *url* is where it was
    served, the URL asked for when not given (a redirect gives another)."""
    if isinstance(body, dict | list):
        body = json.dumps(body)
    response = requests.Response()
    response.status_code = status
    response.reason = "OK" if status < 400 else "Error"
    response._content = body.encode("utf-8") if isinstance(body, str) else body
    response._content_consumed = True
    response.headers = CaseInsensitiveDict(headers or {})
    if url is not None:
        response.url = url
    return response


@dataclass(frozen=True)
class Sent:
    """One request of a client: what it passed, and the URL and headers that went out."""

    url: str  # as the client passed it
    params: Any
    full_url: str  # with the parameters
    headers: Mapping[str, str]  # those of the session and of the request together
    timeout: float | None
    stream: bool


# A step of a script: a body (HTTP 200), a response, an exception to raise, or a function of
# the request that gives one of those.
Answer = str | bytes | dict | list | requests.Response | Exception
Step = Answer | Callable[[Sent], Answer]


class ScriptedSession(PacedSession):
    """The session of a client under test: it sends nothing and is not paced. Each request
    gets the next step of the script and is kept in ``sent``; a request past the end of the
    script fails the test.

    It is a ``PacedSession`` for what that session adds to every request (the
    ``User-Agent``). The parameters of every request also go into *asked*, when given.
    """

    def __init__(self, *script: Step, asked: list[dict] | None = None) -> None:
        super().__init__()
        self.script = list(script)
        self.sent: list[Sent] = []
        self.asked = asked

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        params: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stream: bool | None = None,
        **_kwargs: Any,
    ) -> requests.Response:
        prepared = self.prepare_request(
            requests.Request(method, url, params=params, headers=headers)
        )
        sent = Sent(
            url=url,
            params=params,
            full_url=str(prepared.url),
            headers=dict(prepared.headers),
            timeout=timeout,
            stream=bool(stream),
        )
        self.sent.append(sent)
        if self.asked is not None:
            self.asked.append(dict(params or {}))
        if not self.script:
            raise AssertionError(f"no answer scripted for {sent.full_url}")
        step = self.script.pop(0)
        reply = step(sent) if callable(step) else step
        if isinstance(reply, Exception):
            raise reply
        response = reply if isinstance(reply, requests.Response) else answer(reply)
        if not response.url:
            response.url = sent.full_url
        return response
