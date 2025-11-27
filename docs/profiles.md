# Profielen

## Doel en scope
Profielen beschrijven domeinspecifieke configuraties voor retrieve-, normalize- en semantic-pijplijnen. Ze bepalen welke BWB/EU-instrumenten belangrijk zijn, welke Rechtspraak-filters actief zijn, welke topics horen bij een domein (bijv. strafrecht) en welke code-aliasen moeten worden gebruikt om citaties te herkennen. Profielen zijn bedoeld voor pipeline-operators en domeinexperts, niet voor eindgebruikers.

## Structuur van een profiel
Een profiel bestaat uit een YAML-bestand onder `src/config/`, zoals `strafrecht.yml`. Belangrijke secties:

- `topic`: metadata over het domein (`id`, `name`, `description`, `labels`, `tags`). Dit wordt gebruikt bij het aanmaken van topic-nodes en seed CLI's.
- `code_aliases` & `instrument_aliases`: mappings (bijv. `Sr -> BWBR0001854`) die retrieve- én semantic pipelines gebruiken om verwijzingen te herkennen. Aliaswaarden worden ge-normaliseerd (`upper()`) en moeten unieke BWBR- of CELEX-IDs bevatten.
- `nl_instruments` / `eu_instruments`: lijst van instrument-definities die bij seed- en normalize-pijplijnen gebruikt worden; ze bevatten `id`, `bwb_id`/`celex`, `title`, `kind`, `topics`, `labels`.
- `filters`: per bron (zoals `rechtspraak`, `tk`, `eurlex`) kun je zoekcriteria definiëren (`search_terms`, `ecli_prefixes`, `celex_ids`, `title_contains`, `dossier_keywords`). Deze worden door retrieve-pijplijnen als `bind_vars` meegegeven.
- `seed_examples`: optionele startwaarden (bijv. `rechtspraak_eclis`, `extra_celex_candidates`) voor de seed CLI.
- `bwb`: aanvullende BWBR-config zoals `default_date` en `ids`.

Profielen worden geladen via `config.config.load_domain_config` of `LAWGRAPH_PROFILE`/`--profile`. CLI’s injecteren het profiel in pipelines zodat alle alias- en filtergegevens centraal blijven.

## Een nieuw profiel maken
1. **Kopieer een bestaand profiel** (`strafrecht.yml`) als basis. Geef je bestand een beschrijvende naam (`src/config/<domein>.yml`).
2. **Pas de secties aan**:
   - Werk `topic` bij met nieuwe labels/tags.
   - Voeg `code_aliases`/`instrument_aliases` toe of pas ze aan. Zorg dat elke alias een geldige BWBR- of CELEX-ID verwijst.
   - Definieer instrumentlijsten (`nl_instruments`, `eu_instruments`) die de normale lifecycle van je domein representeren.
   - Vul `filters` met relevante zoektermen of ECLI-prefixen voor retrieve-pijplijnen.
   - Voeg (indien nodig) `seed_examples` toe die door `lawgraph-strafrecht-seed` kunnen worden ingezet.
3. **Valideer het bestand**: gebruik YAML-linting en zorg dat alle references strings zijn (bijv. `"BWBR0001854"`, `"32010L0064"`). Vermijd duplicate keys.
4. **Documenteer** het profiel in `docs/profiles.md` (bijv. beschrijf welk domein het bedient) en eventuele README-secties.
5. **Voeg het profiel toe aan de CLI**: gebruik `LAWGRAPH_PROFILE=<jouw-profiel>` of `--profile <jouw-profiel>` bij retrieve/normalize/semantic commands.

## Validatie en governance

- Gebruik Git om profielen te versioneren; elke wijziging gaat via een pull request met review door een domeinexpert.
- Voer linting (bijv. `ruff check src tests`) en pytest uit; tests kunnen specifieke profielen laden om de pipeline-logica te dekken (`tests/test_semantic_*` gebruiken bijvoorbeeld `strafrecht`).
- Zorg dat profielen geen gevoelige data bevatten (gebruik `.env` voor credentials).
- Labels/ids moeten uniek blijven zodat `make_node_key` deterministisch blijft.

## Voorbeeld

```yaml
topic:
  id: "topic:milieu"
  name: "Milieu"
  labels: ["Milieu", "Environment"]
code_aliases:
  BW: "BWBR0005289"
instrument_aliases:
  "Wet milieubeheer": "BWBR0005289"
filters:
  rechtspraak:
    rechtsgebieden: ["Bestuursrecht", "Milieu"]
    ecli_prefixes: ["ECLI:NL:RVS", "ECLI:NL:CRVB"]
  tk:
    title_contains:
      - "milieu"
    dossier_keywords:
      - "milieu-initiatieven"
seed_examples:
  rechtspraak_eclis:
    - "ECLI:NL:RVS:2023:1234"
```

Dit profiel zou worden gebruikt door pipelines die zich op milieurecht concentreren; door `LAWGRAPH_PROFILE=milieu` in te stellen wordt alle retrieval/filtering afgestemd op deze configuratie.
