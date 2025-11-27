# Configuratie

## Algemene richtlijnen
Configuratie bestaat uit een `.env` voor secrets/connection strings en domeinprofielen (`src/config/*.yml`) voor domain-specific settings. `.env` bevat API-bases, ArangoDB credentials, collection- en edge-overrides, en is verantwoordelijk voor elke omgeving (dev/stage/prod). Profielen worden gepusht via git (met reviews) en alle wijzigingsverzoeken doorstaan lint/tests voordat ze deployed worden. Operators mogen `.env` updaten via configuratiebeheer (bijv. Kubernetes secrets of dotenv-bestand) wanneer de Arango-host of API-eindpunten wijzigen.

## Belangrijke configuratiebestanden
- **`.env`** (project root): bevat ARANGO_URL/DB/USER/PASSWORD, API bases (TK, RECHTSPRAAK, EURLEX, BWB), en optionele overrides zoals `LAWGRAPH_PROFILE`, `LAWGRAPH_SEMANTIC_EDGE_COLLECTION`, `LAWGRAPH_RELATION_MENTIONS_ARTICLE`. Ook `LAWGRAPH_DOCUMENT_COLLECTIONS` / `LAWGRAPH_EDGE_COLLECTIONS` kan hier gedefinieerd worden. CLI’s en runtime lezen dit via `dotenv.load_dotenv()`.
- **`src/lawgraph/config/settings.py`**: definieert defaults, env-aware overrides, en helpers (`_env_list`). Pipelinecode importeert constants (`COLLECTION_INSTRUMENTS`, `RELATION_MENTIONS_ARTICLE`, etc.) zodat er geen hard-coded strings meer in modules staan.
- **`src/config/*.yml`** (profielen zoals `strafrecht.yml`): beschrijven `topic`, `code_aliases`, `filters`, seeds. Worden ingeladen door `config.config.load_domain_config()` en doorgegeven aan pipelines via `--profile`/`LAWGRAPH_PROFILE`.
- **`pyproject.toml` entrypoints**: definiëren CLI-commando’s (`lawgraph-retrieve-tk`, ...). Wanneer je een nieuwe pipeline toevoegt, registreer je het script hier en documenteer je het ook in docs/cli.md.

## Omgevingsvariabelen
- `ARANGO_URL/DB_NAME/USER/PASSWORD`: verbinding met ArangoDB. Production wijkt af van dev en moet bijvoorbeeld in Kubernetes secrets opgeslagen zijn.
- `LAWGRAPH_PROFILE`: kiest het domeinprofiel (CSV, strafrecht, etc.). CLI’s kunnen dit overschrijven met `--profile`.
- `TK_API_BASE`, `RECHTSPRAAK_BASE`, `EURLEX_BASE`, `BWB_BASE`, `BWB_SRU_ENDPOINT`: base URLs voor respectievelijke clients. Override bij API veranderingen.
- `LAWGRAPH_SEMANTIC_EDGE_COLLECTION`, `LAWGRAPH_RELATION_MENTIONS_ARTICLE`: bepalen waar semantische edges heen geschreven worden en welke relation string wordt gebruikt (default `edges_semantic`, `MENTIONS_ARTICLE`).
- `LAWGRAPH_DOCUMENT_COLLECTIONS`, `LAWGRAPH_EDGE_COLLECTIONS`: comma-separated lijsten met collections; gebruikt door `lawgraph.config.settings._env_list`. Laat ze leeg of configureer nieuwe collections voor speciale deployments.

## Configuratie in code
- `dotenv.load_dotenv()` in `settings.py` zorgt dat env variabelen beschikbaar zijn in modules. Pipelines importeren `lawgraph.config.settings` voor constants en `config.config.load_domain_config` voor profile data.
- `config.config.load_domain_config(profile_name)` leest YAML en voert minimale validatie uit (dict-structuren). CLI’s doen `domain_config = load_domain_config(profile)` en geven dit door aan pipelines (bv. `TKArticleSemanticPipeline(domain_profile=profile)`).
- `lawgraph.models.make_node_key` en `lawgraph.utils.display` zijn helpers die ook gebruik maken van ingestelde properties (zoals instrument identifiers) om deterministic keys/namen te maken.
- `ArangoStore` (in `lawgraph/db.py`) gebruikt settings voor `collections`/`edge_collections` en accepteert `insert_or_update` paremeters zodat pipelines geen constants hoeven te dupliceren.

## Wijzigingsproces
1. Pas `.env` of een profiel aan in een feature branch; commit changes met beschrijving en verwijder nooit credentials (gebruik placeholders).  
2. Draai `ruff check src tests` en `pytest tests/` (zonder network calls tenzij `ALLOW_NETWORK_TESTS=1`).  
3. Verifieer CLI usage (bijv. `LAWGRAPH_PROFILE=strafrecht lawgraph-retrieve-tk`) en bekijk logs voor `describe_since()`/edge counts.  
4. Na review merge je en deploy je `.env`/secret updates via je infrastructuur (bijv. Kubernetes secrets of `.env` in CI).  
5. Voor rollback restore je de vorige versie van `.env`/profiel of geef een oude `LAWGRAPH_PROFILE` door; pipelines blijven idempotent dankzij deterministic `_key`s. All changes must be documented in corresponding docs (`docs/profiles.md`, `docs/configuration.md`, etc.).
