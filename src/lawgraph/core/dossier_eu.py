"""What the title of a dossier says of the EU: the Commission documents it is about and the
EU acts it implements.

The Tweede Kamer gives no field for either. Its title names them: an EU proposal by its
COM number ("EU-voorstel: Omnibus over belastingen COM (2026) 560"), a bill by the acts it
carries out ("ter implementatie van Richtlijn (EU) 2024/2811"). ``semantic tk-dossier-eu``
reads them from there (basis ``title``) and adds the EU acts that the laws the dossier
legislated implement (``IMPLEMENTS``, with the bases of those edges).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from lawgraph.config.constants import IMPLEMENTS_BASIS_TITLE
from lawgraph.core.eu_citations import implemented_acts

# "COM (2025) 80", "COM(2026)710", "COM(2025) 0080": the year and number of a document of the
# Commission.
_COM = re.compile(r"\bCOM\s*\(\s*(\d{4})\s*\)\s*(\d{1,4})\b")
# The CELEX descriptors of a COM document (sector 5): a proposal for an act, any other.
_COM_DESCRIPTORS = ("PC", "DC")


def com_numbers(title: str | None) -> list[str]:
    """The COM numbers *title* names, as EUR-Lex writes them (``COM(2025) 80``), in order,
    each once."""
    found = (f"COM({year}) {int(number)}" for year, number in _COM.findall(title or ""))
    return list(dict.fromkeys(found))


def com_celex_candidates(com: str) -> list[str]:
    """The CELEX numbers the COM document *com* (``COM(2025) 80``) has in EUR-Lex, one of
    which it is: ``52025PC0080`` for a proposal, ``52025DC0080`` for another document."""
    year, number = _COM.findall(com)[0]
    return [f"5{year}{d}{int(number):04d}" for d in _COM_DESCRIPTORS]


def eu_ref(title: str | None, in_graph: Iterable[str]) -> list[dict[str, Any]] | None:
    """``{com, celex}`` per COM number of *title*; ``celex`` that of the document among the
    CELEX numbers of the graph *in_graph*, null when the graph lacks it."""
    known = set(in_graph)
    refs = [
        {
            "com": com,
            "celex": next((c for c in com_celex_candidates(com) if c in known), None),
        }
        for com in com_numbers(title)
    ]
    return refs or None


def implements(
    title: str | None, legislated: Mapping[str, Iterable[str]]
) -> list[dict[str, Any]] | None:
    """``{celex, bases}`` of the EU acts a dossier implements, by CELEX: those its *title*
    says it implements (basis ``title``) and *legislated*, CELEX to the bases of the
    ``IMPLEMENTS`` of the laws it legislated."""
    bases: dict[str, set[str]] = {
        celex: set(found) for celex, found in legislated.items()
    }
    for celex in implemented_acts([title or ""]):
        bases.setdefault(celex, set()).add(IMPLEMENTS_BASIS_TITLE)
    acts = [{"celex": c, "bases": sorted(bases[c])} for c in sorted(bases)]
    return acts or None
