"""One rule for a shortened name: at a word boundary, with an ellipsis."""

from __future__ import annotations

from lawgraph.core.display import shorten
from lawgraph.core.tk_records import document_display_name


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
    assert all(w in words for w in name.split(": ", 1)[1].rstrip("…").split())
