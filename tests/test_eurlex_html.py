"""The articles of an EU act from its CELLAR HTML: heading, text and parts (core.eurlex_html).

The two real acts in ``tests/fixtures`` are also run end to end in
``tests/integration/test_eu_articles.py``; the cases here are the layouts those acts do not
show, cut down to what makes them different.
"""

from __future__ import annotations

from lawgraph.core.eurlex_html import EuArticle, parse_act
from tests.asserts import show_items
from tests.paths import fixture_text


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
        for article in parse_act(fixture_text(name)).articles:
            failing = [line for line in article.text.split("\n") if not line.strip()]
            assert not failing, show_items(failing)
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
    (article,) = parse_act(_journal("4", "Toezicht", body)).articles

    assert article.text == "1. Een.\n2. a) Twee a.\nb) Twee b."
    assert _ids(article) == ["lid-1", "lid-2", "lid-2-onder-a", "lid-2-onder-b"]


def test_a_point_without_text_of_its_own_shares_its_line() -> None:
    body = '<p class="oj-normal">Openbaar zijn:</p>' + _row(
        "f)",
        _row("—", '<p class="oj-normal">de ontbinding;</p>')
        + _row("—", '<p class="oj-normal">de insolventie.</p>'),
    )
    (article,) = parse_act(_journal("30", "Openbaarmaking", body)).articles

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

    articles = parse_act(html).articles

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

    definitions, law = parse_act(html).articles

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

    amending, addressees = parse_act(html).articles

    assert amending.number == "1"
    assert amending.text.endswith(
        "\nArtikel 1\nDeze richtlijn is van toepassing op pakketreizen."
    )
    assert addressees.number == "2"


def _flat(paragraphs: list[str]) -> str:
    return (
        "<html><body>" + "".join(f"<p>{p}</p>" for p in paragraphs) + "</body></html>"
    )


def _crumbs(article: EuArticle) -> list[tuple[str, str | None, str | None]]:
    return [(c.type, c.label, c.title) for c in article.breadcrumb]


def test_an_article_of_the_official_journal_stands_in_its_divisions() -> None:
    def division(ident: str, label: str, title: str, body: str) -> str:
        return (
            f'<div id="{ident}"><p class="oj-ti-section-1">'
            f'<span class="oj-italic">{label}</span></p>'
            f'<div class="eli-title" id="{ident}.tit_1">'
            f'<p class="oj-ti-section-2">{title}</p></div>{body}</div>'
        )

    text = '<p class="oj-normal">Tekst.</p>'
    html = division(
        "cpt_III",
        "HOOFDSTUK III",
        "ZORGVULDIGHEIDSVERPLICHTINGEN",
        _journal("10", "Kop", text)
        + division("cpt_III.sct_1", "Afdeling 1", "Alle aanbieders", "")
        + division(
            "cpt_III.sct_2",
            "Afdeling 2",
            "Hostingdiensten",
            _journal("16", "Melding", text),
        ),
    )

    first, second = parse_act(html).articles

    chapter = ("hoofdstuk", "Hoofdstuk III", "ZORGVULDIGHEIDSVERPLICHTINGEN")
    assert _crumbs(first) == [chapter]
    assert _crumbs(second) == [chapter, ("afdeling", "Afdeling 2", "Hostingdiensten")]


def test_a_division_of_the_old_format_ends_where_its_kind_comes_again() -> None:
    articles = parse_act(
        _flat(
            [
                "TITEL I",
                "Algemene bepalingen",
                "Artikel 1",
                "Tekst een.",
                "HOOFDSTUK II BEGINSELEN",
                "Afdeling 1: Vestiging",
                "Artikel 2",
                "Tekst twee.",
                "Afdeling 2: Communicatie",
                "Artikel 3",
                "Tekst drie.",
                "TITEL II",
                "Artikel 4",
                "Tekst vier.",
            ]
        )
    ).articles

    assert [_crumbs(a) for a in articles] == [
        [("titel", "Titel I", "Algemene bepalingen")],
        [
            ("titel", "Titel I", "Algemene bepalingen"),
            ("hoofdstuk", "Hoofdstuk II", "BEGINSELEN"),
            ("afdeling", "Afdeling 1", "Vestiging"),
        ],
        [
            ("titel", "Titel I", "Algemene bepalingen"),
            ("hoofdstuk", "Hoofdstuk II", "BEGINSELEN"),
            ("afdeling", "Afdeling 2", "Communicatie"),
        ],
        [("titel", "Titel II", None)],
    ]
    assert articles[1].text == "Tekst twee."


def test_a_heading_in_capitals_before_an_article_ends_the_one_before() -> None:
    articles = parse_act(
        _flat(
            [
                "HEBBEN DE VOLGENDE RICHTLIJN VASTGESTELD:",
                "Artikel 1",
                "Tekst een.",
                "SLOTBEPALINGEN",
                "Artikel 2",
                "Tekst twee.",
            ]
        )
    ).articles

    assert [a.text for a in articles] == ["Tekst een.", "Tekst twee."]
    # without a division open there is no level to put it at
    assert [_crumbs(a) for a in articles] == [[], []]


def test_the_title_of_the_act_as_printed() -> None:
    journal = parse_act(fixture_text("eurlex_32022r0868.html"))
    assert journal.title == (
        "VERORDENING (EU) 2022/868 VAN HET EUROPEES PARLEMENT EN DE RAAD",
        "van 30 mei 2022",
        "betreffende Europese datagovernance en tot wijziging van Verordening (EU) "
        "2018/1724 (Datagovernanceverordening)",
        "(Voor de EER relevante tekst)",
    )

    old = parse_act(fixture_text("eurlex_31995l0046.html"))
    (description,) = old.title
    assert description.startswith("Richtlijn 95/46/EG van het Europees Parlement")


def test_an_inserted_article_has_a_number_of_its_own() -> None:
    """ "Artikel 9 bis" is article "9bis", as a citation names it ("artikel 9bis van
    Richtlijn …"), and so is "Artikel 9bis"; it does not fall into article 9."""
    journal = parse_act(
        _journal("9", "Negen", '<p class="oj-normal">Tekst van 9.</p>')
        + _journal("9\xa0bis", "Negen bis", '<p class="oj-normal">Tekst van 9 bis.</p>')
        + _journal("9 ter", "Negen ter", '<p class="oj-normal">Tekst van 9 ter.</p>')
        + _journal("9quater", "Vier", '<p class="oj-normal">Tekst van 9 quater.</p>')
    ).articles
    flat = parse_act(
        _flat(["Artikel 9", "Tekst van 9.", "Artikel 9 bis", "Tekst van 9 bis."])
    ).articles

    assert [a.number for a in journal] == ["9", "9bis", "9ter", "9quater"]
    assert journal[0].text == "Tekst van 9."
    assert [(a.number, a.text) for a in flat] == [
        ("9", "Tekst van 9."),
        ("9bis", "Tekst van 9 bis."),
    ]
    # Richtlijn 84/450/EEG as amended by 97/55/EG (the consolidated text, old format)
    amended = parse_act(fixture_text("eurlex_01984l0450_20050612.html")).articles
    assert [a.number for a in amended][:5] == ["1", "2", "3", "3bis", "4"]
    assert amended[3].text.startswith("1. Vergelijkende reclame is")
    assert "Vergelijkende reclame" not in amended[2].text


def test_the_old_format_keeps_an_inserted_article_it_quotes_in_the_amending_one() -> (
    None
):
    """An amending act of the old format inserts "Artikel 3 bis" into another act: the
    article it quotes is text of its own article 1 (Richtlijn 97/55/EG)."""
    act = parse_act(fixture_text("eurlex_31997l0055.html"))

    assert [a.number for a in act.articles] == ["1", "2", "3", "4"]
    assert "Artikel 3 bis" in act.articles[0].text
    # quoted without a quotation mark, after an article of another number
    flat = parse_act(
        _flat(
            [
                "Artikel 1",
                "Wordt ingevoegd:",
                "Artikel 3 bis",
                "Nieuw.",
                "Artikel 2",
                "Slot.",
            ]
        )
    ).articles
    assert [a.number for a in flat] == ["1", "2"]


def test_an_article_printed_without_its_number_is_the_next_one() -> None:
    """Richtlijn 89/104/EEG prints its first article as "Artikel " without the 1."""
    act = parse_act(fixture_text("eurlex_31989l0104.html"))

    numbers = [a.number for a in act.articles]
    assert numbers == [str(n) for n in range(1, 18)]
    first = act.articles[0]
    assert first.heading == "Toepassing"
    assert first.text.startswith("Deze richtlijn is van toepassing op ieder merk")
