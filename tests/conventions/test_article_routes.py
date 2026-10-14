"""An article route reads its article by ``api.params.ArticleAddress``: the number as
cited (``6:162``) and its own (``162``) are made one there, not per route."""

from __future__ import annotations

from tests.conventions._scan import SRC

ROUTES = SRC / "api" / "routes"


def test_the_article_routes_take_the_article_address() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in sorted(ROUTES.glob("*.py"))
        if "native_number(" in path.read_text()
    ]
    assert not offenders, f"take ArticleAddress: {offenders}"
