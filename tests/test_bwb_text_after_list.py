"""A paragraph after a list (``<al>`` after ``<lijst>``, in a lid or a list item) stands
after the list in the text, as in the source: its onderdelen end before it.

On art. 47 of the Drinkwaterbesluit (BWBR0030111, lid 1: a, b, c, then "De
verstorings-risicoanalyse wordt …"), and on the shape of BW 6:193c lid 2 onder b (1°, 2°,
then "waardoor de gemiddelde consument …")."""

from __future__ import annotations

from lawgraph.core.bwb_xml import ArticleXml, parse_toestand
from tests.paths import fixture_text


def _article_47() -> ArticleXml:
    (article,) = parse_toestand(
        fixture_text("bwb_drinkwaterbesluit_lijst_toestand.xml")
    ).articles
    return article


def _parts(article: ArticleXml) -> dict[str, str]:
    return {p.id: article.text[p.start : p.end] for p in article.parts}


def test_a_paragraph_after_the_list_of_a_lid_follows_the_list() -> None:
    article = _article_47()
    lid_1 = _parts(article)["lid-1"]

    assert lid_1.endswith(
        "c. nationale dreigingen en scenario’s als bedoeld in het tweede lid.\n"
        "De verstorings-risicoanalyse wordt met het oog op goedkeuring van het "
        "leveringsplan, bedoeld in artikel 37, derde lid, van de wet, voorafgaand aan "
        "de indiening van het leveringsplan aan de inspecteur ter beoordeling "
        "voorgelegd."
    )
    assert "maken in elk geval deel uit:\na. de risicobeoordeling" in lid_1


def test_the_onderdelen_and_aanhef_end_before_the_paragraph_after_the_list() -> None:
    parts = _parts(_article_47())

    assert parts["lid-1-aanhef"].endswith("maken in elk geval deel uit:")
    assert parts["lid-1-onder-c"] == (
        "nationale dreigingen en scenario’s als bedoeld in het tweede lid."
    )


def test_the_references_after_the_list_point_at_their_text() -> None:
    article = _article_47()

    texts = [article.text[r.start : r.end] for r in article.references]
    assert texts[:3] == [
        "artikel 14 van de Wet weerbaarheid kritieke entiteiten",
        "artikel 21, derde lid, van de Cyberbeveiligingswet",
        "artikel 37, derde lid, van de wet",
    ]
    assert [r.text for r in article.references] == texts


def test_a_paragraph_after_the_list_of_an_onderdeel_stays_in_it() -> None:
    (article,) = parse_toestand(
        """<toestand bwb-id='BWBR0005289'><artikel><kop><nr>193c</nr></kop>
        <lid><lidnr>2</lidnr><al>Een handelspraktijk is eveneens misleidend indien:</al>
        <lijst><li><li.nr>a.</li.nr><al>alfa;</al></li>
        <li><li.nr>b.</li.nr><al>de handelaar een verplichting niet nakomt, voor zover:</al>
          <lijst><li><li.nr>1°.</li.nr><al>de verplichting concreet is, en</al></li>
          <li><li.nr>2°.</li.nr><al>de handelaar aangeeft dat hij gebonden is,</al></li>
          </lijst>
          <al>waardoor de gemiddelde consument een besluit neemt;</al></li>
        <li><li.nr>c.</li.nr><al>gamma.</al></li></lijst></lid></artikel></toestand>"""
    ).articles
    parts = _parts(article)

    assert article.text == (
        "2. Een handelspraktijk is eveneens misleidend indien:\n"
        "a. alfa;\n"
        "b. de handelaar een verplichting niet nakomt, voor zover:\n"
        "1°. de verplichting concreet is, en\n"
        "2°. de handelaar aangeeft dat hij gebonden is,\n"
        "waardoor de gemiddelde consument een besluit neemt;\n"
        "c. gamma."
    )
    assert parts["lid-2-onder-b"].endswith(
        "gebonden is,\nwaardoor de gemiddelde consument een besluit neemt;"
    )
    assert (
        parts["lid-2-onder-b-onder-2"] == "de handelaar aangeeft dat hij gebonden is,"
    )
    assert parts["lid-2-onder-c"] == "gamma."
