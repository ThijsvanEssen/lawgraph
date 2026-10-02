# Pipelines

One section per source: what it provides, how it is retrieved, what normalize writes and
what the semantic pipelines detect. Confidence values are fixed in code unless noted.

## Overview

| Source | Retrieve | Normalize | Semantic |
|--------|----------|-----------|----------|
| Tweede Kamer | `tk`, `tk-dossiers`, `tk-content` | `tk`, `tk-dossiers`, `tk-content` | `tk`, `tk-amends`, `tk-amendment-articles`, `tk-mvt`, `tk-mvt-articles`, `tk-dossier-outcomes`, `tk-dossier-relations` |
| Rechtspraak | `rechtspraak`, `rechtspraak-instanties` | `rechtspraak` (`lawgraph courts build` reads the Instanties list) | `rechtspraak`, `rechtspraak-appeal`, `rechtspraak-conclusions`, `rechtspraak-referrals`, `rechtspraak-duplicates`, `rechtspraak-citations`, `rechtspraak-series` |
| EUR-Lex | `eurlex`, `eurlex-nim` | `eurlex` (`semantic bwb-implements` reads `eurlex-nim`) | `eurlex` |
| EUR-Lex | `eurlex` | `eurlex` | `eurlex` |
| BWB | `bwb`, `bwb-history` | `bwb`, `bwb-history` | `bwb`, `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-implements`, `bwb-relation-types` |
| Staatsblad | `staatsblad` | `staatsblad` | `staatsblad` |
| Staatscourant | `staatscourant`, `staatscourant-posts` | `staatscourant` (`normalize rijksoverheid` reads `staatscourant-posts`) | `staatscourant` |
| Eerste Kamer | `eerstekamer`, `eerstekamer-votes`, `eerstekamer-composition` | `eerstekamer`, `eerstekamer-votes`, `eerstekamer-composition` | `eerstekamer` |
| ECHR | `echr` | `echr` | `echr` |
| Verdragenbank | `verdragenbank` | `verdragenbank` | none |
| Rijksoverheid | `rijksoverheid` | `rijksoverheid` | `tk-government` |
| TOOI | `tooi` | none (`lawgraph ministries build`) | none |
| The graph itself (`graph`) | none | none | `graph-list-stats` |

Clients (`clients/`) share `BaseClient`: base URL from `config/settings.py` (trailing
slash enforced), one `requests.Session`, 30 s timeout, and retry with exponential backoff
(5 tries, factor 2) on HTTP 429, 502, 503, 504 and connection errors. No source needs an API key.

Citation detectors resolve law abbreviations (`Sr`, `Sv`, `BW`) through
`instruments.props.short_title` and `aliases` and law names through instrument titles;
`normalize bwb` writes both from the official abbreviations in the BWB WTI files (see BWB
below), `normalize eurlex` the short title of an EU act. `core/aliases.code_aliases` makes the
table. The sources rank: short titles, then the other abbreviations of the source (the WTI's),
then the curated ones; the first that has an abbreviation decides, and it is a law's only when
one law has it there (`WvSr` is the Wetboek van Strafrecht's, `BW` no single book's). An EU act
or treaty whose source gives no abbreviation gets one from
`src/lawgraph/data/curated/instrument_abbreviations.json` (`lawgraph curated set
instrument-abbreviations`: `AVG` for Verordening (EU) 2016/679), for an instrument in the graph
only; the EVRM is the BWB treaty `BWBV0001000`. The same table serves `/api/resolve`, the
search, and the instrument-level matches of `semantic tk`. A code split over books
(`src/lawgraph/data/code_families.json`, `core/code_families.CODE_FAMILIES`: the Burgerlijk
Wetboek, book 1 to 10 and 7A, each its own BWB id; see the code families under BWB) resolves through the book in the article number: `artikel 6:162 BW` cites
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
| `retrieve tk-dossiers` | Kamerstukdossier, Activiteit, Stemming, Besluit (`Stemmen - …` on a zaak `Wetgeving`, `Initiatiefwetgeving` or `Begroting`: also a hamerstuk, which has no Stemming; with the Stemming window and `--skip-decisions`), Toezegging, Commissie, Persoon, Fractie, FractieZetelPersoon, Document | `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-besluit`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-document` |
| `retrieve tk-content` | the XML of documents whose `kind` contains a `--kind` (repeatable; default `toelichting`, `motie`, `amendement`, `voorstel van wet` and `nota van wijziging`; `""` every paper), at the address of the dossier it is numbered in (`dossier_number`) of which none is stored, so a second run asks only for the new papers; `--dry-run` | `tk-kamerstuk-xml`, `tk-kamerstuk-xml-missing` |
| `retrieve tk-dossiers --mode gaps` | the dossiers the graph names and lacks, each with its documents: those that the publications amending or bringing into force a version of an article name (`origin_publication.dossiers`, `commencement_publication.dossiers`) or a regulation or publication names (`dossier_numbers`), the first reading that the memorandum of a second reading of a change in the Grondwet refers to ("Kamerstukken 35 418", `core/dossier_numbers.first_reading_dossiers`), and the dossiers a Tweede Kamer paper or case is part of (`dossier_numbers`); and the dossiers that lack a paper below the highest number the graph has of them (per suffix) | `tk-dossier`, `tk-document`, `tk-dossier-missing`, `tk-document-missing` (the Tweede Kamer has not all papers of that number either) |

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
relation holds also when the other case was not retrieved). A motie, an amendement, a letter
(`Brief …`), the report of a debate or visit (`Verslag van een …`, `Inbreng verslag …`), a list
of questions, a `Mededeling`, an `Overig` or the advice of another body is named by its
`Onderwerp` (`Motie van het lid … over …`, `Verzamelbrief opvang Oekraïne`): its `Titel` is the
title of its dossier. An `Onderwerp` that only repeats the kind names nothing (`core/tk_records.
is_named_by_subject`, `own_subject`); a bill and the papers on it keep their `Titel`, as their
`Onderwerp` is their kind (`Voorstel van wet`). No edges: a case is linked once the dossiers
exist.

A TK record the Kamer deleted (`Verwijderd`) holds its id and nothing else. `normalize tk` and
`normalize tk-dossiers` make nothing of it, and each normalizer removes, through one shared
`Deleted` (`pipelines/normalize/_tk_deleted.py`), what an earlier run made of it alone: the
node keyed by the record id (case, activity, commitment, document, committee, member), the node
that holds it in `props.external_id(s)` (a dossier, a faction: a faction goes when all its
records are deleted), or the edge that holds it in `meta.record_ids` (the `VOTED` edge of a
Stemming, the `MEMBER_OF` edge of a FractieZetelPersoon), each with the edges at a node that
goes. A deleted Stemming names no decision; its edge does, so a run `--since` also reads the
rows and the `tk-besluit` record of that decision. A decision whose Besluit is deleted (its
`tk-besluit` record, or the Besluit a row carries), or on which no live vote is left and no
`tk-besluit` record, goes with its edges; a decision that keeps votes gets its tally and `VOTED`
edges from its live rows alone, and one that keeps only its `tk-besluit` record stays without
votes.

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
commitments, documents, decisions; then edges; then a backfill of title, kind, phases and
opening date onto each dossier (it needs the document edges).

| Step | Detail |
|------|--------|
| decisions | vote rows grouped by `Besluit_Id`; rows without one are skipped; and the `tk-besluit` records, the decisions on a bill no vote row carries (a hamerstuk), without votes (an incremental run first reads the stored vote rows of the Besluiten of its window); `decision_kind` is the `BesluitSoort`; `passed` from it (`aangenomen`, `zonder stemming aannemen`: true; `verworpen`: false), else the tally, else null; `kind` the `Soort` of the decided Zaak; the decided Zaak is the Besluit's own `Zaak` (`primary_case_id`, and its `Soort` as `primary_case_kind`; without it only an agenda item of one case names it: `AgendapuntZaakBesluitVolgorde` is the place of the Besluit on the agenda item, not of its Zaak), and `subject` prefers its subject over the agenda item; `date` is the day of the agenda item's Activiteit (the vote), else the `GewijzigdOp` of a row |
| factions | from the Fractie endpoint; without `tk-fractie` records they are derived from the `ActorFractie` strings of the votes; `aliases` map the differing abbreviations (`Fractie.Afkorting` versus `Stemming.ActorFractie`); the records with one abbreviation are one faction (a faction that returns gets a new record, and the Kamer names the old one on a vote of today): one node, its props from the seated (else the latest changed) record, its period from the first start to the last end, reached by the id of every record. A decision whose faction votes name a Fractie the graph lacks is logged, as its votes then do not add up to its tally |
| committees | every Commissie with a name (`NaamNL`); a record without one is not written, so no id stands in for a name, and is written by the run after the source fills it in. The voortouw of every plenary activity is such a record: the Kamer itself |
| members | every Persoon, with `family_name` (`Achternaam`), `name_prefix` (`Tussenvoegsel`) and `birth_date` (`Geboortedatum`) (`normalize rijksoverheid` finds them by surname and date of birth); `party` and `faction_memberships` come from FractieZetelPersoon (dated), so a member without those records has no party: the Kamer keeps the seats of those who sat from 2002 (every seat from 30 November 2006), not of members of old or of the Eerste Kamer, and withholds a few |
| activities | `agenda_title` from `Onderwerp`, `status` as the source writes it (`Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; a planned activity may lie beyond the end of its dossier), `committee_id` from `Voortouwcommissie_Id` unless `Voortouwafkorting` is `TK`: a plenary activity has the Kamer as voortouw, not a committee; `replaced_by`: the numbers of the activities a moved one was replaced by (`VervangenDoor`, retrieved with the activity) |
| dossiers | `Nummer` plus `Toevoeging` form the key (`36554` and `36554-I` are distinct); `order` sorts them as the Kamer does; `same_number_count` is recounted for every number the run writes (this pipeline is the only one that makes dossiers); `kind`, `kind_basis`, `phases`, `current_phase` and `title` (from a voorstel-van-wet or MvT document when the dossier has none) are derived from its zaken, documents, activities and decisions by `core/dossier_stages.py`: the kind from the `Zaak.Soort` of its own zaken (those `PART_OF` it, those of its papers that belong to it alone, and those its activities roll up as `case_kinds`), the phases from the curated list `phases` (an activity that did not take place, `Gepland`, `Geannuleerd`, `Verplaatst` or `Vervallen`, marks no phase; a decision marks one only on a zaak of the bill) |
| documents | a paper named by its subject (as a case above: a motie, amendement, letter, report of a debate …) is named by its `Onderwerp` (else that of its Zaak) and keeps its `Titel`, the dossier's, as `dossier_title` (what `tk-amends` and the dossier title backfill read); dossier numbers via Zaak to Kamerstukdossier, and the `Soort` of those Zaken as `case_kinds`; `DocumentActor` becomes `props.actors`; several dossiers per document are kept in `dossier_numbers`; `DocumentNummer` as `document_number`, from which the API makes the link to tweedekamer.nl (no link is stored) |

`dossier_numbers` of a case, document, activity or decision (and the keys of
`case_kinds_by_dossier`) are dossier labels: `37020-XV` for a budget chapter, `37020` for the
Miljoenennota itself, so each record links to the dossier node with that key.

Edges: `PART_OF` (Document to Case and Dossier, Case to Dossier), `ABOUT` (Activity, Decision
to Case and Dossier; Commitment to the dossiers of its activity, or, when that activity was moved (`Verplaatst`) and kept no agenda, of the activity that replaced it: `replaced_by`), `LED_BY` (Activity to
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
| an abbreviation of an instrument, as written (`EVRM`, `AVG`, `Boek 7 BW`: short title, WTI abbreviations, curated; see the Overview), not as the law of an article citation (`art. 8 EVRM` cites the article) | instrument | 0.60 |

Every hit becomes a `REFERS_TO` edge to the article or instrument; a missing article is resolved
as the Overview says (a stub from 0.85); instruments are never created. Edges
hold `raw_match`, `snippet`, `reason` (`bwb_article`, `celex_article`, `bwb_instrument`,
`celex_instrument`) and `qualifier`.

**Semantic `tk-amends` and `bwb-implements`.** One detector each:

| Relation | Detection | Confidence |
|----------|-----------|-----------|
| `AMENDS` (Document to Instrument, `voorgesteld`) | an amendement, the text of a bill (`Voorstel van wet`, `Nota van wijziging`, `Nota van verbetering`, `Wijzigingen voorgesteld door de regering`, `Oorspronkelijke tekst`, `Bijgewerkte tekst`, `Eindtekst`) or its `Memorie van toelichting` (`core/tk_records.may_amend`) whose title (of an amendement: its `dossier_title`) contains `wijziging van` and a known instrument title; any other paper on the bill's dossier, a motie too, amends nothing. A document the step reads loses the `AMENDS` edges of the step it no longer gets | 0.85 |
| `IMPLEMENTS` (Instrument to Instrument) | an implementation source (`meta.bases`): EUR-Lex lists the publication as a national implementing measure of the act (`retrieve eurlex-nim`): from the publication when the graph has it, and from every regulation it enacted (`props.enacted_publication`) or made an article version of (`national_implementing_measure`, `meta.publications`); or the considerans of the regulation implements the act (`considerans`: "ter uitvoering van", "te implementeren", "om te zetten", the "Gelet op" of an order; an act cited in the title of the implemented one, up to its reference in the Official Journal, is not implemented; `props.implements_celex`, kept by `normalize bwb`). Not per article: a measure names no article, and what it changed may be more than the implementation. Both instruments must exist; the edges are derived in full on every run | 1.0 |
| `REFERS_TO` (Instrument to Instrument) | an EU act whose CELEX number the BWB XML of a regulation names (`props.celex_refs`) and that it does not implement (`meta.celex`) | 1.0 |

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
| `heading_target` | the heading names the article: `Artikel I, onderdeel B (artikel 1a)`, `Onderdeel A (artikel 3 van de Woningwet)`; the law is the one named, else the nearest enclosing heading names one (`ARTIKEL II (Woningwet)`), else the only law the dossier changes | 0.95; 0.3 when the dossier did not change the article |
| `body_named_law` | the text under the heading says `artikel N van de <Law>` for a law the dossier changes (title, citation title or short title) and the dossier changed that article | 0.65 |
| `own_number` | new law: the heading is `Artikel N` (Arabic, or `3:159n`) and the dossier made the law: its instrument is `LEGISLATED_IN` the dossier and no article of it was changed but to introduce it | 0.95 |
| `inferred_law` | an article number without its law, in the first 600 characters of the text under the heading (`artikel 2`), or an Arabic `Artikel N` heading in a bill that changes another law: of the law the nearest heading names, else of the only law the dossier changes; the dossier changed that article | 0.8 |

The confidences (`core/mvt_articles.py`) are the share a hand check of 10 edges per kind in
lawgraph_small found right. A change of the article by the dossier corroborates a match; a
heading that names an article the dossier did not change mostly names one of another law than
the one it is taken for (the heading says `Wft`, the dossier changes Boek 2 BW). What a match
rests on is `match_type`, `changed` (whether the dossier changed the article) and
`explanation`, in Dutch ("De kop 'Onderdeel A (artikel 247)' noemt het artikel; het dossier
wijzigt het artikel."). A heading with several numbers (`Artikelen 3 en
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
holds `section_anchor`, `char_start`, `char_end`, `match_type`, `changed`, `explanation` and
`heading` of that section and `sections`, every section that explains the article (each with
its `confidence`, `changed` and `explanation`), in document order. The span of a
section is `text[char_start:char_end]`: the whole section for a heading match, the text before
its first subsection for a match in the body. The two pipelines can run in either order and any
number of times: `tk-mvt` skips the targets that `tk-mvt-articles` has an edge to.

**Semantic `tk-dossier-outcomes`.** Whether a dossier is closed, how it ended and on which day,
read from the graph (`core/dossier_stages.derive_outcome`); the first rule that holds wins:

| `outcome` | Evidence | `closed_on` |
|-----------|----------|-------------|
| `aangenomen` | an instrument is `LEGISLATED_IN` the dossier: the Staatsblad publication of its law, or a regulation whose BWB metadata names the dossier (`semantic bwb-amendments`) | the first `date_published` (else `date_signed`) of those publications; none when only a regulation names it |
| `verworpen`, `aangenomen` | its outcome in the Eerste Kamer (`ek_outcome`, below) | the day of that vote |
| `verworpen` | the last vote of the Tweede Kamer on the bill's own case (`primary_case_kind` `Wetgeving`, `Initiatiefwetgeving` or `Begroting`, not an amendment or a motion) did not pass | the date of that vote |

Anything else is open (`closed: false`): a bill the Tweede Kamer passed that the Eerste Kamer has
not voted on, and a dossier without a bill (a budget chapter, a policy dossier), which has no end
the graph can see. No record of the Kamer says a bill was withdrawn (its zaak keeps `Status` `Vrijgegeven`; only a
free text now and then says so), so a withdrawn bill stays open too.

Next to the outcome it writes `tk_decision`: the last decision on the bill's own case with a
`BesluitSoort`, as the Kamer writes it (`Stemmen - aangenomen`, `Stemmen - zonder stemming
aannemen` for a hamerstuk, `Stemmen - uitstellen`, …), with its `BesluitTekst` and date; and
`ek_outcome` (`core/dossier_stages.ek_outcome`): `Verworpen` when the list of rejected bills
names the bill (`ek_rejected`), with the vote `Verworpen` of that day as its vote (else the list
as its source); otherwise `Aangenomen` by its latest vote `Aangenomen`; none when neither (a
bill with only a motion voted down). `{outcome, date, method, source_url, retrieved_on}`, as the
Kamer writes them. The vote chosen gets `bill_decision: true` and `kind`, the kind of the
dossier (the list of the Eerste Kamer names none); the other votes of the Eerste Kamer about
the dossier `bill_decision: false` and no `kind`.

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

**Retrieve.** The index is read in pages of 1,000, of every court or filtered by court
(`creator`, an OWMS term; several are OR), by decision date (`date`, twice for a range) and,
for a `--since` up to 60 days back, also by when a judgment was published or changed
(`modified`), which finds one published long after its decision. Further back `modified` is no
filter: the Rechtspraak republished nearly its whole corpus. For each judgment of the index one `rs-content` record is stored, as soon as it is
downloaded. A judgment that is stored and was fetched after its last change (`updated` in the
index) is skipped, so a re-run or a resumed run only downloads the rest.

| Option | Meaning |
|--------|---------|
| `--court NAME` (repeatable) | `all` (every court of the index: the rechtbanken, the special courts and the courts that no longer exist too), an ECLI court code (`HR`, `RVS`, `GHAMS`, any case), or a tier of the court table (`gerechtshof`: every court of appeal, the older ones too; `rechtbank`, ...). The court table gives each court its OWMS term, the `creator` the index is filtered by (`owms_term` of `data/courts.json`, from the `Identifier` of the Instanties list); a court without one (the courts before ECLI, `XX`) cannot be asked for. Default: `all`; none when only `--ecli` is given |
| `--mode incremental` (default) | judgments decided from `--since` (default `1d`) minus 30 days, because judgments are published up to weeks after the decision |
| `--mode full` | no date filter: every judgment of the courts (928,955 of every court on 2026-09-29) |
| `--ecli ECLI` (repeatable) | also fetch these judgments as they are (`--mode gaps` uses this for the cited judgments); skipped when stored in the last 24 hours |
| `--mode gaps` | the cited judgments that are stubs, and the decisions that asked the questions of a preliminary ruling without an `ANSWERS` edge: the index of the date the ruling names, of every court (60 to 450 judgments a day), is read once per date, and an entry whose title (`ECLI, court, dd-mm-yyyy, case numbers`) has a case number the ruling names is fetched |

Over the last two years the index holds 160,718 judgments of every court (Hoge Raad 4,100,
Raad van State 11,000, the four courts of appeal about 18,000, the rechtbanken most of the
rest), about 5.5 hours at the paced rate (`docs/operations.md`, slow steps). `retrieve all`
reads the `--window` (a judgment is in it by decision date).

**Normalize.** From `rs-content` XML: RDF header (`creator` as `court`, `date`, `zaaknummer` as
`case_number` (and split, lower case and without spaces, as `case_number_keys`: `C/19/117301 /
HA ZA 16-256` is `c/19/117301/haza16-256`), `procedure` as `judgment_metadata.type`, `type`
(`Uitspraak` or `Conclusie`) as `judgment_metadata.document_type`, `subject`s, as
`conclusion_eclis` every `dcterms:relation` of `psi:type` …/conclusie (the conclusion of a
judgment, or the judgment of a conclusion), and as `related_eclis` the judgments of the earlier
instance it ruled on: the `ecli:resourceIdentifier` of every other `dcterms:relation` that is not
a later instance (`psi:aanleg` …/latereAanleg)), `inhoudsindicatie` as
`summary`, `uitspraak` (of a conclusion: `conclusie`) as `text` and as `paragraphs` (the kop,
heading, subheading, body; see the paragraph props in the data model), `isReplacedBy` (an ECLI)
as `replaced_by`, the parties its kop names as `parties`, and of a conclusion the
advocate-general its opening lines name as `advocate_general` (data model, Judgment). Every judgment normalized before `parties` existed gets them from a run of
`normalize rechtspraak` without `--since`; run `semantic rechtspraak` after it, since the kop is
one paragraph now. The XML itself stays in the payload store. `court_code` is the ECLI court
segment. The court table (`src/lawgraph/data/courts.json`, `core/courts.court_of`, whose table
`graph-list-stats` reads too; see [Courts](#courts)) gives a judgment two levels: `tier`, the
`Type` of its court in the Instanties value list of the Rechtspraak, and `court_kind`, the kind
of court within it. The tiers: `hoge_raad` (`HR`), `raad_van_state` (`RVS`),
`centrale_raad_van_beroep` (`CRVB`), `college_van_beroep_bedrijfsleven` (`CBB`), `parket`
(`PHR`, the conclusions of the Parket bij de Hoge Raad), `gerechtshof`, `rechtbank`,
`kantongerecht` (until 2002), `tuchtcollege` (every disciplinary tribunal), `andere_instantie`
(the ambtenarengerechten, the raden van beroep until 1992, the College van Beroep voor het hoger
onderwijs, the Tariefcommissie, …), `koninkrijksinstantie` (the courts of Aruba, Curaçao, Sint
Maarten and the BES islands), `buitenlandse_instantie` (code `XX`, a court outside the
Rechtspraak), and from the curated courts `kroon` (`XX` named `KB`, a decision of the Crown on
an appeal), `hvj_eu` (the Court of Justice of the EU) and `ehrm` (the European Court of Human
Rights, also every ECHR judgment of HUDOC). A code the table does not know has no tier and no
kind: there is no catch-all, and a test holds every code of the value list to a tier and a kind;
`date_eff` is the judgment date.

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
opens with `arrest`, `vonnis`, `beschikking`, `uitspraak` or `beslissing van`, also as `tussenvonnis`, `eindarrest`
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

`names` comes from `src/lawgraph/data/curated/judgment_names.json` (`core/judgment_names.py`;
`lawgraph curated set judgment-names`), a list of landmark cases kept by hand: the open data
carries no name for a judgment. Its RDF has no `dcterms:alternative` (none of 14,446 judgments
checked), its vindplaatsen (`dcterms:hasVersion`) are citations without a title ("NJ 1981/635
met annotatie van C.J.H. Brunner"), and an inhoudsindicatie names the precedent it applies as
readily as the judgment itself ("Uitleg. Haviltex." in a judgment of 2026). A name is added for
an ECLI checked against the judgment (court, date, inhoudsindicatie); an English translation
carries the name of the judgment it translates. `semantic graph-list-stats` gives a stub its
names and the kind of its kind of court.

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
| `artikel 2.8 van de Wnb` after `... (hierna: de Wnb)`, `(verder: Wnb)` or `(Wnb)` in the same text | 0.90 |
| `artikel 3a van die wet` (also `deze`, `genoemde`, `voornoemde`), the law named last within 3,000 characters | 0.70 |

Codes come from `instruments.props.short_title` and `aliases` (see the Overview), names from
instrument titles; a title two instruments share is not a name. A missing target article is
resolved as the Overview says (a stub from 0.9); an article cited only as `artikel N` with no
law is not written.

A citation of a law the graph does not have (`art. 392 Rv` before the Rv is loaded) has no
article to point at: the judgment keeps it in `props.unresolved_citations`, one per law and
article in reading order, at most 100: `law` as written, `article_number`, `raw_match` and
`qualifier` of the first citation, its `leden`, `onderdelen`, `aanhef`, `paragraph_ids` and
`mention_count`; null when there is none, written only when it changed. Such a law is an
abbreviation (`Rv`, `RO`, `AWR`, `Vw 2000`) or a name of one word (`Opiumwet`,
`Huisvestingswet 2014`) after the article; a name of several words (`Wet op de rechterlijke
organisatie`) is not read, nor a word that starts a sentence (`Onze Minister`). A short name the
text gives such a law (`artikel 4.16 van de Aanbestedingswet (Aw)`, also `hierna:` or `verder:`)
is that law further on in the same text: `artikel 4.16 Aw` counts for `Aanbestedingswet` 4.16,
one entry. The article number stays as written (`2:163c Aw` where the court means 2.163c). Once
the law is loaded, the next run links the citation and drops it from the list.

One `REFERS_TO` edge per judgment and article, its `confidence` the strongest mention and
`meta.mentions` the mentions in reading order (`paragraph_id`, `paragraph_number`, `start`,
`end`, `raw_match`, `qualifier`, `leden`, `onderdelen`, `aanhef`, `snippet`, `confidence`),
`meta.mention_count` how many there are: an edge keeps the first 100 and counts the rest. The
lid, onderdelen and aanhef are read from the qualifier with `core/qualifiers.py`, as `semantic
bwb` and `semantic tk` do. Text of a judgment outside its `paragraphs` (the `inhoudsindicatie`)
is not read. The edges of a judgment are derived in full each time it is read: one its text no
longer makes goes. `--since` takes the judgments retrieved from then on.

**Semantic `rechtspraak-citations`.** `ECLI:<country>:<court>:<year>:<number>` in the text of
each judgment, the `<uitspraak>` and `<conclusie>` the court or advocate-general wrote (from
`raw_sources`; `core/judgments.body_text`), never in its metadata: the `dcterms:relation` of the
metadata names the earlier instance and the conclusion, which are `APPEAL_OF` and `ADVISES_ON`
of their own steps, not citations. `REFERS_TO`, 0.95, `meta.cited_ecli`, no self citations,
missing judgments become stubs. The ECLIs are read by `core/ecli.cited_eclis`: one is valid when
its country issues ECLIs, its court code has the shape of one (letters for a Dutch court; whether
the court exists is not checked), its year lies between 1900 and the current year and its number
has the shape of one (Dutch: a number or an LJN). What the text shows is repaired: an LJN whose
digits it sets apart (`BH 2815`, `BH:4033`), NL and the court swapped, a range (`2018:2374-2375`)
as its members, a word or the next ECLI glued to the number, a zero or one typed for a letter of
an LJN (`A09006`). The rest is dropped and makes no stub; `_resolve_eclis` makes no stub of a
malformed ECLI for any step. The citations of a judgment are derived in full each time it is
read: an edge of this step its text no longer names is removed, and then every stub judgment no
edge reaches or leaves. No `REFERS_TO` is written between two judgments that `APPEAL_OF`,
`CONTINUES`, `REFERRED_BY`, `ADVISES_ON` or `ANSWERS` tie (either way): a Hoge Raad ruling that
names the arrest under cassation and the conclusion in a footnote does not cite them. It runs
after the steps that make those edges. `semantic graph-list-stats` recounts
`inbound_citation_count` and `outbound_citation_count` after it.

**Semantic `rechtspraak-duplicates`.** The Rechtspraak published many old arresten again under a
new ECLI (HR:1985:BH3435, BV4163 and BV4180 are AW8335); the old publication has no text and its
`dcterms:isReplacedBy` (`replaced_by`) names the new one. That is the signal, not the court, date
and case number: a republication may carry another date or number, or the code of another
court. A publication whose replacing one is loaded (followed to the last that is) gets
`SAME_AS` to it and `same_as`, its ECLI; `/api/judgments` leaves it out and `graph-list-stats`
counts its citations with the one kept. One whose replacing publication is not loaded stands
alone. Derived in full each run.

**Semantic `rechtspraak-appeal`.** Judgments whose `judgment_metadata.type` contains `hoger
beroep`, `cassatie` or `verwijzing` (`core/appeals.py`). To each of their `related_eclis`
(`meta.basis` `formal_relation`, 0.95, `meta.procedure_type`): `CONTINUES` when it is of the
same court with a case number the two share (an interim judgment, then the final one);
`REFERRED_BY` when it is a ruling of the Hoge Raad and the judgment is of another court (the
decision after referral), no edge when that ruling is a preliminary ruling the court asked for;
no edge to a conclusion or to a judgment given later; `APPEAL_OF` otherwise. An appeal without
`related_eclis` is read for the decision it appeals, in its first 12 paragraphs: `tegen
de/het/een uitspraak|vonnis|beschikking|beslissing|arrest van <court> van <date>`, optionally
followed by `in zaak nr.`, `nummer`, `onder parketnummer`, `met zaaknummer`, `kenmerk` and the
case number, where `<court>` names a court (not an administrative body). The decision of that
date with that case number (`core.judgments.same_case_number`) gets `APPEAL_OF` (`appeal_text`,
0.9); one not loaded is written to `unresolved_appeal_targets` (`court`, `date`,
`case_number`) of the appeal. Missing judgments become stubs. The edges of a judgment read are
derived in full: one no longer derived is removed.

**Semantic `rechtspraak-conclusions`.** `ADVISES_ON` from the conclusion of an
advocate-general to the judgment of its case, one way only. A judgment is a conclusion by its
`document_type` or its court (`PHR`). Pairs come from `conclusion_eclis` on either side
(`meta.basis` `formal_relation`, 1.0), except where a judgment names as its conclusion a loaded
judgment that is no conclusion; a conclusion that no relation ties is paired with the
judgments of the court it advises (the Parket bij de Hoge Raad the Hoge Raad, any other court
itself) that share one of its `case_number_keys` (`case_number`, 0.9). A court that advises
itself asks for the conclusion under a number of its own (the staatsraad advocaat-generaal of
the Raad van State: conclusion `201406676/2/A3`, judgment `201406676/1/A3`): such a conclusion
without a pair goes to the decisions of its court of the three years after it that share its
dossier number (`same_case_number`; `case_number`). A judgment named but not loaded becomes a
stub; an edge no longer derived is removed.

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
and the Jaccard of their shingles is at least 0.85, or 0.5 when both texts have 600 words or
more (each long parallel case tells its own facts and parties), or 0.5 (0.3 for two such long
texts) when their summaries share at least 97% of their words and the summary is not a
template (the same summary on three dates or more: `kopje volgt`, `HR: 81.1 RO.`). A series is the judgments that pairs connect: `series_id` (its lowest
ECLI) and `series_size` on each; a judgment in no series has both null. `--since` groups
only the days of the judgments retrieved from then on.

## EUR-Lex

**Provides.** EU acts as HTML by CELEX number. The site `eur-lex.europa.eu` answers automated
clients with HTTP 202 bot challenges, so the client uses the Publications Office CELLAR
server (`https://publications.europa.eu/resource/celex/<CELEX>`, content negotiation on
language, redirects followed, 60 s timeout). CELEX numbers are enumerated by SPARQL
(`EURLEX_SPARQL_ENDPOINT`, pages of 500). That endpoint is not a complete list: it has no
entry for many recent acts (about 150 directives for 2010, 1 for 2016; the GDPR is missing),
and it answers HTTP 500 from offset 10000 (a failing page raises). Acts are therefore
fetched by the CELEX numbers that loaded records refer to (`retrieve eurlex --mode gaps`,
`expand-graph`), not by listing them.

**Retrieve `--mode`.**

| Mode | CELEX numbers fetched |
|------|-----------------------|
| `incremental` (default) | those of instruments already in the graph, or `--celex` (repeatable) |
| `full` | the directives SPARQL lists, without corrigenda; `--type` (repeatable: `directive`, `regulation`, `decision`) chooses other types, at most 10000 per type. Not part of `retrieve all` |
| `nim` | the acts that have national implementing measures of `--country` (default `NLD`) |
| `cjeu` | judgments that cite acts in the graph |
| `com` | Commission proposals for acts in the graph |

`--lang` (default `NL`). Stored as `eu-celex-html` while the acts are fetched. An act
without an HTML text (HTTP 404, in every language: old regulations and every corrigendum)
counts as skipped, not as an error.

**Normalize.** Instrument per CELEX (`jurisdiction: eu`). Its names come from the printed
title (`core/eu_titles.py`): the `doc-ti` paragraphs, or the `DC.description` of a page of
the old format. `citation_title` follows the rules of the Official Journal: from 2015
`Verordening (EU) 2016/679`, `Richtlijn (EU) 2019/1937`; before, a regulation `Verordening
(EEG) nr. 295/91` and any other act `Richtlijn 95/46/EG`, with two digits for a year before
1999; the domain is that of the day of adoption in the title (`EEG` before 1 November 1993,
`EG` before 1 December 2009, `EU` after; `JBZ` for a framework decision), the word before
the number the one the title starts with (`Beschikking`, `Tweede Richtlijn`). A title in
capitals is written with the citation title (`Verordening (EU) 2022/868 van het Europees
Parlement en de Raad van 30 mei 2022 betreffende …`); a closing note between brackets
(`(Voor de EER relevante tekst)`) is left out; a name between brackets that ends the title
and names the kind of act is `short_title` (`Datagovernanceverordening`). `display_name` is
the citation title. Articles are read from the structure of the HTML
(`core/eurlex_html.py`), in either format CELLAR serves:

- the Official Journal format (acts from about 2004): an article is the `oj-ti-art` title
  ("Artikel 1") with what follows it up to the next title; its heading is the `oj-sti-art`
  paragraph. A lid is a paragraph that starts with its number ("1.   Deze verordening
  bevat:"), or the lid container (`div id="004.002"`) laid out as one row numbered like the
  lid; a point is a table row of a marker cell ("a)", "1)", "i)", "—") and a text cell, and a
  table in the text cell holds the points inside it. A title inside a table cell is an
  article that an amendment quotes: it stays text of the amending article. The divisions
  of an article are the `div` elements around it that open with an `oj-ti-section-1` label
  (`HOOFDSTUK III`, `Afdeling 1`), titled by their `oj-ti-section-2` paragraph;
- the old format (older acts, flat `<p>` paragraphs): an article starts at a paragraph that is
  only "Artikel N" and ends at the next one, at a division heading (`HOOFDSTUK II`,
  `TITEL II`, `Afdeling 1: …`, `BIJLAGE`), at a heading in capitals right before an
  article (`SLOTBEPALINGEN`) or at the closing formula ("Gedaan te …"). A division heading
  has its title after its label or in the next paragraph; a kind of division that is open
  ends at the next of its kind, another kind nests in it; a heading in capitals without a
  label stands at the top level. A short paragraph right
  after the number that does not end in `.`, `:`, `;` or `,` is the heading. Leden and points
  are read from the marker a paragraph starts with (also spaced: `a )`, `1 .`); a marker
  kind that is not yet open nests in the point before it (a dash under `a)`), one that is
  open returns to its level, and `i)` after `h)` is a letter. A paragraph without a marker
  continues the part before it.

The text and parts are built as for BWB (see [data model](data-model.md), "Article and
versions"): no empty lines, the heading not in the text. A number is taken once per act, and an
article without text is not written. `position` is its place in the act, `breadcrumb` its
divisions (`type` `hoofdstuk`, `label` `Hoofdstuk III`, `title`). `PART_OF` from article to instrument.

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
| `retrieve bwb-history [ids...]` | every toestand of each id, or of every regulation of which the current toestand is stored when none are given, that is not stored yet (`--mode full`: every one again); stored `<bwb_id>@<start_date>`, a file the repository does not serve as `bwb-toestand-xml-all-missing`. From 150 regulations the toestanden come from the SRU listing, below that from one SRU query per regulation. It is part of `retrieve all`, after `bwb`; it gives a law its versions: `history`, `versions` and `articles/at` of the API (the Wetboek van Strafrecht has 126 toestanden since 2002, the Awb 236) |

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
(citeertitel, else intitule), `kind` (`wetgeving@soort`), `date_signed`, `date_published` and
`date_in_force` of the regulation as enacted (the `oorspronkelijk` publication and the
`inwerkingtreding.datum` in the `meta-data` of the `<intitule>`; null when it does not say
them), `dossier_numbers` of that enacting publication (the `meta-data` of `<wetgeving>`
names the last change to the structure of the law, not the law), `version_date_in_force`
(the start of the toestand). One Article per
`(bwb_id, article number)`, or per `stam-id` for an article with a heading and no number (its
`label` is the heading), with its `heading` (the `<titel>` of its `<kop>`, numbered or not) and
its `breadcrumb`, at its `position` in the toestand, with the article text (leden as `1. text`, list items on their
own lines, a paragraph next to the leden is included), the structured `references` with text
offsets, the `parts` of the article (aanhef, leden, onderdelen as offsets into that text, see
`docs/data-model.md`), and `stam_id`, `versie_id`, `valid_from`, `source_publication`,
`repealed`. Two
articles of one regulation with the same number share a key. `PART_OF` (article to
instrument).

After the nodes, `normalize bwb` sets `short_title` on existing instruments from the stored
WTI records (`core/bwb_wti.py`). A regulation can have several abbreviations, listed
alphabetically by the source, so their order means nothing. The rule:

1. Case is ignored (`GW` and `Gw` are one abbreviation). The spelling kept is the one a
   citation writes, a capital and then lower case (`Gw`), else the first.
2. An abbreviation that several loaded regulations claim never wins: every book of the
   Burgerlijk Wetboek lists `BW`, and a short title must lead to one regulation.
3. Of the rest the shortest wins (`Sr` over `WvS` and `WvSr`, `WVW` over `WVW 1994`, `BW1`
   over `BW Boek 1`); of equal lengths the citation form, then the source order.
4. A regulation left with nothing has no `short_title`; one it had is removed.

Rule 2 depends on the other regulations, so every WTI record is read on every run, whatever
`--since` is, and a short title can change when more regulations are loaded. `BW` itself is
nobody's short title; the books are `BW1`, `BW2`, ... and a book is only citable once its WTI
record is loaded.

In the same pass it sets `aliases`, the names the search finds an instrument by
(`core/bwb_wti.py` `instrument_aliases`): every WTI abbreviation, shared ones included, and
for each book of a code in `CODE_FAMILIES` the forms `Boek 6 BW`, `6 BW`, `BW 6`, `BW6`,
`BW Boek 6` and `BW`, also when its WTI record is missing. Instruments that do not exist are
not created.

**The code families.** `lawgraph code-families build` makes `src/lawgraph/data/code_families.json`
from the stored WTI records (`core/code_families.families_from_wti`) and prints what changed;
`lawgraph code-families check` prints the same and fails on a change. Commit what a build
writes. A code is an abbreviation that two or more regulations list, each of which also lists
a book of it (`BW` with `BW Boek 6`): the book is the number of that abbreviation (`7A` too),
the code keeps the spelling most regulations give it. So the families follow the WTI; nothing
is kept by hand. A book whose WTI record is not stored is not in its family.

**Retrieve `eurlex-nim`.** The national implementing measures of `--country` (default
`NLD`, about 7,400) from CELLAR SPARQL, those CELLAR changed since `--since` (default 30 days;
`--mode full`: all), paged by document id (500 measures a page). One record per measure
(`eu-nim-json`, external id its CELLAR document id): `celex` (the acts it implements),
`journal`, `number`, `date` (of the journal), `type`, `title`, `modified`. `core/eurlex_nim`
reads the publication a measure is: the Staatsblad or Staatscourant (without a journal: a wet
is in the Staatsblad, a ministeriële regeling in the Staatscourant), its number (also
`178/2002`, `2025, 449`, `stb-2025-449`) and the year of the date, else the year the title
gives the number ("Staatsblad 1992, nr. 329"). About 4,800 of the 7,400 measures name one; the
rest (`Administrative measures`, no number, a placeholder date `1001-01-01`) none.

**Normalize `bwb-history`.** Reads every stored toestand once and writes:

- an InstrumentVersion per toestand and an ArticleVersion per `(stam_id, versie_id)` (a
  toestand only repeats versions still valid), with `parts`, `origin_publication` and
  `commencement_publication`; an article without a `versie-id` (an article of a bijlage) has
  an ArticleVersion per text (its number and a digest of its text), which begins in the first
  toestand holding that text, also over incremental runs;
- one version for a republication (effect `tekstplaatsing-*`) with the label, heading, place
  and text (`content_digest`) of the version before it: a republication gives every article of
  the Grondwet a new `versie-id` and changes nothing. It is removed with its edges, and the
  version before it holds on until the next change. An amendment whose text shows no change
  (a reference that points elsewhere now) stays a version;
- `valid_until` and `current`, recomputed from the database in chunks of 200 regulations, so
  incremental runs stay correct: a version is `current` exactly when nothing follows it, also
  after a re-run has written it again. Every period is half-open (`valid_until` is the first day
  it no longer holds, null when open; a toestand's inclusive end date becomes the day after), and
  at most one version of an article holds on a date:
  - a version ends where the next version of the same article (its `stam-id`; an article of a
    bijlage, which has none, by its number) begins;
  - a version that says the article lapsed (effect `vervallen`, or the text "Vervallen") holds on
    no date: its `valid_until` is its `valid_from`;
  - the last version of an article that a later toestand no longer holds (it left the law, as the
    old inheritance law of BW Boek 4 in 2003) ends when the first toestand without it starts;
    `last_seen` on the version is the start of the latest toestand that holds it;
  - a toestand from before an article's commencement shows it as "Dit onderdeel is nog niet
    inwerking getreden", under the versie-id its text will have; that placeholder is written only
    while no toestand gave the text, and never replaces it;
- the place of each ArticleVersion on a day (`pipelines/normalize/_bwb_places.py`): its
  `position` in one order of the versions of the law in which the versions of every toestand
  keep their order, and its `breadcrumb` with `breadcrumb_changes` from every toestand that
  holds it; a run with `--since` starts from what is stored for each law it reads;
- `VERSION_OF` from each ArticleVersion to its Article and from each InstrumentVersion to its
  Instrument;
- an Instrument if `normalize bwb` has not created it, and a historical Article for an identity
  that is not in the current toestand.

Run `normalize bwb` first.

**Semantic `bwb`.** `REFERS_TO` between articles, read from the XML rather than from the text:
only articles that carry `props.references` are scanned, and each reference naming a regulation
and an article becomes one edge with confidence 1.0, `meta` = `start`, `end`, `text`,
`reason = bwb_xml_ref`, `reference_kind` (`intref` or `extref`) and the `leden`, `onderdelen` and
`aanhef` the reference names. The link of the XML is written by hand beside the words and is
sometimes wrong where the words are not ("artikel 230m" linked to article 230, "artikel 1133"
to 113, "Artikel 62 leden 2 en 3 van Boek 4" to 178): where the words name another article,
numbered the same way, they count, and `meta.linked_article` keeps the key of the linked one. A
link inside a range the words name ("395a tot en met 397") stands; a book the words name
("van Boek 4", `6:162`) counts for a link into a book of a code. When the graph has no article
the words name, the link counts (14 of 8,063 references changed target in lawgraph_small).
An edge is keyed by its two articles, so an article that refers to another twice keeps the span
of one; `props.references` keeps both. Self references are dropped and targets must exist —
nothing is stubbed. The edges of an article are derived in full: one its references no longer
support is removed.
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
   version `effect` (`nieuw` introduces; `wijziging` amends; `vervallen` repeals), confidence
   1.0, `meta` = `effective_date`, `article_version`, `effect`, `source_publication`; one edge
   per publication, article and kind, with the earliest effective date. A republication
   (`tekstplaatsing-wijziging`, `tekstplaatsing-vernummering`: the Grondwet placed again as a
   whole, Stb. 2019, 33) changes nothing and has no edge; the edges of the step into an article
   that it no longer derives are removed;
4. writes `LEGISLATED_IN` from each publication and each regulation to the dossiers of
   `dossier_numbers` that exist (key = the plain dossier number), and removes its
   `LEGISLATED_IN` from a regulation to a dossier the regulation no longer lists.

Versions with an unknown effect or without a matching article count as skipped.

**Semantic `bwb-annexes`.** Finds `bijlage <label>` in article texts, and the name of an annex
of the same regulation (its title without the parentheses at its end: "de bij deze wet
behorende Bevoegdheidsregeling bestuursrechtspraak"; a name of at least two words, not in the
annex's own articles), and writes `SCOPED_BY` (0.9 with a label or a name, 0.7 for "de
bijlage") with `meta.scope_type` `discretionary` when
ministerial-designation wording is near (`bij ministeriële regeling`, `Onze Minister
kan ...`), else `fixed`. The Annex nodes (`label`, `title`, `description` up to 2,000
characters, `entries` from `<li>` items, at most 200: each item's own text with its marker,
`heading` (the paragraph ending in a colon that introduces its outermost list, without the
colon: "Gemeentewet") and `parent_index` (the entry it is nested in)) and their `PART_OF` to the instrument
are made by `normalize bwb` from the toestand it parses; a reference to an annex that is not
there gets a stub.

**Semantic `bwb-relation-types`.** Sets `semantic_type` on article-to-article `REFERS_TO` edges
from the sentence around the reference (`meta.start`/`end`; a sentence ends at a full stop
before a capital, a semicolon or a line break): a trigger phrase in the 40 characters before the
reference (`adjacent`), "in <reference> bedoelde/genoemde/omschreven/vermelde"
(`definitional_reference_inverted`), a trigger elsewhere within 120 characters in the sentence
(`window`), else `cross_reference`. Types: `limiting_exception`, `definitional_reference`
(also "genoemd in", "vermeld in", "opgenomen in"), `conditional_requirement`,
`prerequisite_procedure`, `scope_limitation`, `delegated_discretion`, `cross_reference`. A
type rests on a phrase only, so `meta.semantic_confidence` is the share of such classifications
a hand check found right (10 per cell in lawgraph_small, `_relation_type_patterns.CONFIDENCE`):

| Pattern | adjacent | window |
|---------|----------|--------|
| `limiting_exception` | 0.85 | 0.65 |
| `definitional_reference` | 0.85 (inverted 0.9) | 0.25 |
| `conditional_requirement` | 0.8 | 0.3 |
| `scope_limitation` | 0.8 | 0.8 |
| `prerequisite_procedure` | 0.6 | 0.3 |
| `delegated_discretion` | 0.3 | 0.3 |
| `cross_reference_explicit` | 0.5 | 0.5 |
| `cross_reference_fallback` | 0.5 | |

`meta.semantic_pattern` is `<pattern>_<adjacent|window>` (`cross_reference_fallback`),
`explanation` names the phrase and where it stood; the edge's own `confidence` (1.0) is that the
reference exists. Only the classifications that changed are written. The confidence of one
pattern can be overridden with `LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>`, for example
`LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION_WINDOW=0.7`.

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

**Retrieve `staatscourant-posts`.** For every post on the stored Rijksoverheid cabinet pages
whose function names no ministry, held from 1995 on (the repository holds the Staatscourant
and the Staatsblad in full from then): how many publications of the Staatscourant and the
Staatsblad name the function (full text, the function in lower case without accents) while
the post was held, per `dcterms:creator` (`Ministerie van Buitenlandse Zaken`). One
`stcrt-post-creators-json` record per query, external id `<phrase>|<from>|<to>` (`to` empty
while the post is held), `payload_json.creators`. The query of an ended post is asked once;
that of a post still held on every run. After `retrieve rijksoverheid`, on the KOOP lane.
`normalize rijksoverheid` reads the records (no normalize of its own).

**Semantic `staatscourant`.** `EXPLAINS`: `bwb_id` match 0.92, title contains an instrument
`citation_title` 0.65, a BWB id found in the text 0.75 (at most 5,000 documents).

## Eerste Kamer

**Provides.** The Kamerstukken of the Eerste Kamer, about 38,000 from 1994 on, from the KOOP SRU
(`EERSTEKAMER_SRU`; creator `Eerste Kamer der Staten-Generaal`, `w.publicatienaam==Kamerstuk`,
`dt.type==Kamerstuk`, so attachments `blg-*` are left out). The Eerste Kamer has no API of its
own. Per paper: identifier (`kst-<dossier>-<letter>`, some `kst-<number>`), own title
(`documenttitel`), dossier title, kind (`subrubriek`), number in the dossier (`ondernummer`),
date, session year, dossier number and the page on zoek.officielebekendmakingen.nl. Papers
before about 2007 have no kind and no own title in the source. The votes come from
eerstekamer.nl (`eerstekamer-votes`, below); the plenary reports and PDFs are not fetched.

**Retrieve `--mode`.** `incremental` (default): `--since` on `dt.modified`; `full`: everything.
`--max-records` stops early. The SRU record is stored as `ek-kamerstuk-json`.

**Normalize.** Document `ek_<identifier>`, labels `EersteKamer` and `EK` (the API `chamber`
filter), `kind`, `number`, `title`, `subject` (dossier title), `session_year`, `date`, `url`,
`dossier_number` and `dossier_suffix` (the Tweede Kamer stores the two parts of `35925 VII`
separately). A Roman numeral instead of a number (the own dossiers of the Eerste Kamer, 525
papers) sets neither. No edges here.

**Semantic `eerstekamer`.** `PART_OF` from the paper to the Tweede Kamer dossier with the same
number and addition, 0.95, `meta.chamber = EK`.

**Retrieve `eerstekamer-votes`.** The Eerste Kamer publishes its votes only on its website
(no open data; its terms allow reuse, also commercial, with the source and the day it was taken
over; `robots.txt` allows these pages). `clients/eerstekamer_site.py` reads, a page every two
seconds with the `Concordans` User-Agent:

- `/stemmingen_per_vergaderdag?filter=wetsvoorstellen`: every vote on a bill since June 2015
  (2,650 on 2026-09-30), newest first, 25 to a page, grouped by the day of the meeting; a day
  that runs over a page starts the next one again (`(vervolg)`). One record per day
  (`ek-votes-day-html`, external id the date), from one page or two. `--since` stops at the
  first page that ends before it; `--mode full` reads the whole list (106 pages).
- `/verworpen_in_de_eerste_kamer`: every rejected bill since 1996 (two pages), stored whole on
  every run (`ek-rejected-html`).

**Normalize `eerstekamer-votes`.** `core/eerstekamer_votes.py` reads the structure of the pages,
never a sentence. Each vote becomes a decision `ek_<date>_<label>_<n>` (the n-th on that bill
that day), labels `EK`, `chamber` `EK`: `result` (the outcome the Kamer shows, the `alt` of its
image: `Aangenomen`, `Verworpen`), `passed`, `method` (the text of the link to the report:
`Hamerstuk`, `Stemming bij zitten en opstaan, aangenomen`, `Hoofdelijke stemming, verworpen`,
`Algemene stemmen`, `Zonder stemmen`), `factions_for`, `factions_against`, `factions_noted`
(`aantekening gevraagd`), `subject` (the bill's name), `dossier_numbers` (the number as the
Tweede Kamer labels it: `36.600 VII` is `36600-VII`, `36.455 (R2188)` is `36455-(R2188)`),
`bill_url`, `source_url` (the part of the report) and `retrieved_on`; `ABOUT` the dossier. The
list names a vote on a motion on a bill by the bill (33.348, 15 December 2015: the bill adopted,
a motion rejected), which nothing on it tells apart. A rejected bill gives its dossier
`ek_rejected` (`date`, `source_url`, `retrieved_on`); a rejected bill of a day read that no vote
of that day rejects is logged.

**Retrieve `eerstekamer-composition`.** The pages of eerstekamer.nl on who sits where today:
`/fracties` (every faction with its seats), `/commissies` (every committee), and the page of each
(`/fractie/<slug>`: its board and members; `/commissies/<slug>`: its members with faction and
role), and `/wie_zit_waar` (the plan of the hall), about 40 pages, one record each (`ek-composition-html`, external id the path, `read_on`).
The site gives today's composition only, so every run reads it all: a snapshot.

**Normalize `eerstekamer-composition`.** `core/eerstekamer_composition.py` reads the pages'
structure and labelled fields (`Anciënniteit`, `Woonplaats`, `Geboortedatum`, `<function>:
<name> (sinds <date>)`), never a sentence. The snapshot is dated by the `read_on` of
`/fracties`. A faction `ek_<slug>` with its seats and board, a committee `ek_<slug>`, and a
member for every person on a faction page: the member of the Tweede Kamer born that day whose
surname ends the name as the Eerste Kamer writes it, when exactly one is, else one of its own
`ek_<slug>`; a member keeps the node it was first given, and its `ek.seat` is where the plan
of `/wie_zit_waar` draws it (its places, each linked to a faction's page and, through the
member's biography, to `/persoon/<slug>`; an empty place is `l-virt`). `MEMBER_OF` from the member to its
faction and committees (`meta.chamber` `EK`, `role` in a committee). Periods are as observed:
`observed_from` the day of the first snapshot that shows a faction, committee, membership or
seat, `observed_until` the day of the first that no longer does.

## ECHR

**Provides.** HUDOC judgments (`ECHR_HUDOC_BASE`, `/app/query/results`), filtered by
respondent (`--respondent`, default `NLD`) and collection `JUDGMENTS`, 100 per request with
0.5 s between requests. Fields: application number, name, item id, date, respondent,
importance, cited articles, conclusion, originating body. HUDOC holds a judgment once per
language and translation, each an item of its own with the same ECLI. The text of an item is
the DOCX HUDOC converts it to (`/app/conversion/docx/?library=ECHR&id=<itemid>`; HTTP 500 for
an unknown item), of which the main part, `word/document.xml`, is stored: the paragraphs with
the Word styles of the Court's templates, which the HTML conversion replaces with generated
class names. Terms (the Court's "Copyright and disclaimer", `echr.coe.int/copyright-and-disclaimer`,
read 29 September 2026): its texts may be reproduced free of charge for private use or for
information and education, with the source acknowledged (`© ECHR-CEDH`); other use, commercial
use in particular, needs its written permission. The electronic texts are subject to editorial
revision; the signed original in the Court's archives is authentic.

**Retrieve.** `--since` (`kpdate >=`), `--max-records` (default 10,000); `--mode full`
reads up to 50,000 and fetches every text again; `--mode gaps` the judgments cited by ECLI,
against any state (the English item, else the French one). After the judgments, every run
fetches the text of each stored or fetched judgment that has none: of its English item, else
its French one (none for a judgment in neither), 0.5 s apart. An item HUDOC has no text for is
skipped and remembered as missing, and asked for again after 30 days: HTTP 404, an answer that
is no DOCX, or an HTTP 5xx that outlasted the retries (HUDOC answers HTTP 500, run after run,
for an item it cannot convert, such as 001-208029). A 5xx counts toward the failures in a
row that end the run as a host that is down. The 200 judgments against the Netherlands take
about 100 s the first time (on average 170 KB of XML, 22 KB compressed, the largest about
1 MB); a daily run fetches only the texts of new judgments.

**Normalize.** Judgment per judgment: by its ECLI (the node a Dutch judgment that cites it
has), else by item (`echr_<itemid>`); the English item's record, else the French one's, else
another; `appno`, `title`, `date`, `articles`, `conclusion`, `importance`. A text record adds
`text` and `paragraphs` to the node of its `meta.ecli` (see [data model](data-model.md),
"Judgment").

**Semantic `echr`.** `REFERS_TO` from a judgment to the articles of the Convention it
applies, at 0.95, and to a BWB instrument whose id its `conclusion` names, at 0.80. The
Convention is the BWB treaty `BWBV0001000`, whose articles are numbered as HUDOC numbers them:
HUDOC's `8;8-1;8-2;41;P1-1` is article 8 (`meta.leden` `["1", "2"]`, `meta.hudoc_articles` the
field as HUDOC gave it) and article 41. `P1-1`, an article of a Protocol, is article 1 of
the Protocol's own BWB treaty: the curated list `echr-protocols` gives it (P1 is
`BWBV0001001`, P4 `BWBV0001029`, P6, P7, P12, P13), from the titles and the place and date of
signing the BWB gives; `meta.protocol` names the Protocol. A Dutch judgment that cites "art. 8
EVRM" reaches the same article. While a treaty is not loaded its cited articles are stubs
(`bwbv0001000_8`, `bwbv0001001_1`; `bwb_id` and `article_number`), as the cited articles of any
law that is not loaded, and `retrieve bwb --bwb-id BWBV0001000` loads it. The edges of a
judgment are derived in full: one it no longer supports is removed.

**Known limits.** An article of a Protocol the list does not have (11, 14, 15, 16: they change
the procedure of the Court) is not linked; `lawgraph check` counts them, and `semantic echr`
logs how many it left out.

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
`in_force` only for `Inwerkinggetreden`, `treaty_number` its id). No edges and no semantic
pipeline. Not ingested: the Trb references (`dcterms:isPartOf`), the parties and the place of
signing.

**Joined to the BWB by number.** The toestand of a BWB treaty names its Verdragenbank id
(`<wetgeving soort="verdrag" verdragnummer="005132">`, the EVRM), which `normalize bwb` writes
as `treaty_number`; the Verdragenbank record has no BWB id. The number is the join: the
instrument detail lists the other instruments with it (`same_treaty`), and `lawgraph check`
counts the BWB treaties whose number the Verdragenbank has, does not have, or that name none.
The BWB has 3,703 treaties and the Verdragenbank 8,774 (September 2026); of 40 BWB treaties
drawn at random every one named a number and 39 were in the Verdragenbank, with the same
title (000462, an arrangement of the Minister van Sociale Zaken, is not). Titles are not
compared.

## Rijksoverheid

**Provides.** Every cabinet since 1945 (32 pages; Rijksoverheid describes Biesheuvel I and II
as one cabinet), from `rijksoverheid.nl/regering/over-de-regering/kabinetten-sinds-1945`
(`RIJKSOVERHEID_BASE`), published under CC0. A page names each seat (`Minister van
Infrastructuur en Waterstaat`, `Staatssecretarissen / Buitenlandse Zaken`) with its holders,
their party and, for a holder who did not serve the whole period, their days (`3 juni 2025 -
19 juni 2025`, `afgetreden 31 aug. 1966`, `a.i.`); a block `Kabinetsformatie` with dated facts
(`Tweede Kamerverkiezingen`, `Beëdiging kabinet`, `Ontslagaanvraag vorig kabinet`) and, for a
crisis, `Ontslagaanvraag kabinet` and `Ontslagaanvraag ingetrokken`; and sentences that say
on which day the cabinet or some of its members resigned. The Tweede Kamer has no record of
cabinet posts: `PersoonLoopbaan` is a career the person reports, empty for most ministers, and
a signed paper (`AUTHORED meta.function`) names a function only on its own date. Nothing
official gives the posts or phases of the cabinets before 1945.

**Retrieve.** The index, then one page at a time (`www.rijksoverheid.nl` paced at 2 s, a
`User-Agent` naming Concordans): one `rijksoverheid-cabinet-html` record per page, external id
its slug, with `meta.url` and `meta.read_on`. Read in full on every run; a rebuild normalizes
from the stored pages without asking again. An index without cabinet links raises.

**Normalize.** `core/rijksoverheid.py` reads a page (seats, holder lines, dated facts,
resignation sentences); `core/cabinet_posts.py` turns its seats into posts;
`core/cabinet_phases.py` its facts into phases; `core/cabinet_sources.py` puts the cabinets
together.

A post is held in a **seat**: `<ministry>/<post>[/<portfolio>]` (`ienw/minister`,
`-/minister_zonder_portefeuille/buitenlandse-handel-en-ontwikkelingshulp`,
`-/staatssecretaris/rechtsbescherming`: `-` where the function names no ministry); the
minister-president and the minister of
Algemene Zaken are one seat (`az/minister-president`), every viceminister-president sits in
the shared seat `viceminister-president`. A heading can name several posts (`Vice-minister-president
en minister van Financiën`, `Minister-president, tot 15 sept. 1947 tevens minister van
Binnenlandse Zaken`), each with the days it gives. The rules of a seat:

- a holder line without a start held the post from the start of the cabinet, one without an
  end until its end; `from_date_source` and `to_date_source` keep what the page gave;
- the holders of one heading who follow one another hold one seat, the one the heading
  names, also where their own lines name the post otherwise (Schoof: Idsinga as
  "staatssecretaris Fiscaliteit en Belastingdienst" under "Staatssecretaris Fiscaliteit,
  Belastingdienst en Douane"; that name in `also_named`); holders of one heading at the same
  time (Szabó and Van Marum under Binnenlandse Zaken, two ministers without portfolio) hold
  seats of their own;
- a seat is named by the name its ministry had when the seat ended (Rutte-Asscher:
  `ez/minister` and `ez/staatssecretaris`, although Economische Zaken, Landbouw en Innovatie
  was named Economische Zaken only from 1 January 2013); each post keeps the `ministry` of its
  own first day, and `/api/cabinets/{key}` places a seat under the ministry of its name;
- two posts of one person in one seat on the same days are one post, the other name in
  `also_named`;
- in a named seat, an end the page does not give is the start of the next holder, a start it
  does not give the end of a holder with a given end (`corrected` says so);
- where the page names no portfolio (two staatssecretarissen of one ministry, two ministers
  without portfolio) it does not say who followed whom: the holders are put in lanes by date
  (`fin/staatssecretaris`, `fin/staatssecretaris#2`) and no date changes;
- a post is `acting` when the page says so (`acting_reason` `source`, its words in
  `acting_basis`: `a.i.`, `tijdelijke voorziening: …`, `beheer portefeuille overgenomen door
  de minister van …`, after which the holder of that seat stands in until the next holder
  begins), or when its holder held another seat through the whole period and it ended where
  the next holder began (`acting_reason` `held_other_seat`, that seat and its function in
  `acting_other_seat`);
- two holders of one named seat at the same time after these rules both get `overlaps_with`.

The **phases** of a cabinet: `formatie` from the earliest dated fact of its formatie block (the
elections, or the resignation of the cabinet before) to the beëdiging; `in_functie` from the
beëdiging; `demissionair` from the first resignation (a fact of its own page or of the next
cabinet's, or a sentence); `dubbel_demissionair` at a second one while demissionair;
`missionair` when a resignation is withdrawn or refused; and a phase with `kind` null from
elections held while the cabinet was in office when the page gives no day of its resignation.
Each keeps the source's words as `label`, and ends where the next begins.
`demissionary_from` is the start of the first `demissionair` phase.

Each holder (initials, surname and party as written) is matched to one Tweede Kamer person
(`core/government.py`):

- a member of parliament: the surname words agree (`family_name`, `Persoon.Achternaam`;
  particles such as `van`, `de` do not count; `ij` and `y` agree when the exact spelling finds
  nobody), the initials agree, and the member was between 28 and 95 on the first day of each
  post; where two fit (father and son), the faction of the holder's party decides. The
  Tweede Kamer writes most initials without dots (`JF`, `WTHC` for W.Th.C., `TM` for Th.M.)
  and at times other initials than the first names of the full name it gives (`JR` for Jan
  Frederik): such initials agree with the holder's written the same way (`jf`, `wthc`, `ij`
  as `y`), with their initial letters, or with the first names of the full name;
- a minister or state secretary who never sat in parliament: the Tweede Kamer holds such a
  person without name or date of birth, known only by what they signed (`AUTHORED` with
  capacity `bewindspersoon`, the signed name in the document's `actors`). The person is the
  holder whose surname is in the signed name and who held a post of the same kind (minister or
  state secretary) on a date they signed, or up to two weeks after it ended;
- a holder neither finds (`J.H. Hoogervorst` on the pages of Balkenende II and III, whom the
  Tweede Kamer knows as J.F.): the one member with the same surname, a faction of the holder's
  party, and a signature in government of the kind of one of the holder's posts while they
  held it (`core/government.match_by_function`); two such members match none. The log says
  how many were found so.

A holder who matches no member or several, or a member two people match, is left out (and
logged). The member gets `government_functions` (the posts, oldest first) and
`government_name` (`S.Th.M. Hermans`) and `known_as` (the first name the pages give in
brackets with the surname, `Sophie Hermans`; null when no page gives one); a member who holds
no post any more loses them. A holder
no Tweede Kamer person matches becomes a member of their own, key
`rijksoverheid_<initials>_<surname>`, label `Rijksoverheid`; once a later run matches them,
that member is removed. Every page is read on every run. Needs `normalize tk-dossiers` (the
members, their signatures and the factions).

Every post also gets its normalised `post` (`minister-president`, `viceminister-president`,
`minister`, `minister_zonder_portefeuille`, `staatssecretaris`), `cabinet_key` and `ministry`.
The ministries are the table `src/lawgraph/data/ministries.json` (`GET /api/ministries`), in
protocol order, built from the official sources (see TOOI below). A ministry name that no
longer exists (`venw` Verkeer en Waterstaat, `vrom`, `justitie`) has its own key; each name
has periods, each with its last day and successor, and a later source that writes an old
name ("Binnenlandse Zaken" for BZK) is read as the name it had then.

The **ministry of a post** (`core/post_ministries.py`) is the one its function names
(`Minister van Financiën`, `ministry_source` `page`; `core/ministries.classify_function`). A
minister without portfolio ("Minister voor Ontwikkelingssamenwerking") or a state secretary
with a portfolio of their own ("Staatssecretaris Herstel en Toeslagen") names none; for those
the first of these official sources that is clear decides:

1. `tk_signatures`: the functions the holder signed Tweede Kamer papers in, of the kind of the
   post, while holding it (`DocumentActor.Functie`: "staatssecretaris van Financiën"),
   counted per month;
2. `tk_commitments`: the ministry the Tweede Kamer gives the commitments made in a function
   of that kind by someone of the holder's surname while holding the post
   (`Toezegging.Ministerie`, from September 2022);
3. `staatscourant`: the ministry that issued the publications naming the post
   (`retrieve staatscourant-posts`, from 1995).

A source is clear when its largest ministry has at least 60% of its counts and at least one
signature or commitment, or five publications. Otherwise `ministry` stays null, with
`ministry_missing` `ambiguous` (a source had enough, but split: Van Veldhoven, Minister voor
Milieu en Wonen, Infrastructuur en Waterstaat 50 and BZK 32 publications) or `no_source` (none
had enough: a minister without portfolio before 1995, a typo on a page). Nothing decides by
the words of a portfolio: the sources are better at it (Van der Wal, Minister voor Natuur en
Stikstof in 2022: LNV, not the LVVN of 2024). A viceminister-president has no ministry.

Every cabinet becomes a node of `cabinets`, key from its name (`kabinet-Rutte-Asscher`,
key `rutte_asscher`): since 1945 from its page, `from_date` the day of its beëdiging,
`to_date` the beëdiging of the next (null for the cabinet in office), with `phases`,
`demissionary_from`, `prime_minister` (the member who held `az/minister-president` first),
`parties` (the parties of the bewindspersonen sworn in on the first day, the one with most
first; each with the `faction` of its name, `factions` their keys) and `origin` (the page and
the day it was read). The cabinets are derived in full: one no source names any more is
removed. Each member gets an edge `SERVED_IN` to each cabinet they held a post in,
`meta.posts` the posts; the edges are derived in full on every run.

`lawgraph verify cabinets` prints one row per cabinet (posts, seats, seats with a gap of more
than 14 days, seats with an overlap, stand-ins, corrected and clipped dates, double listings,
posts with and without a party, posts without a ministry by reason, members of their own,
phases, `demissionary_from`, whether `in_functie` begins on the first day), the phase labels
with their kind, the number of posts per `ministry_source` and every post without a ministry
by reason, and every broken rule
of `core/cabinet_checks.py` (a post outside its cabinet, two holders of a seat at once without
`overlaps_with`, phases that do not follow each other from start to end); a broken rule fails
the command.

## Courts

**Provides.** The Instanties value list of the Rechtspraak
(`https://data.rechtspraak.nl/Waardelijst/Instanties`, `RECHTSPRAAK_BASE`): every court an ECLI
can name, with its code (`Afkorting`, the court part of the ECLI), official name, `Type` and the
days it existed; 261 courts, of which 237 have a code (the military and colonial courts before
ECLI have none). A free public service of the Rechtspraak, like its judgments.

**Retrieve.** `retrieve rechtspraak-instanties`: the list, one `rs-instanties-xml` record
(external id `Instanties`, meta `url` and `read_on`), on the lane of `retrieve rechtspraak`.

**The court table.** `lawgraph courts build` makes `src/lawgraph/data/courts.json` from the
stored list (`core/court_sources.build_courts`) and prints what changed; `lawgraph courts check`
prints the same and fails on a change. Commit what a build writes, and run `semantic
graph-list-stats` when a tier or kind changed. Per court: `code`, `name`, `type`, `tier`,
`court_kind`, `from`, `until`.

- `tier` is the `Type` (`core/court_sources.TIER_OF_TYPE`): `TypeHr` `hoge_raad`, `TypeRvS`
  `raad_van_state`, `TypeCRvB` `centrale_raad_van_beroep`, `TypeCBb`
  `college_van_beroep_bedrijfsleven`, `Parket` `parket`, `Gerechtshof`, `Rechtbank`,
  `Kantongerecht` in lower case, `TuchtrechtelijkeInstantie` `tuchtcollege`,
  `AndereGerechtelijkeInstantie` `andere_instantie`, `Koninkrijksinstantie`
  `koninkrijksinstantie`, the foreign courts `buitenlandse_instantie`.
- `court_kind` is the tier itself for a tier of one kind of court. In `andere_instantie` and
  `koninkrijksinstantie` it is the official name without its place, in lower case joined by `_`
  (`core/court_sources.court_kind`): a part in brackets goes, a country of the Kingdom with
  `van`/`voor` before it goes (`Gerecht in eerste aanleg van Curaçao`), and a place the list
  names a rechtbank, kantongerecht or gerechtshof after goes at the end (`Raad van beroep
  Alkmaar`). So `ambtenarengerecht`, `raad_van_beroep`, `college_van_beroep_studiefinanciering`,
  `college_van_beroep_voor_het_hoger_onderwijs`, `tariefcommissie`,
  `raad_voor_strafrechtstoepassing_en_jeugdbescherming`, `raad_van_arbitrage_in_bouwgeschillen`,
  `gerecht_in_eerste_aanleg`, `gemeenschappelijk_hof_van_justitie`, `hof_van_justitie` (its
  predecessor, of the Nederlandse Antillen), `gerecht_in_ambtenarenzaken`,
  `raad_van_beroep_in_ambtenarenzaken`, `raad_van_beroep_voor_belastingzaken`,
  `constitutioneel_hof`.

Curated, as no list holds them (`src/lawgraph/data/curated/`): `courts_outside.json`, the EHRM's
own code and the courts published under `XX` by the name their metadata gives (`KB` the Kroon,
the EHRM, the Court of Justice of the EU under both its names); `decision_kinds.json`, the kind
of decision a kind of court gives when neither the metadata nor the kop names one.

## TOOI

**Provides.** The value list `rwc_ministeries_compleet` of TOOI (Thesauri en Ontologieën
voor Overheidsinformatie, KOOP; `TOOI_BASE`): every ministry since about 2010 with its code
(`mnre1045`), abbreviation, begin and end, its former names (`HistorischeVersie` with the
last day of each) and the events between them (`Oprichting`, `Samenvoeging`,
`Afsplitsing`, `Toestandswijziging`), each with the Staatscourant decree it rests on. The
content of the TOOI registers and value lists may be used by anyone without restriction
(TOOI beheerplan, 2.3 Rechtenbeleid). Numbered versions; the page of the list links each.

**Retrieve.** The latest version, one `tooi-ministries-jsonld` record (external id
`rwc_ministeries_compleet`, `payload_json.items`, `meta.url`, `meta.read_on`). Two
requests; always in full. A page without versions, or a version without a ministry, raises.

**The ministry table.** `lawgraph ministries build` makes `src/lawgraph/data/ministries.json`
from the stored TOOI list, the stored Rijksoverheid cabinet pages and the curated list
`src/lawgraph/data/curated/ministries.json` (`core/ministry_sources.py`), and prints what
changed; `lawgraph ministries check` prints the same and fails on a change. Commit what a
build writes. Per ministry name (the key, `ez`): the name, the TOOI code and abbreviation, and
its periods, each with `from`, `until` (the last day), `successor`, `basis` (the decree)
and `source`:

- `tooi` for every name TOOI knows. A name comes back (`Economische Zaken`: a ministry
  until 2010, a name of `mnre1045` in 2013–2017 and 2024–2026): each time is a period. A
  name that ends is succeeded by the next name of its ministry, or by the name the
  ministry it merged into had the next day (Verkeer en Waterstaat and VROM by Infrastructuur
  en Milieu on 14 October 2010).
- `rijksoverheid` for a name before TOOI: from its first post on the cabinet pages, until the
  day before a post under its successor begins on the day its last post ends (Oorlog and
  Marine until 18 May 1959); else the end stays null.

What no source gives is curated: our key of each name and the protocol order, the other ways
the sources write a name (`OCenW`, `VenW`), and a succession before 2010
(`successor_source: curated`). A curated name no source names is left out, and the build
says so: Openbare Werken, Arbeid, and Arbeid, Handel en Nijverheid have neither a post nor
a TOOI entry.

TOOI's dates are those of the decrees: `justitie` until 30 November 2010 and `venj` until
31 December 2017, while the cabinets changed the names of the posts earlier; a post that
uses a name before its first period keeps that name.

## Ordering

`normalize all` and `semantic all` run in registry order; each row needs what is above it.

| Step | Needs |
|------|-------|
| normalize `bwb-history` | `normalize bwb` (articles and instruments) and stored `bwb-toestand-xml-all` |
| normalize `tk-dossiers` | `normalize tk` (the case-to-dossier links read `cases`) |
| normalize `rijksoverheid` | `normalize tk-dossiers` (the members, their names and signatures, the factions a party is matched to, and the commitments) and `retrieve staatscourant-posts` |
| normalize `tk-content` | `normalize tk-dossiers` (it writes on the Documents that step made) and stored `tk-kamerstuk-xml` |
| retrieve `staatsblad` (from-graph) | `retrieve bwb` |
| semantic `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-relation-types` | normalized articles; `bwb-amendments` also `bwb-history` versions and the dossiers of `normalize tk-dossiers`; `bwb-relation-types` runs after `bwb` |
| semantic `tk-amendment-articles` | `tk-amends` (the document-to-instrument `AMENDS` edges), document text from `normalize tk-content` |
| semantic `tk-mvt` | `bwb-amendments` (`LEGISLATED_IN` and the change edges it walks), `normalize tk-dossiers` (the document-to-dossier `PART_OF` edges) and `tk-dossier-relations` (`SECOND_READING_OF`) |
| semantic `tk-mvt-articles` | as `tk-mvt`, and the sections of `normalize tk-content` |
| semantic `eerstekamer` | `normalize tk-dossiers` and `normalize eerstekamer` |
| semantic `tk-dossier-outcomes` | `bwb-amendments` (`LEGISLATED_IN`), `normalize tk-dossiers` (documents, decisions and their edges to the dossier) and `normalize eerstekamer-votes` (the votes of the Eerste Kamer, `ek_rejected`) |
| normalize `eerstekamer-votes` | `normalize tk-dossiers` (the dossiers the votes are about) |
| semantic `tk-government` | `normalize rijksoverheid` (cabinets and posts), `normalize tk-dossiers` (commitments, documents, `AUTHORED` and `PART_OF` edges) |
| semantic `tk-dossier-relations` | `normalize tk` (`related_cases` of the cases), `normalize tk-dossiers` (the dossiers and their titles) and `normalize tk-content` (the text of the memoranda) |
| semantic `graph-list-stats` (last step of `semantic all`) | backfills what the list endpoints sort and filter on: instruments (`jurisdiction`, `article_count` (the articles `PART_OF` it, not its annexes), `kind`), judgments (`court_code`, `tier`, `court_kind`, `date_eff`, `inbound_citation_count`; `decision_kind` where it is null, from the kind of court, and the curated `names` of a stub), articles (`inbound_citation_count`), committees (`active_dossier_count`, after `tk-dossier-outcomes`). `--instruments-only`, `--judgments-only`, `--articles-only` or `--committees-only` does one of them |
