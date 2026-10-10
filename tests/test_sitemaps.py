"""The files of the sitemaps (``core/sitemaps.py``): parts of at most so many addresses,
an index of them with the last day of each, escaped addresses, and no stale part left."""

from __future__ import annotations

from pathlib import Path

from lawgraph.commands.sitemaps import entries
from lawgraph.core import sitemaps
from lawgraph.core.sitemaps import Entry

BASE = "https://concordans.nl"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_parts_of_at_most_so_many_addresses_and_their_index(tmp_path: Path) -> None:
    laws = [Entry(f"/wetten/BWBR000000{n}", f"2025-0{n}-01") for n in range(1, 6)]
    counts = sitemaps.write(tmp_path, BASE, {"wetten": laws, "moties": []}, max_urls=2)
    assert counts == {"wetten": 5, "moties": 0}
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        "sitemap-wetten-2.xml",
        "sitemap-wetten-3.xml",
        "sitemap-wetten.xml",
        "sitemap.xml",
    ]
    index = (tmp_path / "sitemap.xml").read_text()
    assert (
        "<sitemap><loc>https://concordans.nl/sitemap-wetten-2.xml</loc>"
        "<lastmod>2025-04-01</lastmod></sitemap>"
    ) in index
    first = _read(tmp_path / "sitemap-wetten.xml")
    assert first.count("<url>") == 2
    assert (
        "<url><loc>https://concordans.nl/wetten/BWBR0000001</loc>"
        "<lastmod>2025-01-01</lastmod></url>"
    ) in first


def test_a_part_no_longer_named_is_removed(tmp_path: Path) -> None:
    # a gzipped part of before (the parts are plain XML now) goes too
    (tmp_path / "sitemap-dossiers.xml.gz").write_bytes(b"old")
    many = [Entry(f"/dossiers/{n}") for n in range(30000, 30005)]
    sitemaps.write(tmp_path, BASE, {"dossiers": many}, max_urls=2)
    sitemaps.write(tmp_path, BASE, {"dossiers": many[:1]}, max_urls=2)
    other = tmp_path / "robots.txt"
    other.write_text("kept")
    sitemaps.write(tmp_path, BASE, {"dossiers": many[:1]}, max_urls=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "robots.txt",
        "sitemap-dossiers.xml",
        "sitemap.xml",
    ]
    assert "<lastmod>" not in (tmp_path / "sitemap.xml").read_text()


def test_an_address_is_escaped() -> None:
    xml = sitemaps.urlset(BASE, [Entry("/zoeken?q=a&b=c")]).decode()
    assert "<loc>https://concordans.nl/zoeken?q=a&amp;b=c</loc>" in xml


def test_a_day_is_a_day() -> None:
    assert sitemaps.day("2025-07-01T00:00:00", "2026-10-09") == "2025-07-01"
    assert sitemaps.day("1 juli 2025", "2026-10-09") is None
    assert sitemaps.day(None, "2026-10-09") is None
    # a planned activity has not changed the page yet
    assert sitemaps.day("2026-11-03", "2026-10-09") == "2026-10-09"


def test_the_entries_have_an_address_each_once() -> None:
    rows = [
        {"id": "dossiers/36600_viii", "props": {"label": "36600-VIII"},
         "lastmod": "2026-09-30"},
        {"id": "dossiers/36600_viii", "props": {"label": "36600-VIII"}, "lastmod": None},
        # an activity has no page; a paper without its sequence has no address
        {"id": "activities/a1", "props": {}, "lastmod": None},
        {"id": "documents/p", "props": {"dossier_number": "36600"}, "lastmod": None},
    ]  # fmt: skip
    assert list(entries(rows, "2026-10-09")) == [
        Entry("/dossiers/36600-VIII", "2026-09-30")
    ]
