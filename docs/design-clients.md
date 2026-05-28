# External API Clients

## 1. BaseClient

**File:** `src/lawgraph/clients/base.py`

### Responsibilities

- Base URL configured via env var with fallback default
- URL building via `_build_url()` — enforces trailing slash, prevents double-slash
- Shared `requests.Session` for connection pooling (injectable for testing)
- 30 s default timeout on all requests, overridable per call
- Retry on HTTP 429, 503, and connection/timeout errors: 3 retries with exponential backoff (factor 2)

### Response methods

| Method | Returns | Use case |
|--------|---------|----------|
| `_get_raw(path, params, timeout)` | `requests.Response` | Binary content (PDFs) |
| `_get_json(path, params, timeout)` | `dict \| list` | JSON API responses |
| `_get_text(path, params, timeout)` | `str` | XML, HTML |

All call `raise_for_status()` on non-2xx responses.

### Pagination helpers

`_paged_get()` — follows `@odata.nextLink` URLs until exhausted. Used for TK legacy endpoints.

`_skip_paged_get()` — skip/top-based pagination for TK endpoints that do not emit `@odata.nextLink`. End-of-data detected when `len(page) < page_size`.

---

## 2. TK Client (Tweede Kamer OData API)

**File:** `src/lawgraph/clients/tk.py`

**Base URL:** `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/`

**Documentation:** https://opendata.tweedekamer.nl/documentatie/odata-api

### Methods

| Method | Entity | Pagination | Incremental |
|--------|--------|-----------|-------------|
| `zaken_modified_since(since, ...)` | Zaak | nextLink | yes |
| `documents_modified_since(since, ...)` | Document | nextLink | yes |
| `raw_entity(entity, params)` | Any | nextLink | via params |
| `fetch_document_bytes(document_id)` | Binary | — | — |
| `fetch_dossiers(since, top=250)` | Kamerstukdossier | skip-based | yes |
| `fetch_activiteiten(since, top=250)` | Activiteit | skip-based | yes |
| `fetch_stemmingen(since, top=250)` | Stemming | skip-based | yes |
| `fetch_toezeggingen(since, top=250)` | Toezegging | skip-based | yes |
| `fetch_commissies(top=250)` | Commissie | skip-based | no (full-refresh) |
| `fetch_documents(since, top=250)` | Document | skip-based | yes |
| `fetch_personen(top=250)` | Persoon | skip-based | no (full-refresh) |

### Critical quirk: OData nested expand syntax

The TK API uses **semicolons `;`** as parameter separators inside nested `$expand()` clauses, not the standard ampersand `&`. The API returns HTTP 400 for standard OData syntax.

```
# Correct (TK-specific):
$expand=Agendapunt($expand=Zaak($select=Id,Soort;$expand=Kamerstukdossier($select=Id,Nummer)))

# Wrong (standard OData — rejected):
$expand=Agendapunt&$expand=Zaak&$select=Id
```

### Other known quirks

- No `@odata.nextLink` on new endpoints — requires skip-based pagination
- `Nummer` often null — dossier linking must traverse Zaak→Kamerstukdossier chain
- Stemmingen: one raw record per fractie per Besluit — must group by `Besluit_Id`
- Documents: ~400K+ full; always use a date filter

---

## 3. BWB Client

**File:** `src/lawgraph/clients/bwb.py`

**Base URL:** `https://wetten.overheid.nl/`

**SRU endpoint:** `https://zoekservice.overheid.nl/sru/Search`

### Methods

| Method | Description |
|--------|-------------|
| `search_toestanden(bwb_id)` | SRU query; returns all versions (ToestandMeta list) |
| `latest_toestand(bwb_id)` | Filters for currently-valid version, then most recent |
| `fetch_toestand_xml(meta, timeout)` | Downloads XML law text from `locatie_toestand` URL |

### Version selection

1. Filter for `einddatum == "9999-12-31"` (currently in force)
2. If none found, fall back to all versions
3. Sort by `(einddatum DESC, startdatum DESC)` — take first

---

## 4. Rechtspraak Client

**File:** `src/lawgraph/clients/rechtspraak.py`

**Base URL:** `https://data.rechtspraak.nl/`

### Methods

| Method | Description |
|--------|-------------|
| `search_ecli_index(modified_since, extra_params)` | Atom/XML feed of available judgments |
| `fetch_ecli_content(ecli)` | Full XML for a single ECLI |

Query parameter is `modifiedsince` (all lowercase, no underscores).

---

## 5. EU Client (EUR-Lex / CELLAR)

**File:** `src/lawgraph/clients/eu.py`

**Base URL:** `https://eur-lex.europa.eu/`

### Methods

| Method | Description |
|--------|-------------|
| `fetch_celex_html(celex, lang="NL")` | Fetch HTML for an EU legislative act |

The main `eur-lex.europa.eu` domain returns HTTP 202 challenges for automated clients. The client routes via the CELLAR publications server instead:

```
https://publications.europa.eu/resource/celex/<CELEX>
```

Redirects are followed. Timeout: 60 s.

---

## 6. Other clients

| Client file | Source | Base URL env var |
|------------|--------|-----------------|
| `staatsblad.py` | Staatsblad AMvBs | `STAATSBLAD_SRU_ENDPOINT` |
| `staatscourant.py` | Staatscourant regelingen | `STAATSCOURANT_SRU_ENDPOINT` |
| `eerstekamer.py` | Eerste Kamer OData | `EERSTEKAMER_BASE` |
| `verdragenbank.py` | Verdragenbank SPARQL | `VERDRAGENBANK_SPARQL` |
| `echr.py` | ECHR HUDOC | `ECHR_HUDOC_BASE` |

---

## 7. Configuration

All base URLs are configurable via env vars. **No API keys required** — all sources are publicly accessible.

| Client | Env var | Default |
|--------|---------|---------|
| TK | `TK_API_BASE` | `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/` |
| BWB | `BWB_BASE` | `https://wetten.overheid.nl/` |
| BWB SRU | `BWB_SRU_ENDPOINT` | `https://zoekservice.overheid.nl/sru/Search` |
| Rechtspraak | `RECHTSPRAAK_BASE` | `https://data.rechtspraak.nl/` |
| EUR-Lex | `EURLEX_BASE` | `https://eur-lex.europa.eu/` |
| Staatsblad | `STAATSBLAD_SRU_ENDPOINT` | `https://sru.officielebekendmakingen.nl/sru/Search` |
| Eerste Kamer | `EERSTEKAMER_BASE` | `https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/` |
| ECHR | `ECHR_HUDOC_BASE` | `https://hudoc.echr.coe.int` |
| Verdragenbank | `VERDRAGENBANK_SPARQL` | `https://linkeddata.overheid.nl/front/portal/sparql` |
