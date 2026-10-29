"""The shell of the front end and the JSON files its build writes beside it: one that is
missing or does not read is a release that went wrong, logged with its path."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from lawgraph.api.seo import shell
from lawgraph.api.seo.pages.base import Page
from lawgraph.config import settings


@pytest.fixture
def index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "index.html"
    path.write_text("<!doctype html><html><head></head><body></body></html>")
    (tmp_path / "spa-routes.json").write_text('[{"path": "/zoeken/"}]')
    (tmp_path / "start.json").write_text('{"heading": "Kop"}')
    monkeypatch.setattr(settings, "SPA_INDEX", str(path))
    shell.forget()
    yield path
    shell.forget()


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_whole_build_is_read_without_a_word(
    index: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (index.parent / "first-paint.js").write_text("paint()")
    read = shell.shell()
    assert set(read.routes) == {"/zoeken"} and read.start == {"heading": "Kop"}
    assert read.first_paint == {"": "paint()"}
    assert _errors(caplog) == []


def test_a_build_without_the_first_paint_paints_nothing_first(
    index: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A front end of before has no ``first-paint.js``: no word, no first paint."""
    page = Page(
        title="T",
        description="D",
        path="/wetten/X",
        body="<h1>T</h1>",
        first_paint={"kind": "article"},
    )
    assert shell.shell().first_paint == {}
    assert "first-paint-data" not in shell.render(page)
    assert _errors(caplog) == []


def test_the_source_a_page_paints_first_stands_after_its_content_with_the_script(
    index: Path,
) -> None:
    (index.parent / "first-paint.js").write_text("paint()")
    page = Page(
        title="T",
        description="D",
        path="/wetten/X",
        body="<h1>T</h1>",
        first_paint={"kind": "article", "text": "a </script> b"},
    )
    html = shell.render(page)
    data = '<script type="application/json" id="first-paint-data">'
    assert (
        html.index("</main>")
        < html.index(data)
        < html.index("<script>paint()</script>")
    )
    # no end of the script inside its data
    assert '"a <\\/script> b"' in html
    page.first_paint = None
    assert "first-paint" not in shell.render(page)


def test_a_page_gets_the_script_of_its_kind_else_the_one_of_every_kind(
    index: Path,
) -> None:
    """The build writes a script per kind of bron beside the one that paints every kind: a
    page carries only the code of its own kind."""
    (index.parent / "first-paint.js").write_text("all()")
    (index.parent / "first-paint-judgment.js").write_text("judgment()")
    page = Page(
        title="T",
        description="D",
        path="/uitspraken/X",
        body="<h1>T</h1>",
        first_paint={"kind": "judgment"},
    )
    assert "<script>judgment()</script>" in shell.render(page)
    page.first_paint = {"kind": "article"}
    assert "<script>all()</script>" in shell.render(page)


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        ("spa-routes.json", None, "does not read: FileNotFoundError"),
        ("spa-routes.json", '[{"path": "/zoeken"', "does not read: JSONDecodeError"),
        ("spa-routes.json", '{"path": "/zoeken"}', "is no JSON list but a dict"),
        ("start.json", None, "does not read: FileNotFoundError"),
        ("start.json", "{", "does not read: JSONDecodeError"),
        ("start.json", "[]", "is no JSON dict but a list"),
    ],
)
def test_a_file_that_is_missing_or_does_not_read_is_logged_with_its_path(
    index: Path,
    caplog: pytest.LogCaptureFixture,
    name: str,
    text: str | None,
    reason: str,
) -> None:
    beside = index.parent / name
    if text is None:
        beside.unlink()
    else:
        beside.write_text(text)
    read = shell.shell()
    assert (read.routes if name == "spa-routes.json" else read.start) == {}
    (error,) = _errors(caplog)
    assert f"The front end's {beside} {reason}" in error
    shell.shell()  # kept until the shell changes: said once
    assert len(_errors(caplog)) == 1


def test_the_text_of_a_prose_page_stands_in_main_seo_and_a_build_without_it_is_silent(
    index: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``spa-texts.json``: path to HTML; a front end of before has none, no word."""
    from lawgraph.api.routes.render import _app_page

    (index.parent / "spa-routes.json").write_text(
        '[{"path": "/over", "title": "Over, Concordans"}, {"path": "/privacy"}]'
    )
    shell.forget()
    assert shell.shell().texts == {} and _app_page("/over").body == ""  # type: ignore[union-attr]
    assert _errors(caplog) == []

    (index.parent / "spa-texts.json").write_text(
        '{"/over/": "<h1>Over</h1><p>Tekst</p>", "/privacy": 3, "/leeg": " "}'
    )
    shell.forget()
    assert shell.shell().texts == {"/over": "<h1>Over</h1><p>Tekst</p>"}
    over, privacy = _app_page("/over"), _app_page("/privacy")
    assert over is not None and privacy is not None and privacy.body == ""
    html = shell.render(over)
    assert '<main id="seo"><h1>Over</h1><p>Tekst</p></main>' in html
    assert html.count("<h1") == 1
    assert _errors(caplog) == []


def test_concordans_is_an_organization_on_the_start_page_and_over_only(
    index: Path,
) -> None:
    import json
    import re

    from lawgraph.api.routes.render import _app_page

    (index.parent / "spa-routes.json").write_text(
        '[{"path": "/"}, {"path": "/over"}, {"path": "/privacy"}]'
    )
    shell.forget()

    def organizations(path: str) -> list[dict[str, object]]:
        page = _app_page(path)
        assert page is not None
        found = re.findall(
            r'<script type="application/ld\+json" data-seo>(.*?)</script>',
            shell.render(page),
        )
        graph = json.loads(found[0])["@graph"] if found else []
        return [n for n in graph if n["@type"] == "Organization"]

    expected = {
        "@type": "Organization",
        "@id": f"{settings.SITE_URL}/#organization",
        "name": "Concordans",
        "url": f"{settings.SITE_URL}/",
        "logo": f"{settings.SITE_URL}/icon-512.png",
        "email": "concordans@tmve.nl",
    }
    assert organizations("/") == [expected]
    assert organizations("/over") == [expected]
    assert organizations("/privacy") == []


def test_the_website_names_its_publisher_by_reference_not_a_second_organization(
    index: Path,
) -> None:
    import json
    import re

    from lawgraph.api.routes.render import _app_page

    (index.parent / "spa-routes.json").write_text('[{"path": "/"}]')
    shell.forget()
    page = _app_page("/")
    assert page is not None
    (found,) = re.findall(
        r'<script type="application/ld\+json" data-seo>(.*?)</script>',
        shell.render(page),
    )
    graph = json.loads(found)["@graph"]
    (site,) = [n for n in graph if n["@type"] == "WebSite"]
    (org,) = [n for n in graph if n["@type"] == "Organization"]
    assert site["publisher"] == {"@id": org["@id"]}
