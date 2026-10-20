"""One rule for a shortened name: at a word boundary, with an ellipsis."""

from __future__ import annotations

from lawgraph.core.display import shorten
from lawgraph.core.tk_records.documents import document_display_name
from tests.asserts import show_items


def test_a_name_that_fits_is_kept() -> None:
    assert (
        shorten("Amendement van het lid Bakker", 80) == "Amendement van het lid Bakker"
    )
    assert shorten("", 10) == ""


def test_a_long_name_is_cut_at_a_word_with_an_ellipsis() -> None:
    title = "Amendement over het onvoorwaardelijk delen van gegevens met gemeenten"
    short = shorten(title, 40)
    assert short == "Amendement over het onvoorwaardelijk…"
    assert len(short) <= 40
    # no comma or dash before the ellipsis
    assert shorten("Wet op de zorg, de jeugd en de gemeenten", 18) == "Wet op de zorg…"


def test_one_long_word_is_cut_where_the_limit_falls() -> None:
    assert shorten("Aanbestedingsconcessiemarktenverordening", 12) == "Aanbestedin…"


def test_an_amendment_is_named_without_a_word_cut_in_half() -> None:
    title = (
        "Amendement van het lid Bakker over het onvoorwaardelijk delen van gegevens "
        "tussen de Belastingdienst, het UWV en de gemeenten bij de uitvoering"
    )
    name = document_display_name("36000", 12, "Amendement", title)
    assert name.startswith("Kamerstuk 36000, nr. 12: Amendement van het lid Bakker")
    assert name.endswith("…")
    words = set(title.split())
    failing = [w for w in name.split(": ", 1)[1].rstrip("…").split() if w not in words]
    assert not failing, show_items(failing)


# ── every cut with an ellipsis is ``shorten`` ──────────────────────────────


def test_a_full_stop_before_the_ellipsis_is_dropped() -> None:
    assert shorten("Het hof bekrachtigt het vonnis. Het hof veroordeelt", 33) == (
        "Het hof bekrachtigt het vonnis…"
    )


def test_the_seo_cut_is_shorten_on_one_line() -> None:
    from lawgraph.api.seo.pages.base import cut

    assert cut("Een  tekst\n met   witruimte die lang genoeg is", 25) == (
        "Een tekst met witruimte…"
    )
    assert cut("Wet op de zorg - de jeugd en de gemeenten", 18) == "Wet op de zorg…"
    assert cut("A " + "x" * 40, 20) == "A xxxxxxxxxxxxxxxxx…"
    assert cut("Kort", 10) == "Kort"


def test_a_passage_excerpt_is_its_opening_without_the_heading() -> None:
    from lawgraph.api.schemas.articles import EXCERPT_CHARS, passage_excerpt

    excerpt = passage_excerpt("Artikel 1\n" + "Dit is een zin. " * 30, "Artikel 1")
    assert excerpt is not None
    assert excerpt.startswith("Dit is een zin.")
    assert excerpt.endswith(" Dit is een…")
    assert len(excerpt) <= EXCERPT_CHARS
    assert passage_excerpt("Kop\nTekst", "Kop") == "Tekst"
    assert passage_excerpt("Kop\n  ", "Kop") is None
    assert passage_excerpt(None, None) is None


def test_an_explanation_keeps_its_sentences_that_fit() -> None:
    from lawgraph.core.amendment_explanation import EXPLANATION_CHARS, _cut

    assert _cut("woord " * 60) == ("woord " * 60)[:360]
    sentences = "Een zin. " * 60
    assert _cut(sentences) == ("Een zin. " * 44)[:-1]
    words = _cut("woord " * 80)
    assert words.endswith("woord woord…")
    assert len(words) <= EXPLANATION_CHARS
