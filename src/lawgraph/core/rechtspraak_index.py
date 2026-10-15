"""The Atom index pages of the Rechtspraak: which judgments were published or changed."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from lawgraph.core.xml import local_name


@dataclass(frozen=True)
class IndexEntry:
    """One judgment of a Rechtspraak index page."""

    ecli: str
    updated: dt.datetime | None  # when the judgment was published or last changed
    title: (
        str  # "ECLI:NL:RBROT:2021:207, Rechtbank Rotterdam, 15-01-2021, 8527084 VZ ..."
    )

    @property
    def case_numbers(self) -> str:
        """The case numbers at the end of the title, after the date; empty without."""
        match = _TITLE_CASE_NUMBERS.search(self.title)
        return match["numbers"].strip() if match else ""


# A court name can hold commas ("Gemeenschappelijk Hof van Justitie van Aruba, Curaçao, ...").
_TITLE_CASE_NUMBERS = re.compile(r",\s*\d{2}-\d{2}-\d{4},\s*(?P<numbers>.+)$")


def parse_index(xml_text: str) -> tuple[int | None, list[IndexEntry]]:
    """``(total, entries)`` of an Atom index page; the total is what the search matched.

    Raises on a page that is not XML (``ET.ParseError``), not a feed (``ValueError``; a
    maintenance page can be well-formed) or with an entry whose time cannot be read
    (``ValueError``): an index that cannot be read must not look like an empty one.
    """
    root = ET.fromstring(xml_text)
    if local_name(root.tag) != "feed":
        raise ValueError(f"not an Atom feed: the page is a <{local_name(root.tag)}>")
    total: int | None = None
    entries: list[IndexEntry] = []
    for child in root:
        name = local_name(child.tag)
        if name == "subtitle":
            match = re.search(r"(\d+)", child.text or "")
            total = int(match.group(1)) if match else None
        elif name == "entry":
            fields = {local_name(e.tag): (e.text or "").strip() for e in child}
            if fields.get("id"):
                entries.append(
                    IndexEntry(
                        ecli=fields["id"],
                        updated=_parse_timestamp(fields["id"], fields.get("updated")),
                        title=fields.get("title", ""),
                    )
                )
    return total, entries


def _parse_timestamp(ecli: str, value: str | None) -> dt.datetime | None:
    """When the entry of *ecli* was published or last changed (UTC where the feed names no
    zone); None without a time. A time that cannot be read raises, as an unreadable page."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"{ecli}: unreadable <updated> {value!r} in the index"
        ) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
