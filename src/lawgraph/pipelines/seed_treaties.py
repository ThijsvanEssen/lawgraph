"""Seed pipeline for international treaty nodes (EVRM/ECHR).

Keeps EVRM article nodes consistent and independent of the strafrecht domain
profile.  Run this once (or idempotently on every deploy) to guarantee every
article reference resolves.

EVRM article coverage:
  Arts. 1–18   Substantive rights
  Arts. 19–51  Court structure and procedure
  Arts. 52–59  Final provisions
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.utils.display import make_display_name

logger = get_logger(__name__)

# CELEX identifier for EVRM / Convention for the Protection of Human Rights and
# Fundamental Freedoms (Rome, 4 November 1950, entry into force 3 September 1953).
EVRM_CELEX = "21970A0718(02)"

# Article titles — substantive rights (1-18) have full Dutch names; procedural
# articles (19-59) use a generic title so that "artikel 34 EVRM" still resolves.
EVRM_ARTICLE_TITLES: dict[str, str] = {
    "1": "Verplichting tot eerbiediging van de rechten van de mens",
    "2": "Recht op leven",
    "3": "Verbod van foltering",
    "4": "Verbod van slavernij en dwangarbeid",
    "5": "Recht op vrijheid en veiligheid",
    "6": "Recht op een eerlijk proces",
    "7": "Geen straf zonder wet",
    "8": "Recht op eerbiediging van privé-, familie- en gezinsleven",
    "9": "Vrijheid van gedachte, geweten en godsdienst",
    "10": "Vrijheid van meningsuiting",
    "11": "Vrijheid van vergadering en vereniging",
    "12": "Recht op huwelijk",
    "13": "Recht op een daadwerkelijk rechtsmiddel",
    "14": "Verbod van discriminatie",
    "15": "Afwijking in geval van noodtoestand",
    "16": "Beperkingen op politieke activiteit van vreemdelingen",
    "17": "Verbod van misbruik van rechten",
    "18": "Begrenzing van de beperkingen van de rechten",
    # Court structure / procedure (arts. 19-51)
    "19": "Instelling van het Hof",
    "20": "Aantal rechters",
    "21": "Vereisten",
    "22": "Verkiezing van rechters",
    "23": "Ambtstermijn en ontslag",
    "24": "Griffie en rapporteurs",
    "25": "Plenaire zitting van het Hof",
    "26": "Enkelvoudige formatie, comités, Kamers en Grote Kamer",
    "27": "Bevoegdheid van enkelvoudige formaties",
    "28": "Bevoegdheid van comités",
    "29": "Beslissingen van Kamers over ontvankelijkheid en gegrondheid",
    "30": "Afstand van rechtsmacht ten gunste van de Grote Kamer",
    "31": "Bevoegdheid van de Grote Kamer",
    "32": "Rechtsmacht van het Hof",
    "33": "Interstatelijke zaken",
    "34": "Individuele klachten",
    "35": "Ontvankelijkheidsvereisten",
    "36": "Interventie van derden",
    "37": "Doorhaling van de rol",
    "38": "Behandeling van de zaak",
    "39": "Minnelijke schikking",
    "40": "Openbare zittingen en toegang tot documenten",
    "41": "Billijke genoegdoening",
    "42": "Uitspraken van Kamers",
    "43": "Verwijzing naar de Grote Kamer",
    "44": "Definitieve uitspraken",
    "45": "Motivering van uitspraken en beslissingen",
    "46": "Bindende kracht en tenuitvoerlegging van uitspraken",
    "47": "Adviezen",
    "48": "Advierende bevoegdheid van het Hof",
    "49": "Motivering van adviezen",
    "50": "Kosten van het Hof",
    "51": "Privileges en immuniteiten van de rechters",
    # Final provisions (arts. 52-59)
    "52": "Onderzoek door de Secretaris-Generaal",
    "53": "Vrijwaring van bestaande rechten van de mens",
    "54": "Bevoegdheden van het Comité van Ministers",
    "55": "Afstand doen van andere wijzen van geschillenbeslechting",
    "56": "Territoriale toepassing",
    "57": "Voorbehouden",
    "58": "Opzegging",
    "59": "Ondertekening en bekrachtiging",
}

_EVRM_INSTRUMENT_PROPS: dict[str, Any] = {
    "celex": EVRM_CELEX,
    "title": "Europees Verdrag voor de Rechten van de Mens",
    "short_title": "EVRM",
    "jurisdiction": "EU",
    "kind": "verdrag",
}


class TreatiesSeedPipeline:
    """Seed EVRM instrument node and all 59 article nodes.

    This pipeline is idempotent — running it multiple times is safe.
    It ensures:
    - One instrument node for the EVRM (keyed by CELEX)
    - 59 article nodes, one per article (keyed by CELEX + article_number)
    - PART_OF_INSTRUMENT edges from each article to the EVRM instrument
    """

    def __init__(self, *, store: ArangoStore) -> None:
        self.store = store

    def run(self) -> dict[str, int]:
        summary = {
            "instrument_created": 0,
            "instrument_updated": 0,
            "articles_created": 0,
            "articles_updated": 0,
            "edges_created": 0,
        }

        instrument, inst_created = self._ensure_evrm_instrument()
        summary["instrument_created" if inst_created else "instrument_updated"] = 1

        from lawgraph.config.settings import RELATION_PART_OF_INSTRUMENT

        for article_number, title in EVRM_ARTICLE_TITLES.items():
            article, art_created = self._ensure_article(article_number, title)
            if art_created:
                summary["articles_created"] += 1
            else:
                summary["articles_updated"] += 1

            if instrument.id and article.id:
                try:
                    self.store.create_edge(
                        from_id=article.id,
                        to_id=instrument.id,
                        relation=RELATION_PART_OF_INSTRUMENT,
                        source="seed-treaties",
                    )
                    summary["edges_created"] += 1
                except Exception as exc:
                    logger.warning(
                        "Could not create PART_OF_INSTRUMENT edge for art. %s EVRM: %s",
                        article_number,
                        exc,
                    )

        logger.info("Treaties seed completed: %s", summary)
        return summary

    def _ensure_evrm_instrument(self) -> tuple[Node, bool]:
        instrument_key = make_node_key(EVRM_CELEX)
        props: dict[str, Any] = dict(_EVRM_INSTRUMENT_PROPS)
        props["display_name"] = make_display_name(NodeType.INSTRUMENT, props)

        node = Node(
            collection=COLLECTION_INSTRUMENTS,
            type=NodeType.INSTRUMENT,
            key=instrument_key,
            labels=["EU", "Verdrag", "Mensenrechten", "EVRM"],
            props=props,
        )
        existing = self.store.get_node(COLLECTION_INSTRUMENTS, instrument_key)
        self.store.insert_or_update(node)
        return node, existing is None

    def _ensure_article(self, article_number: str, title: str) -> tuple[Node, bool]:
        props: dict[str, Any] = {
            "celex": EVRM_CELEX,
            "article_number": article_number,
            "text": title,
        }
        props["display_name"] = make_display_name(NodeType.ARTICLE, props)
        key = make_node_key(EVRM_CELEX, article_number)

        node = Node(
            collection=COLLECTION_INSTRUMENT_ARTICLES,
            type=NodeType.ARTICLE,
            key=key,
            labels=["EU", "EVRM", "Mensenrechten", "Article"],
            props=props,
        )
        existing = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
        self.store.insert_or_update(node)
        return node, existing is None
