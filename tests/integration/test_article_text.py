"""The narrow form of an article (``/api/articles/.../text``, ``/api/articles/batch``) of real
BWB articles, from the XML through normalize and semantic to the API: art. 51 and 67 to 69
Cbw (leden, a lid with an aanhef and onderdelen), art. 19, 23 and 28 Cbb (no leden; a link
to an onderdeel of a lid of the Cbw) and art. 6:161 to 163 BW (cited by its book).

The fixtures are those articles cut from the toestanden of wetten.overheid.nl.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
)
from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden
from tests.paths import FIXTURES

CBW, CBB, BW6 = "BWBR0052872", "BWBR0052875", "BWBR0005289"
_LAWS = {
    CBW: ("bwb_article_text_cbw.xml", "2026-08-15"),
    CBB: ("bwb_article_text_cbb.xml", "2026-08-15"),
    BW6: ("bwb_article_text_bw6.xml", "2022-05-28"),
}

pytestmark = pytest.mark.xdist_group("article_text")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        write_toestanden(
            store,
            [
                (
                    kind,
                    external_id,
                    (FIXTURES / name).read_text(encoding="utf-8"),
                    {
                        "bwb_id": bwb_id,
                        "state_url": f"https://repo/{bwb_id}/x.xml",
                        "start_date": start,
                    },
                )
                for bwb_id, (name, start) in _LAWS.items()
                for kind, external_id in (
                    (RAW_KIND_BWB_TOESTAND, bwb_id),
                    (RAW_KIND_BWB_TOESTAND_ALL, f"{bwb_id}@{start}"),
                )
            ],
        )
        cli("normalize", "bwb")
        cli("normalize", "bwb-history")
        cli("semantic", "bwb")
        yield store


def _blocks(body: dict[str, Any]) -> list[tuple[str | None, str | None, list[str]]]:
    return [(b["anchor"], b["marker"], b["within"]) for b in body["blocks"]]


def _bare(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _same_text_and_places(api: Api, path: str) -> dict[str, Any]:
    """The narrow form of the article at *path*: its blocks with their markers are its
    whole text, and each anchor is the id of one of its parts."""
    body = api.get_json(f"{path}/text")
    detail = api.get_json(path)
    article = detail["article"]
    printed = "".join(f"{b['marker'] or ''}{b['text']}" for b in body["blocks"])
    assert _bare(printed) == _bare(article["text"])
    ids = {part["id"] for part in article["parts"]}
    named = {b["anchor"] for b in body["blocks"] if b["anchor"]}
    named |= {anchor for b in body["blocks"] for anchor in b["within"]}
    assert named <= ids, named - ids
    assert body["validity"] == article["validity"]
    assert body["key"] == article["key"] and body["path"] == article["path"]
    return body


def test_the_leden_are_blocks_with_their_anchors(api: Api) -> None:
    body = _same_text_and_places(api, f"/api/articles/{CBW}/68")

    assert _blocks(body) == [
        ("lid-1", "1.", []),
        ("lid-2", "2.", []),
        ("lid-3", "3.", []),
        ("lid-4", "4.", []),
    ]
    assert (body["label"], body["heading"]) == ("Artikel 68", "(toezichthouders)")
    assert body["law"]["key"] == CBW.lower()
    assert body["law"]["title"] == "Cyberbeveiligingswet"
    previous, following = body["previous"], body["next"]
    assert (previous["article_number"], following["article_number"]) == ("67", "69")
    assert previous["path"] == f"/wetten/{CBW}/artikel/67"


def test_an_onderdeel_stands_in_its_lid(api: Api) -> None:
    body = _same_text_and_places(api, f"/api/articles/{CBW}/51")

    blocks = _blocks(body)
    assert blocks[:3] == [
        ("lid-1", "1.", []),
        ("lid-2-aanhef", "2.", ["lid-2"]),
        ("lid-2-onder-a", "a.", ["lid-2"]),
    ]
    assert ("lid-2-onder-i", "i.", ["lid-2"]) in blocks
    assert blocks[-1] == ("lid-3", "3.", [])
    # the first article of the law (as far as the data holds it) has none before it
    assert body["previous"] is None
    assert body["next"]["article_number"] == "67"


def test_a_link_names_the_place_it_cites(api: Api) -> None:
    body = _same_text_and_places(api, f"/api/articles/{CBB}/28")

    (block,) = body["blocks"]
    assert (block["anchor"], block["kind"], block["marker"]) == (None, "tekst", None)
    (link,) = block["links"]
    assert link["text"] == "artikel 51, tweede lid, onderdeel i, van de wet"
    assert block["text"][link["start"] : link["end"]] == link["text"]
    assert link["target"]["id"] == f"articles/{CBW.lower()}_51"
    assert link["target"]["path"] == f"/wetten/{CBW}/artikel/51"
    assert (link["leden"], link["onderdelen"]) == (["2"], ["i"])


def test_an_article_cited_by_its_book(api: Api) -> None:
    body = _same_text_and_places(api, f"/api/articles/{BW6}/6:162")

    assert [anchor for anchor, _, _ in _blocks(body)] == ["lid-1", "lid-2", "lid-3"]
    assert body["display_name"] == "Art. 6:162 BW"
    assert body["previous"]["path"] == f"/wetten/{BW6}/artikel/6:161"
    assert body["next"]["path"] == f"/wetten/{BW6}/artikel/6:163"


def test_the_batch_keeps_the_order_and_names_what_is_missing(api: Api) -> None:
    refs = [f"{CBB}/28", f"{CBB}/19", f"{CBB}/999", f"{CBB}/23", f"{BW6}/6:162"]
    body = api.get_json("/api/articles/batch", refs=",".join(refs))

    assert [item["ref"] for item in body["items"]] == refs
    assert [
        (item["article"] or {}).get("article_number") for item in body["items"]
    ] == [
        "28",
        "19",
        None,
        "23",
        "162",
    ]
    assert body["not_in_data"] == [f"{CBB}/999"]
    for item in body["items"]:
        if item["article"]:
            single = api.get_json(f"/api/articles/{item['ref']}/text")
            assert item["article"] == single


def test_an_unknown_article_is_a_404(api: Api) -> None:
    response = api.get(f"/api/articles/{CBB}/999/text")
    assert response.status_code == 404, response.text
