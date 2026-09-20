# Pipelines

One section per source: what it provides, how it is retrieved, what normalize writes and
what the semantic pipelines detect. Confidence values are fixed in code unless noted.

## Overview

| Source | Retrieve | Normalize | Semantic |
|--------|----------|-----------|----------|
| Tweede Kamer | `tk`, `tk-dossiers`, `tk-content` (manual) | `tk`, `tk-dossiers` | `tk`, `instrument-relations`, `amendment-articles`, `mvt-articles` |
| Rechtspraak | `rechtspraak` | `rechtspraak` | `rechtspraak`, `judgment-citations`, `judgment-appeal` |
| EUR-Lex | `eurlex` | `eurlex` | `eurlex` |
| BWB | `bwb`, `bwb-history` (manual) | `bwb`, `bwb-history` | `bwb`, `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `relation-semantics` |
| Staatsblad | `staatsblad` | `staatsblad` | `staatsblad` |
| Staatscourant | `staatscourant` | `staatscourant` | `staatscourant` |
| Eerste Kamer | `eerstekamer` | `eerstekamer` | `eerstekamer` |
| ECHR | `echr` | `echr` | `echr` |
| Verdragenbank | `verdragenbank` | `verdragenbank` | none |

Clients (`clients/`) share `BaseClient`: base URL from `config/settings.py` (trailing
slash enforced), one `requests.Session`, 30 s timeout, and retry with exponential backoff
(3 tries, factor 2) on HTTP 429, 503 and connection errors. No source needs an API key.

Citation detectors resolve law abbreviations (`Sr`, `Sv`, `BW`) through
`instruments.props.short_title` and law names through instrument titles; the API judgment
view uses the same lookup. `normalize bwb` writes `short_title` from the official
abbreviations in the BWB WTI files (see BWB below). A code split over books resolves through
the book in the article number: `artikel 6:162 BW` cites article `162` of the regulation whose
short title is `BW6` (`DutchCitationExtractor`); without a book (`artikel 162 BW`) or with an
unknown one there is no hit.

## Tweede Kamer

**Provides.** OData v4 JSON API of the Gegevensmagazijn (`TK_API_BASE`): cases (Zaak),
documents, dossiers, activities, votes, commitments, committees, persons, factions.

**Retrieve.**

| Command | Fetches | Stored kinds |
|---------|---------|--------------|
| `retrieve tk` | Zaak modified since `--since` (default `1d`); `--mode full` since 1995-01-01; `--limit` caps the result for development | `tk-zaak` |
| `retrieve tk-dossiers` | Kamerstukdossier, Activiteit, Stemming, Toezegging, Commissie, Persoon, Fractie, FractieZetelPersoon, Document | `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-document` |
| `retrieve tk-content` | XML text of documents whose `kind` contains `--kind` (default `toelichting`) and that have no `props.text`; `--dry-run` | writes `documents.props.text` |

`tk-dossiers` options: `--since`, `--skip-members` (also skips Fractie and FractieZetelPersoon),
`--skip-decisions`, `--decisions-since`, `--skip-documents`, `--documents-since`,
`--dossier-number N` (fetches only the documents of that dossier, ignoring dates). Commissie,
Persoon, Fractie and FractieZetelPersoon are always full refreshes. Each entity type is
stored while it is fetched (a buffer at a time), so an interrupted run keeps what it fetched.

Client quirks:

- Nested `$expand` options are separated by `;`, not `&`:
  `$expand=Agendapunt($expand=Zaak($select=Id,Soort;$expand=Kamerstukdossier($select=Id,Nummer)))`.
  Standard OData syntax returns HTTP 400.
- The dossier endpoints emit no `@odata.nextLink`; the client pages with `$top=250` and
  `$skip` until a page is short. Zaak follows `@odata.nextLink` when no `$top` is sent
  (`$top=0` answers no records at all).
- Votes arrive as one row per faction per `Besluit`.
- A full Document fetch is about 400K records; use a date window (`retrieve all --window 730d`, or `--documents-since 730d`).
- `tk-content` does not use the PDF the API serves: the same paper is published as structured
  XML in the KOOP repository, filed under its dossier
  (`.../kst/<dossier>/kst-<dossier>-<number>/1/xml/kst-<dossier>-<number>.xml`, the dossier
  being the number with its addition, `37020-X` for a budget chapter). It builds the identifier
  from the dossier the paper is `PART_OF` and its `sequence`, takes the plain text of the XML,
  keeps at most 500,000 characters (and logs when it cuts), and stores each paper as it comes.
  A paper the repository does not have (404) is skipped; 25 failures in a row fail the step.

**Normalize `tk`.** Zaak to Case (`cases`, key = Zaak GUID, whole payload in `props.raw`,
`dossier_numbers` kept for the dossier pipeline). No edges: a case is linked once the dossiers
exist.

**Normalize `tk-dossiers`.** Order: committees, members, factions, dossiers, activities,
commitments, documents, decisions; then edges; then a backfill of title and stages onto each
dossier (it needs the document edges).

| Step | Detail |
|------|--------|
| decisions | vote rows grouped by `Besluit_Id`; rows without one are skipped; `passed` from the `BesluitSoort` text, else the tally; `subject` prefers the subject of the decided Zaak (`AgendapuntZaakBesluitVolgorde`) over the agenda item |
| factions | from the Fractie endpoint; without `tk-fractie` records they are derived from the `ActorFractie` strings of the votes; `aliases` map the differing abbreviations (`Fractie.Afkorting` versus `Stemming.ActorFractie`); TK reuses abbreviations, so the active or most recent record wins |
| members | every Persoon; `party` and `faction_memberships` come from FractieZetelPersoon (dated), so a member without those records has no party |
| dossiers | `Nummer` plus `Toevoeging` form the key (`36554` and `36554-I` are distinct); `current_stage`, `stages_present`, `track_kind`, `title` (from a voorstel-van-wet or MvT document when the dossier has none) and `outcome` (closed dossiers only) are derived from documents, activities and decisions by `core/dossier_stages.py` |
| documents | dossier numbers via Zaak to Kamerstukdossier; `DocumentActor` becomes `props.actors`; several dossiers per document are kept in `dossier_numbers` |

Edges: `PART_OF` (Document to Case and Dossier, Case to Dossier), `ABOUT` (Activity, Decision
to Case and Dossier; Commitment to the dossiers of its activity), `LED_BY` (Activity to
Committee from `Voortouwcommissie_Id`), `MADE_IN` (Commitment to Activity), `MEMBER_OF`
(dated, to committee and faction), `AUTHORED` (signatory to Document), `VOTED`.

**Semantic `tk`.** Reads `documents` labelled `TK`. Text is title, summary, body, text and
every string in `props.raw`, capped at 200,000 characters. Aliases come from the graph:
`instruments.props.short_title` (codes such as `Sr`) and instrument titles (see `semantic
rechtspraak` for the article forms).

| Pattern | Kind | Confidence |
|---------|------|-----------|
| `artikel 36e, derde lid, Sr` / `artikel 3 van de Wwft` / `artikel 3 van het <name>` | article | 0.95 |
| `artikel N van (de) Richtlijn / Verordening / (het) Besluit / Kaderbesluit YYYY/N` | article | 0.88 |
| `CELEX:<id>` | instrument | 0.90 |
| `BWBR...` id | instrument | 0.75 |
| `Richtlijn` or `Verordening YYYY/N` (CELEX derived) | instrument | 0.65 |
| an instrument's title or citation title appears | instrument | 0.60 |

Every hit becomes a `REFERS_TO` edge to the article or instrument. A missing article target is
created as a stub when the confidence is at least 0.85; instruments are never created. Edges
hold `raw_match`, `snippet`, `reason` (`bwb_article`, `celex_article`, `bwb_instrument`,
`celex_instrument`) and `qualifier`.

**Semantic `instrument-relations`.** Two detectors:

| Relation | Detection | Confidence |
|----------|-----------|-----------|
| `AMENDS` (Document to Instrument, `voorgesteld`) | TK document title contains `wijziging van` and a known instrument title | 0.85 |
| `IMPLEMENTS` (Instrument to Instrument) | CELEX `3YYYY[CLRDF]NNNN` in the raw BWB XML of an instrument; both instruments must exist | 0.75 |

**Semantic `amendment-articles`.** Scans TK documents that have `props.text` (filled by
`tk-content`) for amendment wording, for every BWB id the document is tied to (`props.bwb_id`,
else its `AMENDS` edges to instruments). Targets must exist. Every edge is written with status
`voorgesteld`.

| Wording | Relation | Confidence |
|---------|----------|-----------|
| `Artikel N ... wordt gewijzigd` | `AMENDS` | 0.90 |
| `Na artikel N wordt een artikel M ingevoegd` | `INTRODUCES` (article M) | 0.85 |
| `Artikel N ... komt te luiden` | `AMENDS` | 0.85 |
| `Artikel N ... vervalt` / `komt te vervallen` | `REPEALS` | 0.80 |
| `In artikel N ... wordt` | `AMENDS` | 0.80 |

**Semantic `mvt-articles`.** No text matching: the link is read from the graph. For every
document whose `kind` contains `toelichting`, one AQL pass walks
`Document -PART_OF-> Dossier <-LEGISLATED_IN- Instrument -AMENDS|INTRODUCES|REPEALS-> Article`
and writes `EXPLAINS` at confidence 1.0 to the `meta.article_version` of each change edge, to
the article itself when the edge names no version, and to the instrument when it changed no
articles at all.

## Rechtspraak

**Provides.** Judgments from data.rechtspraak.nl: an Atom index (`uitspraken/zoeken`) and the
XML of one judgment (`uitspraken/content?id=<ECLI>`).

**Retrieve.** The index is filtered by court (`creator`, an OWMS term; several are OR) and by
decision date (`date`, twice for a range) and read in pages of 1,000. `modifiedsince` is not
used as a window: the Rechtspraak republished nearly its whole corpus, so it matches almost
everything. For each judgment of the index one `rs-content` record is stored, as soon as it is
downloaded. A judgment that is stored and was fetched after its last change (`updated` in the
index) is skipped, so a re-run or a resumed run only downloads the rest.

| Option | Meaning |
|--------|---------|
| `--court NAME` (repeatable) | `hr`, `rvs`, `crvb`, `cbb`, `gh-amsterdam`, `gh-arnhem-leeuwarden`, `gh-den-haag`, `gh-s-hertogenbosch` (the older `gh-arnhem`, `gh-leeuwarden`, `gh-s-gravenhage`), or the group `hoven` (all courts of appeal). Default: `hr`, `rvs`, `hoven`; none when only `--ecli` is given |
| `--mode incremental` (default) | judgments decided from `--since` (default `1d`) minus 30 days, because judgments are published up to weeks after the decision |
| `--mode full` | no date filter: every judgment of the courts (the Raad van State alone is far over 100,000) |
| `--ecli ECLI` (repeatable) | also fetch these judgments as they are (`fill-gaps` uses this for stubs); skipped when stored in the last 24 hours |

Over the last two years the default courts hold about 33,000 judgments (Hoge Raad 4,100, Raad van
State 11,000, the four courts of appeal about 18,000), a few hours at the paced rate.
`retrieve all` reads the `--window` (a judgment is in it by decision date). Other courts, such as
the rechtbanken (over 100,000 in two years), are chosen with `--court`.

**Normalize.** From `rs-content` XML: RDF header (`creator` as `court`, `date`, `zaaknummer` as
`case_number`, `procedure` as `judgment_metadata.type`, `subject`s, `relation` ECLIs as
`related_eclis`), `inhoudsindicatie` as `summary`, `uitspraak` as `text` and as `paragraphs`
(heading, subheading, body), the XML itself as `raw_xml`. `court_code` is the ECLI court
segment; `tier` is `hoge_raad` (`HR`), `gerechtshof` (`GH*`), `rechtbank` (`RB*`) or
`bijzonder`; `date_eff` is the judgment date.

**Semantic `rechtspraak`.** Reads `raw_xml` (else `text` and `summary`), strips the tags and
extracts article citations with the detector of `tk`, without its instrument-level title
patterns: the EU forms and `CELEX`/`BWBR` literals are kept. The detector reads the article
first and resolves the law after it:

| Form | Confidence |
|------|-----------|
| `artikel 3.26, eerste lid, van de Wet ruimtelijke ordening` (code or full name; dotted, colon and lettered numbers; `lid`, `onder`, `sub`, `aanhef`, `volzin`) | 0.95 |
| `artikelen 338 (lid 2) en 339 Fw`, `artikelen 2 tot en met 5 Sv` | 0.95 each |
| `artikel 2.8 van de Wnb` after `... (hierna: de Wnb)` in the same text | 0.90 |
| `artikel 3a van die wet` (also `deze`, `genoemde`, `voornoemde`), the law named last within 3,000 characters | 0.70 |

Codes come from `instruments.props.short_title`, names from instrument titles; a title two
instruments share is not a name. A missing target article is created as a stub from 0.9; an
article cited only as `artikel N` with no law is not written.

**Semantic `judgment-citations`.** `ECLI:<country>:<court>:<year>:<number>` in `raw_xml`, `text` or `body`:
`REFERS_TO`, 0.95, `meta.cited_ecli`, no self citations, missing judgments become stubs.

**Semantic `judgment-appeal`.** Judgments with `related_eclis` whose `judgment_metadata.type`
contains `hoger beroep` or `cassatie`: `APPEAL_OF` from the appeal judgment to each related
ECLI, 0.95, `meta.procedure_type`; missing judgments become stubs.

## EUR-Lex

**Provides.** EU acts as HTML by CELEX number. The site `eur-lex.europa.eu` answers automated
clients with HTTP 202 bot challenges, so the client uses the Publications Office CELLAR
server (`https://publications.europa.eu/resource/celex/<CELEX>`, content negotiation on
language, redirects followed, 60 s timeout). CELEX numbers are enumerated by SPARQL
(`EURLEX_SPARQL_ENDPOINT`, pages of 500). That endpoint is not a complete list: it has no
entry for many recent acts (about 150 directives for 2010, 1 for 2016; the GDPR is missing),
it answers HTTP 500 from offset 10000 (a failing page raises), and it holds no national
implementation measures. Acts are therefore fetched by the CELEX numbers that loaded records
refer to (`fill-gaps`, `expand-graph`), not by listing them.

**Retrieve `--mode`.**

| Mode | CELEX numbers fetched |
|------|-----------------------|
| `incremental` (default) | those of instruments already in the graph, or `--celex` (repeatable) |
| `full` | the directives SPARQL lists, without corrigenda; `--type` (repeatable: `directive`, `regulation`, `decision`) chooses other types, at most 10000 per type. Not part of `retrieve all` |
| `nim` | acts with national implementation measures for `--country` (default `NLD`); the endpoint holds none, so this is an error |
| `cjeu` | judgments that cite acts in the graph |
| `com` | Commission proposals for acts in the graph |

`--lang` (default `NL`). Stored as `eu-celex-html` while the acts are fetched. An act
without an HTML text (HTTP 404, in every language: old regulations and every corrigendum)
counts as skipped, not as an error.

**Normalize.** Instrument per CELEX (`jurisdiction: eu`, `title` from the `doc-ti` paragraph,
`citation_title` derived from the number, for example `Richtlijn 2010/64/EU`). Articles are
cut out of the plain text at `Artikel N` / `Article N` headers; numbers above
`EURLEX_MAX_ARTICLE_NUMBER` (200, read at import) and bodies shorter than 10 characters or
starting with `,` are skipped. `PART_OF` from article to instrument.

**Semantic `eurlex`.** Scans the text of EU articles.

| Pattern | Confidence |
|---------|-----------|
| `artikel N` + code `Sr` / `Sv` / `BW` | 0.95 |
| `CELEX:<id>` | 0.90 |
| `artikel N van Richtlijn / Verordening YYYY/N` | 0.85 |
| `Richtlijn` or `Verordening YYYY/N` | 0.70 |
| `BWBR0...` id | 0.70 |

All hits become `REFERS_TO` edges; missing articles with confidence 0.85 or more become stubs.

## BWB (Dutch legislation)

**Provides.** wetten.overheid.nl via the SRU service (`BWB_SRU_ENDPOINT`, `x-connection=BWB`)
and the toestand XML: one dated version of a regulation, with every article carrying
`stam-id`, `versie-id`, `inwerking` (in force from), `bron` (originating publication) and
`effect`; `<meta-data><brondata>` naming the originating and commencement publication and
their `<dossierref>`; `<extref>`/`<intref>` references with a `jci` address; the preamble
paragraph `Gelet op ...` with `<extref>` to the legal basis; `<bijlage>` annexes. Each SRU
record also names the regulation's WTI file (`locatie_wti`, `.../bwb/<id>/<id>.WTI`), whose
first element `<algemene-informatie>` lists the official abbreviations (`<afkortingen>`).

**Retrieve.**

| Command | Behaviour |
|---------|-----------|
| `retrieve bwb` | `--bwb-id` (repeatable) or `BWB_IDS` (comma-separated): the current toestand of each id (in force means end date `9999-12-31`, else the newest), plus the `<algemene-informatie>` element of its WTI file (kind `bwb-wti-algemene-informatie-xml`). Without ids in incremental mode nothing is fetched. `--mode full` enumerates every id first |
| `retrieve bwb-history [ids...]` | every toestand of each id, or of all ids when none are given; stored `<bwb_id>@<start_date>` |

Enumeration queries `dcterms.type=="<type>"` for each type in `BWB_INSTRUMENT_TYPES`
(case-sensitive: `AMvB`, `ministeriele-regeling`), 1,000 records a page (the service silently
caps larger requests), at most 150,000 records per type. The service returns one record per
toestand, so ids repeat and are de-duplicated. A `<diagnostic>` response raises an error
instead of yielding an empty list. A toestand XML document is large; history runs are slow.

A WTI file is large too (27 MB for the Wetboek van Strafrecht: amendment log and related
regulations), but `<algemene-informatie>` comes first. The client streams the file and closes
the connection once that element is complete, so about 1 KB is downloaded and stored. A
failed WTI download is reported as an error; the toestand is stored regardless. A regulation
without a WTI location or element gets no WTI record.

**Normalize `bwb`.** `core/bwb_xml.parse_toestand` is the single parser. Instrument props: title
(citeertitel, else intitule), `kind` (`wetgeving@soort`), `date_signed`, `date_published`,
`date_in_force`, `dossier_numbers` of the originating publication. One Article per
`(bwb_id, article number)` with the article text (leden as `1. text`, list items on their
own lines, a paragraph next to the leden is included), the structured `references` with text
offsets, and `stam_id`, `versie_id`, `valid_from`, `source_publication`, `repealed`. Two
articles of one regulation with the same number share a key. `PART_OF` (article to
instrument).

After the nodes, `normalize bwb` sets `short_title` on existing instruments from the stored
WTI records (`core/bwb_wti.py`). A regulation can have several abbreviations, listed
alphabetically by the source, so their order means nothing. The rule:

1. Case is ignored (`GW` and `Gw` are one abbreviation; the first spelling is kept).
2. An abbreviation that several loaded regulations claim never wins: every book of the
   Burgerlijk Wetboek lists `BW`, and a short title must lead to one regulation.
3. Of the rest the shortest wins (`Sr` over `WvS` and `WvSr`, `WVW` over `WVW 1994`, `BW1`
   over `BW Boek 1`); equal lengths keep the source order.
4. A regulation left with nothing has no `short_title`; one it had is removed.

Rule 2 depends on the other regulations, so every WTI record is read on every run, whatever
`--since` is, and a short title can change when more regulations are loaded. `BW` itself is
nobody's short title; the books are `BW1`, `BW2`, ... and a book is only citable once its WTI
record is loaded.

**Normalize `bwb-history`.** Reads every stored toestand once and writes:

- an InstrumentVersion per toestand and an ArticleVersion per `(stam_id, versie_id)` (a
  toestand only repeats versions still valid), with `origin_publication` and
  `commencement_publication`;
- `valid_until` and `current`, recomputed from the database in chunks of 200 regulations, so
  incremental runs stay correct;
- `VERSION_OF` from each ArticleVersion to its Article and from each InstrumentVersion to its
  Instrument;
- an Instrument if `normalize bwb` has not created it, and a historical Article for an identity
  that is not in the current toestand.

Run `normalize bwb` first.

**Semantic `bwb`.** `REFERS_TO` between articles, read from the XML rather than from the text:
only articles that carry `props.references` are scanned, and each reference naming a regulation
and an article becomes one edge with confidence 1.0, `meta` = `start`, `end`, `text` and
`reason = bwb_xml_ref`. Self references are dropped and targets must exist — nothing is stubbed.
Articles are processed in chunks of 500 so one lookup resolves a whole chunk's targets.
`--store-citations` also writes the references onto the article as `props.citations`.

**Semantic `bwb-grondslagen`.** `BASED_ON` from a regulation to the article named in its
`Gelet op` paragraph, 1.0, `meta = {text, doc}`. Entries without an article, self references
and targets that are not in the graph are skipped.

**Semantic `bwb-amendments`.** Reads the article versions that carry `origin_publication`:

1. upserts each originating and commencement publication as an Instrument (`stb_2019_33`),
   merging the dossier numbers of every version that mentions it;
2. resolves each `(bwb_id, stam_id)` to its Article, one query per chunk;
3. writes `Instrument(publication) -> AMENDS | INTRODUCES | REPEALS -> Article` from the
   version `effect` (`nieuw` introduces; `wijziging`, `tekstplaatsing-wijziging` and
   `tekstplaatsing-vernummering` amend; `vervallen` repeals), confidence 1.0, `meta` =
   `effective_date`, `article_version`, `effect`, `source_publication`; one edge per
   publication, article and kind, with the earliest effective date;
4. writes `LEGISLATED_IN` from each publication and each regulation to the dossiers of
   `dossier_numbers` that exist (key = the plain dossier number).

Versions with an unknown effect or without a matching article count as skipped.

**Semantic `bwb-annexes`.** Pass 1 parses `<bijlage>` elements from the raw toestand XML into
Annex nodes (`label`, `title`, `description` up to 2,000 characters, `entries` from `<li>` items,
at most 200) with `PART_OF` to the instrument. Pass 2 finds `bijlage <label>` in article texts
and writes `SCOPED_BY` (0.9 with a label, 0.7 without) with `meta.scope_type` `discretionary`
when ministerial-designation wording is near (`bij ministeriële regeling`, `Onze Minister
kan ...`), else `fixed`. A reference to an annex the XML did not contain gets a stub.

**Semantic `relation-semantics`.** Sets `semantic_type` on article-to-article `REFERS_TO` edges
from the text around the reference (`meta.start`/`end`): a trigger phrase in the 40 characters before
the reference scores 0.9, elsewhere within 120 characters either side 0.7, no trigger gives
`cross_reference` at 0.5. Types and their patterns: `limiting_exception`,
`definitional_reference`, `conditional_requirement`, `prerequisite_procedure`,
`scope_limitation`, `delegated_discretion`, `cross_reference`. It writes `semantic_source =
structured` and never touches edges classified by an `expert` or `community`. The
confidence of one pattern can be overridden with `LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>`, for
example `LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION=0.8` (patterns: the type names above and
`cross_reference_explicit`, `cross_reference_fallback`).

## Staatsblad

**Provides.** Staatsblad publications as XML from repository.overheid.nl
(`/frbr/officielepublicaties/stb/<year>/<id>/1/xml/<id>.xml`, a 404 is "not found"),
enumerated through the KOOP SRU (`dt.type=AMvB`, about 19,900 records). Every KOOP SRU
search (`clients/_sru.py`) is paged by key, `dt.identifier>"<last>" sortBy dt.identifier`,
100 per page, because the service answers HTTP 504 for any record from position 10000 on;
the pages must add up to the reported total, and an SRU diagnostic or a failed request raises.

**Retrieve `--mode`.** `from-graph` (default): reads the stored BWB XML, extracts the
publication year and number of each regulation and fetches those not yet stored (run
`retrieve bwb` first). `full`: every AMvB from the SRU.

**Normalize.** Document per record (`kind` "Nota van toelichting", `text` from the
`nota-van-toelichting` or `toelichting` section, `bwb_id` = first BWB id in the XML), key
`stb_<identifier>`. No edges. The same Staatsblad number also exists as an amending Instrument;
that node comes from `bwb-amendments`.

**Semantic `staatsblad`.** `EXPLAINS` to the instrument with that `bwb_id` (0.85), else whose
`citation_title` occurs in the title (0.60); `meta.match_type` says which.

## Staatscourant

**Provides.** Ministeriële regelingen as XML, enumerated through the KOOP SRU
(`dt.type=Ministeriele-regeling`, optional `dt.modified>=since`; the query also returns some
Staatsblad records, which are dropped: about 13,800 regulations).

**Retrieve.** `incremental` (default) searches the SRU (`--since`), `full` fetches all,
`--identifiers` fetches given `stcrt-YYYY-N` identifiers.

**Normalize.** Document (`kind` "Ministeriële regeling", `title`, `text`, `bwb_id`, `date`),
key `stcrt_<identifier>`.

**Semantic `staatscourant`.** `EXPLAINS`: `bwb_id` match 0.92, title contains an instrument
`citation_title` 0.65, a BWB id found in the text 0.75 (at most 5,000 documents).

## Eerste Kamer

**Provides.** The Kamerstukken of the Eerste Kamer, about 38,000 from 1994 on, from the KOOP SRU
(`EERSTEKAMER_SRU`; creator `Eerste Kamer der Staten-Generaal`, `w.publicatienaam==Kamerstuk`,
`dt.type==Kamerstuk`, so attachments `blg-*` are left out). The Eerste Kamer has no API of its
own. Per paper: identifier (`kst-<dossier>-<letter>`, some `kst-<number>`), own title
(`documenttitel`), dossier title, kind (`subrubriek`), number in the dossier (`ondernummer`),
date, session year, dossier number and the page on zoek.officielebekendmakingen.nl. Papers
before about 2007 have no kind and no own title in the source. Not loaded: votes and their
outcome (aanvaard, verworpen, per fractie): they exist only as prose in the Handelingen and as
HTML on eerstekamer.nl, and the plenary reports and PDFs are not fetched.

**Retrieve `--mode`.** `incremental` (default): `--since` on `dt.modified`; `full`: everything.
`--max-records` stops early. The SRU record is stored as `ek-kamerstuk-json`.

**Normalize.** Document `ek_<identifier>`, labels `EersteKamer` and `EK` (the API `chamber`
filter), `kind`, `number`, `title`, `subject` (dossier title), `session_year`, `date`, `url`,
`dossier_number` and `dossier_suffix` (the Tweede Kamer stores the two parts of `35925 VII`
separately). A Roman numeral instead of a number (the own dossiers of the Eerste Kamer, 525
papers) sets neither. No edges here.

**Semantic `eerstekamer`.** `PART_OF` from the paper to the Tweede Kamer dossier with the same
number and addition, 0.95, `meta.chamber = EK`.

## ECHR

**Provides.** HUDOC judgments (`ECHR_HUDOC_BASE`, `/app/query/results`), filtered by
respondent (`--respondent`, default `NLD`) and collection `JUDGMENTS`, 100 per request with
0.5 s between requests. Fields: application number, name, item id, date, respondent,
importance, cited articles, conclusion, originating body.

**Retrieve.** `--since` (`kpdate >=`), `--max-records` (default 10,000); `--mode full`
reads up to 50,000.

**Normalize.** Judgment per item (`echr_<itemid>`; `appno`, `title`, `date`, `articles`,
`conclusion`, `importance`); no judgment text.

**Semantic `echr`.** Creates the instrument `EVRM` (`echr_convention`, `bwb_id`
`ECHR-CONVENTION`) and one article per cited Convention article (`echr_convention_<n>`);
`REFERS_TO` from judgment to article at 0.95, and from judgment to a BWB instrument named in
the `conclusion` at 0.80.

## Verdragenbank

**Provides.** Treaties the Netherlands is party to, from the KOOP SRU
(`VERDRAGENBANK_SRU`, `c.product-area==vd AND w.documenttype==verdrag`, 250 per page):
titles (nl and en are separate records with the same id and are joined), signing and
in-force dates, type (`Bilateraal`, `Multilateraal`, `Plurilateraal`), status
(`Inwerkinggetreden`, `Buitenwerkinggetreden`, `Totstandgekomen`, ...) and the six-digit
Verdragenbank id (`verdragsnummer`), about 8,800 treaties. The former SPARQL endpoint
(`linkeddata.overheid.nl`) holds no treaty data. Records of amendments (`wijziging`) are
not read. An empty result raises: the endpoint or its data model has changed.

**Retrieve.** `--max-records` stops early. **Normalize.** Instrument `verdrag_<id>`
(`kind` `verdrag`, `multilateraalverdrag` or `bilateraalverdrag`, `jurisdiction: int`,
`in_force` only for `Inwerkinggetreden`). No edges and no semantic pipeline. These
instruments are not linked to the BWB treaties (`BWBV...`). Not ingested: the Trb references
(`dcterms:isPartOf`), the parties and the place of signing.

## Ordering

`normalize all` and `semantic all` run in registry order; each row needs what is above it.

| Step | Needs |
|------|-------|
| normalize `bwb-history` | `normalize bwb` (articles and instruments) and stored `bwb-toestand-xml-all` |
| normalize `tk-dossiers` | `normalize tk` (the case-to-dossier links read `cases`) |
| retrieve `staatsblad` (from-graph) | `retrieve bwb` |
| semantic `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `relation-semantics` | normalized articles; `bwb-amendments` also `bwb-history` versions and the dossiers of `normalize tk-dossiers`; `relation-semantics` runs after `bwb` |
| semantic `amendment-articles` | `instrument-relations` (the document-to-instrument `AMENDS` edges), document text from `tk-content` |
| semantic `mvt-articles` | `bwb-amendments` (`LEGISLATED_IN` and the change edges it walks) and `normalize tk-dossiers` (the document-to-dossier `PART_OF` edges) |
| semantic `eerstekamer` | `normalize tk-dossiers` and `normalize eerstekamer` |
| semantic `list-stats` (last step of `semantic all`) | backfills what the list endpoints sort and filter on: instruments (`jurisdiction`, `article_count`, `kind`), judgments (`court_code`, `tier`, `date_eff`, `inbound_citation_count`), articles (`inbound_citation_count`), committees (`active_dossier_count`) |--judgments-only|--committees-only|--articles-only]` |
