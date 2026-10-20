"""Asserts whose failure shows what was found: the answer behind a status, the items behind
an ``any``/``all``. ``tests/conventions/test_assert_messages.py`` holds the suite to them."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

_BODY = 2000  # characters of an answer's body a failure shows
_ITEMS = 20  # items of a collection a failure shows


class Answer(Protocol):
    """An answer of ``httpx`` (the API's test client) or of ``requests`` (the clients)."""

    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    @property
    def headers(self) -> Mapping[str, str]: ...


def _request(response: Answer) -> str:
    """The method and URL of the request *response* answers, as far as it knows them."""
    try:
        request = getattr(response, "request", None)
    except RuntimeError:  # an httpx answer made in the test, without a request
        request = None
    if request is None:
        return "the request"
    return f"{request.method} {request.url}"


def assert_status(response: Answer, expected: int) -> None:
    """Fail unless *response* has the status *expected*, showing the request, the request
    id and the body of the answer."""
    __tracebackhide__ = True
    if response.status_code == expected:
        return
    request = _request(response)
    request_id = response.headers.get("x-request-id")
    body = response.text
    if len(body) > _BODY:
        body = f"{body[:_BODY]}… ({len(body)} characters in all)"
    raise AssertionError(
        f"{request} answered {response.status_code}, expected {expected}"
        + (f" (request id {request_id})" if request_id else "")
        + f":\n{body}"
    )


def show_items(items: Iterable[object]) -> str:
    """The first items of *items* for a failure message, and how many there are."""
    shown = list(items)
    if len(shown) <= _ITEMS:
        return repr(shown)
    return f"{shown[:_ITEMS]!r}… ({len(shown)} in all)"
