# Bijdragen aan Lawgraph

Lawgraph bouwt een NL/EU-wetgevings- en rechtspraakknowledgegraph in **ArangoDB** en verzamelt informatie uit Tweede Kamer, Rechtspraak.nl, EUR-Lex/CELEX en wetten.overheid.nl. De pipelines draaien deterministisch zodat meerdere runs tot dezelfde `_key`s in document- en edgecollecties leiden. Die focus op reproduceerbaarheid en configuratie via profielen vormt de scope van het project; de graph zelf is het aggregatielagenwerk, zonder UI/UX-laag.

## Lokale setup

1. Clone de repository en zet een virtuele omgeving klaar:

   ```bash
   git clone https://example.com/lawgraph.git
   cd lawgraph
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

2. Maak een `.env` in de projectroot. Minimaal dienen de Arango-verbinding en credentials erin te staan:

   ```env
   ARANGO_URL=http://localhost:8529
   ARANGO_DB_NAME=lawgraph
   ARANGO_USER=root
   ARANGO_PASSWORD=changeme
   ```

   Voeg naar behoefte API-baseurls en profielkeuzes toe (bijv. `TK_API_BASE`, `RECHTSPRAAK_BASE`, `EURLEX_BASE`, `LAWGRAPH_PROFILE`).

## ArangoDB lokaal draaien

De repository bevat een `docker-compose.yml` met een Arango-service. Start de database met:

```bash
docker-compose up -d arangodb
```

Controleer daarna met `docker-compose logs -f arangodb` of de database klaar is. Gebruik dezelfde credentials als in `.env`.

## Profiles en LAWGRAPH_PROFILE

Profielen in `src/config/*.yml` definiëren welke instrumenten, filters en topics een pipeline moet gebruiken (bijv. `strafrecht`). De CLI’s lezen standaard `LAWGRAPH_PROFILE` of accepteren `--profile`-argumenten; zo blijven filters, API-keys en metadata buiten de code en in één beheerlaag. Een profiel bevat doorgaans `nl_instruments`, `eurlex`, `rechtspraak` en topicdefinities.

## Pipelines draaien

Zorg dat de juiste profiellocatie actief is:

```bash
export LAWGRAPH_PROFILE=strafrecht
```

- **Retrieve**: elke `lawgraph-retrieve-*`-command vult `raw_sources` met JSON/metadata. Run:

  ```bash
  lawgraph-retrieve-tk
  lawgraph-retrieve-rechtspraak
  lawgraph-retrieve-eurlex
  lawgraph-retrieve-bwb
  lawgraph-retrieve-all
  ```

- **Normalize**: de `lawgraph-normalize-*`-commands transformeren `raw_sources` naar nodes/edges met deterministische `_key`s:

  ```bash
  lawgraph-normalize-tk
  lawgraph-normalize-rechtspraak
  lawgraph-normalize-eurlex
  lawgraph-normalize-bwb
  lawgraph-normalize-all
  ```

Gebruik `LAWGRAPH_PROFILE` of `--profile <naam>` om de juiste filters en metadata te laden. Seed-CLI (`lawgraph-strafrecht-seed`) injecteert specifieke domeindata in een nieuwe database.

## Coding conventions

- Python 3.11 wordt gebruikt; typannotaties en moderne taalfeatures zijn standaard.
- Schrijf deterministic keys via `lawgraph.models.make_node_key`; meerdere runs moeten identieke `_key`s produceren.
- Plaats alle constants, API-bases en collectionnamen in `.env` of in profielconfiguraties (`src/config/*.yml`); vermijd hardcoderingen in de business logic.
- Configuratie hoort in profielen en `LAWGRAPH_PROFILE`, zodat pipelines agnostisch blijven over specifieke domeinen.
- Houd code leesbaar en split pipelines op in `retrieve` vs `normalize` respectievelijk `clients`, `models` en `config`. Voeg waar nodig korte commentaarregels toe die intentie verduidelijken zonder obvious statements.

## Tests

- Unit- en integratietests draaien met `pytest tests/`.
- Netwerktests vereisen echte API-keys, dus ze zijn opt-in:  
  ```bash
  ALLOW_NETWORK_TESTS=1 pytest tests/
  ```

  Ook hier geldt dat profielfiles en `.env`-waarden de filters en authenticatie regelen.

## Linting

Gebruik `ruff` voor linting:

```bash
ruff check src tests
```

Voer linting uit voordat je code naar de repository pusht; corrigeer stijl-, type- en importissues die `ruff` aangeeft.

## Branches, commits en PR’s

- Branches leven op `develop` en feature-takken onder `feature/*`. Werk per feature/bugfix op een eigen branch.
- Commitboodschappen zijn beschrijvend en kort: `npm`-achtige prefixen zijn niet verplicht, maar vermeld altijd de kernwijziging (bv. `fix: deterministic keys for topics` of `feat: new normalize pipeline for tk`).
- Open PR’s tegen `develop`. Voeg in de beschrijving een korte samenvatting, welke pipelines zijn getest en welke profielinstellingen zijn gebruikt. Voeg links naar relevante issues toe waar mogelijk.
- Vermeld in de PR welke tests en lintchecks zijn uitgevoerd en of `ALLOW_NETWORK_TESTS` nodig was.

## PR workflow

1. Update je branch en zorg dat tests/lint succesvol zijn.
2. Push naar `feature/<kort-beschrijvende-naam>`.
3. Maak een PR aan tegen `main`, voeg reviewers toe, beschrijf de change en geef aan welke Pipelines/Profielen relevant zijn.
4. Na review voer je eventuele feedback door en squash of rebase indien gewenst. Vermijd force-pushes op `main`.

Dank voor je bijdrage!
