# Lawgraph — Schematisch overzicht voor de ontwerper

Dit document beschrijft de structuur, werking en onderlinge samenhang van het Lawgraph-systeem
op een manier die bruikbaar is voor het ontwerpen van diagrammen. Het is geen technische
specificatie: details die voor de lezer niet relevant zijn, zijn weggelaten of
vereenvoudigd. Het doel is dat een ontwerper begrijpt *wat* er te visualiseren valt en
*hoe de onderdelen zich tot elkaar verhouden.*

---

## 1. Wat doet Lawgraph?

Lawgraph brengt de Nederlandse rechtswereld in kaart als een netwerk van verbonden objecten
(een **kennisgraaf**). De kern van het idee: rechtspraak, wetsartikelen en parlementaire
besluitvorming zijn niet los van elkaar — ze verwijzen voortdurend naar elkaar. Lawgraph
maakt die verwijzingen zichtbaar en doorzoekbaar.

**Metafoor voor de ontwerper:** stel je een kaart voor van een stad. De straten zijn de
verbindingen, de gebouwen zijn de entiteiten (wetten, uitspraken, dossiers). Lawgraph
tekent die kaart automatisch — en werkt hem bij telkens als er iets verandert.

---

## 2. De vier databronnen

Lawgraph haalt data op uit vier officiële overheidsbronnen. Elke bron levert een specifiek
domein en een eigen dataformaat.

```
┌──────────────────────────────────────────────────────────────────────┐
│  BRON 1: wetten.overheid.nl                                          │
│  Domein: Nederlandse wet- en regelgeving                             │
│  Wat het levert: de volledige tekst van wetten, opgesplitst per      │
│    artikel. Inclusief historische versies (toestanden).              │
│  Formaat: XML (BWBR-standaard)                                       │
│  Uniek kenmerk: elke wet heeft een stabiel BWB-nummer (bijv. BWBR0001854) │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  BRON 2: rechtspraak.nl                                              │
│  Domein: Nederlandse rechterlijke uitspraken                         │
│  Wat het levert: de volledige tekst van uitspraken van rechtbanken,  │
│    gerechtshoven en de Hoge Raad.                                    │
│  Formaat: XML (ECLI-standaard)                                       │
│  Uniek kenmerk: elke uitspraak heeft een ECLI-nummer                 │
│    (bijv. ECLI:NL:HR:2023:1234)                                      │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  BRON 3: tweedekamer.nl (gegevensmagazijn)                           │
│  Domein: parlementaire informatica                                    │
│  Wat het levert: dossiers, documenten, debatten, stemmingen,         │
│    toezeggingen, commissies en Kamerleden.                           │
│  Formaat: JSON (OData-protocol)                                      │
│  Uniek kenmerk: rijke structuur — elk document is onderdeel van een  │
│    groter dossier; activiteiten zijn gekoppeld aan commissies        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  BRON 4: eur-lex.europa.eu                                           │
│  Domein: Europese wet- en regelgeving                                │
│  Wat het levert: Europese richtlijnen en verordeningen die           │
│    relevant zijn voor de Nederlandse rechtsorde.                     │
│  Formaat: HTML (CELEX-nummers als identifier)                        │
│  Uniek kenmerk: verbindt de nationale rechtsorde met het Europese    │
│    recht (implementatierelaties)                                     │
└──────────────────────────────────────────────────────────────────────┘
```

**Visuele suggestie:** vier kaarten of tegels op een rij, elk met een eigen kleur/icoon
per domein (juridisch, parlementair, Europees). Het BWB-nummer, ECLI, kamerstuknummer en
CELEX-nummer zijn de "identiteitsnummers" van dat domein — die kunnen als badges worden
weergegeven.

---

## 3. De pijplijn — hoe ruwe data wordt omgezet naar de graaf

De verwerking verloopt in drie duidelijk afgebakende fases. Elke fase bouwt voort op de vorige.

```
FASE 1 — OPHALEN
  ↕ Wat gebeurt er?
    Lawgraph bezoekt de externe bronnen en slaat de originele documenten
    op, volledig ongewijzigd. Niets wordt vertaald of bewerkt — het is
    een "fotokopie" van de bron op dat moment.
  ↕ Wat gaat erin?
    Een verzoek per bron (bijv.: "geef alle nieuwe uitspraken van deze week")
  ↕ Wat komt eruit?
    Ruwe bronrecords in de staging-laag (raw_sources). Elk record bevat:
    - de originele data (XML/JSON/HTML)
    - de bron (bwb / rechtspraak / tk / eurlex)
    - het type document (bijv. "tk-stemming")
    - een uniek ID (het externe identifier van de bron)
  ↕ Deduplicatie:
    Als hetzelfde document al bestaat (zelfde bron + type + ID), wordt het
    niet opnieuw opgeslagen. Een herhaalde run is altijd veilig.

         ─────────────────────────────────────
                    [raw_sources]
                 (staging-opslagplaats)
         ─────────────────────────────────────

FASE 2 — NORMALISEREN
  ↕ Wat gebeurt er?
    De ruwe data wordt gelezen en omgezet naar het uniforme
    datamodel van Lawgraph. Structuur wordt herkend en opgeslagen
    als knooppunten en structurele verbindingen in de graaf.
  ↕ Voorbeelden:
    - Een wet-XML wordt opgesplitst in artikel-knooppunten, elk met
      zijn eigen tekst. Elk artikel krijgt een verbinding naar de wet.
    - Een uitspraak-XML wordt omgezet naar een uitspraak-knooppunt met
      samenvatting, datum, rechter, paragrafen.
    - Een TK-stemming wordt opgeslagen met de uitslag (voor/tegen/onthouden)
      en een verbinding naar het bijbehorende dossier en de activiteit.
  ↕ Wat gaat erin?
    Ruwe bronrecords uit de staging-laag
  ↕ Wat komt eruit?
    Knooppunten in de graaf + structurele verbindingen (zie §4 en §5)
  ↕ Idempotent:
    Een knooppunt heeft altijd hetzelfde adres, ongeacht hoe vaak het is
    verwerkt. Dubbele verwerking overschrijft het knooppunt, maar maakt
    nooit duplicaten.

         ─────────────────────────────────────
               [graaf: knooppunten]
           + structurele verbindingen
         ─────────────────────────────────────

FASE 3 — SEMANTISCH VERBINDEN
  ↕ Wat gebeurt er?
    De tekst van uitspraken en wetteksten wordt geanalyseerd om te
    bepalen welke artikelen ze noemen of citeren. Dit is de
    "intelligente" stap — maar zonder AI of taalmodellen.
    Detectie werkt puur op patroonherkenning in de tekst.
  ↕ Voorbeelden:
    - "artikel 47 Sr" → verbinding naar Wetboek van Strafrecht, art. 47
    - "art. 6 EVRM" → verbinding naar het Europees Verdrag, art. 6
    - "richtlijn 2016/343" → verbinding naar die EU-richtlijn
  ↕ Wat gaat erin?
    Knooppunten met tekstvelden (uitspraken, wetsartikelen, kamerstukken)
  ↕ Wat komt eruit?
    Semantische verbindingen, elk met een betrouwbaarheidsscore
  ↕ Betrouwbaarheid:
    Niet elke verbinding is even zeker. Een expliciete volledige
    verwijzing ("artikel 47 Sr") is betrouwbaarder dan een generiek
    artikelnummer zonder wetsaanduiding.

         ─────────────────────────────────────
             [graaf: semantische verbindingen]
           + betrouwbaarheidsscores per relatie
         ─────────────────────────────────────
```

**Visuele suggestie:** een verticale stroom met drie grote blokken verbonden door pijlen.
De staging-laag is een tussenstation (grijs/neutraal), de graaf is het einddoel. Elke fase
heeft een duidelijk "in" en "uit".

---

## 4. De graaf — knooppunten (entiteiten)

De graaf bestaat uit twee soorten objecten: **knooppunten** (de entiteiten zelf) en
**verbindingen** (de relaties daartussen). Dit hoofdstuk beschrijft de knooppunten.

Er zijn twaalf typen knooppunten, gegroepeerd in drie domeinen:

### Domein A: Wetgeving

```
┌─────────────────────────────────────────────────────────┐
│  INSTRUMENT (wet / richtlijn / regeling)                │
│  Beschrijving: een juridisch instrument als geheel.     │
│    Bijv. het Wetboek van Strafrecht, de AVG,            │
│    de Wet op de kansspelen.                             │
│  Identificatie: BWB-nummer (NL) of CELEX-nummer (EU)    │
│  Bevat: titel, soort (wet, AMvB, richtlijn, ...), datum │
└─────────────────────────────────────────────────────────┘
          │
          │ (een instrument bestaat uit meerdere artikelen)
          ▼
┌─────────────────────────────────────────────────────────┐
│  ARTIKEL                                                │
│  Beschrijving: één artikel van één instrument.          │
│    Bijv. "artikel 47 Sr" of "artikel 6 EVRM".          │
│  Identificatie: combinatie van BWB-nummer + artikelnummer│
│  Bevat: de volledige tekst van het artikel              │
└─────────────────────────────────────────────────────────┘
```

### Domein B: Rechtspraak

```
┌─────────────────────────────────────────────────────────┐
│  UITSPRAAK (judgment)                                   │
│  Beschrijving: een rechterlijke uitspraak.              │
│    Bijv. een arrest van de Hoge Raad, een vonnis van    │
│    de rechtbank Amsterdam.                              │
│  Identificatie: ECLI-nummer                             │
│  Bevat: instantie, datum, samenvatting, volledige tekst │
│    opgesplitst in paragrafen                            │
└─────────────────────────────────────────────────────────┘
```

### Domein C: Parlementair

```
┌─────────────────────────────────────────────────────────┐
│  KAMERSTUKDOSSIER (dossier)                             │
│  Beschrijving: het overkoepelende dossier voor een      │
│    wetgevingstraject of politiek onderwerp.             │
│    Bijv. "Wet open overheid" of "35925".                │
│  Bevat: kamerstuknummer, titel, status (open/gesloten), │
│    huidige fase (bijv. "aanvaard", "intrekking"), datum │
│  Relatie: groepeert alle documenten, debatten en        │
│    stemmingen die bij dit traject horen                 │
└─────────────────────────────────────────────────────────┘
          │
          ├─── PUBLICATIE (publication)
          │    Een parlementair document: wetsvoorstel,
          │    memorie van toelichting, amendement, motie, etc.
          │    Bevat: soort, datum, indieners, tekst
          │
          ├─── ACTIVITEIT (debat/hoorzitting)
          │    Een vergadering of debat in de Kamer.
          │    Bevat: datum, onderwerp, betrokken commissie
          │
          ├─── STEMMING
          │    De uitkomst van een stemming over een wetsvoorstel
          │    of motie. Bevat: uitslag per fractie (voor/tegen/
          │    onthouden), datum, besluit.
          │
          └─── TOEZEGGING
               Een toezegging gedaan door een minister of
               staatssecretaris tijdens een debat.
               Bevat: tekst van de toezegging, gedaan door wie,
               in welk debat.

┌─────────────────────────────────────────────────────────┐
│  COMMISSIE                                              │
│  Beschrijving: een vaste Kamercommissie.                │
│    Bijv. "Commissie Justitie en Veiligheid".            │
│  Bevat: naam, slug, lijst van leden                     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  LID (kamerlid / minister)                              │
│  Beschrijving: een persoon die optreedt in de Kamer     │
│    of als minister.                                     │
│  Bevat: naam, partij, functie                           │
└─────────────────────────────────────────────────────────┘
```

**Visuele suggestie:** drie gekleurde clusters (wetgeving / rechtspraak / parlementair),
elk met de knooppunttypen erin. De hiërarchische relaties (instrument → artikel,
dossier → publicatie) kunnen als boomstructuur worden weergegeven binnen een cluster.

---

## 5. De graaf — verbindingen (relaties)

Verbindingen zijn de "straten" van de kaart. Ze lopen altijd van één knooppunt naar een
ander. Er zijn drie categorieën:

### 5A. Structurele verbindingen

Zeker en volledig bepaald door de brondata. Geen interpretatie nodig.

```
ARTIKEL ──────────────────── DEEL_VAN ──────────────────── INSTRUMENT
  "artikel 47 Sr"                                         "Wetboek van Strafrecht"

PUBLICATIE ────────────────── DEEL_VAN ─────────────────── KAMERSTUKDOSSIER
  "Memorie van Toelichting"                               "Dossier 36558"

ACTIVITEIT ──────────────────DEEL_VAN ─────────────────── KAMERSTUKDOSSIER
  "Debat 15 maart 2024"                                   "Dossier 36558"

STEMMING ─────────────────── DEEL_VAN ─────────────────── KAMERSTUKDOSSIER
  "Stemming 22 maart 2024"                                "Dossier 36558"

ACTIVITEIT ────────────────── BEHANDELD_DOOR ────────────── COMMISSIE
  "Hoorzitting"                                           "Commissie J&V"

STEMMING ─────────────────── BESLUIT ──────────────────── PUBLICATIE
  "Stemming"                                              "Wetsvoorstel"

TOEZEGGING ─────────────────GEDAAN_IN ─────────────────── ACTIVITEIT
  "Toezegging minister"                                   "Debat"

LID ─────────────────────── LID_VAN ────────────────────── COMMISSIE
  "Kamerlid X"                                            "Commissie J&V"

KAMERSTUKDOSSIER ────────── RAAKT ─────────────────────── INSTRUMENT
  "Dossier over wijziging Sr"                             "Wetboek van Strafrecht"
```

### 5B. Wetgevingsmutatieverbindingen

Een speciale subcategorie van structurele verbindingen: ze geven aan dat een
parlementair document een *wijziging* voorstelt voor een wetsartikel.

```
PUBLICATIE ─── WIJZIGT ──────────────────────────────────► ARTIKEL
  "Amendement"               (status: voorgesteld)          "art. 47 Sr"

PUBLICATIE ─── INTRODUCEERT ────────────────────────────► ARTIKEL
  "Wetsvoorstel"             (status: voorgesteld)          "art. 47a Sr (nieuw)"

PUBLICATIE ─── TREKT_IN ──────────────────────────────── ARTIKEL
  "Intrekkingsvoorstel"      (status: voorgesteld)          "art. 48 Sr"

PUBLICATIE ─── LICHT_TOE ────────────────────────────────► ARTIKEL
  "Memorie van Toelichting"                                 "art. 47 Sr"
```

Deze verbindingen zijn altijd voorzien van een **status** (zie §6).

### 5C. Semantische verbindingen

Afgeleid door analyse van de tekst. Elke verbinding draagt een **betrouwbaarheidsscore**
(een getal tussen 0 en 1).

```
UITSPRAAK ─── NOEMT_ARTIKEL ────────────────────────────► ARTIKEL
  "ECLI:NL:HR:2023:1234"     (conf: 0.95)                  "art. 47 Sr"

UITSPRAAK ─── CITEERT_UITSPRAAK ────────────────────────► UITSPRAAK
  "ECLI:NL:HR:2023:1234"     (conf: 0.85)                  "ECLI:NL:HR:2019:567"

ARTIKEL ──── VERWIJST_NAAR ─────────────────────────────► ARTIKEL
  "art. 9 AVG"               (conf: 0.90)                  "art. 8 EVRM"

INSTRUMENT ─ IMPLEMENTEERT ─────────────────────────────► INSTRUMENT (EU-richtlijn)
  "Wet bescherming pers.geg."  (conf: 0.95)                "Richtlijn 2016/679"

PUBLICATIE ─ NOEMT_ARTIKEL ─────────────────────────────► ARTIKEL
  "Kamerstuk / motie"        (conf: 0.70)                  "art. 47 Sr"
```

**Visuele suggestie:** maak structurele verbindingen dikker/solider dan semantische.
Semantische verbindingen kunnen als gestreepte lijnen worden weergegeven, met een
kleurgradiënt of dikte die de betrouwbaarheid aangeeft (dun + licht = laag vertrouwen,
dik + donker = hoog vertrouwen).

---

## 6. Verbindingsstatus — de levenscyclus van een wijziging

Wetgevingsmutatieverbindingen (type 5B hierboven) gaan door een levenscyclus. Dit is een
van de uniekere kenmerken van Lawgraph: het systeem weet niet alleen *wat de wet zegt*,
maar ook *wat er aan de wet wordt voorgesteld en of dat is aangenomen.*

```
                     ┌─────────────────────┐
                     │    VOORGESTELD      │
                     │                     │
                     │  Er is een dossier  │
                     │  dat dit artikel    │
                     │  wil wijzigen, maar │
                     │  de Kamer heeft nog │
                     │  niet gestemd.      │
                     └──────────┬──────────┘
                                │
                   ┌────────────┴────────────┐
                   │    (stemming vindt      │
                   │     plaats)             │
                   │                         │
         ┌─────────▼──────────┐   ┌──────────▼─────────┐
         │    CANONIEK        │   │    VERWORPEN        │
         │                    │   │                     │
         │  Het voorstel is   │   │  De Kamer heeft     │
         │  aangenomen. De    │   │  het voorstel       │
         │  verbinding is nu  │   │  afgestemd.         │
         │  geldend recht.    │   │  De verbinding      │
         │                    │   │  blijft bewaard     │
         └────────────────────┘   │  maar is inactief.  │
                                  └─────────────────────┘

         ┌────────────────────────────────────────────┐
         │  VERLOPEN                                  │
         │                                            │
         │  De wet is gewijzigd maar door een latere  │
         │  wet alweer aangepast of ingetrokken.      │
         │  Historisch bewaard.                       │
         └────────────────────────────────────────────┘
```

**Elke statuswijziging wordt gelogd** in een onveranderlijk logboek: wanneer, waarom
(welke stemming), van welke status naar welke. Dit maakt de wetgevingsgeschiedenis
van elk artikel reconstrueerbaar.

**Visuele suggestie:** een toestandsdiagram met vier staten verbonden door pijlen.
`voorgesteld` is de beginstaat. De gesplitste pijl na de stemming toont het verschil
tussen aangenomen en verworpen.

---

## 7. Het parlementaire circuit in detail

De parlementaire kant is de meest gestructureerde: elk "ding" heeft een vaste plek
in het geheel.

```
KAMERSTUKDOSSIER
  │  Het overkoepelende dossier. Alles hangt hieraan.
  │  Heeft een kamerstuknummer (bijv. "36558") en een status.
  │
  ├──► PUBLICATIES (documenten)
  │      - Wetsvoorstel (de initiële tekst)
  │      - Nota van wijziging (aanpassing door minister)
  │      - Amendement (wijzigingsvoorstel door Kamerlid)
  │      - Motie (politieke opdracht aan de minister)
  │      - Memorie van Toelichting (uitleg bij het voorstel)
  │      Elk document kan WIJZIGT / INTRODUCEERT / TREKT_IN relaties
  │      hebben naar specifieke wetsartikelen.
  │
  ├──► ACTIVITEITEN (debatten / hoorzittingen)
  │      - Een vergadering waar dit dossier behandeld wordt.
  │      - Elke activiteit is behandeld door één of meer commissies.
  │      - Tijdens een activiteit kunnen toezeggingen worden gedaan.
  │
  ├──► STEMMINGEN
  │      - De formele beslissing. Uitslag per fractie.
  │      - Een stemming is gekoppeld aan een activiteit.
  │      - Resultaat bepaalt de status van de wetgevingsverbindingen.
  │
  └──► TOEZEGGINGEN
         - Informele maar geregistreerde beloftes van een minister.
         - Gekoppeld aan de activiteit waarin ze zijn gedaan.
         - Kunnen verwijzen naar een specifiek wetsartikel.

COMMISSIE
  │  Behandelt meerdere dossiers. Heeft vaste leden.
  │
  └──► LEDEN (kamerleden / ministers)
         - Elk lid hoort bij een partij.
         - Leden kunnen auteur zijn van documenten.
```

**Tijdlijn-dimensie:** per dossier zijn alle publicaties, activiteiten en stemmingen
chronologisch te ordenen — een tijdlijn van het wetgevingsproces. Dit is een
aantrekkelijk visueel concept: een horizontale tijdlijn per dossier met de verschillende
typen events elk met een eigen icoon/kleur.

---

## 8. Citaatdetectie — hoe verbindingen worden gevonden

De semantische verbindingen komen niet uit de brondata maar worden *afgeleid*. Dit is
de meest interessante maar ook de meest onzekere stap.

### Hoe werkt het?

De tekst van een uitspraak of wetsartikel wordt gescand op patronen die lijken op
juridische verwijzingen:

```
Patroon A — volledig gekwalificeerd (hoge zekerheid):
  "artikel 47 Sr"        → Wetboek van Strafrecht, art. 47
  "art. 6 lid 1 EVRM"   → Europees Verdrag, art. 6
  "artikel 3:305a BW"   → Burgerlijk Wetboek Boek 3, art. 305a

Patroon B — alias zonder wet (lagere zekerheid):
  "artikel 47"           → welke wet? Moet worden afgeleid uit context.
  "het eerste lid"       → verwijst naar het vorige artikel (structureel)

Patroon C — instrument zonder artikel (indicatief):
  "de AVG"              → Algemene Verordening Gegevensbescherming
  "richtlijn 2016/343"  → specifieke EU-richtlijn
```

### Betrouwbaarheidsschaal (conceptueel)

```
  Laag                                                    Hoog
  ──────────────────────────────────────────────────────────
  "artikel 47"    "artikel 47 BW"    "artikel 47 lid 2 Sr"
  (geen wet)      (vage wet)         (volledig gekwalificeerd)
```

### Wat wordt er vastgelegd per verbinding?

```
  Van:        de uitspraak (ECLI-nummer)
  Naar:       het artikel (BWB-nummer + artikelnummer)
  Relatie:    NOEMT_ARTIKEL / CITEERT_ARTIKEL
  Score:      een getal (bijv. 0.35 of 0.95)
  Positie:    waar in de tekst staat de verwijzing (beginpositie, eindpositie)
  Tekst:      het originele tekstfragment dat de verwijzing bevat
```

**Visuele suggestie:** een "zekerheidsspectrometer" als visueel element — van vaag naar
zeker, met voorbeelden van citaten op de schaal.

---

## 9. De graaf als geheel — mogelijke overzichtsdiagrammen

Hier zijn de vijf conceptuele diagrammen die het meest waardevol zijn:

### Diagram A — Systeemoverzicht (het grote plaatje)
Vier bronnen → pijplijn met drie fasen → één graaf → API → gebruiker.
Horizontaal of verticaal. Meest geschikt als introductie of voorpagina.

### Diagram B — Pijplijnflow
Verticale stroom: bronnen → staging → knooppunten + structuur → semantische verbindingen.
Elk blok heeft een "in" en "uit" beschrijving. Nadruk op de stappen.

### Diagram C — Entiteitenkaart (knooppunttypen)
Drie clusters (wetgeving / rechtspraak / parlementair) met de knooppunttypen erin.
Hiërarchische relaties als pijlen binnen het cluster.
Semantische verbindingen als stippellijnen die de clusters verbinden.

### Diagram D — Wetgevingslevenscyclus
Toestandsdiagram voor verbindingsstatus: voorgesteld → canoniek / verworpen / verlopen.
Met de tijdlijn van het parlementaire proces eronder.
Nadruk op de koppeling tussen stemming en statuswijziging.

### Diagram E — Citaatnetwerk (conceptueel)
Visuele weergave van hoe uitspraken en wetsartikelen naar elkaar verwijzen.
Knooppunten als cirkels, verbindingen als lijnen met betrouwbaarheidszwaarte.
Kan illustratief zijn (niet alle data tonen, wel de structuur).

---

## 10. Kleur- en stijlsuggesties

Ter inspiratie — niet bindend:

```
Wetgeving (instrumenten / artikelen):    warm geel of oranje-tint
Rechtspraak (uitspraken):               blauw of teal
Parlementair:                            groen of paars
EU / Europees:                           blauw (donkerder)

Structurele verbindingen:               solide lijn, neutraal grijs
Semantische verbindingen:               gestreepte lijn, kleurgecodeerd
  - hoge betrouwbaarheid:               donker, dik
  - lage betrouwbaarheid:               licht, dun

Verbindingsstatus:
  - voorgesteld:                         geel / amber
  - canoniek (geldend recht):           groen
  - verworpen:                          rood
  - verlopen:                           grijs
```

---

## 11. Getallen en omvang (ter referentie)

Voor het kalibreren van de diagrammen — de graaf bevat ruwweg:

- **Instrumenten:** honderden (Nederlandse wetten + EU-richtlijnen)
- **Artikelen:** tienduizenden (elk instrument heeft er gemiddeld tientallen)
- **Uitspraken:** tienduizenden (groeiend)
- **Kamerstukdossiers:** duizenden
- **Publicaties per dossier:** gemiddeld 10–50 documenten
- **Verbindingen totaal:** vele honderdduizenden, waarvan het grootste deel semantisch

De graaf is dus erg groot voor volledige weergave — diagrammen zijn altijd
**illustratief** of tonen een **subset** (bijv. één dossier, één wet, één uitspraak).

---

*Dit document is gegenereerd op basis van de actuele broncode van Lawgraph (mei 2025).*
