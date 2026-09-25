# Pipelines

One section per source: what it provides, how it is retrieved, what normalize writes and
what the semantic pipelines detect. Confidence values are fixed in code unless noted.

## Overview

| Source | Retrieve | Normalize | Semantic |
|--------|----------|-----------|----------|
| Tweede Kamer | `tk`, `tk-dossiers`, `tk-content` (manual) | `tk`, `tk-dossiers`, `tk-content` | `tk`, `tk-amends`, `tk-amendment-articles`, `tk-mvt`, `tk-mvt-articles`, `tk-dossier-outcomes`, `tk-dossier-relations` |
| Rechtspraak | `rechtspraak` | `rechtspraak` | `rechtspraak`, `rechtspraak-citations`, `rechtspraak-appeal`, `rechtspraak-conclusions`, `rechtspraak-referrals`, `rechtspraak-series` |
| EUR-Lex | `eurlex` | `eurlex` | `eurlex` |
| BWB | `bwb`, `bwb-history` (manual) | `bwb`, `bwb-history` | `bwb`, `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-implements`, `bwb-relation-types` |
| Staatsblad | `staatsblad` | `staatsblad` | `staatsblad` |
| Staatscourant | `staatscourant` | `staatscourant` | `staatscourant` |
| Eerste Kamer | `eerstekamer` | `eerstekamer` | `eerstekamer` |
| ECHR | `echr` | `echr` | `echr` |
| Verdragenbank | `verdragenbank` | `verdragenbank` | none |
| Wikidata | `wikidata` | `wikidata` | `tk-government` |
| The graph itself (`graph`) | none | none | `graph-list-stats` |

Clients (`clients/`) share `BaseClient`: base URL from `config/settings.py` (trailing
slash enforced), one `requests.Session`, 30 s timeout, and retry with exponential backoff
(5 tries, factor 2) on HTTP 429, 502, 503, 504 and connection errors. No source needs an API key.

Citation detectors resolve law abbreviations (`Sr`, `Sv`, `BW`) through
`instruments.props.short_title` and law names through instrument titles; `normalize bwb` writes `short_title` from the official
abbreviations in the BWB WTI files (see BWB below). A code split over books
(`CODE_FAMILIES` in `config/constants.py`: the Burgerlijk Wetboek, book 1 to 10 and 7A, each
its own BWB id) resolves through the book in the article number: `artikel 6:162 BW` cites
article `162` of book 6 (`BWBR0005289`, key `bwbr0005289_162`), whichever books are loaded, so a
citation of a book that is not loaded becomes a stub of that book, which its load fills; without
a book (`artikel 162 BW`) or with an unknown one there is no hit. The code of the family itself
(`BW`) is never a short title. A law that numbers `Hoofdstuk:artikel` in one regulation (the
Awb: `8:54`) is no family; its articles keep the colon.

A number with a leading zero (`047`) is no article number, and the letters of a number are
lower case (`36e`, `420bis`): in `artikel 82Sr` the `Sr` is the law. The linkers of running
text (`semantic tk`, `semantic rechtspraak`) resolve a cited article in one way
(`SemanticPipelineBase._cited_article`): the article with that number; else, of a law whose
articles are loaded, the historical article that last had the number (a repealed or
renumbered article cited by an older text: `bwbr0001854_248e_stam_…`), and no edge for a
number of a shape none of the law's articles has (`core.citations.number_shape`: digits as
`9`, letters as `a`; `140.1 Sr` is `9.9` while Sr has `9`, `9a` and `9a.9`: article 140, first
lid, written short), also when a stub of it exists; else a stub, when the
citation is sure enough (`tk` 0.85, `rechtspraak` 0.9).

## Tweede Kamer

**Provides.** OData v4 JSON API of the Gegevensmagazijn (`TK_API_BASE`): cases (Zaak),
documents, dossiers, activities, votes, commitments, committees, persons, factions.

**Retrieve.**

| Command | Fetches | Stored kinds |
|---------|---------|--------------|
| `retrieve tk` | Zaak modified since `--since` (default `1d`); `--mode full` since 1995-01-01; `--limit` caps the result for development | `tk-zaak` |
| `retrieve tk-dossiers` | Kamerstukdossier, Activiteit, Stemming, Toezegging, Commissie, Persoon, Fractie, FractieZetelPersoon, Document | `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-document` |
| `retrieve tk-content` | the XML of documents whose `kind` contains `--kind` (default `toelichting`; `""` every paper) of which none is stored; `--dry-run` | `tk-kamerstuk-xml`, `tk-kamerstuk-xml-missing` |
| `retrieve tk-dossiers --mode gaps` | the dossiers the graph names and lacks, each with its documents: those that the publications amending or bringing into force a version of an article name (`origin_publication.dossiers`, `commencement_publication.dossiers`) or a regulation or publication names (`dossier_numbers`), and the first reading that the memorandum of a second reading of a change in the Grondwet refers to ("Kamerstukken 35 418", `core/dossier_numbers.first_reading_dossiers`) | `tk-dossier`, `tk-document`, `tk-dossier-missing` |

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
  from the dossier the paper is `PART_OF` and its `sequence`, and stores the XML unchanged as
  `tk-kamerstuk-xml` under that identifier (`meta.document` is the key of the Document). The
  papers it fetches are those without such a record and without a `-missing` record that is
  still to wait (`lawgraph gaps` lists them). A paper the repository has no XML for (404)
  becomes a `-missing` record: for 30 days, or for 3 when the paper is a week old or younger
  (new papers are published as a PDF first and their XML follows within days). Error pages that
  answer 200 are not stored; 25 failures in a row fail the step. XML exists for papers from
  December 1994 on.

**Normalize `tk`.** Zaak to Case (`cases`, key = Zaak GUID; its `kind` is the `Soort`;
`dossier_numbers` kept for the dossier pipeline; `related_cases` the cases of
`GerelateerdNaar`, each with its `Soort` and dossiers, which `retrieve tk` expands with it so the
relation holds also when the other case was not retrieved). No edges: a case is linked once the
dossiers exist.

**Normalize `tk-content`.** Reads the `tk-kamerstuk-xml` records (`--since` filters on
`fetched_at`), turns each into text and sections with `core/kamerstuk_xml.py` and writes them
on the Document named by `meta.document`. A record whose Document does not exist yet, whose
XML cannot be read or that has no text is skipped and counted; run it after `normalize
tk-dossiers`. What it writes (`text`, `sections`, `footnotes`, `structure_quality`, `budget`,
...) is described in `docs/data-model.md`.

The parser handles both dialects of the XML (`kamerwrk`, 1995-2009, with flat `tuskop`
headings; `officiele-publicatie`, 2010 on, with nested `divisie/kop` and flat `tussenkop`).
The artikelsgewijs part is heading text only, so the parser reads it from the words of the
headings: an opener ("Artikelsgewijs", "Artikelsgewijze toelichting", "Artikelen"), then
article headings (`Artikel 3`, `Artikelen 3 en 4`, `Artikel II`, `Artikel 3:159n`,
`Artikel I, onderdeel B (artikel 1a)`), `onderdeel` and `lid` headings under them, until a
heading of the opener's level or a bijlage. Article numbers come from the grammar of
`core/citations.py`. On a corpus of 147 real papers a structure with an opener and articles
is found in about 70%, and article headings without an opener in another 5%.

**Normalize `tk-dossiers`.** Order: committees, members, factions, dossiers, activities,
commitments, documents, decisions; then edges; then a backfill of title, stages and opening
date onto each dossier (it needs the document edges).

| Step | Detail |
|------|--------|
| decisions | vote rows grouped by `Besluit_Id`; rows without one are skipped; `passed` from the `BesluitSoort` text, else the tally; the decided Zaak is the Besluit's own `Zaak` (`primary_case_id`, and its `Soort` as `primary_case_kind`; without it only an agenda item of one case names it: `AgendapuntZaakBesluitVolgorde` is the place of the Besluit on the agenda item, not of its Zaak), and `subject` prefers its subject over the agenda item; `date` is the day of the agenda item's Activiteit (the vote), else the `GewijzigdOp` of a row |
| factions | from the Fractie endpoint; without `tk-fractie` records they are derived from the `ActorFractie` strings of the votes; `aliases` map the differing abbreviations (`Fractie.Afkorting` versus `Stemming.ActorFractie`); TK reuses abbreviations, so the active or most recent record wins |
| committees | every Commissie with a name (`NaamNL`); a record without one is not written, so no id stands in for a name, and is written by the run after the source fills it in. The voortouw of every plenary activity is such a record: the Kamer itself |
| members | every Persoon, with `family_name` (`Achternaam`) and `birth_date` (`Geboortedatum`), by which `normalize wikidata` finds them; `party` and `faction_memberships` come from FractieZetelPersoon (dated), so a member without those records has no party |
| activities | `agenda_title` from `Onderwerp`, `status` as the source writes it (`Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; a planned activity may lie beyond the end of its dossier), `committee_id` from `Voortouwcommissie_Id` unless `Voortouwafkorting` is `TK`: a plenary activity has the Kamer as voortouw, not a committee |
| dossiers | `Nummer` plus `Toevoeging` form the key (`36554` and `36554-I` are distinct); `same_number_count` is recounted for every number the run writes (this pipeline is the only one that makes dossiers); `current_stage`, `stages_present`, `track_kind` and `title` (from a voorstel-van-wet or MvT document when the dossier has none) are derived from documents, activities and decisions by `core/dossier_stages.py` (an activity that did not take place, `Gepland`, `Geannuleerd`, `Verplaatst` or `Vervallen`, marks no stage), and `stages_missing`: the stages the bill passed to reach its current one without a dated document, activity or vote (the listed stages up to the current one, and those its track always passes: `wetsvoorstel`, `mvt`, `advies_rvs` of a bill, `wetsvoorstel` and `mvt` of a budget, `advies_rvs` of a treaty; and `stemming` for a bill or budget aangenomen or verworpen, of which an `Eindtekst` is evidence too; a stage known only from the kind of a case has no date), and `stages_complete` when there are none; `opened_on` is the date of the first document or activity. The record has no end: `Afgesloten` is false on every dossier and there is no closing date, so `closed`, `outcome` and `closed_on` are `semantic tk-dossier-outcomes`; a closed dossier (as stored) is at stage `afgehandeld` |
| documents | dossier numbers via Zaak to Kamerstukdossier, and the `Soort` of those Zaken as `case_kinds`; `DocumentActor` becomes `props.actors`; several dossiers per document are kept in `dossier_numbers`; `DocumentNummer` as `document_number`, from which the API makes the link to tweedekamer.nl (no link is stored) |

`dossier_numbers` of a case, document, activity or decision (and the keys of
`case_kinds_by_dossier`) are dossier labels: `37020-XV` for a budget chapter, `37020` for the
Miljoenennota itself, so each record links to the dossier node with that key.

Edges: `PART_OF` (Document to Case and Dossier, Case to Dossier), `ABOUT` (Activity, Decision
to Case and Dossier; Commitment to the dossiers of its activity), `LED_BY` (Activity to
Committee from `committee_id`; none for a plenary activity), `MADE_IN` (Commitment to Activity), `MEMBER_OF`
(dated, to committee and faction), `AUTHORED` (signatory to Document), `VOTED`.

**Semantic `tk`.** Reads `documents` labelled `TK`. Text is title, summary, body, text, the
footnotes and every string in `props.raw`, capped at 200,000 characters. Aliases come from the graph:
`instruments.props.short_title` (codes such as `Sr`) and instrument titles (see `semantic
rechtspraak` for the article forms). The qualifier of an article edge is read into `meta.leden`,
`meta.onderdelen` and `meta.aanhef` as on judgment edges; only the first citation of an article
in a document is kept.

| Pattern | Kind | Confidence |
|---------|------|-----------|
| `artikel 36e, derde lid, Sr` / `artikel 3 van de Wwft` / `artikel 3 van het <name>` | article | 0.95 |
| `artikel N van (de) Richtlijn / Verordening / (het) Besluit / Kaderbesluit YYYY/N` | article | 0.88 |
| `CELEX:<id>` | instrument | 0.90 |
| `BWBR...` id | instrument | 0.75 |
| `Richtlijn` or `Verordening YYYY/N` (CELEX derived) | instrument | 0.65 |
| an instrument's title or citation title appears | instrument | 0.60 |

Every hit becomes a `REFERS_TO` edge to the article or instrument; a missing article is resolved
as the Overview says (a stub from 0.85); instruments are never created. Edges
hold `raw_match`, `snippet`, `reason` (`bwb_article`, `celex_article`, `bwb_instrument`,
`celex_instrument`) and `qualifier`.

**Semantic `tk-amends` and `bwb-implements`.** One detector each:

| Relation | Detection | Confidence |
|----------|-----------|-----------|
| `AMENDS` (Document to Instrument, `voorgesteld`) | TK document title contains `wijziging van` and a known instrument title | 0.85 |
| `IMPLEMENTS` (Instrument to Instrument) | CELEX `3YYYY[CLRDF]NNNN` in the BWB XML of an instrument (`props.celex_refs`, kept by `normalize bwb`); both instruments must exist; naming the number is all the edge says (`meta.celex`), not that the regulation transposes the act | 0.75 |

**Semantic `tk-amendment-articles`.** Scans TK documents that have `props.text` (filled by
`normalize tk-content`) for amendment wording, for every BWB id the document is tied to (`props.bwb_id`,
else its `AMENDS` edges to instruments). Targets must exist. Every edge is written with status
`voorgesteld`.

| Wording | Relation | Confidence |
|---------|----------|-----------|
| `Artikel N ... wordt gewijzigd` | `AMENDS` | 0.90 |
| `Na artikel N wordt een artikel M ingevoegd` | `INTRODUCES` (article M) | 0.85 |
| `Artikel N ... komt te luiden` | `AMENDS` | 0.85 |
| `Artikel N ... vervalt` / `komt te vervallen` | `REPEALS` | 0.80 |
| `In artikel N ... wordt` | `AMENDS` | 0.80 |

**Semantic `tk-mvt`.** No text matching: the link is read from the graph. For every
document whose `kind` contains `toelichting`, one AQL pass walks
`Document -PART_OF-> Dossier <-LEGISLATED_IN- Instrument -AMENDS|INTRODUCES|REPEALS-> Article`
and writes `EXPLAINS` at confidence 0.5 (`DOSSIER_CONFIDENCE`: the memorandum explains the
change as a whole, each article is a candidate) to the `meta.article_version` of each change
edge, to the article itself when the edge names no version, and to the instrument when it
changed no articles at all. An edge that `tk-mvt-articles` has written is left alone.

**Semantic `tk-mvt-articles`.** The article-by-article part of a memorandum, per section
(`props.sections`, from `normalize tk-content`). Which article of which law a section is about
is read from its words (`core/mvt_articles.py`) and matched with what the dossier changed
(`Document -PART_OF-> Dossier <-LEGISLATED_IN- Instrument -AMENDS|INTRODUCES|REPEALS-> Article`).
`EXPLAINS` goes to the `meta.article_version` of the change edge, else to the article. Papers
with `budget`, with `structure_quality` `none`, and dossiers that legislated nothing are left
out; a section that names no article of a law the dossier changes has no edge of its own (the
dossier-level edges of `tk-mvt` stay). Only sections of kind `article`, `onderdeel` and `lid`
are read.

| `meta.match_type` | Section says | Confidence |
|-------------------|--------------|-----------|
| `heading_target` | the heading names the article: `Artikel I, onderdeel B (artikel 1a)`, `Onderdeel A (artikel 3 van de Woningwet)`; the law is the one named, else the nearest enclosing heading names one (`ARTIKEL II (Woningwet)`), else the only law the dossier changes | 0.90 |
| `body_named_law` | the text under the heading says `artikel N van de <Law>` for a law the dossier changes (title, citation title or short title) and the dossier changed that article | 0.85 |
| `own_number` | new law: the heading is `Artikel N` (Arabic, or `3:159n`) and the dossier made the law: its instrument is `LEGISLATED_IN` the dossier and no article of it was changed but to introduce it | 0.80 |
| `inferred_law` | an article number without its law, in the first 600 characters of the text under the heading (`artikel 2`), or an Arabic `Artikel N` heading in a bill that changes another law: of the law the nearest heading names, else of the only law the dossier changes; the dossier changed that article | 0.70 |

The confidences are constants (`core/mvt_articles.py`) and a first estimate: there is no set of
labelled sections to calibrate them against. A heading with several numbers (`Artikelen 3 en
4`) gives a reference per number. An `Artikel I` / `Onderdeel B` that names no article gives
nothing: attaching it to every article the dossier changed would only repeat the dossier-level
edges. `heading_target` and `own_number` also point at the article of the law when the dossier
has no change edge for it (an article of a law that is new, or whose history is not loaded);
the other two only at articles the dossier changed. Not detected: a new law whose numbering a
nota van wijziging shifted; articles of a treaty; a law the graph does not have or whose name
two laws share.

An edge is one per (document, target), so an article that several sections explain has one
edge, and it is the edge `tk-mvt` writes at dossier level: the same key, upgraded in place.
Its `confidence` is that of the surest section, `source` is `mvt-section-linker` and `meta`
holds `section_anchor`, `char_start`, `char_end`, `match_type` and `heading` of that section
and `sections`, every section that explains the article, in document order. The span of a
section is `text[char_start:char_end]`: the whole section for a heading match, the text before
its first subsection for a match in the body. The two pipelines can run in either order and any
number of times: `tk-mvt` skips the targets that `tk-mvt-articles` has an edge to.

**Semantic `tk-dossier-outcomes`.** Whether a dossier is closed, how it ended and on which day,
read from the graph (`core/dossier_stages.derive_outcome`); the first rule that holds wins:

| `outcome` | Evidence | `closed_on` |
|-----------|----------|-------------|
| `aangenomen` | an instrument is `LEGISLATED_IN` the dossier: the Staatsblad publication of its law, or a regulation whose BWB metadata names the dossier (`semantic bwb-amendments`) | the first `date_published` (else `date_signed`) of those publications; none when only a regulation names it |
| `ingetrokken` | a document of the dossier whose kind is a letter (`Brief regering`, `Brief lid / fractie`; not a committee's), whose `case_kinds` hold the bill's case (`Wetgeving`, `Initiatiefwetgeving`) and whose subject withdraws the bill ("Brief houdende intrekking van het wetsvoorstel", "... overname en intrekking van het voorstel"); not a request, an intention, a recall or a report about one | the date of the letter |
| `verworpen` | the last decision on the bill's own case (`primary_case_kind` `Wetgeving` or `Initiatiefwetgeving`, not an amendment or a motion) did not pass | the date of that vote |

Anything else is open (`closed: false`): a bill the Tweede Kamer passed still waits for the Eerste
Kamer and the Staatsblad, and a dossier without a bill (a budget chapter, a policy dossier) has no
end the graph can see. The Eerste Kamer votes are not loaded, so a bill it rejected stays open.
A closed dossier gets stage `afgehandeld` (`current_stage`, and last in `stages_present`); for a
dossier whose outcome changed the step recomputes its stages with the same rules as
`normalize tk-dossiers`, so `stages_complete` and `stages_missing` hold for it closed.

It walks every dossier on every run, since a law published today closes a dossier whose own
record did not change, and writes only the dossiers whose answer changed. It runs after
`bwb-amendments` and before `graph-list-stats`, which counts the open dossiers of a committee.

<a id="semantic-tk-dossier-relations"></a>
**Semantic `tk-dossier-relations`.** Edges between dossiers, which the Kamerstukdossier record
itself never names (`core/dossier_relations.py`). An edge is written only when both dossiers are
in the graph; the dossiers of one number need no edge (`GET /api/dossiers?number=`).

| Edge | Rule | In the source (24 Sep 2026) |
|------|------|-----------------------------|
| `RELATED_TO` | the Kamer's own statement: a case of dossier A relates to a case of dossier B (`Zaak.GerelateerdNaar`, read by `normalize tk`). `meta.cases` counts the pairs of cases, `meta.case_kinds` names their kinds. Cases within one dossier relate no dossiers | 80,544 related pairs of cases, of which 24,241 between dossiers of different numbers and 894 between two dossiers of one number: 10,571 pairs of dossiers. Mostly `Brief regering → Motie` (a letter that answers a motion filed elsewhere), then `→ Begroting` and `→ Wetgeving` |
| `REVISES` | a budget is "Vaststelling van de begrotingsstaten … voor het jaar Y" under a chapter or fund (`36800-XXII`). "Wijziging van de begrotingsstaten … voor het jaar Y" revises the budget of year Y with its own suffix; one with a number of its own (an incidental supplementary budget) names its chapter in its title ("(XIII)"; `IXB` falls back to `IX`), or else the budget by name, which must fit exactly one budget of the year. "Jaarverslag en slotwet … Y" revises the budget of year Y with its suffix. `meta.rule` is `begrotingswijziging` or `slotwet` | 1,529: 1,123 of 1,131 budget changes and 406 of 419 slotwetten; the rest (2007-2009) have no budget of their year in the source |
| `ACCOMPANIES` | "(wijziging samenhangende met de Voorjaarsnota)" of year Y goes with the dossier "Voorjaarsnota Y", likewise the Najaarsnota. The Miljoenennota of Prinsjesdag in year Y presents the budgets of Y + 1, so a change of year Y "samenhangende met de Miljoenennota" goes with the dossier "Nota over de toestand van ’s Rijks Financiën" whose number holds the budgets of Y + 1. `meta.nota` names it | 912: 412 Voorjaarsnota, 404 Najaarsnota, 96 Miljoenennota; 15 changes "samenhangende met" something else (an incidental supplementary budget, the refinancing of covid loans) get none |
| `SECOND_READING_OF` | a change in the Grondwet is made law in its second reading; the memorandum of the second reading speaks of the first reading and only refers to its papers ("Voor de toelichting verwijzen wij naar … (Kamerstukken 35 418, Kamerstukken II 2019/20, 35 419, nr. 9 …)"). Every dossier such a memorandum cites (`core/dossier_numbers.first_reading_dossiers`) is its first reading. `semantic tk-mvt` and `tk-mvt-articles` count the memoranda of the first reading with the second, so the first reading explains what the second made law | 35785 → 35418, 35419 |

So the route from Prinsjesdag 2026: the Miljoenennota `37020` and its budgets `37020-*` share a
number; each `37035-*` `ACCOMPANIES` `37020` and `REVISES` the budget of 2026 of its chapter
(`37035-XXII` → `36800-XXII`); the policy dossiers the Kamer relates to a budget (letters on its
motions) are `RELATED_TO` it. The Kamer relates none of the cases of `37035`; `37020` is
`RELATED_TO` from the dossiers whose letters answer the motions of the Algemene Politieke
Beschouwingen, which are filed under it (16 on 24 Sep 2026).

Checked by hand: `37035-XXII`, `-III`, `-IX`, `-M` → `36800` of the same suffix; `36038`
(incidental, IenW, no chapter in the title) → `35925-XII` by name; `35830-B` (slotwet
Gemeentefonds 2020) → `35300-B`; `36945-IX` (slotwet Financiën 2025) → `36600-IX`; `35975-XIV`
→ `Najaarsnota 2021`, `33280-IIB` → `Voorjaarsnota 2012`, `37035-*` → `37020`.

It reads every dossier and every related case on every run, since a dossier loaded today can be
the other end of a relation stated earlier. Like every semantic pipeline it only adds and updates
edges: an edge whose evidence is gone stays until the database is built again.

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
| `--ecli ECLI` (repeatable) | also fetch these judgments as they are (`--mode gaps` uses this for the cited judgments); skipped when stored in the last 24 hours |
| `--mode gaps` | the cited judgments that are stubs, and the decisions that asked the questions of a preliminary ruling without an `ANSWERS` edge: the index of the date the ruling names, of every court (60 to 450 judgments a day), is read once per date, and an entry whose title (`ECLI, court, dd-mm-yyyy, case numbers`) has a case number the ruling names is fetched |

Over the last two years the default courts hold about 33,000 judgments (Hoge Raad 4,100, Raad van
State 11,000, the four courts of appeal about 18,000), a few hours at the paced rate.
`retrieve all` reads the `--window` (a judgment is in it by decision date). Other courts, such as
the rechtbanken (over 100,000 in two years), are chosen with `--court`.

**Normalize.** From `rs-content` XML: RDF header (`creator` as `court`, `date`, `zaaknummer` as
`case_number` (and split, lower case and without spaces, as `case_number_keys`: `C/19/117301 /
HA ZA 16-256` is `c/19/117301/haza16-256`), `procedure` as `judgment_metadata.type`, `type`
(`Uitspraak` or `Conclusie`) as `judgment_metadata.document_type`, `subject`s, as
`conclusion_eclis` every `dcterms:relation` of `psi:type` …/conclusie (the conclusion of a
judgment, or the judgment of a conclusion), and as `related_eclis` the judgments of the earlier
instance it ruled on: the `ecli:resourceIdentifier` of every other `dcterms:relation` that is not
a later instance (`psi:aanleg` …/latereAanleg)), `inhoudsindicatie` as
`summary`, `uitspraak` as `text` and as `paragraphs` (the kop, heading, subheading, body; see the
paragraph props in the data model), and the parties its kop names as `parties` (data model,
Judgment). Every judgment normalized before `parties` existed gets them from a run of
`normalize rechtspraak` without `--since`; run `semantic rechtspraak` after it, since the kop is
one paragraph now and the `p-<n>` ids after it moved. The XML itself stays in the payload store. `court_code` is the ECLI court
segment; `tier` is the college that gave the judgment (`core/judgments.court_tier`, whose
tables `graph-list-stats` reads too), as the Rechtspraak sorts its instanties (the `Type` in its
waardelijst `/Waardelijst/Instanties`, kept as `tests/fixtures/rechtspraak_instanties.xml`):
`hoge_raad` (`HR`), `raad_van_state` (`RVS`), `centrale_raad_van_beroep` (`CRVB`),
`college_van_beroep_bedrijfsleven` (`CBB`), `parket` (`PHR`, the conclusions of the Parket bij de
Hoge Raad), `gerechtshof` (`GH*`), `rechtbank` (`RB*`), `kantongerecht` (`KTG*`, until 2002),
`tuchtcollege` (every disciplinary tribunal: `T*`, `IAR`), `ambtenarengerecht` (`AG*`),
`raad_van_beroep` (`RVB*`, until 1992), every other college under its own name
(`college_van_beroep_hoger_onderwijs`, `college_van_beroep_studiefinanciering`,
`tariefcommissie`, `raad_voor_strafrechtstoepassing_en_jeugdbescherming`,
`raad_van_arbitrage_in_bouwgeschillen`), the Caribbean part of the Kingdom
(`gemeenschappelijk_hof`, `gerecht_in_eerste_aanleg`, `gerecht_in_ambtenarenzaken`,
`raad_van_beroep_in_ambtenarenzaken`, `raad_van_beroep_voor_belastingzaken`,
`constitutioneel_hof`), and for the code `XX` (the courts outside the Rechtspraak) the court it names: `kroon` (`KB`, a
decision of the Crown on an appeal), `ehrm` (the European Court of Human Rights, also every ECHR
judgment of HUDOC), `hvj_eu` (the Court of Justice of the EU), `buitenlandse_instantie` for any
other. A code
no table knows has no tier: there is no catch-all, and a test holds every code of the waardelijst
to a named tier; `date_eff` is the judgment date.

The inhoudsindicatie is `summary` when it is Dutch. An English one (`core.judgments.is_english`:
at least three short English words such as "the", "and", "with", and more than twice as many as
Dutch ones; the XML says `lang="nl"` for both) is `summary_en`: it is the translation the
Rechtspraak publishes of a judgment under an ECLI of its own, with the case number followed by
a remark in brackets (`19/00135 (Engels)`, `(Engelse vertaling)`, `(English translation)`).
After the run each translation is linked to the judgment it translates (the same `court_code`,
`date_eff` and case number without the remark, one that has a `summary`): the translation gets
its Dutch `summary` and `translation_of`, the judgment the `summary_en`.

`decision_kind` is the first that tells of: the document type (`Conclusie`: `conclusie`), the
procedure (`Prejudiciële beslissing`: `prejudiciële beslissing`), the kop (its first line that
opens with `arrest`, `vonnis`, `beschikking` or `uitspraak`, also as `tussenvonnis`, `eindarrest`
and the like; not a label with its value, "Uitspraak : 10 augustus 2026", and a line with only a
date after the word, "Uitspraak van 21 september 2026", only when no other line names one), the
procedure again (`Beschikking`, `Tussenbeschikking`, `Raadkamer`, `Rekestprocedure`:
`beschikking`), and last the college (`core.judgments.KIND_OF_TIER`): `arrest` for the Hoge Raad,
a gerechtshof, the EHRM and the HvJ EU, `vonnis` for a rechtbank, a kantongerecht and a gerecht
in eerste aanleg, `uitspraak` for the Raad van State, the Centrale Raad van Beroep, the CBB,
every other administrative college and a tuchtcollege, `conclusie` for the Parket; a gerechtshof,
rechtbank or gerecht in eerste aanleg gives an `uitspraak` in administrative law (the first of
the `subjects` is `Bestuursrecht`, tax law too). The Kroon, a foreign court, the Gemeenschappelijk
Hof, the Constitutioneel Hof and the arbitration board have no default: null unless the metadata
or the kop tells.

`names` comes from `core/judgment_names.py`, a list of landmark cases kept by hand: the open data
carries no name for a judgment. Its RDF has no `dcterms:alternative` (none of 14,446 judgments
checked), its vindplaatsen (`dcterms:hasVersion`) are citations without a title ("NJ 1981/635
met annotatie van C.J.H. Brunner"), and an inhoudsindicatie names the precedent it applies as
readily as the judgment itself ("Uitleg. Haviltex." in a judgment of 2026). A name is added for
an ECLI checked against the judgment (court, date, inhoudsindicatie); an English translation
carries the name of the judgment it translates. `semantic graph-list-stats` gives a stub its
names and the kind of its tier.

**Semantic `rechtspraak`.** Reads the `paragraphs` of each judgment that `normalize rechtspraak`
made and extracts article citations from them, as one text ("artikel 3a van die wet" reaches
over a paragraph break; a citation that runs over one is dropped), with the detector of `tk`,
without its instrument-level title patterns: the EU forms and `CELEX`/`BWBR` literals are
kept. Every citation counts, not only the first of an article: each becomes a mention with
its paragraph and the span in that paragraph's text (`core/mentions.py`). The detector reads
the article first and resolves the law after it:

| Form | Confidence |
|------|-----------|
| `artikel 3.26, eerste lid, van de Wet ruimtelijke ordening` (code or full name; dotted, colon and lettered numbers; `lid`, `onder`, `sub`, `aanhef`, `volzin`) | 0.95 |
| `artikelen 338 (lid 2) en 339 Fw`, `artikelen 2 tot en met 5 Sv` | 0.95 each |
| `artikel 2.8 van de Wnb` after `... (hierna: de Wnb)` in the same text | 0.90 |
| `artikel 3a van die wet` (also `deze`, `genoemde`, `voornoemde`), the law named last within 3,000 characters | 0.70 |

Codes come from `instruments.props.short_title`, names from instrument titles; a title two
instruments share is not a name. A missing target article is resolved as the Overview says (a
stub from 0.9); an article cited only as `artikel N` with no law is not written.

One `REFERS_TO` edge per judgment and article, its `confidence` the strongest mention and
`meta.mentions` the mentions in reading order (`paragraph_id`, `paragraph_number`, `start`,
`end`, `raw_match`, `qualifier`, `leden`, `onderdelen`, `aanhef`, `snippet`, `confidence`),
`meta.mention_count` how many there are: an edge keeps the first 100 and counts the rest. The
lid, onderdelen and aanhef are read from the qualifier with `core/qualifiers.py`, as `semantic
bwb` and `semantic tk` do. Text of a judgment outside `uitspraak` (the `inhoudsindicatie`) is not
read. `--since` takes the judgments retrieved from then on.

**Semantic `rechtspraak-citations`.** `ECLI:<country>:<court>:<year>:<number>` in the XML of each judgment (from `raw_sources`):
`REFERS_TO`, 0.95, `meta.cited_ecli`, no self citations, missing judgments become stubs.

**Semantic `rechtspraak-appeal`.** Judgments with `related_eclis` whose `judgment_metadata.type`
contains `hoger beroep` or `cassatie`: `APPEAL_OF` from the appeal judgment to each related
ECLI, 0.95, `meta.procedure_type`; missing judgments become stubs.

**Semantic `rechtspraak-conclusions`.** `ADVISES_ON` from the conclusion of an
advocate-general to the judgment of its case. A judgment is a conclusion by its
`document_type` or its court (`PHR`). Pairs come from `conclusion_eclis` on either side
(`meta.basis` `formal_relation`, 1.0); a conclusion that no relation ties is paired with the
judgments of the court it advises (the Parket bij de Hoge Raad the Hoge Raad, any other court
itself) that share one of its `case_number_keys` (`case_number`, 0.9). A judgment named but not
loaded becomes a stub.

**Semantic `rechtspraak-referrals`.** `ANSWERS` from a preliminary ruling
(`judgment_metadata.type` `Prejudiciële beslissing`) to the decision that asked its questions:
its `related_eclis` (`formal_relation`, 1.0); without them, every one of its opening 40
paragraphs that says questions were asked (`prejudiciële vragen … gesteld`, `gestelde
rechtsvragen`; `core/judgments.read_referrals`), so a ruling that answers two courts names
two: the ECLIs it names, else the decision (not a conclusion) of the date it names with one
of its case numbers (`referral_text`, 0.9). The case numbers are read in the forms `in de
zaak <numbers> van <date>`, `van <date> met zaaknummer <number>`, `van <date>, in zaak nr.
<number>`, `bij beslissing van <date>, nummers <numbers>, gestelde` and, in older rulings,
`verwijst … naar het vonnis in de zaak <number> … van <date>` followed by `bij laatstgenoemd
vonnis`. Two case numbers are the same when they share a number of five digits or more,
else a roll number (`22/2463T`), else all their letters and digits
(`core/judgments.same_case_number`): `C/09/610280/ KG ZA 21/346` is `C-09-610280-KG ZA
21-346`, `200.273.775/01` is `200.273.775`. A ruling that names no case number (the Gerecht
in eerste aanleg of Aruba) or a decision that is not published stays unlinked. The referring
decision is found only when it is loaded; `retrieve rechtspraak --mode gaps` fetches it.

**Semantic `rechtspraak-series`.** Parallel cases: judgments of one court (`court_code`) on one
day (`date_eff`) with the same `document_type`, compared per court and day, one day in memory.
A text is its lower-case word 8-shingles, one in eight kept by CRC-32; two judgments are a pair
when they share no case number key, neither summary says `gerectificeerd` or `rectificatie`,
and the Jaccard of their shingles is at least 0.85, or 0.7 when both texts have 600 words or
more, or 0.5 (0.3 for two such long texts) when their summaries share at least 97% of their
words and the summary is not a template (the same summary on three dates or more: `kopje
volgt`, `HR: 81.1 RO.`). A series is the judgments that pairs connect: `series_id` (its lowest
ECLI) and `series_size` on each; a judgment in no series has both null. `--since` groups
only the days of the judgments retrieved from then on.

## EUR-Lex

**Provides.** EU acts as HTML by CELEX number. The site `eur-lex.europa.eu` answers automated
clients with HTTP 202 bot challenges, so the client uses the Publications Office CELLAR
server (`https://publications.europa.eu/resource/celex/<CELEX>`, content negotiation on
language, redirects followed, 60 s timeout). CELEX numbers are enumerated by SPARQL
(`EURLEX_SPARQL_ENDPOINT`, pages of 500). That endpoint is not a complete list: it has no
entry for many recent acts (about 150 directives for 2010, 1 for 2016; the GDPR is missing),
it answers HTTP 500 from offset 10000 (a failing page raises), and it holds no national
implementation measures. Acts are therefore fetched by the CELEX numbers that loaded records
refer to (`retrieve eurlex --mode gaps`, `expand-graph`), not by listing them.

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
| `retrieve bwb-history [ids...]` | every toestand of each id, or of all ids when none are given; stored `<bwb_id>@<start_date>`. Without it a law has no versions: `history`, `versions` and `articles/at` of the API are empty for it (the Wetboek van Strafrecht has 126 toestanden since 2002, the Awb 236) |

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
`(bwb_id, article number)`, or per `stam-id` for an article with a heading and no number (its
`label` is the heading), at its `position` in the toestand, with the article text (leden as `1. text`, list items on their
own lines, a paragraph next to the leden is included), the structured `references` with text
offsets, the `parts` of the article (aanhef, leden, onderdelen as offsets into that text, see
`docs/data-model.md`), and `stam_id`, `versie_id`, `valid_from`, `source_publication`,
`repealed`. Two
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
  toestand only repeats versions still valid), with `parts`, `origin_publication` and
  `commencement_publication`;
- `valid_until` and `current`, recomputed from the database in chunks of 200 regulations, so
  incremental runs stay correct: a version is `current` exactly when nothing follows it, also
  after a re-run has written it again;
- `VERSION_OF` from each ArticleVersion to its Article and from each InstrumentVersion to its
  Instrument;
- an Instrument if `normalize bwb` has not created it, and a historical Article for an identity
  that is not in the current toestand.

Run `normalize bwb` first.

**Semantic `bwb`.** `REFERS_TO` between articles, read from the XML rather than from the text:
only articles that carry `props.references` are scanned, and each reference naming a regulation
and an article becomes one edge with confidence 1.0, `meta` = `start`, `end`, `text`,
`reason = bwb_xml_ref`, `reference_kind` (`intref` or `extref`) and the `leden`, `onderdelen` and
`aanhef` the reference names. An edge is keyed by its two articles, so an article that refers
to another twice keeps the span of one; `props.references` keeps both. Self references are dropped and targets must exist — nothing is stubbed.
Articles are processed in chunks of 500 so one lookup resolves a whole chunk's targets.
`--store-citations` also writes the references onto the article as `props.citations`.

**Semantic `bwb-grondslagen`.** `BASED_ON` from a regulation to the article named in its
`Gelet op` paragraph, 1.0, `meta = {text, doc}`. Entries without an article, self references
and targets that are not in the graph are skipped. It reads `props.basis` of the regulations,
which `normalize bwb` keeps when it parses the toestand; no XML is read again.

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

**Semantic `bwb-annexes`.** Finds `bijlage <label>` in article texts and writes `SCOPED_BY`
(0.9 with a label, 0.7 without) with `meta.scope_type` `discretionary` when
ministerial-designation wording is near (`bij ministeriële regeling`, `Onze Minister
kan ...`), else `fixed`. The Annex nodes (`label`, `title`, `description` up to 2,000
characters, `entries` from `<li>` items, at most 200) and their `PART_OF` to the instrument
are made by `normalize bwb` from the toestand it parses; a reference to an annex that is not
there gets a stub.

**Semantic `bwb-relation-types`.** Sets `semantic_type` on article-to-article `REFERS_TO` edges
from the text around the reference (`meta.start`/`end`): a trigger phrase in the 40 characters before
the reference scores 0.9, elsewhere within 120 characters either side 0.7, no trigger gives
`cross_reference` at 0.5. Types and their patterns: `limiting_exception`,
`definitional_reference`, `conditional_requirement`, `prerequisite_procedure`,
`scope_limitation`, `delegated_discretion`, `cross_reference`, and writes only the
classifications that changed. The
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

## Wikidata

**Provides.** Every Dutch cabinet, and every post a person held in one: the statements `position held`
(P39) with the qualifier `parliamentary group / cabinet` (P5054) whose cabinet is an instance of
`Cabinet of the Netherlands` (Q2479200), with start (P580), end (P582), the name of the person
and their date of birth (P569, with its precision), in one SPARQL query to
`WIKIDATA_SPARQL`. The Tweede Kamer has no record of cabinet posts: `PersoonLoopbaan` is a
career the person reports, empty for most ministers, and a signed paper (`AUTHORED
meta.function`) names a function only on its own date. Wikidata is complete from the cabinets
of the 1970s (30 to 60 posts each); older cabinets have a few. About 400 people. A second query
reads the parties of those people (`member of political party`, P102, with its start and end
where Wikidata has them, and the party's founding and dissolution), a third every item that is a
`Cabinet of the Netherlands`: its name, start (the most precise of P580 and P571), end (of P582
and P576), each with its precision, head of government (P6) and the cabinet before it (P155).
57 cabinets; most before 1945 are dated to the year only, often without an end or predecessor.

**Retrieve.** One `wikidata-cabinet-posts-json` record per person (external id the Q-id:
`id`, `name`, `birth_date`, `birth_precision`, `posts` with `function`, `cabinet`, `from_date`,
`to_date` and their Q-ids, `parties` with `id`, `name`, `short`, `from_date`, `to_date`,
`founded`, `dissolved`), and one `wikidata-cabinet-json` record per cabinet (`id`, `name`,
`from_date`, `to_date`, `heads`, `previous`), in full on every run. An empty answer raises.

**Normalize.** Matches each person to one Tweede Kamer person (`core/government.py`):

- a member of parliament: the same date of birth (`members.props.birth_date`, from
  `Persoon.Geboortedatum`; by year when Wikidata knows only the year) and a word of the surname
  (`family_name`, `Persoon.Achternaam`; particles such as `van`, `de` do not count) among the
  words of the name. When the exact spelling finds nobody, `ij` and `y` agree (`Gruijters`,
  `Gruyters`); when the date finds nobody, a date that differs in one of year, month or day
  (the year by two at most) agrees if the first names start alike too.
- a minister or state secretary who never sat in parliament: the Tweede Kamer holds such a
  person without name or date of birth, known only by what they signed (`AUTHORED` with
  capacity `bewindspersoon`, the signed name in the document's `actors`). The person is the
  one whose surname is in the signed name and who held a post of the same kind (minister or
  state secretary) on a date they signed, or up to two weeks after it ended.

A person who matches no member or several, or a member two people match, is left out (and
logged). The member gets `wikidata_id`, `wikidata_name` and `government_functions` (the posts,
oldest first); a member no person matches any more loses them. A person no Tweede Kamer person
matches becomes a member of their own, key `wikidata_q<number>`, label `Wikidata`, with `name`,
`birth_date` (known to the day only) and the same three props; when a later run matches that
person to a Tweede Kamer person, the member of their own is removed, so one person is never
two members. Every record is read on every run. Needs `normalize tk-dossiers` (the members and
their signatures).

Every post also gets its normalised `post` (`minister-president`, `viceminister-president`,
`minister`, `minister_zonder_portefeuille`, `staatssecretaris`) and `ministry`, read from the
function by `core/ministries.classify_function`, and `cabinet_key`. The ministries are one
controlled list in `core/ministries.py` (`GET /api/ministries`), in protocol order: `az`, `bz`,
`jenv`, `bzk`, `ocw`, `fin`, `def`, `ienw`, `ez`, `kgg`, `lvvn`, `szw`, `vws`, `vro`, `aenm`;
a ministry that no longer exists under its name (`venw` Verkeer en Waterstaat, `vrom`, `justitie`,
`ezk`, ...) has its own key, a `successor` and the last day it had the name, and a later source
that writes the old name ("Binnenlandse Zaken" for BZK) is read as the successor. A minister
without portfolio ("minister voor …") and a state secretary belong to the ministry their post is
placed under, by the words of the portfolio (Klimaat en Energie `ezk`, Basis- en Voortgezet
Onderwijs `ocw`, Rechtsbescherming `jenv`, Herstel Groningen `bzk`); a name that names no
portfolio ("Nederlandse minister", the viceminister-president) has none.

Every cabinet becomes a node of `cabinets` (`core/cabinets.py`), key from its name
(`kabinet-Balkenende II (2003-2006)` is `kabinet-Balkenende II`, key `balkenende_ii`), with
`from_date`, `to_date`, their precision (`day`, `month`, `year`), `previous`, completed where
Wikidata leaves them open (`core/cabinets.complete_periods`): `previous` is the cabinet that
started before it when Wikidata names none; a cabinet without an end ended when the next one
started, so only the cabinet in office has none; a date known to the year only becomes the day
the neighbouring cabinet began or ended when that falls in the same year (a year between them
means a cabinet Wikidata lacks, such as Heemskerk 1883-1888, and the year stays).
`prime_minister` (the member who held the
post of minister-president in it, else its head of government) and `parties`: the parties at
least two of its members belonged to when their post began (a dated membership that holds that
day, or an undated one of a party that existed then; a member with several counts only for those
another member counts for; an independent is no party). Wikidata records no coalition, so a
member whose old party it records without dates can still bring that party in. Each party names
the `faction` with its name or abbreviation (`factions` lists their keys); a party from before the
Tweede Kamer data (KVP, ARP, CHU) has none. Each member gets an edge `SERVED_IN` to each cabinet
they held a post in, `meta.posts` the posts; the edges are derived in full on every run and one
no post supports any more is removed.

**Semantic `tk-government`.** Who in government made each commitment and brought each dossier
in (`pipelines/semantic/tk_government.py`). A commitment names its maker as the Tweede Kamer
writes it (`Herbert, H.G.`, `Minister van Economische Zaken`) on its date: the member is the one
who held a post of that kind that day and whose surname is in the name
(`core/government.match_signatory`), else none (`member_key` null); `post` and `ministry` come
from the role, `cabinet` is the cabinet in office that day (on a handover day the new one). A
dossier is brought in by whoever signed its earliest signed document first (`AUTHORED` role
`Eerste ondertekenaar`, capacity `bewindspersoon` or `kamerlid`, the document `PART_OF` the
dossier directly or through a case): a bewindspersoon gives it the `ministry` of their function
that day and `initiative: false`, a Kamerlid `initiative: true`; `cabinet` is the cabinet in
office then. Every commitment and dossier on every run; writes what changed. On lawgraph_small
192 of 195 commitments find their member.

## Ordering

`normalize all` and `semantic all` run in registry order; each row needs what is above it.

| Step | Needs |
|------|-------|
| normalize `bwb-history` | `normalize bwb` (articles and instruments) and stored `bwb-toestand-xml-all` |
| normalize `tk-dossiers` | `normalize tk` (the case-to-dossier links read `cases`) |
| normalize `wikidata` | `normalize tk-dossiers` (the members, with their date of birth) and `normalize tk` (the factions a party of a cabinet is matched to) |
| normalize `tk-content` | `normalize tk-dossiers` (it writes on the Documents that step made) and stored `tk-kamerstuk-xml` |
| retrieve `staatsblad` (from-graph) | `retrieve bwb` |
| semantic `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-relation-types` | normalized articles; `bwb-amendments` also `bwb-history` versions and the dossiers of `normalize tk-dossiers`; `bwb-relation-types` runs after `bwb` |
| semantic `tk-amendment-articles` | `tk-amends` (the document-to-instrument `AMENDS` edges), document text from `normalize tk-content` |
| semantic `tk-mvt` | `bwb-amendments` (`LEGISLATED_IN` and the change edges it walks), `normalize tk-dossiers` (the document-to-dossier `PART_OF` edges) and `tk-dossier-relations` (`SECOND_READING_OF`) |
| semantic `tk-mvt-articles` | as `tk-mvt`, and the sections of `normalize tk-content` |
| semantic `eerstekamer` | `normalize tk-dossiers` and `normalize eerstekamer` |
| semantic `tk-dossier-outcomes` | `bwb-amendments` (`LEGISLATED_IN`) and `normalize tk-dossiers` (documents, decisions and their edges to the dossier) |
| semantic `tk-government` | `normalize wikidata` (cabinets and posts), `normalize tk-dossiers` (commitments, documents, `AUTHORED` and `PART_OF` edges) |
| semantic `tk-dossier-relations` | `normalize tk` (`related_cases` of the cases), `normalize tk-dossiers` (the dossiers and their titles) and `normalize tk-content` (the text of the memoranda) |
| semantic `graph-list-stats` (last step of `semantic all`) | backfills what the list endpoints sort and filter on: instruments (`jurisdiction`, `article_count`, `kind`), judgments (`court_code`, `tier`, `date_eff`, `inbound_citation_count`; `decision_kind` where it is null, from the tier, and the curated `names` of a stub), articles (`inbound_citation_count`), committees (`active_dossier_count`, after `tk-dossier-outcomes`). `--instruments-only`, `--judgments-only`, `--articles-only` or `--committees-only` does one of them |
