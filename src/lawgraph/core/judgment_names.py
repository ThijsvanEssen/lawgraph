"""The names lawyers call landmark judgments by ("Haviltex", "Urgenda", "Lindenbaum/Cohen").

CURATED DATA: the names are kept by hand, in ``data/curated/judgment_names.json``
(``lawgraph curated set judgment-names``). The open data of the Rechtspraak carries no
name for a judgment: its metadata has no ``dcterms:alternative``, its vindplaatsen
(``dcterms:hasVersion``) are citations ("NJ 1981/635 met annotatie van C.J.H. Brunner"), and
the inhoudsindicatie of a later judgment names the precedent it applies as readily as its
own ("Uitleg. Haviltex."). A name is added here only for an ECLI checked against the
judgment itself (its court, date and inhoudsindicatie); an English translation the
Rechtspraak publishes under an ECLI of its own carries the name of the judgment it
translates.

``normalize rechtspraak`` writes ``props.names`` from this table on every judgment it
reads; ``semantic graph-list-stats`` writes it on a stub (a judgment cited but not loaded).
"""

from __future__ import annotations

from lawgraph.core.curated import LISTS

# ECLI -> the names of the judgment (``data/curated/judgment_names.json``)
CURATED_NAMES: dict[str, tuple[str, ...]] = {
    ecli: tuple(value["names"])
    for ecli, value in LISTS["judgment-names"].entries().items()
}


def judgment_names(ecli: str | None) -> list[str]:
    """The names of the judgment *ecli* (``CURATED_NAMES``); empty when it has none."""
    return list(CURATED_NAMES.get((ecli or "").upper(), ()))
