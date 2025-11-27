# Commandoregelinterface (CLI)

## Inleiding
Lawgraph biedt een set CLI-entrypoints onder `lawgraph.cli.*` die retrieve-, normalize-, semantic- en seed-pijplijnen draaien. Ze zijn bedoeld voor data-engineers en operators die ArangoDB willen vullen en onderhouden via repeatable commando’s (`lawgraph-retrieve-*`, `lawgraph-normalize-*`, `lawgraph-semantic-*`, `lawgraph-strafrecht-seed`). De CLI’s schakelen het juiste profiel (`LAWGRAPH_PROFILE` of `--profile`) in en loggen via `lawgraph.logging.get_logger(__name__)`.

## Installatie en vereisten
1. Zorg dat Python ≥3.11 geïnstalleerd is.
2. Clone de repository en installeer dependencies:
   ```bash
   git clone https://example.com/lawgraph.git
   cd lawgraph
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Zet een `.env` met Arango-gegevens, API-bases en (optioneel) `LAWGRAPH_PROFILE`. De CLI’s gebruiken `dotenv` om deze waarden te laden.
4. Voor versiebeheer worden CLI-scripts gekoppeld aan `pyproject.toml` entrypoints (`lawgraph-retrieve-tk`, etc.). Je draait ze direct via `pip install -e .` of via `poetry run`/`python -m`.

## Basiscommando's
1. **Retrieve pipelines**:
   - `lawgraph-retrieve-tk`, `lawgraph-retrieve-rechtspraak`, `lawgraph-retrieve-eurlex`, `lawgraph-retrieve-bwb`, `lawgraph-retrieve-all`.
   - Voert HTTP-calls uit, zet `RetrieveRecord`s in `raw_sources`.
   - Verplicht: `.env` met Arango-config (`ARANGO_URL`, etc.) en eventueel `LAWGRAPH_PROFILE`.
   - Output: INFO-logs met aantal records, warnings bij ontbrekende filters.

2. **Normalize pipelines**:
   - `lawgraph-normalize-tk`, `lawgraph-normalize-rechtspraak`, `lawgraph-normalize-eurlex`, `lawgraph-normalize-bwb`, `lawgraph-normalize-all`.
   - Leest `raw_sources`, maakt nodes/edges (`part_of_*`, `related_topic`).
   - Verplicht: toegang tot `raw_sources` collectie en `LAWGRAPH_PROFILE` of `--profile`.
   - Test: run `lawgraph-normalize-tk --profile strafrecht` zonder volgorde; log toont `insert_or_update` counts.

3. **Semantic pipelines**:
   - `lawgraph-semantic-tk-articles`, `lawgraph-semantic-eu-articles`, `lawgraph-semantic-rechtspraak-articles`.
   - Detecteert article hits en schrijft `edges_semantic`.
   - Vereist: aanwezige nodes (publications, instruments, judgments).
   - Output: INFO met `describe_since` en `edges created`.

4. **Seed**: `lawgraph-strafrecht-seed` – injecteert topics/instrumenten gebaseerd op een profiel. Gebruikt `lawgraph.pipelines.strafrecht_seed`.

## Geavanceerde opties
- Flags: `--profile <naam>` om een specifiek profiel te forceren zelfs als `LAWGRAPH_PROFILE` ontbreekt.
- Configuratie: `.env` variabelen zoals `ARANGO_URL`, `LAWGRAPH_SEMANTIC_EDGE_COLLECTION`, `LAWGRAPH_RELATION_MENTIONS_ARTICLE` en API-bases (TK/EURLEX/BWB).
- Logging: `LOG_LEVEL` (via `python -m lawgraph.cli...`) kan niveau verlagen/verhogen; ruff/lint check ruig via `ruff check src tests`.
- Override bind vars: profielen bepalen filters, maar je kunt ook custom `--since`/`--ecli` parameters op CLI-niveau toe voegen waar voorzien.

## Voorbeelden en scripts
```bash
LAWGRAPH_PROFILE=strafrecht lawgraph-retrieve-tk
LAWGRAPH_PROFILE=strafrecht lawgraph-normalize-tk
LAWGRAPH_PROFILE=strafrecht lawgraph-semantic-tk-articles
```
Gebruik `docker-compose up -d arangodb` voordat je CLI’s draait. Voor batch runs kan je een shellscript gebruiken:
```bash
#!/bin/zsh
LAWGRAPH_PROFILE=strafrecht
lawgraph-retrieve-all
lawgraph-normalize-all
lawgraph-semantic-tk-articles
lawgraph-semantic-rechtspraak-articles
```
CLI’s kunnen ook in CI worden uitgevoerd; stel `ALLOW_NETWORK_TESTS=1` in voor tests die echte API-calls nodig hebben.

## Foutopsporing
- Logs worden naar stdout geschreven; verhoog logniveau om DEBUG queries/edges te zien.
- Inspecteer `raw_sources` (AQL query) om te zien of retrieve records correct zijn. `ArangoStore` logt `insert_or_update` resultaten.
- Mislukte semantic runs? Controleer aliasen in het profiel (`code_aliases`, `instrument_aliases`).
- Voor connection errors check `.env` credentials. Bij `ruff check` of `pytest` fouten: draai `pytest tests/test_<module>.py` en inspecteer fixtures (bijv. dummy ArangoStore).
