# LawGraph

@~/Development/lawgraph/docs/claude/werkruimte.md

Python 3.14, uv, FastAPI, PostgreSQL 18. Drie fasen per bron: `retrieve` → `normalize` → `semantic`. Uitleg: `README.md`, `docs/architecture.md`, `docs/operations.md`, `CONTRIBUTING.md`.

## Commando's
- `uv sync --extra dev`; CLI `lawgraph <command>` (`lawgraph sources` toont alles).
- Unit: `pytest tests -q` (geen database). Integratie: `tests/integration/` en `tests/pg/` tegen `docker-compose.test.yml` (poort 5433), **serieel** (geen `-n`).
- Vóór push: `.venv/bin/mypy src`, `ruff check`, `ruff format --check` (pre-commit doet de rest).
- Volledige suites alleen in CI; lokaal de bestanden die je raakt, plus elk integratiebestand dat een gewijzigde route leest. Een wijziging aan een `cached()`/warm-up-lezer: ook `tests/pg/test_cached_tables.py`.

## Regels
- Fouten herstel je met een pipeline-run uit de bron, nooit met een handmatige correctie; elke afgeleide tabel is opnieuw te bouwen.
- Alleen officiële bronnen (Rijksoverheid, Wikidata; geen Wikipedia). Gaten markeren, nooit met de hand vullen.
- Docs kort en zelfstandig, zonder historie; geen migratie- of legacycode (enige gebruiker). `data-model.md` heeft gegenereerde tabellen.
- Complexiteit per functie ≤ 15 (C901).
- Geen pipelines draaien op een gedeelde database vóór merge. Een retrieve op `lawgraph_small` krijgt altijd `--since` (+ `--skip-*`).

## Productie (web-1)
- Alleen via `gh workflow run ops --ref develop -f action=…` met gemergede scripts in `ops/` of `deploy/server/`. `status`, `log`, `run-log`, `sql`, `config-check` = alleen lezen, mag zonder vraag.
- `run`, `config-apply`, deploys, restarts: alleen met go van Thijs in deze sessie.
- Een kolom erbij breekt ook de oude release (schema drift): stap 0 vlak vóór de deploy.
- Backfills in stappen van ≤ 30 min die de lock vrijgeven, na de nightly. Handgestarte scripts sourcen `scheduler.env`.
- Ops-scripts schrijven stapuitvoer naar een bestand, niet via `$(...)`; nooit een ouder met SIGSTOP pauzeren. Na een kill: `free-orphan-lock`.
