"""The articles of an EU act from its CELLAR HTML: heading, text and parts (core.eurlex_html).

The two real acts in ``tests/fixtures`` are also run end to end in
``tests/integration/test_eu_articles.py``; the cases here are the layouts those acts do not
show, cut down to what makes them different.
"""

from __future__ import annotations

from lawgraph.core.eurlex_html import EuArticle, parse_articles
from tests.integration.seed import FIXTURES


def _row(marker: str, body: str) -> str:
    return (
        f'<table><tbody><tr><td><p class="oj-normal">{marker}</p></td>'
        f"<td>{body}</td></tr></tbody></table>"
    )


def _journal(number: str, heading: str, body: str) -> str:
    return (
        f'<div class="eli-subdivision" id="art_{number}">'
        f'<p class="oj-ti-art">Artikel {number}</p>'
        f'<div class="eli-title"><p class="oj-sti-art">{heading}</p></div>{body}</div>'
    )


def _ids(article: EuArticle) -> list[str]:
    return [part.id for part in article.parts]


def _spans(article: EuArticle) -> dict[str, str]:
    return {part.id: article.text[part.start : part.end] for part in article.parts}


def test_the_real_acts_give_every_article_a_clean_text() -> None:
    for name in ("eurlex_32022r0868.html", "eurlex_31995l0046.html"):
        for article in parse_articles((FIXTURES / name).read_text()):
            assert all(line.strip() for line in article.text.split("\n"))
            for part in article.parts:
                assert not article.text[part.start].isspace()


def test_a_lid_laid_out_as_a_point_is_a_lid() -> None:
    body = (
        '<div id="004.001"><p class="oj-normal">1.   Een.</p></div>'
        '<div id="004.002">'
        + _row(
            "2.",
            _row("a)", '<p class="oj-normal">Twee a.</p>')
            + _row("b)", '<p class="oj-normal">Twee b.</p>'),
        )
        + "</div>"
    )
    (article,) = parse_articles(_journal("4", "Toezicht", body))

    assert article.text == "1. Een.\n2. a) Twee a.\nb) Twee b."
    assert _ids(article) == ["lid-1", "lid-2", "lid-2-onder-a", "lid-2-onder-b"]


def test_a_point_without_text_of_its_own_shares_its_line() -> None:
    body = '<p class="oj-normal">Openbaar zijn:</p>' + _row(
        "f)",
        _row("—", '<p class="oj-normal">de ontbinding;</p>')
        + _row("—", '<p class="oj-normal">de insolventie.</p>'),
    )
    (article,) = parse_articles(_journal("30", "Openbaarmaking", body))

    assert article.text == "Openbaar zijn:\nf) — de ontbinding;\n— de insolventie."
    assert _spans(article) == {
        "aanhef": "Openbaar zijn:",
        "onder-f": "— de ontbinding;\n— de insolventie.",
        "onder-f-onder-_1": "de ontbinding;",
        "onder-f-onder-_2": "de insolventie.",
    }


def test_an_article_quoted_in_an_amendment_is_text_of_the_amending_article() -> None:
    quoted = (
        '<p class="oj-normal">Artikel 6 wordt vervangen door:</p>'
        '<p class="oj-ti-art">„Artikel 6</p><p class="oj-normal">Nieuwe tekst.”</p>'
    )
    html = _journal("1", "Wijziging", _row("1)", quoted)) + _journal(
        "2",
        "Inwerkingtreding",
        '<p class="oj-normal">Deze verordening treedt in werking.</p>',
    )

    articles = parse_articles(html)

    assert [a.number for a in articles] == ["1", "2"]
    assert "„Artikel 6" in articles[0].text


def test_the_old_format_reads_spaced_markers_and_a_letter_i() -> None:
    paragraphs = [
        "Artikel 2",
        "In de zin van deze richtlijn wordt verstaan onder :",
        "h ) moederonderneming : een moederonderneming;",
        "i ) dochteronderneming : een dochteronderneming;",
        "_ in de zin van Richtlijn 83/349/EEG,",
        "j ) vestiging : een bijkantoor.",
        "Artikel 3",
        "1 . Het recht van de Lid-Staat.",
        "Gedaan te Brussel, 8 november 1990.",
    ]
    html = (
        "<html><body>" + "".join(f"<p>{p}</p>" for p in paragraphs) + "</body></html>"
    )

    definitions, law = parse_articles(html)

    assert definitions.heading is None
    assert _ids(definitions) == [
        "aanhef",
        "onder-h",
        "onder-i",
        "onder-i-onder-_1",
        "onder-j",
    ]
    assert "\ni) dochteronderneming" in definitions.text
    assert law.text == "1. Het recht van de Lid-Staat."
    assert _ids(law) == ["lid-1"]


def test_the_old_format_keeps_a_quoted_article_in_the_article_that_quotes_it() -> None:
    paragraphs = [
        "Artikel 1",
        "Artikel 1 van Richtlijn 90/314/EEG wordt vervangen door:",
        "Artikel 1",
        "Deze richtlijn is van toepassing op pakketreizen.",
        "Artikel 2",
        "Deze richtlijn is gericht tot de Lid-Staten.",
    ]
    html = (
        "<html><body>" + "".join(f"<p>{p}</p>" for p in paragraphs) + "</body></html>"
    )

    amending, addressees = parse_articles(html)

    assert amending.number == "1"
    assert amending.text.endswith(
        "\nArtikel 1\nDeze richtlijn is van toepassing op pakketreizen."
    )
    assert addressees.number == "2"
