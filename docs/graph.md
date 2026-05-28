# Graph model

## Document collections

| Collection | Node type | Contents |
|-----------|-----------|----------|
| `instruments` | INSTRUMENT | Dutch statutes (BWB), EU directives/regulations (CELEX) |
| `instrument_articles` | ARTICLE | Individual articles within a statute |
| `instrument_versions` | INSTRUMENT_VERSION | Historical versions of instruments |
| `instrument_article_versions` | ARTICLE_VERSION | Historical versions of articles |
| `judgments` | JUDGMENT | Court judgments (Rechtspraak.nl, ECHR) |
| `procedures` | PROCEDURE | TK Zaak — one legislative track |
| `publications` | PUBLICATION | TK Kamerstukken, Staatsblad, Staatscourant publications |
| `kamerstukdossiers` | DOSSIER | Parliamentary dossiers |
| `activiteiten` | ACTIVITEIT | Debates and hearings |
| `stemmingen` | STEMMING | Votes on motions, grouped by Besluit |
| `toezeggingen` | TOEZEGGING | Ministerial commitments |
| `commissies` | COMMISSIE | Parliamentary committees |
| `leden` | LID | Members of parliament |
| `fracties` | FRACTIE | Parliamentary parties / political groups |
| `topics` | TOPIC | Domain topic nodes |
| `raw_sources` | — | Verbatim API responses (staging area) |
| `watches` | — | User-defined node watches |
| `edge_status_log` | — | Audit log for edge status transitions |

## Edge collection

All edges live in the single `edges` collection. The collection name is configurable via `LAWGRAPH_EDGE_COLLECTION` (default: `edges`).

## Edge types

### Structural (written by normalize pipelines)

| Relation | From | To |
|----------|------|----|
| `PART_OF_INSTRUMENT` | instrument_articles | instruments |
| `PART_OF_PROCEDURE` | publications | procedures |
| `DEEL_VAN_DOSSIER` | publications / activiteiten / stemmingen / toezeggingen / procedures | kamerstukdossiers |
| `BEHANDELD_DOOR` | activiteiten | commissies |
| `GEDAAN_IN` | toezeggingen | activiteiten |
| `LID_VAN` | leden | commissies |
| `LID_VAN_FRACTIE` | leden | fracties |
| `STEMT` | fracties | stemmingen |
| `DISCUSSES` | procedures | instruments |
| `RAAKT` | kamerstukdossiers | instruments |

### Parliamentary (written by normalize and semantic pipelines)

| Relation | From | To |
|----------|------|----|
| `WIJZIGT` | publications | instrument_articles (proposes change; status=voorgesteld) |
| `INTRODUCEERT` | publications | instrument_articles (proposes new article) |
| `TREKT_IN` | publications | instrument_articles (proposes repeal) |
| `LICHT_TOE` | publications (MvT/NvT) | instrument_articles |
| `BESLUIT` | stemmingen | publications |
| `AUTEUR_VAN` | leden | publications |
| `RESULTED_IN` | kamerstukdossiers | instruments |

### Semantic (written by semantic pipelines, confidence-weighted)

| Relation | From | To | Confidence |
|----------|------|----|-----------|
| `REFERS_TO_ARTICLE` | instrument_articles | instrument_articles | 0.80–0.95 |
| `CITES_ARTICLE` | judgments | instrument_articles | 0.35–0.95 |
| `MENTIONS_ARTICLE` | publications / procedures | instrument_articles | 0.60–0.95 |
| `EXPLAINS_ARTICLE` | publications (MvT) | instrument_articles | 0.60–0.95 |
| `MENTIONS_INSTRUMENT` | publications / procedures / instrument_articles | instruments | 0.60–0.95 |
| `AMENDS_INSTRUMENT` | publications | instruments | 0.85 |
| `IMPLEMENTS_DIRECTIVE` | instruments | instruments | 0.75–1.0 |
| `EXPLAINS_INSTRUMENT` | publications | instruments | — |
| `DELEGATED_BY` | instruments (AMvB) | instrument_articles | — |
| `CITES_JUDGMENT` | judgments | judgments | 0.95 |
| `APPEAL_OF` | judgments | judgments | — |
| `CAUSED_VERSION` | publications | instrument_article_versions | — |
| `SUPERSEDES` | instrument_versions | instrument_versions | — |
| `VERSION_OF` | instrument_versions | instruments | — |
| `PART_OF_VERSION` | instrument_article_versions | instrument_versions | — |

Semantic edges carry:
- `confidence` (0–1): detection reliability
- `source`: which pipeline wrote the edge
- `status`: `canoniek` (confirmed) or `voorgesteld` (pending)
- `meta`: raw match text, snippet, span offsets, reason label

## Edge status values

| Value | Meaning |
|-------|---------|
| `canoniek` | Current law / confirmed relation |
| `voorgesteld` | Proposed (in legislative procedure) |

## Key generation

All `_key` values are computed deterministically by `make_node_key()` from `lawgraph.core.models`:

```
instruments (BWB)          →  make_node_key(bwb_id)           e.g. bwbr0001854
instruments (EU)           →  make_node_key(celex)            e.g. 32016l0680
instrument_articles (BWB)  →  make_node_key(bwb_id, art_nr)   e.g. bwbr0001854_47
instrument_articles (EU)   →  make_node_key(celex, art_nr)    e.g. 32016l0680_3
judgments                  →  make_node_key(ecli)             e.g. ecli_nl_hr_2023_1234
stemmingen                 →  make_node_key("stemming", besluit_id)
raw_sources                →  SHA-1(source:kind:external_id)
edges                      →  SHA-1(from_id:relation:to_id)
```

`make_node_key` lowercases, replaces non-alphanumeric characters with `_`, and collapses consecutive underscores.
