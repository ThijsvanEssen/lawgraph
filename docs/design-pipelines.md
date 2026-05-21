# LawGraph Data Pipelines — Design Document

## 1. Pipeline Architecture

The system uses a strict **three-phase pattern**: **Retrieve → Normalize → Semantic**.

### Phase 1: Retrieve
- External sources (TK OData, BWB XML, Rechtspraak XML, EUR-Lex HTML) are fetched
- Raw records stored idempotently in the `raw_sources` collection, keyed by `SHA-1(source:kind:external_id)`
- Each source implements a subclass of `RetrievePipelineBase` or `TkDossiersRetrievePipeline`

### Phase 2: Normalize
- Raw records queried from `raw_sources`, transformed into domain nodes
- Nodes upserted into target collections via `store.insert_or_update()`
- Edges built with deterministic SHA-1 keys (idempotent)
- **Incremental mode:** `_query_raw_sources()` filters by `fetched_at >= @since`

### Phase 3: Semantic
- Citation and relation detection on normalized text fields
- Produces additional edges (REFERS_TO_ARTICLE, CITES_JUDGMENT, AMENDS, etc.)
- See `design-semantic-pipelines.md` for full detail

### Base Classes

**`RetrievePipelineBase`** (`pipelines/retrieve/base.py`):
- `run() -> PipelineResult`: orchestrates `fetch()` → `_insert()` per record
- Subclasses override `fetch()` returning `Sequence[RetrieveRecord]`

**`NormalizePipeline`** (`pipelines/normalize/base.py`):
- `run(since=None) -> None`: three steps: `fetch_raw()` → `normalize_nodes()` → `build_edges()`
- `_query_raw_sources(source, kinds, since)`: AQL query on `raw_sources` filtered by source + kind + optional `fetched_at >= since`
- `_group_by_kind(rows, kinds)`: groups raw records into per-kind lists
- `_text_contains_keywords(text, keywords)`: case-insensitive substring match used for domain classification
- `_ensure_related_topic_edge(node, topic_node, source)`: idempotent edge to domain topic node

### RetrieveRecord

```python
@dataclass(frozen=True)
class RetrieveRecord:
    source: str           # "tk", "bwb", "rechtspraak", "eurlex"
    kind: str             # "tk-zaak", "bwb-toestand-xml", etc.
    external_id: str | None
    payload_json: dict | list | None = None   # OData/API responses
    payload_text: str | None = None            # XML/HTML content
    meta: dict | None = None
```

---

## 2. Retrieve Pipelines

### TK Parliamentary Dossiers — `TkDossiersRetrievePipeline`

**File:** `pipelines/retrieve/tk_dossiers.py`

| Entity | Kind | Incremental | Notes |
|--------|------|-------------|-------|
| Kamerstukdossier | `tk-dossier` | yes (`ApiGewijzigdOp`) | |
| Activiteit | `tk-activiteit` | yes | 3-level expand: Agendapunt→Zaak→Kamerstukdossier |
| Stemming | `tk-stemming` | yes; optional override `stemmingen_since` | One raw row per fractie per Besluit |
| Toezegging | `tk-toezegging` | yes | |
| Commissie | `tk-commissie` | **no** — always full-refresh | CommissieZetel + CommissieZetelVastPersoon expanded |
| Persoon | `tk-persoon` | **no** — always full-refresh | Fractielabel included directly |
| Document (Kamerstuk) | `tk-document` | yes; optional override `documents_since` | ~400K+ full; always use `since` |

**CLI flags:**
```
--since DATE            incremental for all entities (parses "Nd" shorthand)
--skip-personen         skip slow Persoon full-refresh
--skip-stemmingen       skip Stemming fetch
--stemmingen-since      override --since for stemmingen only
--skip-documents        skip Document fetch
--documents-since       override --since for documents only (recommended: 730d)
```

**Pagination:** skip-based (`$skip=0, 250, 500...`) — TK API does not emit `@odata.nextLink` for these endpoints. End-of-page detected when `len(page) < page_size`.

### TK Procedures & Publications — `TKRetrievePipeline`

**File:** `pipelines/retrieve/tk.py`

| Entity | Kind | Notes |
|--------|------|-------|
| Zaak | `tk-zaak` | Filtered by `since`; optional server-side keyword pre-filter |
| Document (as DocumentVersie) | `tk-documentversie` | Expanded with parent Zaak via `$expand=Zaak` |

**CLI flags:**
```
--profile PROFILE    Domain profile to filter by (e.g. strafrecht)
--since-days N       Days to look back for modified records (default: 1)
--limit N            Dev/smoke-test hard cap per endpoint; 0 = no cap (default: 0)
```

**Pagination:** nextLink-based via `_paged_get()` — the TK API emits `@odata.nextLink` for Zaak and Document endpoints. `$top` is never sent, so the API returns all matching pages. Pass `--limit N` only for development smoke-tests; it applies a post-fetch in-memory cap and logs a `WARNING` so the cap is never silent.

**Keyword filtering:** there is no `--keywords` CLI flag. When `--profile` is used, up to 3 keywords are derived from `filters.tk.title_contains` in the domain config and pushed server-side as `contains(tolower(Field), 'kw')` OData filter clauses (the TK API rejects more than ~3 such OR clauses). The full client-side `make_tk_filter` then runs on every returned record for precise filtering.

### TK Text Hydration — `TKTextHydratePipeline`

**File:** `pipelines/retrieve/tk_content.py`

Hybrid pipeline: reads the `publications` collection (not `raw_sources`), fetches PDF binary from TK API for each publication where `props.text` is null, extracts plain text via `pdfminer`, and stores the text back via AQL MERGE. Rate-limited at 0.5 s between calls. Text cap: 500,000 characters stored per document.

### BWB — `BWBRetrievePipeline`

**File:** `pipelines/retrieve/bwb.py`

Fetches the current `Toestand` (law version) XML for an explicit list of BWB IDs. Uses the SRU service to find the active version (einddatum == "9999-12-31"), then downloads the XML. No incremental support — must re-provide the full ID list each run.

### Rechtspraak — `RechtspraakRetrievePipeline`

**File:** `pipelines/retrieve/rechtspraak.py`

| Entity | Kind | Notes |
|--------|------|-------|
| Index feed | `rs-index` | Atom/XML feed; stored but not consumed by normalize |
| ECLI content | `rs-content` | One XML per ECLI; explicit ECLI list required |

### EUR-Lex — `EurlexRetrievePipeline`

**File:** `pipelines/retrieve/eurlex.py`

Fetches HTML for an explicit list of CELEX IDs via the CELLAR publications server (`publications.europa.eu/resource/celex/<CELEX>`). Follows redirects. No incremental support.

---

## 3. Normalize Pipelines

All normalize pipelines share the same three-step contract: `fetch_raw()` → `normalize_nodes()` → `build_edges()`. The base class handles AQL queries and domain config loading; subclasses implement domain-specific parsing.

---

### 3.1 TK Parliamentary Dossiers — `TkDossiersNormalizePipeline`

**File:** `pipelines/normalize/tk_dossiers.py`

**Processing order matters** (dependencies flow downward):

```
1. Commissies      — no deps; needed by Activiteiten edge builder
2. Personen        — no deps; needed by Lid→Commissie edge builder
3. Kamerstukdossiers — no deps; needed by everything below
4. Activiteiten    — depend on Commissie nodes existing
5. Stemmingen      — grouped by Besluit_Id; depend on Dossier nodes
6. Toezeggingen    — depend on Activiteit nodes
7. TK Documents    — produce publication nodes; link to Dossiers
```

Fase enrichment runs after all nodes are created, traversing Activiteit → Zaak chains to classify dossiers as `wetsvoorstel` / `overig` / `afgehandeld`.

---

#### Commissies

**Source:** `raw_sources` where `source="tk"` and `kind="tk-commissie"`

**Key derivation:** `make_node_key(payload["Id"])` — the TK UUID

**Matching / field extraction:**

| Prop | Source field | Fallback |
|------|-------------|---------|
| `external_id` | `Id` | — |
| `naam` | `NaamNL` | `Naam` → `Id` |
| `afkorting` | `Afkorting` | `""` |
| `slug` | `make_node_key(afkorting \|\| naam)` | — |
| `display_name` | `naam` | — |

Skips records with no `Id`.

---

#### Personen (Leden)

**Source:** `raw_sources` where `source="tk"` and `kind="tk-persoon"`

**Key derivation:** `make_node_key(payload["Id"])`

**Matching / field extraction:**

| Prop | Source field | Notes |
|------|-------------|-------|
| `external_id` | `Id` | |
| `naam` | `Voornamen` + `Tussenvoegsel` + `Achternaam` | Joined with spaces; extra whitespace collapsed |
| `partij` | `Fractielabel` | Empty string for independents |
| `actief` | `not bool(Verwijderd)` | |
| `display_name` | `"naam (partij)"` | Just `naam` if no fractie |

Skips records with no `Id`.

---

#### Kamerstukdossiers

**Source:** `raw_sources` where `source="tk"` and `kind="tk-dossier"`

**Key derivation:** `make_node_key(nummer)` if no toevoeging; `make_node_key(nummer, toevoeging)` if toevoeging is present. This prevents dossiers with the same nummer but different toevoeging (e.g. `36554` vs `36554-I`) from overwriting each other.

The in-memory `nodes` dict is indexed under **both** `external_id` (TK UUID) and `"{nummer}-{toevoeging}"` (or bare `nummer` if no toevoeging) to allow fast lookups from edge builders.

**Matching / field extraction:**

| Prop | Source field | Fallback / Notes |
|------|-------------|-----------------|
| `external_id` | `Id` | |
| `nummer` | `Nummer` (int) | Required; skip if None |
| `kamerstuknummer` | `str(Nummer)` | |
| `toevoeging` | `Toevoeging` | `""` if absent |
| `titel` | `Titel` | `Citeertitel` → `str(nummer)` |
| `afgedaan` | `bool(Afgedaan)` | |
| `geopend_op` | `DatumRegistratie` | ISO date (YYYY-MM-DD) |
| `gesloten_op` | `DatumGesloten` | ISO date |
| `huidige_fase` | derived | `"afgehandeld"` if closed; `null` until fase enrichment |
| `display_name` | `"Kamerstukdossier {nummer}[-toevoeging]: titel"` | |

**Fase enrichment** (`_enrich_dossier_fasen`): runs after all nodes are stored. Traverses Activiteit raw records to build a `dossier_nummer → set(Zaak.Soort)` mapping. For each dossier:
- Already `"afgehandeld"` → skip (immutable)
- Any linked Zaak.Soort in `{"Wetgeving", "Initiatiefwetgeving"}` → `"wetsvoorstel"`
- Otherwise → `"overig"`

---

#### Activiteiten

**Source:** `raw_sources` where `source="tk"` and `kind="tk-activiteit"`

**Key derivation:** `make_node_key(payload["Id"])`

**Field extraction via expand chain `Agendapunt → Zaak → Kamerstukdossier`:**

The TK API returns Activiteit with a nested `Agendapunt` list. Each Agendapunt has a `Zaak` list. Each Zaak has a `Kamerstukdossier` list. The normalize pipeline walks this chain to collect:

- `dossier_nummers`: all unique `Kamerstukdossier.Nummer` values reachable through the chain
- `zaak_soorten`: all unique `Zaak.Soort` values (used for fase enrichment)
- `commissie_id`: `Voortouwcommissie_Id` directly on Activiteit

| Prop | Source field | Notes |
|------|-------------|-------|
| `external_id` | `Id` | |
| `datum` | `Datum` | ISO date split at `T` |
| `agenda_titel` | `Omschrijving` | |
| `soort` | `Soort` | |
| `commissie_id` | `Voortouwcommissie_Id` | |
| `dossier_nummers` | via Agendapunt→Zaak→Kamerstukdossier.Nummer | deduplicated list |
| `zaak_soorten` | via Agendapunt→Zaak.Soort | deduplicated list |
| `tk_url` | `https://www.tweedekamer.nl/vergaderingen/details?id={Id}` | |

---

#### Stemmingen

**Source:** `raw_sources` where `source="tk"` and `kind="tk-stemming"`

The TK API returns **one raw Stemming record per fractie per Besluit**. The normalize pipeline groups these by `Besluit_Id` into a single Stemming node per Besluit.

**Grouping key:** `payload["Besluit_Id"]` — records without a `Besluit_Id` are skipped (logged as warning).

**Key derivation:** `make_node_key("stemming", besluit_id)`

**Aggregation logic:**

Each raw vote record carries:
- `ActorFractie` — party name
- `Soort` — `"Voor"` / `"Tegen"` / `"Onthouden"` (matched case-insensitively via substring)
- `FractieGrootte` — number of seats

Per Besluit, votes are bucketed into `voor`, `tegen`, `onthouding` lists. Each entry: `{partij, aantal_zetels}`.

**Outcome (`aangenomen`) determination:**
1. `besluit.BesluitSoort` or `StemmingsSoort` contains `"aangenomen"` → `True`
2. `besluit.BesluitSoort` contains `"verworpen"` → `False`
3. Otherwise: `sum(voor.zetels) > sum(tegen.zetels)`

**Onderwerp resolution** (priority order):
1. `Besluit.Agendapunt.Onderwerp` — the agenda item description
2. First `Zaak.Titel` linked via `Besluit→Agendapunt→Zaak`
3. `Besluit.BesluitTekst` (typically just "Aangenomen." — used as last resort)
4. `"Besluit {besluit_id[:8]}"`

**Dossier nummers:** resolved via `Besluit → Agendapunt → Zaak → Kamerstukdossier.Nummer`.

| Prop | Source / Derivation |
|------|-------------------|
| `besluit_id` | `Besluit_Id` |
| `agendapunt_id` | `Besluit.Agendapunt_Id` |
| `datum` | `GewijzigdOp` of first vote row (ISO date) |
| `onderwerp` | see resolution above |
| `dossier_nummers` | via expand chain |
| `voor` / `tegen` / `onthouding` | aggregated from fractie rows |
| `aangenomen` | see outcome logic above |

---

#### Toezeggingen

**Source:** `raw_sources` where `source="tk"` and `kind="tk-toezegging"`

**Key derivation:** `make_node_key(payload["Id"])`

**Status mapping:**

| TK API value | Stored as |
|-------------|----------|
| `"Openstaand"` | `"open"` |
| `"Afgedaan"` | `"gedaan"` |
| `"Nagekomen"` | `"gedaan"` |
| `"Niet nagekomen"` | `"vervallen"` |
| (unknown) | `"open"` |

**Field extraction:**

| Prop | Source field | Fallback |
|------|-------------|---------|
| `tekst` | `TekstAlgemeen` | `TekstBrief` → `Tekst` → `""` |
| `minister_naam` | `MinisterNaam` | `NaamMinistrieAfkorting` |
| `minister_functie` | `MinisterTitel` | |
| `gedaan_op` | `DatumRegistratie` | `Datum` |
| `verwachte_afhandeling` | `VerwachteAfhandeling` | |
| `status` | mapped from `Status` | |
| `activiteit_id` | `ActiviteitId` | |
| `dossier_id` | `KamerstukdossierId` | (stored but not yet used for edges) |

---

#### TK Documents (Kamerstukken)

**Source:** `raw_sources` where `source="tk"` and `kind="tk-document"`

Documents land in the **`publications`** collection alongside TK publications from `TkNormalizePipeline`.

**Key derivation:** `make_node_key(payload["Id"])` — the TK document UUID; avoids collision with BWO publications that use different identifiers.

**Dossier link extraction:** `payload["Zaak"]` is a list (expanded during retrieve). For each Zaak in that list, `Zaak["Kamerstukdossier"]` provides the dossier nummer(s). All unique nummers are collected into `dossier_nummers`; the first becomes `dossier_nummer` (kept for backwards compatibility with `_link_publications_to_dossiers`).

| Prop | Source field | Notes |
|------|-------------|-------|
| `soort` | `Soort` | Motie, Amendement, Brief, etc. |
| `titel` | `Titel` | `Onderwerp` → `soort` |
| `volgnummer` | `Volgnummer` | Stored as `null` if ≤ 0 |
| `datum` | `Datum` | `DatumRegistratie` |
| `vergaderjaar` | `Vergaderjaar` | |
| `dossier_nummer` | first from chain | backwards-compat |
| `dossier_nummers` | all from chain | |
| `tk_url` | `https://www.tweedekamer.nl/kamerstukken/detail?id={Id}` | |
| `display_name` | `"Kamerstuk {nr}, nr. {vol} — {soort}: {titel}"` | |

Labels: `["TK", "Kamerstuk"]`

---

#### Edges — `TkDossiersNormalizePipeline`

All edges have `status="canoniek"` and `source="tk-dossiers"`.

| Relation | From | To | Resolution |
|----------|------|----|-----------|
| `DEEL_VAN_DOSSIER` | TK Document publication | Kamerstukdossier | `dossier_nummers` → `make_node_key(nummer)` → `store.get_node()` |
| `DEEL_VAN_DOSSIER` | existing publications (all) | Kamerstukdossier | AQL scan on `publications` where `props.dossier_nummer != null`; resolves dossier by `make_node_key(nummer)` |
| `DEEL_VAN_DOSSIER` | Zaak (procedure) | Kamerstukdossier | AQL scan on `procedures` where `props.kamerstuknummer != null`; resolves dossier from raw payload |
| `DEEL_VAN_DOSSIER` | Activiteit | Kamerstukdossier | `activiteit.props.dossier_nummers` → `make_node_key(nummer)` → `store.get_node()` |
| `DEEL_VAN_DOSSIER` | Stemming | Kamerstukdossier | `stemming.props.dossier_nummers` → `make_node_key(nummer)` → `store.get_node()` |
| `BEHANDELD_DOOR` | Activiteit | Commissie | `activiteit.props.commissie_id` → `make_node_key(commissie_id)` → `store.get_node()` |
| `GEDAAN_IN` | Toezegging | Activiteit | `toezegging.props.activiteit_id` → `make_node_key(activiteit_id)` → `store.get_node()` |
| `LID_VAN` | Lid | Commissie | `commissie.CommissieZetel[].CommissieZetelVastPersoon[].Persoon_Id` → `make_node_key(persoon_id)` → `store.get_node()` |

All edges use deterministic SHA-1 keys (`SHA-1(from_id:relation:to_id)`), so re-running produces no duplicates.

---

### 3.2 TK Procedures & Publications — `TkNormalizePipeline`

**File:** `pipelines/normalize/tk.py`
**Domain profile:** `strafrecht`

This pipeline processes the legacy `tk-zaak` / `tk-documentversie` kinds produced by `TKRetrievePipeline`. It is **always instantiated with `domain_profile="strafrecht"`** — records not matching strafrecht criteria are still stored but not tagged or connected to the domain topic.

#### Procedures (Zaken)

**Source:** `raw_sources` where `source="tk"` and `kind="tk-zaak"`
**Collection:** `procedures`
**Key:** `make_node_key(external_id)` where `external_id` = first non-empty of `Id`, `ZaakId`, `ZaakNummer`

**Strafrecht classification** (`_is_strafrecht_tk_payload`):

Checks the following text fields in order:
- `Titel`, `Onderwerp`, `ZaakTitel`, `Omschrijving`, `TitelMetBijlagen`

Each field is tested for case-insensitive substring match against `filters.tk.title_contains` keywords from the strafrecht domain config.

If no title-field match, the **full JSON payload** is serialized and tested against `filters.tk.dossier_keywords`.

A match on any field classifies the Zaak as strafrecht. It then gets label `"Strafrecht"`, prop `strafrecht_profile="tk"`, and a `RELATED_TOPIC` edge to the strafrecht topic node.

#### Publications (DocumentVersies)

**Source:** `raw_sources` where `source="tk"` and `kind="tk-documentversie"`
**Collection:** `publications`
**Key:** `make_node_key(external_id)` where `external_id` = first non-empty of `Id`, `DocumentVersieId`

**Procedure linking:** `payload["Zaak"]` is a list (expanded during retrieve). The procedure external_id is resolved as the first non-empty of `zaak[0]["Id"]`, `zaak[0]["Nummer"]`, `payload["ZaakId"]`, `payload["ZaakNummer"]`. This id is stored as `props.procedure_external_id` and used in `build_edges()` to look up the in-memory `procedures_by_external_id` dict.

**Edge:** `PART_OF_PROCEDURE` (publication → procedure), built in-memory from the same normalize run.

**Strafrecht classification:** same logic as Zaken — checks `Titel`, `Onderwerp`, `TitelMetBijlagen`, then full JSON against `dossier_keywords`.

---

### 3.3 BWB — `BWBNormalizePipeline`

**File:** `pipelines/normalize/bwb.py`

**Source:** `raw_sources` where `source="bwb"` and `kind` in `RAW_SOURCE_KINDS["bwb"]`

**`bwb_id` resolution:** `meta["bwb_id"]` from the raw record, falling back to `external_id`.

#### Instrument nodes

**Collection:** `instruments`
**Key:** `make_node_key(bwb_id)`

Created once per BWB ID with a stub title `"BWB-regeling {bwb_id}"`. If an instrument already exists in the store (e.g. from a prior run or manual seed), `insert_or_update` merges props rather than replacing.

Labels: `["BWB"]`

#### Article extraction from XML

The pipeline parses the `payload_text` (raw BWB XML) using `xml.etree.ElementTree`. All XML namespace prefixes are stripped (`{ns}local` → `local`) before tag comparison.

**Finding article elements** (`_find_article_elements`):

Two strategies are tried in a single `root.iter()` pass:
1. Any element whose local tag name is `"artikel"`
2. Any element with `label` attribute that starts with `"artikel"` (case-insensitive)

**Extracting article number** (`_extract_article_number`):

1. Look for a `<kop>` descendant; within it look for a `<nr>` element; return its `itertext()` content
2. Fall back to `element.attrib["label"]` — strip the leading `"artikel"` prefix and any colon/space, return the remainder

**Extracting article text** (`_extract_article_text`):

1. **Primary:** collect all `<lid>` descendants. For each `<lid>`, collect the text of all `<al>` children. Prefix with `<lidnr>` if present (e.g. `"1. tekst van het lid"`). Join with newlines.
2. **Fallback:** if no `<lid>` found, collect all `<al>` elements directly under the article and join their `itertext()` content.

Articles without a number, or whose text is empty, are skipped.

#### Article nodes

**Collection:** `instrument_articles`
**Key:** `make_node_key(bwb_id, article_number)` — e.g. `bwbr0001854_300` for artikel 300 of the Wetboek van Strafrecht

Labels: `["BWB", "Article"]`

#### Edges

`PART_OF_INSTRUMENT` from instrument → article (note: direction is instrument → article, not article → instrument).

---

### 3.4 Rechtspraak — `RechtspraakNormalizePipeline`

**File:** `pipelines/normalize/rechtspraak.py`
**Domain profile:** `strafrecht`

**Source:** `raw_sources` where `source="rechtspraak"`. Two kinds are fetched:
- `rs-index` — stored but **not consumed** during normalization (no normalize logic for index records)
- `rs-content` — one XML document per ECLI; this is what is normalized into judgment nodes

**ECLI resolution:** `meta["ecli"]` from the raw record. Records without an ECLI are skipped.

**Collection:** `judgments`
**Key:** `make_node_key(ecli)` — e.g. `ecli_nl_hr_2023_123` for `ECLI:NL:HR:2023:123`

#### XML parsing — text extraction (`_extract_judgment_text`)

Parses `payload_text` with `ET.fromstring()`. All namespace prefixes stripped.

- **`summary`:** text content of the first `<inhoudsindicatie>` element (joined with spaces via `itertext()`)
- **`text`:** text content of all `<uitspraak>` elements (one per section, joined with `"\n\n"`)

#### XML parsing — RDF metadata (`_extract_rdf_metadata`)

Iterates all elements and maps by local tag name (first occurrence wins for most fields):

| Stored prop | XML tag | Notes |
|------------|---------|-------|
| `court` | `creator` | First occurrence |
| `date` | `date` | First occurrence |
| `case_number` | `zaaknummer` | First occurrence |
| `type` | `procedure` | First occurrence |
| `subjects` | `subject` | All occurrences collected as list |

#### XML parsing — structured sections (`_extract_sections`)

Walks the `<uitspraak>` element recursively:

- `<section>` → `kind: "heading"` (depth=0) or `kind: "subheading"` (depth≥1), text from first `<title>` child
- `<uitspraak.info>` → `kind: "subheading"`
- `<para>` or `<al>` → `kind: "body"`
- `<footnote>` → skipped
- `<title>` inside a section → handled as section header, not re-emitted as body
- Nested `<section>` → recursive with `depth + 1`

Each entry: `{number: str|None, kind: "heading"|"subheading"|"body", text: str}`

#### Strafrecht classification (`_is_strafrecht_judgment`)

Loads strafrecht domain config. A judgment is classified as strafrecht if **any** of:

1. **Seed or prefix match:** ECLI is in `config.seed_examples.rechtspraak_eclis` (exact match), OR starts with any prefix in `config.filters.rechtspraak.ecli_prefixes`
2. **Full-text keyword match:** `payload_text` contains any keyword from `config.filters.rechtspraak.search_terms` (case-insensitive substring)
3. **Rechtsgebied match:** `meta["rechtsgebied"]` (comma-separated string or list) contains any value from `config.filters.rechtspraak.rechtsgebieden` (case-insensitive)

Strafrecht judgments get label `"Strafrecht"`, prop `strafrecht_profile="rechtspraak"`, and a `RELATED_TOPIC` edge to the strafrecht topic node.

---

### 3.5 EUR-Lex — `EUNormalizePipeline`

**File:** `pipelines/normalize/eurlex.py`
**Domain profile:** `strafrecht`

**Source:** `raw_sources` where `source="eurlex"` and `kind` in `RAW_SOURCE_KINDS["eurlex"]`

**CELEX resolution:** `meta["celex"]` from the raw record. Records without CELEX are skipped.

#### HTML → plaintext conversion (`_html_to_text`)

Uses a custom `HTMLParser` subclass (`_TextExtractor`):
- Block-level tags (`p`, `div`, `article`, `section`, `h1–h4`, `li`, `tr`, `td`, `th`, `br`, `hr`) insert `"\n"` before and after their content
- Skipped entirely: `<script>`, `<style>`, `<head>` and their content
- `\xa0` (non-breaking space) → regular space
- Runs of 3+ newlines → `"\n\n"`
- Runs of spaces/tabs within a line → single space

#### Article extraction (`_extract_eu_articles`)

After converting HTML to plaintext, the regex

```
(?:^|\n)\s*(?:Artikel|Article)\s+(\d+[a-z]*)\b
```
(case-insensitive) is applied to find all article headers. Capture group 1 is the article number (e.g. `"1"`, `"12a"`).

For each match, the article body runs from the end of the match to the start of the next match (or end of text).

**Filtering — two skip conditions:**
1. Article number (numeric part) > 200 — discards treaty cross-references in preamble sections
2. Body is empty, shorter than 10 characters, or starts with `","` — discards preamble fragments like `", lid 2"` that follow inline article references

#### Instrument nodes

**Collection:** `instruments`
**Key:** `make_node_key(celex)` — e.g. `31997f0266`

Labels: `["EU"]`; `["EU", "Strafrecht"]` if strafrecht.

#### Article nodes

**Collection:** `instrument_articles`
**Key:** `make_node_key(celex, article_number)` — e.g. `31997f0266_3`

Labels: `["EU", "Article"]`

Each article node stores `instrument_citation_title` (the instrument's human-readable short title, e.g. from `CELEX_SHORTHANDS`) to support display in citation edges.

#### Strafrecht classification (`_is_strafrecht_eu_instrument`)

A CELEX is classified as strafrecht if:
1. `celex` is in `config.eu_instruments[].celex` (explicit instrument list), OR
2. `celex` is in `config.filters.eurlex.celex_ids`, OR
3. `payload_text` contains any keyword from `config.filters.eurlex.subject_keywords` (case-insensitive substring)

#### Edges

- `PART_OF_INSTRUMENT` from article → instrument (note: direction is article → instrument, opposite of BWB)
- `RELATED_TOPIC` from instrument → strafrecht topic node (if classified)

---

## 4. Data Flow

```
External APIs (TK OData v4, BWB SRU/XML, Rechtspraak XML, EUR-Lex HTML)
        │
        │  Retrieve pipelines — incremental where supported
        │  Raw keyed: SHA-1(source:kind:external_id)
        ▼
  raw_sources (ArangoDB)
  ─ source, kind, external_id, fetched_at, payload_json, payload_text, meta
        │
        │  Normalize pipelines — query by source+kind+fetched_at≥since
        ▼
  Node collections                         edges collection (unified)
  ─────────────────                        ─────────────────────────
  instruments          kamerstukdossiers   PART_OF_INSTRUMENT
  instrument_articles  activiteiten        DEEL_VAN_DOSSIER
  procedures           stemmingen          BEHANDELD_DOOR
  publications         toezeggingen        PART_OF_PROCEDURE
  judgments            commissies          GEDAAN_IN
  topics               leden               LID_VAN
                                           RELATED_TOPIC
        │
        │  Semantic pipelines — scan normalized text, produce citation edges
        ▼
  Additional edges:
    REFERS_TO_ARTICLE / CITES_ARTICLE / MENTIONS_ARTICLE
    AMENDS_INSTRUMENT / IMPLEMENTS_DIRECTIVE / DISCUSSES_INSTRUMENT
    CITES_JUDGMENT
```

---

## 5. Incremental Update Strategy

| Source | Incremental support | Mechanism |
|--------|--------------------|-----------|
| TK Zaak / DocumentVersie | ✅ | OData `ApiGewijzigdOp ge <datetime>` filter |
| TK Dossier / Activiteit / Stemming / Toezegging / Document | ✅ | Same |
| TK Commissie | ❌ | TK API has no `ApiGewijzigdOp` for Commissie — always full-refresh |
| TK Persoon | ❌ | Same |
| Rechtspraak index | ✅ | `modifiedsince` query param |
| Rechtspraak content | ❌ | Explicit ECLI list required |
| BWB | ❌ | Explicit BWB ID list required |
| EUR-Lex | ❌ | Explicit CELEX list required |

**Normalize incremental:** `_query_raw_sources()` filters by `r.fetched_at >= @since` (ISO string). Only raw records from the current run window are re-normalized. The `(source, kind)` compound index on `raw_sources` makes this filter fast even on 200K+ records.

**Limitations:**
- No delete tracking — removed external records persist as stale nodes indefinitely
- No cascade invalidation — if a Zaak changes its dossier link, both runs must normalize to fix it
- Commissie/Persoon always full-refresh (~100 commissies, ~500 leden per run), so their nodes reflect the current API snapshot, not history

---

## 6. Gaps & Missing Features

| Gap | Impact |
|-----|--------|
| ~~`rs-index` records fetched but never normalized~~ | ✅ Fixed — index records now produce ECLI stub nodes, enabling discovery |
| ~~No `Fractie` (party) nodes~~ | ✅ Fixed — `fracties` collection, `_normalize_fracties()`, and `LID_VAN_FRACTIE` edges added |
| Parliamentary debate transcripts not fetched | No full text for plenaire vergaderingen |
| Parliamentary amendments (Amendementen) not tracked separately | No granular change tracking per article |
| ~~CommissieZetel date ranges ignored — snapshot only~~ | ✅ Fixed — `geldig_van`/`geldig_tot` now stored as edge metadata on `LID_VAN` edges |
| ~~Toezegging `KamerstukdossierId` stored but not linked via edge~~ | ✅ Fixed — `DEEL_VAN_DOSSIER` toezegging→dossier edge now built in `_link_toezeggingen` |
| EUR-Lex: no SPARQL/structured search | Requires explicit CELEX list; no discovery |
| BWB: no incremental update | Must re-fetch all explicitly provided IDs each time |
| ~~`TkNormalizePipeline.domain_profile` hardcoded to `"strafrecht"`~~ | ✅ Fixed — accepts `domain_profile` parameter |
| ~~No cross-link between `procedures` (tk-zaak) and `kamerstukdossiers`~~ | ✅ Fixed — `TkNormalizePipeline` now writes `kamerstuknummer` to procedure nodes; `TkDossiersNormalizePipeline._link_zaken_to_dossiers` uses it to build `DEEL_VAN_DOSSIER` edges |

---

## 7. Bugs & Issues

| # | Severity | File | Status | Description |
|---|----------|------|--------|-------------|
| 1 | P1 | `normalize/tk_dossiers.py` | ✅ Fixed | OData expand chain assumed to always be a list — `isinstance` guards added to `_normalize_activiteiten`, `_enrich_dossier_fasen`, and `_normalize_stemmingen` for Agendapunt, Zaak, and Kamerstukdossier expand fields |
| 2 | P1 | `normalize/tk.py` | ✅ Fixed | `domain_profile="strafrecht"` hardcoded — `TkNormalizePipeline.__init__` now accepts `domain_profile: str = "strafrecht"` parameter; CLI passes `--profile` |
| 3 | P2 | `normalize/tk_dossiers.py` | ✅ Fixed | Mixed-type dossiers discarded non-primary Zaak type info — `_enrich_dossier_fasen` now stores `zaak_soorten` (deduplicated list of all `Zaak.Soort` values) on dossier props alongside `huidige_fase` |
| 4 | P2 | `normalize/tk_dossiers.py` | ✅ Fixed | `Lid.partij` is an empty string for independents — now defaults to `"onafhankelijk"` when `Fractielabel` is absent/empty |
| 5 | P2 | `normalize/rechtspraak.py` | ✅ Fixed | `rs-index` kind is fetched but produced no nodes — now creates lightweight ECLI stub nodes (`labels: ["Rechtspraak", "Stub"]`) from index records, enabling automatic discovery |
| 6 | P3 | `normalize/bwb.py` | ✅ Fixed | Instrument title was always the stub `"BWB-regeling {bwb_id}"` — `_extract_instrument_title()` now parses `citeertitel`/`officiele-titel`/`intitule` from toestand XML; falls back to stub only if no element found |
| 7 | P3 | `normalize/eurlex.py` | ✅ Fixed | Article number cap was inline literal 200 — `_EU_MAX_ARTICLE_NUMBER` now reads `EURLEX_MAX_ARTICLE_NUMBER` env var (default 200); configurable without code change |

---

## 8. Improvement Recommendations

### P1 (Correctness)
1. ✅ Fixed — `isinstance` guards added to `_normalize_activiteiten`, `_normalize_stemmingen`, and `_enrich_dossier_fasen` for all OData expand fields
2. ✅ Fixed — Rechtspraak index records now produce ECLI stub nodes in `judgments`

### P2 (Feature gaps)
3. ✅ Fixed — `Fractie` nodes in `fracties` collection; `LID_VAN_FRACTIE` edges from Lid → Fractie; `_normalize_fracties()` extracts unique `ActorFractie` names from stemmingen
4. ✅ Fixed — CommissieZetel `Van`/`TotEnMet` dates now stored as `meta.geldig_van`/`meta.geldig_tot` on `LID_VAN` edges
5. ✅ Fixed — `DEEL_VAN_DOSSIER` edge from Toezegging → Kamerstukdossier built using `KamerstukdossierId` via `_find_dossier_by_external_id`
6. ✅ Fixed — `TkNormalizePipeline` accepts `domain_profile` parameter (default: `"strafrecht"`)

### P3 (Quality)
7. ✅ Fixed — `_extract_instrument_title()` extracts `citeertitel`/`officiele-titel`/`intitule` from toestand XML; falls back to stub only if no title element found
8. ✅ Fixed — `_EU_MAX_ARTICLE_NUMBER` now reads `EURLEX_MAX_ARTICLE_NUMBER` env var (default 200); per-CELEX cap remains open as a nice-to-have
9. ✅ Fixed — Incremental mode added to TK, EU, and BWB semantic detectors; all now filter by `raw_sources.fetched_at >= since`
