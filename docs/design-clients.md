# LawGraph External API Clients — Design Document

## 1. BaseClient Architecture

**File:** `src/lawgraph/clients/base.py`

### Responsibilities
- Environment variable override per client (`env_var` param with `default_base_url` fallback)
- URL normalization via `_build_url()` — enforces trailing slash, prevents double-slash
- Shared `requests.Session` — injectable for connection pooling and testing
- 30-second default timeout on all requests, overridable per-call
- `load_dotenv()` called on every instantiation (minor redundancy; see bugs)

### Response layers

| Method | Returns | Use case |
|--------|---------|----------|
| `_get_raw(path, params, timeout)` | `requests.Response` | Binary content (PDFs) |
| `_get_json(path, params, timeout)` | `dict \| list` | JSON API responses |
| `_get_text(path, params, timeout)` | `str` | XML, HTML |

All call `raise_for_status()` on non-2xx responses.

### Pagination helpers

#### `_paged_get()` — nextLink-based (OData-compliant)

Follows `@odata.nextLink` URLs until exhausted. Used for TK legacy endpoints (`zaken_modified_since`, `documents_modified_since`). The nextLink URL is called directly (absolute, bypasses `_build_url`).

#### `_skip_paged_get()` (in `tk.py:57-79`) — skip/top-based

Used for all new TK parliamentary entity endpoints. The TK API does **not** emit `@odata.nextLink` despite the OData spec requirement.

```
$top=page_size
$skip=0, page_size, 2*page_size, ... until len(page) < page_size
```

**Limitation:** End-of-data detection is fragile — assumes fewer records = last page. No explicit total count available.

---

## 2. TK Client (Tweede Kamer OData API)

**File:** `src/lawgraph/clients/tk.py`

**Base URL:** `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/`

**Documentation:** https://opendata.tweedekamer.nl/documentatie/odata-api

### Methods

| Method | Entity | Pagination | Since support | Notes |
|--------|--------|-----------|---------------|-------|
| `zaken_modified_since(since, top, keyword_fields, keywords)` | Zaak | nextLink | yes | Legacy; supports keyword filtering |
| `documents_modified_since(since, top, ...)` | Document | nextLink | yes | Legacy; `$expand=Zaak` |
| `raw_entity(entity, params)` | Any | nextLink | via params | Generic passthrough |
| `fetch_document_bytes(document_id, timeout=60)` | Binary | N/A | N/A | PDF/document content |
| `fetch_dossiers(since, top=250)` | Kamerstukdossier | skip-based | yes | |
| `fetch_activiteiten(since, top=250)` | Activiteit | skip-based | yes | 3-level expand |
| `fetch_stemmingen(since, top=250)` | Stemming | skip-based | yes | One record per fractie per Besluit |
| `fetch_toezeggingen(since, top=250)` | Toezegging | skip-based | yes | |
| `fetch_commissies(top=250)` | Commissie | skip-based | **no** | CommissieZetel members expanded |
| `fetch_documents(since, top=250)` | Document | skip-based | yes | ~400K+ full; always use `since` |
| `fetch_personen(top=250)` | Persoon | skip-based | **no** | Fractielabel included directly |

### Datetime formatting

`_format_odata_datetime(value)` → `YYYY-MM-DDTHH:MM:SSZ` (UTC, no microseconds).

### OData nested expand syntax — critical quirk

The TK API uses **semicolons `;`** as parameter separators inside nested `$expand()` clauses — **not the standard ampersand `&`**. The API returns HTTP 400 for standard syntax.

```
# CORRECT (TK-specific):
$expand=Agendapunt($expand=Zaak($select=Id,Soort,Titel,Nummer;$expand=Kamerstukdossier($select=Id,Nummer,Toevoeging,Titel)))

# WRONG (standard OData — rejected by TK API):
$expand=Agendapunt&$expand=Zaak&$select=...
```

This affects `fetch_activiteiten()`, `fetch_stemmingen()`, `fetch_documents()`.

### Other known API quirks

| Quirk | Detail |
|-------|--------|
| No `@odata.nextLink` | Forces skip-based pagination for all new endpoints |
| `Nummer` often null | Dossier linking must traverse Zaak→Kamerstukdossier chain |
| `Vergadering_Soort` missing | Field not returned by Agendapunt even if requested |
| Document scale | ~400K+ records for a full unbounded fetch — always use date filter |
| Stemmingen structure | One record per fractie per Besluit — must group by `Besluit_Id` to reconstruct full vote |

---

## 3. BWB Client (Basis Wetten Bestand)

**File:** `src/lawgraph/clients/bwb.py`

**Base URL:** `https://wetten.overheid.nl/`

**SRU endpoint:** `https://zoekservice.overheid.nl/sru/Search`

### Methods

| Method | Description |
|--------|-------------|
| `search_toestanden(bwb_id)` | SRU query; returns all versions (ToestandMeta list) |
| `latest_toestand(bwb_id)` | Filters for currently-valid version (einddatum = 9999-12-31), then most recent |
| `fetch_toestand_xml(meta, timeout)` | Downloads actual XML law text from `locatie_toestand` URL |

### ToestandMeta fields

```python
{
    "bwb_id": "BWBR0001854",
    "locatie_toestand": "https://...",      # XML download URL
    "locatie_wti": "...",                   # Regulatory tracing info (optional)
    "locatie_manifest": "...",              # Manifest URL (optional)
    "geldigheidsperiode_startdatum": "2020-01-01",
    "geldigheidsperiode_einddatum": "9999-12-31"  # "still valid"
}
```

### Version selection logic

1. Filter for versions with `einddatum == "9999-12-31"` (currently in force)
2. If none found, fall back to all versions
3. Sort by `(einddatum DESC, startdatum DESC)` → take first

---

## 4. Rechtspraak Client

**File:** `src/lawgraph/clients/rechtspraak.py`

**Base URL:** `https://data.rechtspraak.nl/`

### Methods

| Method | Description |
|--------|-------------|
| `search_ecli_index(modified_since, extra_params)` | Fetch index XML/Atom feed of available judgments |
| `fetch_ecli_content(ecli)` | Fetch full XML for a single ECLI |

**Important:** The query parameter is `modifiedsince` (all lowercase, no underscores).

**No structured search** — relies on ECLI identifiers extracted from the index feed or provided explicitly.

---

## 5. EU Client (EUR-Lex / CELLAR)

**File:** `src/lawgraph/clients/eu.py`

**Base URL:** `https://eur-lex.europa.eu/`

### Methods

| Method | Description |
|--------|-------------|
| `fetch_celex_html(celex, lang="NL")` | Fetch HTML for an EU legislative act |

### CELLAR proxy routing

The main `eur-lex.europa.eu` domain is behind AWS WAF bot-protection and returns HTTP 202 challenges for automated clients. Instead, the client uses the CELLAR publications server:

```
https://publications.europa.eu/resource/celex/<CELEX>
```

With headers:
```
Accept: text/html, application/xhtml+xml
Accept-Language: nl, nl-NL;q=0.9
```

Redirects are followed (`allow_redirects=True`). Timeout: 60 seconds.

---

## 6. Configuration & Authentication

All base URLs configurable via environment variables:

| Client | Env var | Default |
|--------|---------|---------|
| TK | `TK_API_BASE` | `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/` |
| BWB | `BWB_BASE` | `https://wetten.overheid.nl/` |
| Rechtspraak | `RECHTSPRAAK_BASE` | `https://data.rechtspraak.nl/` |
| EUR-Lex | `EURLEX_BASE` | `https://eur-lex.europa.eu/` |
| BWB SRU | `BWB_SRU_ENDPOINT` | `https://zoekservice.overheid.nl/sru/Search` |

**No API keys required.** All sources are publicly accessible without credentials.

**No rate limiting implemented.** Aggressive fetches may trigger 429 responses which currently crash the pipeline.

---

## 7. Gaps & Missing Features

| Gap | Impact |
|-----|--------|
| No HTTP retry logic (429, 503, timeout) | Single failure crashes entire batch |
| No rate limiting | Risk of being throttled by external APIs |
| `fetch_commissies()` / `fetch_personen()` have no `since` parameter | Always full-refresh (~100 commissies, ~500 personen) |
| `TKRetrievePipeline` has no pagination loop | Silently drops records beyond `limit=100` |
| No ECLI/CELEX search endpoints | Requires pre-known identifiers |
| All methods return `list` (materializes in memory) | Memory pressure for 400K+ document fetches |
| No `Fractie`, `Agendapunt`, or `Besluit` dedicated fetchers | Must use `raw_entity()` workaround |

---

## 8. Bugs & Issues

| # | Severity | File | Line | Description |
|---|----------|------|------|-------------|
| 1 | **HIGH** | `retrieve/tk.py` | 54 | `limit` caps result set with no pagination — silently drops excess records |
| 2 | MEDIUM | `clients/tk.py` | 57–79 | `_skip_paged_get()` end-of-data detection fragile — assumes `len(page) < page_size` = last page |
| 3 | LOW | `clients/base.py` | 38 | `load_dotenv()` called on every `BaseClient()` instantiation — minor redundant I/O |
| 4 | LOW | `clients/rechtspraak.py` | 45 | `modifiedsince` param name is easy to mistype — no constant defined |
| 5 | LOW | `clients/eu.py` | 42 | Direct `self.session.get()` bypasses `_get_raw()` helper — inconsistent style |
| 6 | LOW | `clients/base.py` | 120 | Pagination next_link calls `session.get()` directly — bypasses `_build_url()` normalization (intentional but undocumented) |

---

## 9. Improvement Recommendations

### P1 — Critical
1. **Implement HTTP retry with exponential backoff** in `BaseClient._get_raw()`:
   - Retry on: 429, 503, `Timeout`, `ConnectionError`
   - Max 3 retries, backoff factor 1.0s
2. **Paginate `TKRetrievePipeline`** — implement `$skip/$top` loop; current `limit=100` silently drops data

### P2 — High
3. **Return iterators instead of lists** from TK fetch methods — reduce memory footprint for 400K+ record fetches
4. **Add rate-limit logging** — log HTTP 429/503 responses with structured metadata before retrying
5. **Document TK API quirks** in `docs/external-apis.md` (semicolon syntax, no nextLink, Nummer null, Vergadering_Soort missing)

### P3 — Medium
6. **Add `since` support** to `fetch_commissies()` and `fetch_personen()` — check if TK API supports `ApiGewijzigdOp` for these entities
7. **Move `load_dotenv()` to application startup** — remove from `BaseClient.__init__()`
8. **Optimize connection pooling** via `HTTPAdapter(pool_connections=10, pool_maxsize=10)`
9. **Define `MODIFIEDSINCE_PARAM` constant** in rechtspraak.py to prevent typos

### P4 — Nice-to-have
10. **Add `search_ecli()` to RechtspraakClient** — parse index feed to return matching ECLIs by keyword
11. **Async support** via `httpx` — for I/O-bound parallel fetches
