# Pipelines

One section per source: what it provides, how it is retrieved, what normalize writes and
what the semantic pipelines detect. Confidence values are fixed in code unless noted.

## Overview

| Source | Retrieve | Normalize | Semantic |
|--------|----------|-----------|----------|
| Tweede Kamer | `tk`, `tk-dossiers`, `tk-document-links`, `tk-case-actors`, `tk-content`, `tk-transposition-tables` | `tk`, `tk-dossiers`, `tk-document-links`, `tk-case-actors`, `tk-content` | `tk`, `tk-amends`, `tk-amendment-articles`, `tk-mvt`, `tk-mvt-articles`, `tk-dossier-titles`, `tk-dossier-outcomes`, `tk-dossier-relations`, `tk-cited-papers`, `tk-government`, `tk-coalition-votes`, `tk-person-duplicates`, `tk-dictum`, `tk-paper-outcomes`, `tk-motion-kinds`, `tk-transposition-tables` |
| Rechtspraak | `rechtspraak`, `rechtspraak-instanties` | `rechtspraak` (`lawgraph courts build` reads the Instanties list) | `rechtspraak`, `rechtspraak-appeal`, `rechtspraak-conclusions`, `rechtspraak-referrals`, `rechtspraak-related`, `rechtspraak-duplicates`, `rechtspraak-citations`, `rechtspraak-series` |
| EUR-Lex | `eurlex`, `eurlex-nim` | `eurlex` (`semantic bwb-implements` reads `eurlex-nim`) | `eurlex`, `eurlex-cjeu` |
| BWB | `bwb`, `bwb-history` | `bwb`, `bwb-history` | `bwb`, `bwb-captions`, `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-publications`, `bwb-implements`, `bwb-relation-types` |
| Staatsblad | `staatsblad` | `staatsblad`, `staatsblad-laws` | `staatsblad`, `staatsblad-law-references` |
| Staatscourant | `staatscourant`, `staatscourant-posts` | `staatscourant` (`normalize rijksoverheid` reads `staatscourant-posts`) | `staatscourant` |
| Eerste Kamer | `eerstekamer`, `eerstekamer-votes`, `eerstekamer-composition-observed`, `eerstekamer-composition`, `eerstekamer-mutations`, `eerstekamer-persons`, `eerstekamer-motions`, `eerstekamer-agenda`, `eerstekamer-bills` | `eerstekamer`, `eerstekamer-composition` (which also reads `eerstekamer-composition-observed`), `eerstekamer-mutations`, `eerstekamer-persons`, `eerstekamer-agenda`, `eerstekamer-bills`, `eerstekamer-votes`, `eerstekamer-motions` | `eerstekamer` |
| ECHR | `echr` | `echr` | `echr`, `echr-versions` |
| Verdragenbank | `verdragenbank` | `verdragenbank` | `verdragenbank` |
| Rijksoverheid | `rijksoverheid` | `rijksoverheid` | none (`semantic tk-government` reads its cabinets) |
| TOOI | `tooi` | none (`lawgraph ministries build`) | none |
| Kiesraad | `kiesraad` | none (`normalize eerstekamer-mutations` reads it) | none |
| The graph itself (`graph`) | none | none | `graph-derive`, `graph-light`, `graph-article-terms`, `graph-heat`, `graph-list-stats` |

Clients (`clients/`) share `BaseClient`: a host from `config/sources.py`, one `get` (with
`get_text`, `get_xml` and `get_json`) with a timeout of 30 s (60 s for a page, 120 s for a
long query), and retries with exponential backoff (factor 2) on HTTP 429, 502, 503, 504 and
connection errors, following a longer `Retry-After`. Every client paces its requests per host
through one `PacedSession` (`clients/pacing.py`; the intervals: `docs/operations.md`,
"Pacing"), which names Concordans in the `User-Agent`. No source needs an API key.

Citation detectors resolve a law's abbreviation (`Sr`, `Sv`) through
`instruments.props.short_title` and `aliases`, and its name through instrument titles.
`core/aliases.code_aliases` makes the table, which also serves `/api/resolve`, the search and
the instrument-level matches of `semantic tk`. `normalize bwb` writes the official
abbreviations of the WTI files (see BWB), `normalize eurlex` the short title of an EU act.

The sources rank: short titles, then the other abbreviations of the WTI, then the curated ones
(`data/curated/instrument_abbreviations.json`, `lawgraph curated set instrument-abbreviations`:
`AVG` for Verordening (EU) 2016/679, for an instrument in the graph only). The first source
that has an abbreviation decides, and the abbreviation is a law's only when one law has it there
(`WvSr` is the Wetboek van Strafrecht's, `BW` no single book's), or when the others are versions
of it: their title is its title with a parenthesis after it (`Rv` is the Wetboek van Burgerlijke
Rechtsvordering's, not that of its version "(geldt in geval van niet-digitaal procederen)").
A text that names a law in full and gives it an abbreviation, in a citation or outside one ("de
Werkloosheidswet (WW)", "de Wet werk en bijstand (hierna: WWB)"), uses that abbreviation for that
law throughout: so an abbreviation several laws claim (WW: also the Woningwet and the Waterwet)
names a law where the text says which. An abbreviation that is one law's keeps that law.

In running text (`semantic tk`, `semantic rechtspraak`) an abbreviation of one word cites its
law as its source writes it. Another case (`Vw` for `VW`, `AWB` for `Awb`) cites the law in a
text that also names it so or by its title or citation title, and in a judgment dated five
years or more after the law came into force (`date_in_force`) while it was still in force
(before its `date_expired`): "art. 8 Vw" is the
Vreemdelingenwet 2000, while `CBW` in 2026 is the Centrale Branchevereniging Wonen ("artikel
12 van de CBW-voorwaarden"), not the new Cyberbeveiligingswet (`Cbw`), and `Hw` in 2020 is
not the Huurwet (`HW`, expired in 2003). A spelling that starts
in lower case where the source starts with a capital (`bis` for `BIS`, `cao` for `CAO`) never
cites the law. Else the citation is one of a law the graph does not know. The first part of a
compound (`art. 6 EVRM-verweer`) still cites the article.

A judgment cites no law that came to be after its date, in any spelling: the earliest of the
law's `date_signed`, `date_published` and `date_in_force` (`artikel 1a Vw` in 1998 is the
Vreemdelingenwet of 1965, not the Vreemdelingenwet 2000). A law without these dates is not
held to them. `semantic tk` does not date its papers: a bill is discussed before its law is
signed.

An abbreviation that several laws have in their sources, none of them first (`OW` of the
Onteigeningswet, `Ow` of the Omgevingswet; `BRO` of the Besluit op de ruimtelijke ordening
1985, `Bro` of the Besluit ruimtelijke ordening), cites in a judgment the law that was in force
on its date, in a spelling that may stand for it as above: of several in force the one written
as its source writes it, and when none was in force the one in force last. "Bro" in 2005 is
the BRO 1985, in 2010 the Bro (2008); "Ow" in 2020 is the Onteigeningswet, in 2025 the
Omgevingswet (the Onteigeningswet is still in force in part, but written `OW`). Without a date
(`semantic tk`) such an abbreviation cites no law unless the text defines it.

The EVRM is the BWB treaty `BWBV0001000`; its First Protocol (`BWBV0001001`) is cited as `EP
EVRM`, `Eerste Protocol (bij het EVRM)` or `Protocol nr. 1`. `EP` alone is also the Europees
Parlement, so it is the Protocol only in a judgment that also names the EVRM or the Eerste
Protocol (`in_context` of the curated entry; `semantic rechtspraak` only), or that names the
Protocol so itself (`art. 1 Eerste Protocol EVRM (hierna: EP)`).

A code split over books (`data/code_families.json`, `core/code_families.CODE_FAMILIES`: the
Burgerlijk Wetboek, books 1–8, 7A and 10, each its own BWB id) resolves through the book in the
article number: `artikel 6:162 BW` cites article `162` of book 6 (`BWBR0005289`, key
`bwbr0005289_162`), whichever books are loaded, so a citation of a book that is not loaded
becomes a stub of that book. The family's full name does the same (`artikel 7:669 van het
Burgerlijk Wetboek`): it is the name its books share in the graph (`Burgerlijk Wetboek Boek 7`
less `Boek 7`), unless that is a law's own name. Without a book (`artikel 162 BW`) or with an
unknown one there is no hit, and the family code (`BW`) is never a short title. A law that numbers
`Hoofdstuk:artikel` in one regulation (the Awb: `8:54`) is no family; its articles keep the
colon. How the families are built: see BWB.

A number with a leading zero (`047`) is no article number, and the letters of a number are
lower case (`36e`, `420bis`): in `artikel 82Sr` the `Sr` is the law. The linkers of running
text (`semantic tk`, `semantic rechtspraak`) resolve a cited article in one way
(`SemanticPipelineBase._cited_article`), the first that holds:

1. the article with that number;
2. of a law whose articles are loaded, the historical article that last had the number (a
   repealed or renumbered article cited by an older text: `bwbr0001854_248e_stam_…`);
3. no edge, when the number has a shape none of the law's articles has
   (`core.citations.number_shape`: digits as `9`, letters as `a`; `140.1 Sr` is `9.9` while Sr
   has `9`, `9a` and `9a.9`: article 140, first lid, written short), also when a stub of it
   exists;
4. a stub, when the citation is sure enough (`tk` 0.85, `rechtspraak` 0.9).

## Tweede Kamer

**Provides.** OData v4 JSON API of the Gegevensmagazijn (`TWEEDE_KAMER`): cases (Zaak),
documents, dossiers, activities, votes, commitments, committees, persons, factions.

**Retrieve.**

| Command | Fetches | Stored kinds |
|---------|---------|--------------|
| `retrieve tk` | Zaak modified since `--since` (default `1d`); `--mode full` since 1995-01-01; `--limit` caps the result for development; `--replacing` only the cases that replace another (`Zaak.VervangenVanuit`, some 11,600 in all; with `--mode full` the backfill of that relation for the cases stored before the retrieve read it) | `tk-zaak` |
| `retrieve tk-dossiers` | Kamerstukdossier, Activiteit, Stemming, Besluit (`Stemmen - …` on a zaak `Wetgeving`, `Initiatiefwetgeving` or `Begroting`: also a hamerstuk, which has no Stemming; and those without a Stemming on an `Amendement` or `Motie`: `ingetrokken`, `uitstellen`, `aangehouden`, `vervallen`; with the Stemming window and `--skip-decisions`; `--mode unvoted` those of amendments and motions alone, since `--decisions-since` or `--since`, else all, about 25,000), Toezegging, Commissie, Persoon, Fractie, FractieZetelPersoon, FractieZetelVacature, Document | `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-besluit`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-fractie-zetel-vacature`, `tk-document` |
| `retrieve tk-document-links` | the links of every Document modified since `--since` (default `1d`; `--mode full` all of them) and nothing else: its `Activiteit` (the debate a stenogram is the record of), `BijlageDocument` (its attachments) and `BronDocument` (the letters it is an attachment of), as ids. A few hundred bytes a paper, so the links of all of them can be fetched again; `retrieve tk-dossiers` asks for the same three with every Document | `tk-document-links` |
| `retrieve tk-case-actors` | the actors of every Zaak modified since `--since` (default `1d`; `--mode full` all of them) and nothing else: per `ZaakActor` its `Relatie`, `Functie`, `ActorAfkorting` and the ids of its person, faction or committee. A few hundred bytes a case, so the actors of all of them can be fetched again; a change of an actor moves the `ApiGewijzigdOp` of its Zaak | `tk-case-actors` |
| `retrieve tk-content` | the XML of every document numbered in a dossier (a Kamerstuk: a letter as much as a motie or a memorandum; with `--kind`, repeatable, only those whose `kind` contains it), at the address of the dossier it is numbered in (`dossier_number`; of a Rijkswet without its addition `(R2222)`) of which none is stored, so a second run asks only for the new papers; `--limit N` (at most N papers, the rest in the next run), `--dry-run` | `tk-kamerstuk-xml`, `tk-kamerstuk-xml-missing` |
| `retrieve tk-transposition-tables` | the attachments of Kamerstukken (`dt.type` `Bijlage`) whose title names a transposition or concordance table, as the KOOP SRU lists them, each with its dossier, the paper it belongs to and the URL of its PDF (the `itemUrl` of the manifestation `pdf`: the SRU's `url` is the XML of the few that have one); and the Kamerstukken whose full text names one (`cql.textAndIndexes`) and that are published as XML (the `itemUrl` of the manifestation `xml`); and the publications of the Staatsblad, of any type, whose full text names one (an AMvB that takes over old regulations has its tables in its nota van toelichting: Stb. 2020, 400; most name an EU implementation table); those not stored yet or modified since. The PDF stored as it is (base64); the XML of a paper or a Staatsblad as it is when `core/transposition_xml.py` reads a table in it, else the record without it (so it is not fetched again until it changes). A download that fails is skipped and asked for again the next run | `tk-transposition-table-pdf`, `tk-transposition-document-xml`, `stb-transposition-xml` |
| `retrieve tk-dossiers --mode gaps` | the dossiers the graph names and lacks, each with its documents: those that the publications amending or bringing into force a version of an article name (`origin_publication.dossiers`, `commencement_publication.dossiers`) or a regulation or publication names (`dossier_numbers`), the first reading that the memorandum of a second reading of a change in the Grondwet refers to ("Kamerstukken 35 418", `core/dossier_numbers.first_reading_dossiers`), and the dossiers a Tweede Kamer paper or case is part of (`dossier_numbers`); and the dossiers that lack a paper below the highest number the graph has of them (per suffix) | `tk-dossier`, `tk-document`, `tk-dossier-missing`, `tk-document-missing` (the Tweede Kamer has not all papers of that number either) |

`retrieve tk-dossiers` without `--since` fetches everything, some 400K documents among it. `--dossier-number N` fetches that one dossier and its documents, whatever the dates. The
other options are in `docs/operations.md`. Commissie, Persoon, Fractie, FractieZetelPersoon and
FractieZetelVacature are always read whole. Each entity type is stored while it is fetched (a buffer at a time), so
an interrupted run keeps what it fetched. A gaps run takes at most 50,000 dossiers (and
`retrieve rechtspraak --mode gaps` 50,000 judgments; `MAX_GAPS_PER_RUN`; `retrieve tk-content`
at most 15,000 papers, `MAX_PAPERS_PER_RUN`, about two hours a night); the table of
`retrieve all` says how many are left, and the next run takes them.

Client quirks:

- Nested `$expand` options are separated by `;`, not `&`:
  `$expand=Agendapunt($expand=Zaak($select=Id,Soort;$expand=Kamerstukdossier($select=Id,Nummer)))`.
  Standard OData syntax returns HTTP 400.
- The dossier endpoints emit no `@odata.nextLink`; the client pages with `$top=250` and
  `$skip` until a page is short. Zaak follows `@odata.nextLink` when no `$top` is sent
  (`$top=0` answers no records at all).
- Votes arrive as one row per faction per `Besluit`.
- `tk-content` does not use the PDF the API serves: the same paper is published as structured
  XML in the KOOP repository, filed under its dossier
  (`.../kst/<dossier>/kst-<dossier>-<number>/1/xml/kst-<dossier>-<number>.xml`, the dossier
  being the number with its addition, `37020-X` for a budget chapter). It builds the identifier
  from the dossier the paper is numbered in (`dossier_number`, `dossier_suffix`) and its
  `sequence`, and stores the XML unchanged as
  `tk-kamerstuk-xml` under that identifier (`meta.document` is the key of the Document). The
  papers it fetches are those without such a record and without a `-missing` record that is
  still to wait (`lawgraph gaps` lists them). A paper the repository has no XML for (404)
  becomes a `-missing` record: for 30 days, or for 1 when the paper is 14 days old or younger
  (new papers are published as a PDF first and their XML follows within days, now and then a
  week or more later). A paper the Tweede Kamer has not numbered yet (`Volgnummer` -1, no
  dossier) has no address in the repository and waits until it is. Error pages that
  answer 200 are not stored; 25 failures in a row fail the step. XML exists for papers from
  December 1994 on.

**Normalize `tk`.** Zaak to Case (`cases`, key = Zaak GUID; its `kind` is the `Soort`;
`dossier_numbers` kept for the dossier pipeline; `related_cases` the cases of
`GerelateerdNaar`, each with its `Soort` and dossiers, which `retrieve tk` expands with it so the
relation holds also when the other case was not retrieved). A motie, an amendement, a letter
(`Brief …`), the report of a debate or visit (`Verslag van een …`, `Inbreng verslag …`), a list
of questions, a `Mededeling`, an `Overig` or the advice of another body is named by its
`Onderwerp` (`Motie van het lid … over …`, `Verzamelbrief opvang Oekraïne`): its `Titel` is the
title of its dossier. An `Onderwerp` that only repeats the kind names nothing
(`core/tk_records/kinds.py`: `is_named_by_subject`, `own_subject`); a bill and the papers on it
keep their `Titel`, as their `Onderwerp` is their kind (`Voorstel van wet`). No edges: a case
is linked once the dossiers exist.

A TK record the Kamer deleted (`Verwijderd`) holds its id and nothing else. `normalize tk` and
`normalize tk-dossiers` make nothing of it (the record is counted as skipped, `deleted by the
Kamer`), and each normalizer removes, through one shared
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

**Normalize `tk-document-links`.** Reads the `tk-document-links` records (`--since` filters on
`changed_at`) and writes `MADE_IN` from a document to the activity it is the record of and
`ACCOMPANIES` from an attachment to its letter, named from either side, between nodes that exist;
a link to a paper or activity not stored yet is made by a later run. `normalize tk-dossiers` writes
the same edges of the documents it reads, from their own records (`activity_ids`,
`attachment_ids`, `attached_to_ids`).

**Normalize `tk-case-actors`.** Reads the `tk-case-actors` records (`--since` filters on
`changed_at`) and writes `AUTHORED` from a member to the case they submitted (`meta.role` as the
source writes it, `Indiener` or `Medeindiener`; `function` and `capacity` as on a document) and
`LED_BY` from a case to its voortouwcommissie, none when the plenary leads (`TK`), between nodes
that exist; an actor whose case, member or committee is not stored yet is linked by a later run.

**Normalize `tk-content`.** Reads the `tk-kamerstuk-xml` records (`--since` filters on
`changed_at`; `--after` and `--limit` read a slice of a run over all, past that record key, and
the log names where the next goes on), turns each into text, sections, footnotes and alineas
with `core/document_xml.py` and writes them on the Document named by `meta.document`. A record whose Document does not exist yet, whose
XML cannot be read or that has no text is skipped and counted, XML that does not read also a
note of the step (as is a paper whose headings make no sections: its text is written without
them); run it after `normalize tk-dossiers`. What it writes (`text`, `sections`, `footnotes`, `paragraphs`, `structure_quality`, `budget`,
...) is described in `docs/data-model.md`.

`paragraphs` (`core/document_paragraphs.py`) is every line of the text with an id that follows its
words (`p-` and 8 hex) and its alinea, as a reader cites it ("37020, nr. 57, alinea 4"): the lines
of the text numbered from 1, but for the head of the stuk (the `titel` and, before 2010, the
`datum` of its `stuk` or `wet`), a heading, and of a motion the formula around what it holds
("De Kamer, gehoord de beraadslaging," at its start, from "en gaat over tot de orde van de dag"
on); a table, its title and rows, is one alinea. The XML gives no page numbers.

The parser handles both dialects of the XML (`kamerwrk`, 1995-2009, with flat `tuskop`
headings; `officiele-publicatie`, 2010 on, with nested `divisie/kop` and flat `tussenkop`).
The artikelsgewijs part is heading text only, so the parser reads it from the words of the
headings: an opener ("Artikelsgewijs", "Artikelsgewijze toelichting", "Artikelen"), then
article headings (`Artikel 3`, `Artikelen 3 en 4`, `Artikel II`, `Artikel 3:159n`,
`Artikel I, onderdeel B (artikel 1a)`), `onderdeel` and `lid` headings under them, until a
heading of the opener's level or a bijlage. Article numbers come from the grammar of
`core/citations.py`.

A table (CALS, `core/text_tables.py`) is its title on a line, then a row a line, its cells
separated by a tab; `tables` says where each stands in the text, how many of its first rows are
its `<thead>`, how many columns it has and which cells span columns or rows, as of the tables
of an article. A row of only empty cells is left out, a cell spanning rows over it spanning
the rows left.

**Normalize `tk-dossiers`.** Order: committees, members, factions, dossiers, activities,
commitments, documents, decisions; then edges; then a backfill of title, kind, phases and
opening date onto each dossier (it needs the document edges). The `PART_OF` of a case to its
dossiers: of every case, or on a run over a window (`--since`, a poll) of the cases whose Zaak
it fetched and of the cases that name a dossier it wrote, which may be new.

| Step | Detail |
|------|--------|
| decisions | vote rows grouped by `Besluit_Id`; rows without one are skipped; and the `tk-besluit` records, the decisions on a bill no vote row carries (a hamerstuk), without votes (an incremental run first reads the stored vote rows of the Besluiten of its window); `decision_kind` is the `BesluitSoort`; `passed` from it (`aangenomen`, `zonder stemming aannemen`: true; `verworpen`: false), else the tally, else null; `kind` the `Soort` of the decided Zaak; the decided Zaak is the Besluit's own `Zaak` (`primary_case_id`, and its `Soort` as `primary_case_kind`; without it only an agenda item of one case names it: `AgendapuntZaakBesluitVolgorde` is the place of the Besluit on the agenda item, not of its Zaak), and `subject` prefers its subject over the agenda item; `date` is the day of the agenda item's Activiteit (the vote), else the `GewijzigdOp` of a row |
| factions | from the Fractie endpoint; without `tk-fractie` records they are derived from the `ActorFractie` strings of the votes; `aliases` are its abbreviation, its name and the names the vote rows of its own records give it (`Stemming.ActorFractie` by `Fractie_Id`); `abbreviation` is `Fractie.Afkorting`, and where that is the full name (`Nieuw Sociaal Contract`) the acronym of it its votes use (`NSC`); the records with one abbreviation are one faction (a faction that returns gets a new record, and the Kamer names the old one on a vote of today): one node, its props from the seated (else the latest changed) record, its period from the first start to the last end, reached by the id of every record. A decision whose faction votes name a Fractie the graph lacks is logged, as its votes then do not add up to its tally |
| committees | every Commissie with a name (`NaamNL`); a record without one is not written, so no id stands in for a name, and is written by the run after the source fills it in. The voortouw of every plenary activity is such a record: the Kamer itself |
| members | every Persoon, with `family_name` (`Achternaam`), `name_prefix` (`Tussenvoegsel`) and `birth_date` (`Geboortedatum`) (`normalize rijksoverheid` finds them by surname and date of birth); `party` and `faction_memberships` come from FractieZetelPersoon (dated), so a member without those records has no party: the Kamer keeps the seats of those who sat from 2002 (every seat from 30 November 2006), not of members of old or of the Eerste Kamer, and withholds a few |
| activities | `agenda_title` from `Onderwerp`, `status` as the source writes it (`Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; a planned activity may lie beyond the end of its dossier), `precision` from `DatumSoort` (`Dag`, `Weeknummer`: planned for the week of the Monday it is dated on, `Meerdaags`), `committee_id` from `Voortouwcommissie_Id` unless `Voortouwafkorting` is `TK`: a plenary activity has the Kamer as voortouw, not a committee; `replaced_by`: the numbers of the activities a moved one was replaced by (`VervangenDoor`, retrieved with the activity) |
| dossiers | `Nummer` plus `Toevoeging` form the key (`36554` and `36554-I` are distinct); `order` sorts them as the Kamer does; `same_number_count` is recounted for every number the run writes (this pipeline is the only one that makes dossiers); `kind`, `kind_basis`, `phases`, `current_phase` and `title` (from a voorstel-van-wet or MvT document when the dossier has none) are derived from its zaken, documents, activities and decisions by `core/dossier_stages.py`: the kind from the `Zaak.Soort` of its own zaken (those `PART_OF` it, those of its papers that belong to it alone, and those its activities roll up as `case_kinds`), the phases from the curated list `phases` (an activity that did not take place, `Gepland`, `Geannuleerd`, `Verplaatst` or `Vervallen`, marks no phase; a decision marks one only on a zaak of the bill) |
| documents | a paper named by its subject (as a case above: a motie, amendement, letter, report of a debate …) is named by its `Onderwerp` (else that of its Zaak) and keeps its `Titel`, the dossier's, as `dossier_title` (what `tk-amends` and the dossier title backfill read); dossier numbers via Zaak to Kamerstukdossier, and the `Soort` of those Zaken as `case_kinds`; `DocumentActor` becomes `props.actors`; several dossiers per document are kept in `dossier_numbers`; `DocumentNummer` as `document_number`, from which the API makes the link to tweedekamer.nl (no link is stored) |

`dossier_numbers` of a case, document, activity or decision (and the keys of
`case_kinds_by_dossier`) are dossier labels: `37020-XV` for a budget chapter, `37020` for the
Miljoenennota itself, so each record links to the dossier node with that key.

Edges: `PART_OF` (Document to Case and Dossier, Case to Dossier), `ABOUT` (Activity, Decision
to Case and Dossier; Commitment to the stored dossiers of the letters that fulfil it, `letter_dossiers`, `meta.basis` `nakoming`, else to the dossiers on the agenda of its activity, or, when that activity was moved (`Verplaatst`) and kept no agenda, of the activity that replaced it: `replaced_by`, `meta.basis` `agenda`; derived in full, so a commitment leaves the agenda once a letter in a dossier fulfils it), `LED_BY` (Activity and Case to
Committee from `committee_id`; none for a plenary activity), `MADE_IN` (Commitment to Activity;
Decision to the activity of its agenda item, `activity_id`; Document to the activity it records),
`ANSWERS` (the letter that fulfils a commitment, `letter_ids`, to it),
`MEMBER_OF` (dated, to committee and faction), `AUTHORED` (signatory to Document), `VOTED`. A run
over a window (`--since`) that holds a seat (FractieZetelPersoon) reads every stored seat of that
person, so the member's timeline is made of all their seats, and takes the member and the faction
from the database when the window holds neither. Every run keeps the vacant seats of each faction (FractieZetelVacature, all of
them: they are few) as its `vacancies`: from `Van` to the day before `TotEnMet`, the day the
successor takes the seat; a record that ends before it begins is left out. A seat is held or
vacant, never both: of a vacancy only the days count that no FractieZetelPersoon of the same
FractieZetel holds the seat, and it ends at the latest the day before the seat is taken again
(`tk_records.seats.vacant_periods`). The source holds vacancies that begin on the predecessor's last
day, and some it never closed while members sat (BBB, from 5 Feb 2025).

**Semantic `tk`.** Reads `documents` labelled `TK`. Text is the title (the paper's own subject),
the text and the footnotes; not the record the paper came with (`props.raw`), whose `Titel` is
the dossier's title and whose actors, ids and kinds are no text ("Bikkers VVD Tweede Kamerlid"
names no regulation). `core/document_reading.py` keeps where each part lies, so an edge says in
`meta.place` where its citation stands in what `/api/documents/{key}` serves (the title, the
text and its section, or a footnote by its `id`), and its `snippet` is of that part alone (see
[data-model](data-model.md#judgment)). The edges of a paper are derived in full each time it is
read: one its words no longer make goes. Aliases come from the graph:
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
as the Overview says (a stub from 0.85); instruments are never created. A paper of a dossier of
a law of the Staatsblad (`normalize staatsblad-laws`: the `dossier_numbers` of the law) that
cites a law of the BWB with its citation title (the Wetboek van Strafvordering of 36327) means
that law: the article of that number of the law of the Staatsblad, else a loaded article of
the law of the BWB ("het huidige artikel 126ffa"), never a stub of it. Edges
hold `raw_match`, `snippet`, `reason` (`bwb_article`, `celex_article`, `bwb_instrument`,
`celex_instrument`) and `qualifier`.

**Semantic `tk-amends` and `bwb-implements`.** One detector each:

| Relation | Detection | Confidence |
|----------|-----------|-----------|
| `AMENDS` (Document to Instrument, `voorgesteld`) | an amendement, the text of a bill (`Voorstel van wet`, `Nota van wijziging`, `Nota van verbetering`, `Wijzigingen voorgesteld door de regering`, `Oorspronkelijke tekst`, `Bijgewerkte tekst`, `Eindtekst`) or its `Memorie van toelichting` (`core/tk_records/kinds.py`: `may_amend`) whose title (of an amendement: its `dossier_title`) contains `wijziging van` and a known instrument name as a whole word (not the `Erfgoedwet` in `Erfgoedwetgeving`); any other paper on the bill's dossier, a motie too, amends nothing. Not an EU act the title names (a bill implements EU law, it does not amend it), nor an act of the document's own dossier (the instrument `LEGISLATED_IN` it, whose citeertitel closes the title once it is published). A document the step reads loses the `AMENDS` edges of the step it no longer gets, and every run removes an edge of any document to the act of its own dossier (one linked before its act was published) | 0.85 |
| `IMPLEMENTS` (Instrument to Instrument) | an implementation source (`meta.bases`): EUR-Lex lists the publication as a national implementing measure of the act (`retrieve eurlex-nim`): from the publication when the graph has it, and from every regulation it enacted (`props.enacted_publication`) or made an article version of (`national_implementing_measure`, `meta.publications`); or the considerans of the regulation implements the act (`considerans`: "ter uitvoering van", "te implementeren", "om te zetten", the "Gelet op" of an order; an act cited in the title of the implemented one, up to its reference in the Official Journal, is not implemented; `props.implements_celex`, kept by `normalize bwb`). Not per article: a measure names no article, and what it changed may be more than the implementation. Both instruments must exist; the edges are derived in full on every run | 1.0 |
| `REFERS_TO` (Instrument to Instrument) | an EU act whose CELEX number the BWB XML of a regulation names (`props.celex_refs`) and that it does not implement | 1.0 |

**Semantic `tk-amendment-articles`.** Scans TK documents that have `props.text` (filled by
`normalize tk-content`) for amendment wording, for the laws the document amends (`props.bwb_id`
and its `AMENDS` edges to instruments), except the act of the document's own dossier (the
instrument `LEGISLATED_IN` it): a bill, its memorandum, a nota van wijziging and its amendments
make that act, they do not change it. A document of one law changes it wherever its text says
so; a document of several changes each in its own wijzigingsartikel (the roman `article`
sections, `ARTIKEL I`, `ARTIKEL II` …): the law of a part is the one of them it names first, and
a part that names none of them (or the text before the first part) changes none. Targets must exist. Every edge is written with status
`voorgesteld`; the edges are derived in full on every run, and one no longer derived goes.

<!-- amendment-wordings:begin (generated: python -m lawgraph.pipelines.semantic.tk_amendment_articles) -->

| Wording | Relation | Confidence |
|---------|----------|-----------|
| `Artikel N ... wordt gewijzigd` | `AMENDS` | 0.90 |
| `Na artikel N wordt een artikel M ingevoegd` (article M) | `INTRODUCES` | 0.85 |
| `Artikel N ... komt te luiden` | `AMENDS` | 0.85 |
| `Artikel N ... vervalt` / `komt te vervallen` | `REPEALS` | 0.80 |
| `In artikel N ... wordt` | `AMENDS` | 0.80 |

<!-- amendment-wordings:end -->

**Semantic `tk-mvt`.** No text matching: the link is read from the graph. For every
document whose `kind` contains `toelichting`, one query walks
`Document -PART_OF-> Dossier <-LEGISLATED_IN- Instrument -AMENDS|INTRODUCES|REPEALS|ESTABLISHES-> Article`
(`ESTABLISHES`: the articles of a law the dossier made) and writes `EXPLAINS` at confidence 0.5 (`DOSSIER_CONFIDENCE`: the memorandum explains the
change as a whole, each article is a candidate) to the `meta.article_version` of each change
edge, to the article itself when the edge names no version, and to the instrument when it
changed no articles at all. An edge that `tk-mvt-articles` has written is left alone.

**Semantic `tk-mvt-articles`.** The article-by-article part of a memorandum, per section
(`props.sections`, from `normalize tk-content`). Which article of which law a section is about
is read from its words (`core/mvt_articles.py`) and matched with what the dossier changed
(`Document -PART_OF-> Dossier <-LEGISLATED_IN- Instrument -AMENDS|INTRODUCES|REPEALS|ESTABLISHES-> Article`).
`EXPLAINS` goes to the `meta.article_version` of the change edge, else to the article. Papers
with `budget`, with `structure_quality` `none`, and dossiers that legislated nothing are left
out; a section that names no article of a law the dossier changes has no edge of its own (the
dossier-level edges of `tk-mvt` stay). Only sections of kind `article`, `onderdeel` and `lid`
are read.

| `match_type` | Section says | Confidence |
|-------------------|--------------|-----------|
| `heading_target` | the heading names the article: `Artikel I, onderdeel B (artikel 1a)`, `Onderdeel A (artikel 3 van de Woningwet)`, `Artikel 11 Sr`, `Artikel 4, vijfde lid, Wahv`; the law is the one named, else the nearest enclosing heading names one (`ARTIKEL II (Woningwet)`), else the only law the dossier changes | 0.95; 0.3 when the dossier did not change the article |
| `body_named_law` | the text under the heading says `artikel N van de <Law>` for a law the dossier changes (title, citation title or short title) and the dossier changed that article | 0.65 |
| `own_number` | new law: the heading is `Artikel N` (Arabic, or `3:159n`), also with the law it changes (`Artikel 99 (wijziging Telecommunicatiewet)`), and the dossier made the law: a publication `LEGISLATED_IN` the dossier `ESTABLISHES` its articles (of two laws so made, the one that is `LEGISLATED_IN` the dossier itself), else its instrument is the one `LEGISLATED_IN` the dossier and no article of it was changed but to introduce it. A number without its law under such a heading is the new law's own, not inferred | 0.95 |
| `inferred_law` | an article number without its law, in the first 600 characters of the text under the heading (`artikel 2`), or an Arabic `Artikel N` heading in a bill that changes another law: of the law the nearest heading names (an enclosing one, or the heading of the article of the bill before it under the same heading: `ARTIKEL II – WETBOEK VAN STRAFRECHT`, or `Artikel II, onderdeel D` through the bill's ARTIKEL II), else of the only law the dossier changes; the dossier changed that article | 0.8 |
| `amendment` | an adopted amendment (below) changes the article, and its `Toelichting` section is the passage | 0.9 |
| `bill_part` | the heading names an onderdeel of the bill and no article (`Artikel I, onderdeel B`, `Artikel I, onderdelen C tot en met E`, an `Onderdeel B` under `Artikel I`, an `Artikel III` without onderdelen), and the bill says which article it changes (`core/bill_parts.py`): the articles under its headings when it inserts them (`Na artikel 248c worden twee artikelen ingevoegd: Artikel 248d … Artikel 248e`), else those its instruction names before what it quotes; of the law its `ARTIKEL` says it changes (`Het Wetboek van Strafrecht wordt als volgt gewijzigd`), else the law the instruction names; the section has text of its own, and the dossier changed that article | 0.9 |

The confidences (`core/mvt_articles.py`) are the share a hand check of 10 edges per kind in
lawgraph_small found right; for `bill_part` 10 of 10 on the server's texts of 14 dossiers
(lawgraph_small has no bill texts); for `amendment` 8 of 8, every adopted amendment with a
link in 15 dossiers on the server.

An adopted amendment explains what it changed too: the article 126ffa Sv came in by
amendment 34372 nr. 14, which the memorandum never names. Adopted is the last paper of its
chain (no paper `REVISES` it) whose case was last decided with `passed`. What it changes is
read from its text before the `Toelichting` (`core/bill_parts.amendment_changes`): the articles
under its headings when it inserts them (`Artikel 126ffa`), else those its instructions name
before what they quote (`In artikel II, onderdeel G, wordt in artikel 126nba …`). The law is
the one the article of the bill it names changes (`In artikel II` and the bill's ARTIKEL II),
else the one its instructions name, else the one law of the dossier that changed that number;
an amendment that changes two laws through two articles of the bill gets the first. The
passage is its `Toelichting`, and the dossier must have changed the article. The bill is the first `Voorstel van wet` of the
memorandum's own dossier: the memorandum explains the bill as it was sent, so its onderdelen
carry the bill's letters. A change of the article by the dossier corroborates a match; a
heading that names an article the dossier did not change mostly names one of another law than
the one it is taken for (the heading says `Wft`, the dossier changes Boek 2 BW). What a match
rests on is `match_type`, `changed` (whether the dossier changed or established the article)
and `explanation`, in Dutch ("De kop 'Onderdeel A (artikel 247)' noemt het artikel; het dossier
wijzigt het artikel."; "... het dossier stelt het artikel vast." for an article of the new law). A heading with several numbers (`Artikelen 3 en
4`) gives a reference per number; a range (`Artikelen 15 tot en met 15l Sr`) also the
articles between its ends that the dossier changed of that law, in the order of their numbers.
A reference may leave out the book of a code that the BWB stores per book (`artikel 7:658` is
658 of Boek 7); a law numbered per chapter keeps it (Awb `11:2` is no `artikel 2`). An `Artikel I` / `Onderdeel B` that names no article gives
what the bill says that onderdeel changes (`bill_part`), and nothing without the bill:
attaching it to every article the dossier changed would only repeat the dossier-level edges.
An `ARTIKEL I` over all the onderdelen of a law is the whole change of that law, and gives
nothing either. `heading_target` and `own_number` also point at the article of the law when the dossier
has no change edge for it (an article of a law that is new, or whose history is not loaded);
the others only at articles the dossier changed. Not detected: a new law whose numbering a
nota van wijziging shifted; articles of a treaty; a law the graph does not have or whose name
two laws share.

An edge is one per (document, target), so an article that several sections explain has one
edge, and it is the edge `tk-mvt` writes at dossier level: the same key, upgraded in place.
Its `confidence` is that of the surest section, `source` is `mvt-section-linker` and `meta`
holds `section_anchor`, `char_start`, `char_end` and `heading` of that section and
`sections`, every section that explains the article (each with its
`match_type`, `confidence`, `changed` and `explanation`), in document order. The span of a
section is `text[char_start:char_end]`: the whole section for a heading match, the text before
its first subsection for a match in the body. The two pipelines can run in either order and any
number of times: `tk-mvt` skips the targets that `tk-mvt-articles` has an edge to. A run of
`tk-mvt-articles` reads every memorandum and adopted amendment and replaces its own edges of
them: a section edge it no longer finds (an earlier code, a renumbered article) becomes the
dossier-level edge of a memorandum again at once when the dossier changed the article, and
goes otherwise.

**Semantic `tk-dossier-titles`.** A dossier another source made (a stub of the Eerste Kamer
or of a reference) is not in a run of `normalize tk-dossiers`. Every dossier without a title,
the source of its title or an opening date takes them from its papers and activities as that
pipeline gives them (`core/dossier_stages.select_title`, `opened_on`).

**Semantic `tk-dossier-outcomes`.** Whether a dossier is closed, how it ended and on which day,
read from the graph (`core/dossier_stages.derive_outcome`); the first rule that holds wins:

| `outcome` | Evidence | `closed_on` |
|-----------|----------|-------------|
| `aangenomen` | an instrument is `LEGISLATED_IN` the dossier: the Staatsblad publication of its law (`semantic bwb-amendments`, `normalize staatsblad-laws`), or a regulation whose BWB metadata names the dossier (`semantic bwb-amendments`) | the first `date_published` (else `date_signed`) of those publications; none when only a regulation names it |
| `verworpen`, `aangenomen` | its outcome in the Eerste Kamer (`ek_outcome`, below) | the day of that vote |
| `verworpen` | the last vote of the Tweede Kamer on the bill's own case (`primary_case_kind` `Wetgeving`, `Initiatiefwetgeving` or `Begroting`, not an amendment or a motion) did not pass | the date of that vote |
| `ingetrokken` | a document of the dossier (`PART_OF`) of kind `Brief regering` has as `Onderwerp` the fixed title the Kamer gives the letter that withdraws a bill, `Brief houdende intrekking van het wetsvoorstel` (`core/dossier_stages.WITHDRAWAL_LETTER_SUBJECT`), compared but for spaces and case; the latest such letter is `withdrawal_letter` | the date of that letter |

Anything else is open (`closed: false`): a bill the Tweede Kamer passed that the Eerste Kamer has
not voted on, a bill withdrawn by a letter with another subject, and a dossier without a bill (a
budget chapter, a policy dossier), which has no end the graph can see.

Next to the outcome it writes `tk_decision`: the last decision on the bill's own case with a
`BesluitSoort`, as the Kamer writes it (`Stemmen - aangenomen`, `Stemmen - zonder stemming
aannemen` for a hamerstuk, `Stemmen - uitstellen`, …), with its `BesluitTekst` and date; and
`ek_outcome` (`core/dossier_stages.ek_outcome`): `Verworpen` when the list of rejected bills
names the bill (`ek_rejected`), with the vote `Verworpen` of that day as its vote (else the list
as its source); otherwise `Aangenomen` by its latest vote `Aangenomen`; none when neither (a
bill with only a motion voted down). Its fields are in the data model (Dossier). The vote chosen gets `bill_decision: true` and `kind`, the kind of the
dossier (the list of the Eerste Kamer names none); the other votes of the Eerste Kamer about
the dossier `bill_decision: false` and no `kind`.

It walks every dossier on every run, since a law published today closes a dossier whose own
record did not change, and writes only the dossiers whose answer changed. It runs after
`bwb-amendments` and before `graph-list-stats`, which counts the open dossiers of a committee.

With `--touched-since` (`lawgraph poll`) it walks only the dossiers touched since then, and
`tk-government` only those dossiers and the commitments touched since then
(`pipelines/semantic/_touched.py`): the dossier, commitment, paper, case or decision whose TK
record was fetched since then (also the decision a fetched Stemming voted on), both ends of
every edge written since then that the step reads, and the dossiers these are `PART_OF`,
`ABOUT` or `LEGISLATED_IN`, directly or through their case. The edges each reads: of
`tk-dossier-outcomes` `ABOUT`, `VOTED`, `LEGISLATED_IN` and `PART_OF`; of `tk-government`
`AUTHORED` to a paper (not to a case: the actors of `tk-case-actors`) and `PART_OF`. A wave of
other edges (the actors of every case, the links between papers) touches none of their
dossiers. For those it comes to what a run over all would. Of the touched dossiers
`tk-government` reads the papers again only of those whose first signature can have changed:
one that keeps none (`first_signed`), or of which a paper the window touched is dated on or
before the one kept, or is it; found in one pass, however many dossiers the window touched. What changes in another way (a cabinet, a post,
the date of a publication) waits for the nightly run, which walks all.

**Semantic `tk-person-duplicates`.** `SAME_AS` from a bare `Persoon` of the Tweede Kamer to the
member with a role (`core/member_role.py`) who is the same person: the same birth date, surname and
initials (letters alone), all three given. The Kamer keeps some people twice, a record with their
seats and a bare one it made for their seat in the Eerste Kamer. A bare member that matches two
members with a role is left alone. The page of the bare member is a 301 to the other. Derived in
full each run.

**Semantic `tk-coalition-votes`.** What the coalition did on each vote of the Tweede Kamer
(`core/coalition.py`), kept in `lg_decision_coalition` (not a table of the graph), which the list
and the detail of decisions and the feed read. The coalition on the day of a vote is the factions whose party
held a post in the cabinet in office then (`meta.posts` of `SERVED_IN`): a party that leaves the
cabinet leaves the coalition the day its last post ends; a faction split off a coalition party
holds none and is opposition. A faction votes with its seats that day (`meta.seats`,
FractieGrootte); a roll call counts each member as one seat of the faction they sat in. Per vote:
the seats `Voor` and `Tegen` of the coalition and of the opposition; `pattern` `together` (every
coalition seat on one side), `split` (on both) or `wissel` (split, and the side with the most
coalition seats lost: a wisselmeerderheid); `carried` (passed with the coalition's seats alone
more than half of those cast), `decisive` (the opposition alone would have decided
otherwise) and `factions`, each coalition faction's seats `Voor` and `Tegen`. A tie is rejected, as the Kamer counts it. Not for a vote without a cabinet or
without a coalition vote, nor for the Eerste Kamer (its seats per day are not known). With
`--since` the decisions dated since then (the daily run); without it every one, and the rows
of decisions that no longer have one go (weekly, which also follows a change of the posts).

**Semantic `tk-dictum`.** Keeps the dictum of a motion (`core/motion_dictum.py`) and the
explanation of an amendment (`core/amendment_explanation.py`) whose text `normalize tk-content`
read before it kept them; `normalize tk-content` keeps both of every paper it reads, the dictum
of a motion only and the explanation of an amendment only (by its `kind`: a letter or a report
that quotes a motion whole has no dictum).

**Semantic `tk-paper-outcomes`.** How each motion and amendment ended (`core/votes.py`,
data model, Document): `outcome`, `decided_on`, `tally` and `decision` from the decisions taken
on it, the status the page of a motion of the Eerste Kamer states, and `REVISES` for a paper a
newer one replaces. A decision comes days after its paper and can change it again (held, then
voted), so every run reads every decision on a motion or an amendment and writes only the
papers whose outcome changed against `lg_document_light`.

**Semantic `tk-motion-kinds`.** Which motions are of censure (`censure`, motie van afkeuring) or
of no confidence (`no_confidence`, motie van wantrouwen), and which votes are on one
(`core/motion_kinds.py`, data model, Document and Decision): `motion_kind` from the fixed wording
of the subject the Kamer gives the motion ("… over afkeuring uitspreken over …", "… over het
opzeggen van het vertrouwen in …"), of a motion its title (its own `Onderwerp`), of a decision its
subject (the `Onderwerp` of its case); null for any other. Writes only what changed, against
`lg_document_light` for a motion. With `--since` the motions and decisions dated from then on (the
`tk` poll, so a new one is marked within the hour); without it every one.

<a id="semantic-tk-dossier-relations"></a>
**Semantic `tk-dossier-relations`.** Edges between dossiers, which the Kamerstukdossier record
itself never names (`core/dossier_relations.py`). An edge is written only when both dossiers are
in the graph; the dossiers of one number need no edge (`GET /api/dossiers?number=`).

| Edge | Rule | In the source |
|------|------|-----------------------------|
| `RELATED_TO` | the Kamer's own statement: a case of dossier A relates to a case of dossier B (`Zaak.GerelateerdNaar`, read by `normalize tk`). `meta.cases` counts the pairs of cases, `meta.case_kinds` names their kinds, `meta.pairs` the papers of the 5 newest pairs (two dossiers may share hundreds: `21501-02`): per pair of papers of the two cases' own kinds (the letter, the motion; not an attachment) `{from, to}`, a side `{paper, kind, dossier_number, dossier_suffix, sequence}` or `{paper: null}` for a case without such a paper in the graph. Cases within one dossier relate no dossiers | 80,544 related pairs of cases, of which 24,241 between dossiers of different numbers and 894 between two dossiers of one number: 10,571 pairs of dossiers. Mostly `Brief regering → Motie` (a letter that answers a motion filed elsewhere), then `→ Begroting` and `→ Wetgeving` |
| `REVISES` | a budget is "Vaststelling van de begrotingsstaten … voor het jaar Y" under a chapter or fund (`36800-XXII`). "Wijziging van de begrotingsstaten … voor het jaar Y" revises the budget of year Y with its own suffix; one with a number of its own (an incidental supplementary budget) names its chapter in its title ("(XIII)"; `IXB` falls back to `IX`), or else the budget by name, which must fit exactly one budget of the year. "Jaarverslag en slotwet … Y" revises the budget of year Y with its suffix. `meta.rule` is `begrotingswijziging` or `slotwet` | 1,529: 1,123 of 1,131 budget changes and 406 of 419 slotwetten; the rest (2007-2009) have no budget of their year in the source |
| `REVISES` (papers) | a paper of a case that replaces another (an amended amendment or motion, "Gewijzigd amendement … ter vervanging van nr. 21": `Zaak.VervangenVanuit`, read by `normalize tk` as `replaces_cases`) revises each paper of that case, Document → Document, `meta.rule` `vervanging` | 11,641 cases that replace another (9 Oct 2026) |
| `ACCOMPANIES` | "(wijziging samenhangende met de Voorjaarsnota)" of year Y goes with the dossier "Voorjaarsnota Y", likewise the Najaarsnota. The Miljoenennota of Prinsjesdag in year Y presents the budgets of Y + 1, so a change of year Y "samenhangende met de Miljoenennota" goes with the dossier "Nota over de toestand van ’s Rijks Financiën" whose number holds the budgets of Y + 1. `meta.nota` names it | 912: 412 Voorjaarsnota, 404 Najaarsnota, 96 Miljoenennota; 15 changes "samenhangende met" something else (an incidental supplementary budget, the refinancing of covid loans) get none |
| `SECOND_READING_OF` | a change in the Grondwet is made law in its second reading; the memorandum of the second reading speaks of the first reading and only refers to its papers ("Voor de toelichting verwijzen wij naar … (Kamerstukken 35 418, Kamerstukken II 2019/20, 35 419, nr. 9 …)"). Every dossier such a memorandum cites (`core/dossier_numbers.first_reading_dossiers`) is its first reading. `semantic tk-mvt` and `tk-mvt-articles` count the memoranda of the first reading with the second, so the first reading explains what the second made law | 35785 → 35418, 35419 |

So the route from Prinsjesdag 2026: the Miljoenennota `37020` and its budgets `37020-*` share a
number; each `37035-*` `ACCOMPANIES` `37020` and `REVISES` the budget of 2026 of its chapter
(`37035-XXII` → `36800-XXII`); the policy dossiers the Kamer relates to a budget (letters on its
motions) are `RELATED_TO` it. The Kamer relates none of the cases of `37035`; `37020` is
`RELATED_TO` from the dossiers whose letters answer the motions of the Algemene Politieke
Beschouwingen, which are filed under it.

The same step ties the two cases of each Kamer relation themselves: `RELATED_TO` case → case
(`meta.case_kinds`), also within one dossier or without one, when both cases are stored. And a moved
activity (`Verplaatst`) is `CONTINUES`d by the activity that replaced it: `replaced_by`
(`Activiteit.VervangenDoor`) names that one's number, the edge runs from it to the moved one
(`meta.reason` `verplaatst`). A motion is `MADE_IN` the debate it was submitted in
(`meta.reason` `ingediend`): the activity that has the motion's case on its agenda
(`Agendapunt.Zaak`, `ABOUT`), was held (`Uitgevoerd`) on the day the case started
(`Zaak.GestartOp`, the day it was submitted) and took no decision on it (no decision `MADE_IN`
it is `ABOUT` the case): the vote is an activity of its own (`Stemmingen`) with the case on its
agenda too, on the same day when the votes follow a tweeminutendebat. A paper of the Kamer names
no activity of a motion (`Document.Activiteit` is the record of a debate only).

It reads every dossier, every related case and every activity on every run, since a node loaded
today can be the other end of a relation stated earlier. It only adds and updates edges: an edge
whose evidence is gone stays until the database is built again; but a motion's `MADE_IN` no
longer derived goes on every run.

<a id="semantic-tk-cited-papers"></a>
**Semantic `tk-cited-papers`.** The papers a paper's subject names by dossier and number, and
the motions a letter of the government names in its text (`core/document_refs.py`). A letter that carries out a motion is often a case of its own, with
no `Zaak.GerelateerdNaar` to the motion; only its subject names it: "Uitvoering van de motie van
het lid Vliegenthart c.s. over … (Kamerstuk 25424-795)". The forms read after "Kamerstuk(ken)":
`25424-795`, `36945-XIV-1` (a suffix), `21501-02-3465` (a numeric suffix, when that dossier
exists; else `35261-13-15-16` is three papers of `35261`), `29 507, nr. 146`, `36 200 XVI, nr. 12`,
`36441, nrs. 38 en 39`, `Kamerstukken II 2025/26, 36600-XV, nr. 5`, and a list of them. A dossier
without a paper, a paper of the Eerste Kamer by its letter (`37035-M`) and the paper an amended
motion replaces ("ter vervanging van Kamerstuk 29826-322", which is `REVISES`) name nothing.
Each paper named is found by `dossier_number`, `dossier_suffix` and `sequence`
(`lg_document_light`); one not in the graph gets no edge and is counted. A letter of the
government (`Brief regering`) `ANSWERS` a motion (`Motie`, `Motie (gewijzigd/nader)`): the
appreciatie, the reaction, the carrying out; every other paper `REFERS_TO` what it names (a list
of questions, an inbreng or the decision note about a letter). `meta.basis` is `subject`,
`meta.text` of a `REFERS_TO` the reference as written, of an `ANSWERS` the whole subject
(what the letter says it does with the motion) with `meta.reference` the reference in it.

A letter of the government also names the motions it answers in its text, mostly in a
footnote ("Uw Kamer heeft met de motie van het lid Kathmann¹ …", note 1 "Kamerstuk 36 764,
nr. 28") or in brackets after "motie" without the word Kamerstuk ("de motie-Kathmann (36764,
nr. 31)"). Of every letter whose text says "motie" each line and each footnote (`footnotes` of
`normalize tk-content`) is read in the forms above; a paper named that is a motion and that the
subject does not name gets `ANSWERS`, confidence 0.9, `meta.basis` `text` or `footnote`,
`meta.text` the line or the footnote (of a long line the 400 characters around the reference), `meta.reference` the reference. Other papers the text
names get no edge. A letter has its text when `retrieve tk-content` fetched its XML. With `--since`
it reads the papers fetched since then and those whose XML was (their text comes with
`normalize tk-content`, often a day later).

<a id="semantic-tk-transposition-tables"></a>
**Semantic `tk-transposition-tables`.** Old law to new law in a recodification:
`TRANSPOSED_TO` from an article of the old law to the article of the new law that takes its
place, as the transposition table sent with the bill says, or the concordance table of an EU
act that codifies or recasts others. One method for every
recodification and every source of the relation: a reader per format gives rows (a part of an
old article and its place as the source writes it), and every row is checked against the text
of both laws (`core/succession.py`); what does not hold is not corrected or filled in but
reported.

- A table in a PDF of its own (`core/transposition_tables.py`; blg-1081574, Bijlage 1 bij de
  MvT 36327, for the new Wetboek van Strafvordering): the half "huidig-nieuw" of its text
  layer, pages headed `Huidig <old law> Nieuw <new law>`, under it `Artikel 126ffa` and a line
  per lid (`1.`), onderdeel (`a.`) or subonderdeel (`1°.`) with its places, `;`-separated: an
  article of the new law with the leden it names (`2.8.6, 1`; `algemene regeling 2.1.10`), a
  place that is no article (`vervallen (mvt)`, `Besluit B2`; `**`, a footnote mark whose note
  the PDF does not hold), or one that does not read (`1,5,2, 6`). A footnote mark after a place
  is no part of its number. A line that ends in a space runs on into the next unlabelled line.
- A table in the XML of a Kamerstuk or a Staatsblad (`core/transposition_xml.py`), as
  `retrieve tk-transposition-tables` stored it. A `<table>` with a column of the law the paper proposes
  (`Wetsvoorstel`, `Wetsvoorstel Energiewet`, `Plaats wetsvoorstel`, `Mediawet 20..`,
  `nieuw`) beside a column of the old law, the other column whose cells read as articles, is
  read wherever it stands (the Wet dieren's tables, kst-31389-3, stand under no heading that
  names them): `Elektriciteitswet 1998 | Onderwerp | Wetsvoorstel Energiewet | Opmerking`
  (kst-36378-3), `Huidige Mediawet | Mediawet 20..` (kst-31356-3), `oud | nieuw | opmerking`
  and `Onderwerp | Plaats | Plaats wetsvoorstel` under the old law's name (`Monumentenwet
  1988`, kst-34109-3; `Tabel 3. Boswet`, kst-33348-3), and pairs side by side either way
  (`Wetsvoorstel | Paspoortwet | Wetsvoorstel | Paspoortwet`, kst-36644-3). The proposed law
  is named by its column or by the dossier's title (`… (Wet dieren)`). A cell of the new law
  in parts (`Eerste lid: 3.1 Tweede lid: 3.2`, `Onder a: 1.1 Onder b-d: 6.1`) places each
  part of the old article; an old cell `Lid 1` continues the article above it, also one
  without a place; an old cell without a letter or figure (`–`) is no row. Another `<table>`
  whose title, a heading above it or the `<tussenkop>` before it names a table is read when
  it has a head row with a column per law (`Artikel Wabo | Artikel Omgevingswet`, the title
  naming one of them, `i. Transponeringstabel Wet algemene bepalingen omgevingsrecht`,
  kst-34986-3), or two columns under `Huidig naar nieuw` (the current and the new text of one
  law, kst-36636-3); the half `Nieuw naar huidig` is not read, another table places nothing.
  Columns of articles may stand in groups. A column of articles with a column of leden beside
  it (`artikel WVO | lid/onderdeel`) reads the leden there (`lid 1 t/m 3 en 5`; a remark in
  brackets, `(deels)`, is no lid). One column of a proposed law beside more columns that each
  name an old law (`artikel WVO | lid/onderdeel | artikel WVO-BES | lid/onderdeel | artikel
  WVO 20xx | lid/onderdeel`, kst-35297-3, and back) is a table per old law. One column of
  articles that names no law beside more that do, under a title that names the old law (`b.
  Transponeringstabel Bouwbesluit 2012` over `Artikel | Artikel Omgevingswet | Artikel AMvB`,
  Stb. 2020, 400), is a table of the old law to each; a column whose cells mostly name their
  law at their end (`1.1 Bbl`, `2.13 Bal en 8.28 Bkl`) a table per law its cells name, and
  one under the column's name (`AMvB`) of the cells with a figure that name none; a cell
  without a figure (`–`) stands with the cells of the law the column names most. Any other
  head with more than two columns of articles places nothing (`columns not recognised`). A
  cell holds references as written (`8.2.26, vierde lid`, `2.1 en 2.2`, `5.8 t/m 5.14`,
  `2.31, eerste lid, onder a`), joined by a word (`16.50 in samenhang met 16.40`, `5.33 jo.
  16.15`, `3.89 i.c.m. 3.10`, `5.1 resp. 5.3`: each a place), divisions (`afdeling 15.2`: a
  place that is no article) or anything else (`–`, `niet overgenomen`: no article;
  `2.21,eerste lid, … 16.89. 20.7`: does not read). A law after the last reference is the law
  of that one (`5.45, 16.7 en afdeling 3.5 Awb`, `16.52, eerste lid, Omgevingswet`, `5.20,
  derde lid, Awb (nieuw)`, `art. 1a WED (door artikel 2.46 IwOw)`): a name that starts with a
  capital, names no part of an article and does not start with the number of a division
  (`4.834, eerste lid Bal`: `Bal`; `5.4 Bijlage VII`: none). The word `besluit` there names
  no law: the references are of the new law, worked out in an AMvB under them (`20, derde
  lid, besluit`, kst-36440-3). A cell in prose reads the references after `komt/keert … terug
  in` (`Komt inhoudelijk gewijzigd terug in artikel 10.20 van de Omgevingswet.`). A row whose
  old cell names only a part (`onder a`) continues the reference above it, in both columns; a
  cell over more rows holds for each. A run of articles stands for each article of the law
  from the first to the last, in its order. An old cell that is a division of the old law (`§
  1.2`, `titel 10.5`) stands for each article of it, by the divisions of its
  `props.breadcrumb` (also an article repealed since).
- The laws: the new law is, of the name the table gives it, the one a publication of the
  table's dossier enacted or put articles in (`LEGISLATED_IN` the dossier, `ESTABLISHES` or
  `INTRODUCES` its articles: `instruments/wet_stb_2026_56`), else the one law of the BWB of
  that name (`Omgevingswet`); a table that names none, the one law of its dossier. A proposed
  law is the law of the dossier of a name its column or dossier gives it, else the one law of
  the dossier, else the one law of the BWB of such a name. The old law is the one law of the
  BWB of the name the table gives it (in a table of a proposed law its column's, else its
  title's, and of more laws of that name the one that had not expired when the proposed law
  came into force: the Wet voortgezet onderwijs BES of 2011, not the one of its first
  months), not the new law; a table that names none, of the new law's name. The law of a name
  is the one of that citation title, else of that abbreviation of the WTI (`WVO`, `WVO BES`,
  `Bal`), else the one the citation extractor reads in `artikel 1 <name>`, of the whole name
  (`WVO-BES` is not `WVO`). Names compare in any case, without spaces and marks
  (`Omgevings-wet`, `WVO-BES`), a year still open for any (`Mediawet 20..` is `Mediawet
  2008`). In a table of an old regulation (a BWB kind other than `wet`), the column of a law
  in a head of more new laws (`Artikel Omgevingswet` beside `Artikel AMvB`, Stb. 2020, 400:
  `4.3, eerste lid` beside `1.3 Bal`) names the delegation basis of the places beside it, no
  place: it places nothing (the basis is the new regulation's `BASED_ON`).
  Of a table with a column per law, which is the new law is read from the sources, not from
  the order of the columns: the one of the two the dossier enacted or put articles in, else
  the one the title does not name; when neither tells, the table places nothing. The rows run
  from the old law's column to the new one's, whichever comes first.
  A table for which either is not one law places nothing (the run counts it as skipped, with
  the reason).
- The concordance table of an EU act (`core/concordance_html.py`): the acts with an article
  whose text names a `concordantietabel` ("… worden gelezen volgens de concordantietabel in
  bijlage III"), their HTML as `retrieve eurlex` stored it. The table follows the paragraph
  whose whole text is `Concordantietabel` and runs to the next bijlage; its head has a column
  per act: the old acts by name (`Verordening (EG) nr. 207/2009`, `Richtlijn 82/891/EEG`, read
  to a CELEX number), the new act as `Deze richtlijn`, `De onderhavige verordening`. Each
  column of an old act is a table of its own (a codification of six directives, Richtlijn
  (EU) 2017/1132, gives six), between the instruments of the two acts as `normalize eurlex`
  made them; an old act the graph does not hold places nothing (`the act 32002L0019 is not in
  the graph`; `retrieve eurlex --mode gaps` fetches it), as does a heading without a table (an old
  page with the table as an image). A head cell over more columns reads their cells as one.
  A cell holds `Artikel 9`, `Artikel 9 bis`, `Artikelen 1 tot en met 7`, `Artikelen 3 en 4`,
  `Artikel 8, leden 1 tot en met 4`, `Artikel 2, punt 8 bis`, `Artikel 16, leden 1 en 2, en
  artikel 17, leden 2 en 3`; `—` and a bijlage are no article (of the old act: no row). A
  cell with a paragraph per line is a row per line. A row that does not line up (its cells
  have not as many lines, or it has fewer cells than the head has columns) places its old
  lines in a place that does not read. The old act goes when an
  article of the new act says it is repealed (`Verordening (EG) nr. 207/2009 wordt
  ingetrokken.`; a recital does not count). The table names the old act as amended, the
  graph holds its text as adopted: an article inserted later (`9 bis`) is a gap of the row.
- The tables between the same two laws are read together. A row holds when the old law has the
  article and the new law the article and every lid it names (`props.parts`). The old law's
  articles are those of its current text and its historical identities (`normalize
  bwb-history`, by `last_article_number`; a current article first): a table names the
  articles of its day. A number compares in any case and without spaces (`509ibis` is `509i
  bis`). A run of old articles in a run of new ones as long pairs them one by one. A place in
  another law is an article of that law: the new law when it is its name, else the one law of
  the BWB of that citation title, else the law the citation extractor reads in `artikel 1
  <name>` (`Awb`, `WED`); a place in the old law itself (`47b WEC` in the WEC's table) stays
  there. Each pair of articles is one edge: `meta.parts` `[{from, to, article, leden, via}]`
  (the part of the old article, empty for the whole; the place as written; the number of the
  new article of the pair, also of a run; the leden it names; the division of the old law the
  row names), `meta.source` the source of the table (the first, when two give the pair; the
  CELEX number of an EU act), `meta.basis` `transposition_table`, confidence 1.0.
- What a table answers instead of a place is an outcome: `vervallen` (`vervallen (mvt)`,
  `vervalt`, `Vervallen.`, also `vervalllen`), `niet_overgenomen` (`–`, `—`, `niet
  overgenomen`, `keert niet terug`), `blijft_in:<law as written>` (`Blijft in Waterwet`,
  `Blijft in Wm 10.6, tweede lid`), `naar:<law as written>` (to another law, no article of it
  named: `naar de Gratiewet (via de invoeringswet)`, `Wordt later ingevoegd in de
  Omgevingswet`). An old article with an outcome has an edge to the new law
  (Instrument): `meta.parts` `[{from, to, outcome, via}]`, `meta.outcome` the outcome its
  parts share; of an article placed elsewhere only the parts with an outcome. An outcome is no
  gap.
- A gap is a row that does not read, of an article (or division) the old law lacks, placing
  in an article or lid the new law lacks, or in a law not found; and an article of the old law
  in force that no row of any of the tables places in an article of the new law or answers
  for: no row for it, only places that are no article (`Besluit B2`), only divisions of the new
  law (`afdeling 15.2`, the PDF's `B6H3` for Boek 6, Hoofdstuk 3: checked against the
  breadcrumbs of the new law, but no place, as the graph has no node of a division), or rows
  none of which hold. Such an article has an edge to the new law with `meta.outcome` `gat`
  and its parts as the table writes them (a writing error stays as written: `1,5,2, 6`). "No
  row" only of an old law that goes: expired in the BWB no later than the new law came into
  force (`date_expired` ≤ `date_in_force`), recodified as a whole under its own name, or
  repealed by the EU act of the table; and only when no table of the old law to another new
  law has a row for it, then once, under the new law it places the most articles in. A law
  that stays (the Wet milieubeheer), or that went after the new
  law came into force (the Wet op het voortgezet onderwijs after the Wet register
  onderwijsdeelnemers), has a row only for what moves. Each gap is a note of the run, as is a
  table that places nothing (an EU directive's implementation table in a Kamerstuk);
  `lawgraph succession-gaps` lists them with their page or row, and counts the outcomes.

Derived in full on every run: an edge no table gives any more goes.

## Rechtspraak

**Provides.** Judgments from data.rechtspraak.nl: an Atom index (`uitspraken/zoeken`) and the
XML of one judgment (`uitspraken/content?id=<ECLI>`).

**Retrieve.** The index is read in pages of 1,000, of every court or filtered by court
(`creator`, an OWMS term; several are OR), by decision date (`date`, twice for a range) and,
for a `--since` up to 60 days back, also by when a judgment was published or changed
(`modified`), which finds one published long after its decision. Further back `modified` is no
filter: the Rechtspraak republished nearly its whole corpus. For each judgment of the index one `rs-content` record is stored, as soon as it is
downloaded. A judgment that is stored and was fetched after its last change (`updated` in the
index) is skipped, so a re-run or a resumed run only downloads the rest. The index is asked
for `type=Uitspraak` only, so a conclusion arrives through `--ecli` or `--mode gaps` (a
conclusion that is cited). A judgment that answers HTTP 404 becomes an `rs-content-missing`
record (data model, raw_sources), which `--mode gaps` leaves out while it waits. A page that is
not XML is not stored, and 25 failed downloads in a row fail the step.

A judgment the Rechtspraak withdrew is listed only by an index without `return=DOC` and without
a type, as an entry with `deleted`: `doc` (the document is no longer published) or `ecli` (the
ECLI was given in error; the decision has another, which arrives as a judgment of its own). An
incremental run with courts reads that index of every court for `modified` since `--since`
first, and stores of each withdrawn ECLI an `rs-content` record with `meta.withdrawn` (`doc`
or `ecli`) and `meta.updated` (when), unless one was stored after the withdrawal. Its payload
overwrites the XML stored before: of a judgment stored, the `<rdf:RDF>` of what
`uitspraken/content` gives now (the metadata, without inhoudsindicatie or text); of one never
stored, or whose metadata cannot be fetched, nothing. A judgment published again is in the
index again and is fetched as any other.

`--mode withdrawn` reads only that index, from `--since` on, the oldest change first; with
`--minutes N` it stops after N minutes and keeps how far it read (`pipeline_state`
`retrieve-rechtspraak-withdrawn`: `since`, `read_until`, `to_the_end`), and the same command
goes on there. The whole history (`--since 1990-01-01`, 3.8 million ECLIs, about 3,800 pages)
is so read in steps that each let the lock go; once read to the end, the command reads what
came after.

| Option | Meaning |
|--------|---------|
| `--court NAME` (repeatable) | `all` (every court of the index: the rechtbanken, the special courts and the courts that no longer exist too), an ECLI court code (`HR`, `RVS`, `GHAMS`, any case), or a tier of the court table (`gerechtshof`: every court of appeal, the older ones too; `rechtbank`, ...). The court table gives each court its OWMS term, the `creator` the index is filtered by (`owms_term` of `data/courts.json`, from the `Identifier` of the Instanties list); a court without one (the courts before ECLI, `XX`) cannot be asked for. Default: `all`; none when only `--ecli` is given |
| `--mode incremental` (default) | judgments decided from `--since` (default `1d`) minus 30 days, because judgments are published up to weeks after the decision |
| `--mode full` | no date filter: every judgment of the courts |
| `--ecli ECLI` (repeatable) | also fetch these judgments as they are (`--mode gaps` uses this for the cited judgments); skipped when stored in the last 24 hours |
| `--mode withdrawn` | only the judgments withdrawn since `--since` (above); a year is about 240 pages of the index |
| `--minutes N` | `--mode withdrawn`: stop after N minutes; the same command goes on there |
| `--mode gaps` | the cited judgments that are stubs, and the decisions that asked the questions of a preliminary ruling without an `ANSWERS` edge: the index of the date the ruling names, of every court (60 to 450 judgments a day), is read once per date, and an entry whose title (`ECLI, court, dd-mm-yyyy, case numbers`) has a case number the ruling names is fetched |

`retrieve all` reads the `--window` (a judgment is in it by its decision date). How many
judgments that is and how long it takes: `docs/operations.md`, "Slow steps".

**Normalize.** From `rs-content` XML: RDF header (`creator` as `court`, `date`, `zaaknummer` as
`case_number` (and split, lower case and without spaces, as `case_number_keys`: `C/19/117301 /
HA ZA 16-256` is `c/19/117301/haza16-256`), `procedure` as `judgment_metadata.type`, `type`
(`Uitspraak` or `Conclusie`) as `judgment_metadata.document_type`, `subject`s, as
`conclusion_eclis` every `dcterms:relation` of `psi:type` …/conclusie (the conclusion of a
judgment, or the judgment of a conclusion), and as `related_eclis` the judgments of the earlier
instance it ruled on: the `ecli:resourceIdentifier` of every other `dcterms:relation` that is not
a later instance (`psi:aanleg` …/latereAanleg)), `inhoudsindicatie` as
`summary`, `uitspraak` (of a conclusion: `conclusie`) as `text` and as `paragraphs` (below;
[the fields](data-model.md#judgment)), `isReplacedBy` (an ECLI)
as `replaced_by`, the parties its kop names as `parties` (with who acts for each, from the kop and
from the account of the procedure, and a party that account hears that the kop does not name), and
of a conclusion the
advocate-general its opening lines name as `advocate_general`, and how it ended: of a judgment
the first clause of its decision as `outcome`, of a conclusion what it proposes as
`conclusion_outcome` (`core/judgment_outcome.py`; data model, Judgment). The XML
itself stays in the payload store. Of a record with `meta.withdrawn` the judgment becomes a stub
in place of all it held: `ecli`, `withdrawn`, `withdrawn_on` (the Dutch day of `meta.updated`)
and of the RDF kept the facts of the decision that name no one, `court` (with `court_code`,
`tier`, `court_kind`), `date` and `date_eff`, `case_number` and `case_number_keys`,
`decision_kind`, `subjects`, and `replaced_by` when the source names the ECLI that replaces it.
Every edge from it is removed, what refers to it stays; a judgment not in the graph gets the
stub too, so `--mode gaps` never fetches it. `/api/judgments/{ecli}` gives that record; the
lists, the search and the feed leave a stub out; its page (`/render/uitspraken/<ECLI>`) is 410
with its court and date, when it was withdrawn (of an ECLI given in error: "ECLI vervallen",
with a link to the one the source names) and what refers to it, not indexed. `court_code` is the ECLI court
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

The inhoudsindicatie is `summary` when it is Dutch. An English one (`core.judgment_metadata.is_english`:
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
`beschikking`), and last the kind of court (`core.judgment_kinds.KIND_OF_COURT_KIND`, from
`data/curated/decision_kinds.json`): `arrest` for the Hoge Raad,
a gerechtshof, the EHRM and the HvJ EU, `vonnis` for a rechtbank, a kantongerecht and a gerecht
in eerste aanleg, `uitspraak` for the Raad van State, the Centrale Raad van Beroep, the CBB,
every other administrative college and a tuchtcollege, `conclusie` for the Parket; a gerechtshof,
rechtbank or gerecht in eerste aanleg gives an `uitspraak` in administrative law (the first of
the `subjects` is `Bestuursrecht`, tax law too). The Kroon, a foreign court, the Gemeenschappelijk
Hof, the Constitutioneel Hof and the arbitration board have no default: null unless the metadata
or the kop tells.

`names` comes from `src/lawgraph/data/curated/judgment_names.json` (`core/judgment_names.py`;
`lawgraph curated set judgment-names`), a list of landmark cases kept by hand: the open data
carries no name for a judgment (no `dcterms:alternative`; its vindplaatsen are citations without
a title, and an inhoudsindicatie names the precedent it applies as readily as itself). A name is
added for
an ECLI checked against the judgment (court, date, inhoudsindicatie); an English translation
carries the name of the judgment it translates. `semantic graph-list-stats` gives a stub its
names and the kind of its kind of court.

<a id="judgment-paragraphs"></a>
**The paragraphs of a judgment.** The kop is every line before the first section heading
(`Procesverloop`, `De procedure`, `Onderzoek van de zaak`, `1 Het verloop van het geding`, ...):
court, case number, date and parties, whether the court writes them in an `<uitspraak.info>`, in
bridgeheads, in loose paragraphs or in sections titled with a party name. It is the first
paragraph, a `subheading` of its lines with a blank line between (a `<?linebreak?>` starts a
line too); a judgment without a heading, or with more than four lines of prose before it, has
none. A conclusion writes its kop in a `<conclusie.info>`; when no heading ends the kop (or a
list of abbreviations), the end of that element does. Once the kop has named a party (a line
that opens with "hierna": "hierna: de verdachte") or its `<uitspraak.info>` is over, the first
numbered unit ends it too: a title with its `<nr>`, a `<paragroup>` with its `<nr>`, or a
numbered list of paragraphs (`<orderedlist numeration="arabic">` standing on its own, its items
on average at least 120 characters: the points of a conclusion, numbered by their place) —
unless the kop's last line joins parties ("en", "tegen"), after which a party may be set as a
numbered section.

A title or bold line that is a line of text, not a heading (it opens with a quotation mark or a
bracket, ends with a comma or semicolon, or is in small letters and ends in punctuation:
"[verdachte] ,", "is niet verschenen." in a quoted record), is `body`. A plain paragraph set
like a heading (one line of at most 80 characters, a capital first, no number in front, no
closing punctuation, no year, amount, "label : value" or initials of a name) is a `heading` (a
`subheading` when nested) when text follows it and it stands alone or with one more
("Procesverloop", "Overwegingen", "Inleiding" of the Raad van State); three or more in a row are
a list. A table of contents (a line "Inhoudsopgave" or "Inhoud", then its lines up to the first
heading, a longer paragraph or the repetition of its first line where the text begins) is `toc`:
its numbered lines are no considerations and get an id from their text, not `rov-N`.

A numbered unit that ends in a heading (its last line alone, all of it in emphasis, short and
without closing punctuation: "Slotsom") has that heading as a paragraph of its own after it. A
run of numbered headings that goes back in the numbering, after which the numbering goes on
where it was (6, then 3 and 4, then 7), is the headings of a decision the text quotes: `body`
paragraphs, the number in front of the text. The closing lines of a conclusion, from the last
short line that opens with "De Procureur-Generaal" to the end ("Hoge Raad der Nederlanden",
"A-G"; at most four short lines after it), are `signature`.

Where the XML has no numbered units (`<paragroup>` with its `<nr>`), a `<para>` is a paragraph,
and a number that its text opens with (`1. Bij het besluit`) is its number. Inside a numbered
unit, a paragraph that opens with a later number of the same level (`4.100.` in the unit of
`4.99`, compared part by part as numbers) begins a unit of its own.

A table (`<informaltable>`, CALS) stands in the text as in a Kamerstuk: a row a line, its cells
(each its paragraphs, a space between) separated by a tab, without the rows of only empty cells
(the lines a court sets under its signature); a table of no text is none. One that stands on
its own is a `body` paragraph of its own (no number: its first cell is no number), one in a
numbered unit a part of its text; the paragraph's `tables` says where each is
(`core/text_tables.py`). A table the kop reads is a line of the kop.

**Semantic `rechtspraak`.** Reads the `paragraphs` of each judgment that `normalize rechtspraak`
made, and of each judgment of a court of the EU (`normalize eurlex`), and extracts article citations from them, as one text ("artikel 3a van die wet" reaches
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
instrument titles; a title two instruments share is not a name. A title that ends in a year is a
name without it too (`Vreemdelingenwet` for the Vreemdelingenwet 2000) when no instrument is
called so and no other has that name with another year. A missing target article is
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
`end`, `raw_match`, `qualifier`, `leden`, `onderdelen`, `aanhef`, `snippet`, `snippet_start`,
`confidence`),
`meta.mention_count` how many there are: an edge keeps the first 100 and counts the rest. The
lid, onderdelen and aanhef are read from the qualifier with `core/qualifiers.py`, as `semantic
bwb` and `semantic tk` do. Text of a judgment outside its `paragraphs` (the `inhoudsindicatie`)
is not read. The edges of a judgment are derived in full each time it is read: one its text no
longer makes goes. `--since` takes the judgments retrieved from then on.

**Semantic `rechtspraak-citations`.** `ECLI:<country>:<court>:<year>:<number>` in the text of
each judgment, the `<uitspraak>` and `<conclusie>` the court or advocate-general wrote (from
`raw_sources`; `core/judgment_metadata.body_text`), never in its metadata: the `dcterms:relation` of the
metadata names the earlier instance and the conclusion, which are `APPEAL_OF` and `ADVISES_ON`
of their own steps, not citations. `REFERS_TO`, 0.95, `meta.cited_ecli`, `meta.mentions` (every
place in the paragraphs and footnotes of `core/judgment_paragraphs.judgment_text` that names it, the first
100, as on an edge to an article without the qualifier fields: a citation in a footnote with its
`footnote` label, counted for the paragraph that refers to it; `core/ecli.ecli_mentions`,
`ljn_mentions`), `meta.mention_count`, `meta.paragraphs` (the numbers of their paragraphs, as the
judgment prints them; none when no numbered paragraph does), no self citations,
missing judgments become stubs. The ECLIs are read by `core/ecli.cited_eclis`: one is valid when
its country issues ECLIs, its court code has the shape of one (letters for a Dutch court; whether
the court exists is not checked), its year lies between 1900 and the current year and its number
has the shape of one (Dutch: a number or an LJN). What the text shows is repaired: an LJN whose
digits it sets apart (`BH 2815`, `BH:4033`), NL and the court swapped, a range (`2018:2374-2375`)
as its members, a word or the next ECLI glued to the number, a zero or one typed for a letter of
an LJN (`A09006`). The rest is dropped and makes no stub; `_resolve_eclis` makes no stub of a
malformed ECLI for any step. An LJN named on its own (`LJN BK9271`, `LJN: BK9271`, `LJN-nummer
BK 9271`), the way a decision was cited before 2013, cites the judgment in the graph whose ECLI has
it for its number (`ECLI:NL:CRVB:2010:BK9271`; `core/ecli.cited_ljns`, `ljn_of`), with its
paragraphs as for an ECLI; an LJN no judgment has, or two have, cites nothing and makes no stub
(without the court and the year there is no ECLI to make one of). How many such LJNs a judgment
cites, but one whose ECLI its text names too, is kept on its row of `lg_unlinked_references`
(`ljns`, null for none; the row `semantic rechtspraak` wrote, which runs first): not linked, for
`completeness.references`. The citations of a judgment are derived in full each time it is
read: an edge of this step its text no longer names is removed, and then every stub judgment no
edge reaches or leaves. No `REFERS_TO` is written between two judgments that `APPEAL_OF`,
`CONTINUES`, `REFERRED_BY`, `ADVISES_ON` or `ANSWERS` tie (either way): a Hoge Raad ruling that
names the arrest under cassation and the conclusion in a footnote does not cite them. It runs
after the steps that make those edges. `semantic graph-list-stats` recounts
`inbound_citation_count` and `outbound_citation_count` after it.

A decision of the ECHR is cited by application number, not by ECLI ("EHRM 28 maart 2000, nr.
22492/93", "EHRM (GK) 12 november 2008, nrs. 34503/97 en 34504/97"): after each "EHRM", the
numbers named with `nr.` or `nrs.` and a date before them (`core/echr_citations.py`).
`REFERS_TO` to the ECHR decision of that number and date (0.9), or, without a date, to the only
decision of the number (0.8); a number of several decisions (admissibility, Chamber, Grand
Chamber) and no date makes none, nor one not loaded (`meta.cited_appno`, and the places as for an ECLI: from "EHRM" to the number, `core/echr_citations.dutch_mentions`).
The language versions of one decision count once (`echr-versions`). The log says how many were
linked, not loaded and ambiguous.

**Semantic `rechtspraak-duplicates`.** The Rechtspraak published many old arresten again under a
new ECLI (HR:1985:BH3435, BV4163 and BV4180 are AW8335); the old publication has no text and its
`dcterms:isReplacedBy` (`replaced_by`) names the new one. That is the signal, not the court, date
and case number: a republication may carry another date or number, or the code of another
court. A publication whose replacing one is loaded (followed to the last that is) gets
`SAME_AS` to it and `same_as`, its ECLI; `/api/judgments` leaves it out and `graph-list-stats`
counts its citations with the one kept. One whose replacing publication is not loaded stands
alone. Derived in full each run.

**Semantic `rechtspraak-appeal`.** From a judgment to each of its `related_eclis`
(`meta.basis` `formal_relation`, 0.95, `meta.procedure_type`): `CONTINUES` when it is of the
same court with a case number the two share (an interim judgment, then the final one), whatever
the procedure; and from a judgment whose `judgment_metadata.type` contains `hoger beroep`,
`cassatie`, `verwijzing`, `artikel 80a RO` or `artikel 81 RO` (`core/appeals.py`):
`REFERRED_BY` when it is a ruling of the Hoge Raad and the judgment is of another court (the
decision after referral), no edge when that ruling is a preliminary ruling the court asked for;
no edge to a conclusion or to a judgment given later; `APPEAL_OF` otherwise. A judgment's
`later_eclis` (`psi:aanleg` latereAanleg) make the same edge from each later judgment that is
loaded, by the same rules (`later_instance`, 0.95): a lower court names its appeal, which need
not name it back. An appeal without
`related_eclis` is read for the decision it appeals, in its first 12 paragraphs: `tegen
de/het/een uitspraak|vonnis|beschikking|beslissing|arrest van <court> van <date>`, optionally
followed by `in zaak nr.`, `nummer`, `onder parketnummer`, `met zaaknummer`, `kenmerk` and the
case number, where `<court>` names a court (not an administrative body). The decision of that
date with that case number (`core.case_numbers.same_case_number`) gets `APPEAL_OF` (`appeal_text`,
0.9); one not loaded is written to `unresolved_appeal_targets` (`court`, `date`,
`case_number`) of the appeal. Missing judgments become stubs. The edges of a judgment read are
derived in full: one no longer derived is removed. With `--since` (the daily run) only the
judgments fetched since then are read, and edges are added, not removed; the run without it
(weekly) links what an older judgment says of a newer one and removes what is no longer
derived.

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
rechtsvragen`; `core/case_numbers.read_referrals`), so a ruling that answers two courts names
two: the ECLIs it names, else the decision (not a conclusion) of the date it names with one
of its case numbers (`referral_text`, 0.9). The case numbers are read in the forms `in de
zaak <numbers> van <date>`, `van <date> met zaaknummer <number>`, `van <date>, in zaak nr.
<number>`, `bij beslissing van <date>, nummers <numbers>, gestelde` and, in older rulings,
`verwijst … naar het vonnis in de zaak <number> … van <date>` followed by `bij laatstgenoemd
vonnis`. Two case numbers are the same when they share a number of five digits or more,
else a roll number (`22/2463T`), else all their letters and digits
(`core/case_numbers.same_case_number`): `C/09/610280/ KG ZA 21/346` is `C-09-610280-KG ZA
21-346`, `200.273.775/01` is `200.273.775`. A ruling that names no case number (the Gerecht
in eerste aanleg of Aruba) or a decision that is not published stays unlinked. The referring
decision is found only when it is loaded; `retrieve rechtspraak --mode gaps` fetches it. The edges of
a ruling are derived in full each run; with `--since` only those of the rulings fetched since
then and of those that answer no decision yet.

**Semantic `rechtspraak-related`.** `RELATED_TO` from a judgment to the connected cases its
summary names (`core/related_cases.py`). The metadata relates judgments only along their
chain of instances; the court tells connected cases in its inhoudsindicatie: "Samenhang met
24/03860 E en 24/03859 P (niet gepubliceerd)", "Zie ook: ECLI:NL:GHDHA:2025:1539". Each such
sentence is read as written:
- the ECLIs it names, also as the courts abbreviate them (`HR:2025:404`);
- its case numbers, compared exactly with `case_number_keys` of the judgments of the same
  court. The type letter of the Hoge Raad is not compared: it writes its type
  of case after the number (`24/03860 E`, `16/01894 UA`) where its metadata gives the
  number alone, and the number is unique within the Hoge Raad. `meta.text` keeps the
  sentence as written, letter included.

What stands between brackets names no case, and an old LJN is not read. An edge only on an
exact match with a judgment in the graph (`meta.basis` `summary_text`, `meta.text` the
sentence); what is named and not found gets no edge and is counted (`skipped`). The edges of
a judgment are derived in full each run; with `--since` only those of the judgments fetched
since then.

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
(`CELLAR_SPARQL`, pages of 500). That endpoint is not a complete list: it has no
entry for many recent acts (about 150 directives for 2010, 1 for 2016; the GDPR is missing),
and it answers HTTP 500 from offset 10000 (a failing page raises). Acts are therefore
fetched by the CELEX numbers that loaded records refer to (`retrieve eurlex --mode gaps`,
`expand-graph`), not by listing them.

**Retrieve `--mode`.**

| Mode | CELEX numbers fetched |
|------|-----------------------|
| `incremental` (default) | those of instruments in the graph that are not stored or that CELLAR changed since they were, or `--celex` (repeatable) |
| `full` | the directives SPARQL lists, without corrigenda; `--type` (repeatable: `directive`, `regulation`, `decision`) chooses other types, at most 10000 per type. Not part of `retrieve all` |
| `gaps` | the acts BWB regulations name (`props.celex_refs`, `implements_celex`), and the old acts the concordance table of a stored act names that the graph does not hold, that were not retrieved. An old act fetched this way may have a table of its own: the next run after `normalize eurlex` fetches its old acts |
| `nim` | the acts that have national implementing measures of `--country` (default `NLD`) |
| `cjeu` | judgments that cite acts in the graph; without acts in the graph, the judgments referred from a court of `--country` |
| `com` | Commission proposals for acts in the graph |

Stored as `eu-celex-html` while the acts are fetched, with the moment CELLAR last changed the
act (`cmr:lastModificationDate` of the work, by SPARQL 100 acts a query) as `meta.modified`. A
judgment (a CELEX number of sector 6) is stored with what CELLAR says of it, by SPARQL 100 a
query: `meta.ecli` (`cdm:case-law_ecli`), `meta.date` (`work_date_document`), `meta.title` (the
Dutch `expression_title`; of joined cases the first in order), `meta.national` (the national
decisions of its case, `case-law_national-judgement`) and `meta.country` (`NLD`, the country
it was referred from).
Incremental asks that moment for every act in the graph and fetches an act that is not stored,
stored without the moment, or stored with an earlier one; an act CELLAR has no moment for is
fetched only when it is not stored. `--celex` and the other modes skip an act stored in the
last 24 hours. An act without an HTML text (HTTP 404, in every language: old regulations and every
corrigendum) counts as skipped, not as an error, and becomes an `eu-celex-html-missing` record
(data model, raw_sources). A download that fails is skipped in every mode (the next run asks
again); 25 in a row fail the step. A listing (`full`, `nim`, `cjeu`, `com`) that fails or is
empty fails the step, and so does `com` on a graph without EU acts.

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

**Normalize.** A judgment per CELEX number of sector 6 (case law: the Court of Justice, the
General Court, the Civil Service Tribunal), keyed by its ECLI (`meta.ecli`; a record without
one is skipped until it is retrieved again), source `cjeu` (data model, judgments); every
instrument and article of such a number, with the edges at them, is removed (no case law is an
act). Instrument per other CELEX (`jurisdiction: eu`). Its names come from the printed
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
the citation title, `date_signed` that day of adoption (`2016-04-27`; none without a date
in the title). Articles are read from the structure of the HTML
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
  continues the part before it. "Artikel" printed without its number is the article after
  the last one (the first of 89/104/EEG); an inserted article ("Artikel 3 bis") counts only
  right after the article of its number, else it is one an amendment quotes.

An article inserted later has a number of its own, written as a citation names it:
"Artikel 9 bis" and "Artikel 9bis" are `9bis`.

The text and parts are built as for BWB (see [data model](data-model.md), "Article and
versions"): no empty lines, the heading not in the text. A number is taken once per act, and an
article without text is not written. `position` is its place in the act, `breadcrumb` its
divisions (`type` `hoofdstuk`, `label` `Hoofdstuk III`, `title`). `PART_OF` from article to
instrument.

**Semantic `eurlex`.** Scans the text of EU articles.

| Pattern | Confidence |
|---------|-----------|
| `artikel N Sr` / `artikel N Sv`, and `artikel 6:162 BW` (through its book, as in the Overview) | 0.95 |
| `CELEX:<id>` | 0.90 |
| `artikel N van Richtlijn / Verordening YYYY/N` | 0.85 |
| `Richtlijn` or `Verordening YYYY/N` | 0.70 |
| `BWBR0...` id | 0.70 |

All hits become `REFERS_TO` edges; missing articles with confidence 0.85 or more become stubs
(the article number as cited, without the historical articles and the number shapes of the
Overview).

**Semantic `eurlex-cjeu`.** Of every judgment of a court of the EU: `REFERS_TO` to each
judgment its paragraphs name by ECLI as the Court writes it ("Schrems, C‑362/14,
EU:C:2015:650, punt 73"; with or without `ECLI:`), 0.95, with the places as `semantic
rechtspraak-citations` keeps them (data model); one not loaded becomes a stub. `ANSWERS` from a
judgment referred from the Netherlands (`meta.country` `NLD`) to the decision that referred its
questions, the `*A9*` line of `meta.national`: its ECLI (1.0), else the decision (not a
conclusion) of its date with one of the case numbers between the brackets that end the line
("Rechtbank Rotterdam, Uitspraak van 20/03/2020 (ROT 19/1249)", 0.9), as `rechtspraak-referrals`
compares them; `meta.basis` `national_decision`. The articles a judgment cites are linked by
`semantic rechtspraak`. Derived in full on every run.

## BWB (Dutch legislation)

**Provides.** wetten.overheid.nl via the SRU service (`BWB_SRU`, `x-connection=BWB`)
and the toestand XML: one dated version of a regulation, with every article carrying
`stam-id`, `versie-id`, `inwerking` (in force from), `bron` (originating publication) and
`effect`; `<meta-data><brondata>` naming the originating and commencement publication and
their `<dossierref>`; `<extref>`/`<intref>` references with a `jci` address, to an EU act
with its CELEX number (`reeks="Celex"`), to an annex with an empty one; the preamble
paragraph `Gelet op ...` with `<extref>` to the legal basis; `<bijlage>` annexes. Each SRU
record also names the regulation's WTI file (`locatie_wti`, `.../bwb/<id>/<id>.WTI`), whose
first element `<algemene-informatie>` lists the official abbreviations (`<afkortingen>`).

**Retrieve.** The options are in [operations](operations.md#retrieve).

`retrieve bwb` fetches the current toestand of each regulation: the one in force today, else
(a repealed regulation) the last one before any toestand still to come; the SRU also lists the
toestanden of the future (`clients/bwb.py`). With it the `<algemene-informatie>` element of its
WTI file (kind `bwb-wti-algemene-informatie-xml`). Incremental mode fetches the ids it is given
and nothing without them; `--mode full` enumerates every regulation first; `--mode gaps` fetches
the laws the graph refers to and lacks: those with at least `--min-stubs` referred articles, and
every law a loaded regulation is issued under (its "Gelet op"). A regulation stored in the last
24 hours is not fetched again. In full mode a regulation whose toestand is the stored one is not
downloaded; its WTI file is read again after 30 days (`WTI_REFRESH_DAYS`), since an
abbreviation can change on its own. A page that is not XML is not stored, and 25 failed
downloads in a row fail the step (also in `bwb-history`).

`retrieve bwb-history` fetches every toestand of a regulation that is not stored yet (`--mode
full`: every one again), of the given ids or of every regulation whose current toestand is
stored, as `<bwb_id>@<start_date>`; a file the repository does not serve becomes
`bwb-toestand-xml-all-missing`. From 150 regulations it reads the toestanden from the SRU
listing, below that with one SRU query per regulation. With `--since` (as `retrieve all` gives
it) it asks the SRU only for the toestanden changed since then (`dcterms.modified`, one query
over all types) and, per regulation, for every toestand of one without any in the history.
`retrieve all` runs it after `bwb`. It
gives a law its versions (`history`, `versions` and `articles/at` of the API): the Wetboek van
Strafrecht has 126 toestanden since 2002, the Awb 236.

Enumeration queries `dcterms.type=="<type>"` for each type in `BWB_INSTRUMENT_TYPES`
(case-sensitive: `AMvB`, `ministeriele-regeling`), 1,000 records a page (the service silently
caps larger requests), at most 150,000 records per type. The service returns one record per
toestand, so ids repeat and are de-duplicated. A `<diagnostic>` response raises an error
instead of yielding an empty list. A toestand XML document is large; history runs are slow.

A WTI file is large too (27 MB for the Wetboek van Strafrecht: amendment log and related
regulations), but `<algemene-informatie>` comes first. The client reads the file in chunks of
8 KB and closes the connection once that element is complete; the element (about 1 KB) is
stored. A failed WTI download is reported as an error; the toestand is stored regardless. A
regulation without a WTI location or element gets no WTI record.

**Normalize `bwb`.** `core/bwb_xml.parse_toestand` is the single parser. Per toestand it writes
the Instrument ([its props](data-model.md#instrument): the dates and dossiers are those of the
regulation as enacted, not of the toestand), one Article per `(bwb_id, article number)`, or per
`stam-id` for an article with a heading and no number ([its
props](data-model.md#article-and-versions)), the Annex nodes of its `<bijlage>` elements (their
text, tables and links read as those of an article), and `PART_OF` from each article and annex
to the instrument. Two articles of one regulation with the same number share a key. A line
break in the text of an element, with the indent around it, is the layout of the XML and reads
as a space.

After the nodes it sets `short_title` on existing instruments from the stored WTI records
(`core/bwb_wti.py`). A regulation can have several abbreviations, listed alphabetically by the
source, so their order means nothing. The rule:

1. Case is ignored (`GW` and `Gw` are one abbreviation). The spelling kept is the one a
   citation writes, a capital and then lower case (`Gw`), else the first.
2. An abbreviation that several loaded regulations claim never wins, and neither does a code
   of `CODE_FAMILIES`: every book of the Burgerlijk Wetboek lists `BW`, and a short title must
   lead to one regulation.
3. Of the rest the shortest wins (`Sr` over `WvS` and `WvSr`, `WVW` over `WVW 1994`, `BW1`
   over `BW Boek 1`); of equal lengths the citation form, then the source order.
4. A regulation left with nothing has no `short_title`; one it had is removed.

Rule 2 depends on the other regulations, so every WTI record is read on every run, whatever
`--since` is, and a short title can change when more regulations are loaded. `BW` itself is
nobody's short title; the books are `BW1`, `BW2`, ... and a book is only citable once its WTI
record is loaded.

In the same pass it sets `aliases` ([the forms](data-model.md#search)), `abbreviation` on the
instrument and `instrument_abbreviation` on its articles; instruments that do not exist are not
created. And `legal_areas` and `policy_domains` ([their fields](data-model.md#instrument)), how
the WTI files a regulation (`core/bwb_wti.parse_subjects`): each label is looked up, without
regard to case, in the TOOI thesauri `scw_bwb_rechtsgebieden` and `scw_bwb_themas` (`retrieve
tooi`); a label they lack has no id or URI. Each gets a slug unique in its list
(`core/bwb_wti.assign_slugs`): that of the label, for a narrower concept whose slug is taken the
slug of its broader concept in front (`bestuursrecht-algemeen`), then a number. The slugs are
made over the whole thesaurus, or without it over the labels of every WTI record. An empty list
removes the prop.

**The code families.** `src/lawgraph/data/code_families.json` (`lawgraph code-families build`
and `check`, see [operations](operations.md#other-commands)) is made from the stored WTI records
(`core/code_families.families_from_wti`). A code is an abbreviation that two or more regulations
list, each of which also lists a book of it (`BW` with `BW Boek 6`): the book is the number of
that abbreviation (`7A` too), the code keeps the spelling most regulations give it. So the
families follow the WTI. Only `names`, the names a code goes by besides its abbreviation
(`Burgerlijk Wetboek`), which no WTI lists, is kept by hand; a build keeps it. A book whose WTI
record is not stored is not in its family. `core/code_families` answers every question about a
code: whether a name is one, in any case (`is_code_family`), and the number an article of a book
is cited by (`cited_number`: `6:162`) or stored by (`native_number`: `162`).

**Normalize `bwb-history`.** Reads every stored toestand once (`bwb_xml.read_toestand`: the
text, references and parts of an article are read only for a version it has not met, so a
toestand costs about its XML parse) and writes:

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
numbered the same way, they count ("artikel 1 064", a space between the thousands, names 1064). A
link inside a range the words name ("395a tot en met 397") stands; a book the words name
("van Boek 4", `6:162`) counts for a link into a book of a code. When the graph has no article
the words name, the link counts.
An edge is keyed by its two articles, so an article that refers to another twice keeps the span
of one; `props.references` keeps both. Self references are dropped and targets must exist —
nothing is stubbed. The edges of an article are derived in full: one its references no longer
support is removed (without `--since` every edge of the step it did not write, also of an
article whose references are gone).
Articles are processed in chunks of 500 so one lookup resolves a whole chunk's targets.

**Semantic `bwb-definitions`.** The definitions a regulation gives itself, its
begripsbepalingen (`core/bwb_definitions.py`), read from the stored toestand XML and kept in
`lg_instrument_definitions` (not a table of the graph, but a write that changes it raises the
data version; apart from the instrument's props, so its lists do not carry them). The BWB marks no definition as such; the article has a structure
all the same: an `<al>` that announces them ("… wordt verstaan onder:"), then a `<lijst>` of
`<li>` with its letter and JCI and an `<al>` "term: definition", a `<definitielijst>` of
`<definitie-item>` with its `<li.nr>`, `<term>` and `<definitie>`, or `<al>` after `<al>` that
begins with the term in `<nadruk>` (the Wft; a following `<al>` without a term goes on with the
definition before it); and a sentence that defines one term. Per definition `term`, `text`,
`article_key`, `article_number`, `place` (the letter; none in a `<lijst>` of type `ongemarkeerd`, and
none whose `<li.nr>` holds no letter or digit: a dash or a bullet), `jci`, `scope` (`kind`: `wet`, `wetboek`, `besluit`, `hoofdstuk`, `paragraaf`,
…, from the announcement; `path`: the `bwb-ng-variabel-deel` of that part, empty for the whole regulation; `reach`: `own_and_based` where the
announcement adds "en de daarop berustende bepalingen", else `own`) and `refers_to` (the BWB id of the regulation a definition
is: "wet: de Zorgverzekeringswet"). An onderdeel without a term before a colon is left out.
A regulation marks the terms of the regulations it is issued under too (`BASED_ON`, two
levels: a ministeriële regeling under an AMvB under a law): their definitions of reach
`own_and_based` whose part holds an article its preamble names, its own definition of a term
first, the nearest level first, and none for a term two regulations of one level define
differently. The article routes read them per data version (`term_matcher`) and mark no
term in the header of a table (`text_tables.table_heads`), which names its columns.
A law of the Staatsblad (`normalize staatsblad-laws`) is read the same way, from its stored
publications with the divisions later laws replaced in place, each article at the
`bwb-ng-variabel-deel` the BWB would give it (`/Boek1/Hoofdstuk11/Titeldeel11.1/Artikel1.11.1`,
its `path`), and kept under its official id (`stb-2026-56`); the law keeps how many it gives
(`definitions_found`). A run that reaches the end of the toestanden (the daily run, the last
slice) reads them: their ids sort after every BWB id.

**Semantic `bwb-captions`.** What each article is about, for its title (`Art. 6:162 BW,
Onrechtmatige daad`): of each regulation the breadcrumbs of its articles are read (no XML, no
text), and every article keeps `caption`, the deepest title of the divisions it stands in that
only one division of its law has (`core/article_caption.py`; a division is its whole path, so
the "Afdeling 1 Algemene bepalingen" that opens nearly every titel of Boek 6 is no caption, its
titel "Onrechtmatige daad" is). A caption that did not change is not written. `--since`: the
regulations whose toestand was fetched since then (the daily run); without it every one, also
in slices (`--after BWB-ID`, `--limit N`; the log names the last one read).

**Semantic `bwb-grondslagen`.** `BASED_ON` from a regulation to the article named in its
`Gelet op` paragraph, 1.0, `meta = {text, doc, basis_kind}`: `text` the reference without its
list word and law (`artikelen 3` is `3`, `107 van de Cyberbeveiligingswet` is `107`),
`basis_kind` `delegates` when the leden named of the article (none: all of it) hold a
delegation formula or another wording of a power ("bij besluit", "bij regeling", "kan nadere
regels stellen", "kan beleidsregels vaststellen"), else `mentioned` (`core/delegations.py`,
read from the text of the article). The BWB links a range ("artikelen 26 tot en met 30") as
one link to its first article: every article in force from the first to the last, in the
order of the law, gets an edge with the text of the range. Entries without an article, self
references and targets that are not in the graph are skipped. It reads `props.basis` of the
regulations, which `normalize bwb` keeps when it parses the toestand; no XML is read again.
Every run reads all of them, also under `--since`.

**Semantic `bwb-amendments`.** Reads the article versions that carry `origin_publication`:

1. upserts each originating and commencement publication as an Instrument (`stb_2019_33`),
   merging the dossier numbers of every version that mentions it;
2. resolves each `(bwb_id, stam_id)` to its Article, one query per chunk;
3. writes `Instrument(publication) -> ESTABLISHES | AMENDS | INTRODUCES | REPEALS -> Article`
   from the version `effect` (`nieuwe-regeling` establishes: the publication that enacted the
   regulation, Stb. 2026, 187 for the Cbw; `nieuw` introduces; `wijziging` amends;
   `vervallen` repeals), confidence
   1.0, `meta` = `effective_date`, `article_version`, `effect`, `source_publication`; one edge
   per publication, article and kind, with the earliest effective date. A republication
   (`tekstplaatsing-wijziging`, `tekstplaatsing-vernummering`: the Grondwet placed again as a
   whole, Stb. 2019, 33) changes nothing and has no edge; the edges of the step into an article
   that it no longer derives are removed;
4. writes `COMMENCES` from the commencement publication of a version that changes an article
   to its origin publication when they differ (Stb. 2024, 197 sets the date of Stb. 2024, 108):
   one edge per pair, confidence 1.0, `meta.effective_date` the earliest of its versions; the
   `COMMENCES` of the step that it no longer derives are removed;
5. writes `LEGISLATED_IN` from each publication and each regulation to the dossiers of
   `dossier_numbers` that exist (`queries/dossier_keys`: the dossier of that number, else the
   one of a Rijkswet of that number, `33440-(R1990)` for `33440`), and removes its
   `LEGISLATED_IN` from a regulation to a dossier the regulation no longer lists.

Versions with an unknown effect or without a matching article count as skipped.

**Semantic `bwb-annexes`.** Finds `bijlage <label>` in article texts, and the name of an annex
of the same regulation (its title without the parentheses at its end: "de bij deze wet
behorende Bevoegdheidsregeling bestuursrechtspraak"; a name of at least two words, not in the
annex's own articles), and writes `SCOPED_BY` (0.9 with a label or a name, 0.7 for "de
bijlage") with `meta.scope_type` `discretionary` when ministerial-designation wording is near
(`bij ministeriële regeling`, `Onze Minister kan ...`), else `fixed`. The annexes themselves
come from `normalize bwb` ([their props](data-model.md#article-and-versions)); a reference to
an annex that is not there gets a stub.

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
pattern can be overridden ([`LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>`](operations.md#pipelines)).

## Staatsblad

**Provides.** Staatsblad publications as XML from repository.overheid.nl
(`/frbr/officielepublicaties/stb/<year>/<id>/1/xml/<id>.xml`, a 404 is "not found"),
enumerated through the KOOP SRU (`dt.type=AMvB`, about 19,900 records; the laws `dt.type=Wet`
per dossier). Every KOOP SRU
search (`clients/_sru.py`) is paged by key, `dt.identifier>"<last>" sortBy dt.identifier`,
100 per page, because the service answers HTTP 504 for any record from position 10000 on;
the pages must add up to the reported total, and an SRU diagnostic or a failed request raises.

**Retrieve `--mode`.** `from-graph` (default): reads the Staatsblad publication of each stored
BWB toestand from its `meta.staatsblad_ref` and fetches those not yet stored, with the `bwb_id`
of that regulation in `meta` (run `retrieve bwb` first). `retrieve bwb` takes it from the XML of
the toestand when it stores it: the `<publicatie soort="Stb">` of the brondata (the one with
`effect="nieuwe-regeling"` first; `publicatiejaar` and `publicatienr`), `stb-<year>-<number>`,
null when it names none (the `<publicatie soort="Trb">` of a treaty names none). A toestand stored without it is read once by `from-graph`, which
writes it into its meta. `full`: every AMvB from the SRU. A page that
is not XML is not stored; a download that fails is skipped and asked for again the next run,
and 25 failures in a row fail the step. `from-graph` also fetches the laws of the dossiers whose bill passed: of every dossier
of kind `Wetgeving`, `Initiatiefwetgeving` or `Begroting` with `outcome` `aangenomen`, or
without an outcome at the phase `Eindtekst` (the Tweede Kamer passed it), and to which no
instrument is `LEGISLATED_IN` yet, the publications the SRU lists as `dt.type=Wet` or
`Rijkswet` of that dossier (`w.behandeldDossier`; a Rijkswet's by its number alone:
`33440` for `33440-(R1990)`), those not stored or changed since (`stb-wet-xml`). The outcome
is that of `semantic tk-dossier-outcomes` of an earlier run. A law the SRU lists without its
dossier (its metadata names none: most laws of 2009 and before) is not found this way.

**Normalize.** Document per record (`kind` "Nota van toelichting", `text` from the
`nota-toelichting` section (as the repository serves an AMvB now; `nota-van-toelichting`, then
`toelichting`, in older formats), `title` = the `citeertitel`, else the official title, else
the `DC.title` of the metadata, else its `intitule` (`Wet van 8 juli 2026, houdende …`), else
the first `titel` that is not the masthead of the series (`Staatsblad`), `bwb_id` = the regulation retrieve found it
for when its stored toestand names this publication, read from its XML as retrieve reads it (not
from its `meta.staatsblad_ref`), else the first BWB id in the XML), key
`stb_<identifier>`. No edges. The same Staatsblad number also exists as an amending Instrument;
that node comes from `bwb-amendments`.

**Semantic `staatsblad`.** `EXPLAINS` to the instrument with that `bwb_id` (0.85), else whose
`citation_title` occurs in the title (0.60); the confidence says which.

**Normalize `staatsblad-laws`.** A law the Staatsblad published and the BWB does not hold
(yet), such as the Wetboek van Strafvordering of Stb. 2026, 56, read from the stored
`stb-wet-xml` records (`core/staatsblad_laws.py`). Its XML has the elements of a toestand
(`boek` ... `artikel`, `lid`, `lijst`), without the ids and links of the BWB.

- A publication enacts a law when its wettekst holds an article of its own (not of a
  `wijzig-artikel`) numbered with a figure; the articles of a law that only changes others
  have Roman numerals. A `wijzig-artikel` of an enacted law is an article of its instruction
  alone.
- A later publication gives a division of such a law a whole new text when a `wijzig-artikel`
  says "<divisions> van het <citation title> komt te luiden:" with one `wijzig-divisie`: Stb.
  2026, 57 gives Boek 1, Hoofdstuk 10 and the Boeken 7 and 8 of the new code, which Stb. 2026,
  56 left reserved. The law is read with that text in place, in the order of the publications.
  A change of single words is not applied: the text is that of the publications, as enacted.
- The law is not written while the BWB holds a regulation the publication enacted
  (`enacted_publication`): then it goes with its articles and their edges, and its addresses
  lead to the BWB (`/render`, a 301 to the article of the same number, else to the law).

It writes the law `instruments/wet_stb_2026_56` ([props](data-model.md#instrument): `status`
`vastgesteld`, `in_force` false, `official_id`, `display_name` "Wetboek van Strafvordering
(Stb. 2026, 56)", `dossier_numbers` of every publication its text comes from), its articles
`articles/stb_2026_56_<number>` (`official_id`, `breadcrumb` with the divisions as a law prints
them, `source_publication` "Stb. 2026, 57" for an article a later law gave), `PART_OF` the law,
and each publication its text comes from as an instrument of kind `publicatie`
(`instruments/stb_2026_56`), which `ESTABLISHES` the articles of its own law and `INTRODUCES`
those it gave a text. Every stored law is a publication `LEGISLATED_IN` the dossiers its
`wetsluiting` names that the graph holds (`queries/dossier_keys`, a Rijkswet's by its number
alone), also one that only changes others and a budget law, whose text is not read (a law of
`Begroting` dossiers alone); one the graph does not hold yet (the BWB names most) is written as
above. Every run derives the laws in full, whatever `--since`.

**Semantic `staatsblad-law-references`.** `REFERS_TO` from the articles of a law of the
Staatsblad to the articles their text cites; the links of its XML are not read (they point at
the old law where the text names the new one). An enumeration whose articles each have their
parts is one citation ("de artikelen 98, eerste en tweede lid, 98c, eerste lid, … van het
Wetboek van Strafrecht", `core.citations.article_chain`).

- "artikel 2.8.16", "de artikelen 1.1.1 en 1.1.2", "artikel 3.1.1, eerste lid, van deze wet",
  not one followed by another law ("van de Wet op de rechterlijke organisatie", "Sr"; a name
  starts with a capital: "van de officier van justitie" names none): the article of that
  number of the same law (0.9, `meta.reference_kind` `intref`).
- "artikel 11.7a van de Telecommunicatiewet": the article of that law, read as a judgment is
  read (dated by the day the law was signed), a stub for one of a law not loaded at 0.9 or
  more (`meta.reference_kind` `extref`); the citation title of its own law names the law
  itself.

Each edge has the place of its number in the text and the parts named. Each article keeps
`unlinked_references`, the references of its text the step could not link (a law not in the
graph, "van die regeling", a number its law lacks), its law their sum: with the edges to a
stub, what `completeness.references` of the API says. Derived in full on every run.

## Staatscourant

**Provides.** Ministeriële regelingen as XML, enumerated through the KOOP SRU
(`dt.type=Ministeriele-regeling`, optional `dt.modified>=since`; the query also returns some
Staatsblad records, which are dropped: about 13,800 regulations).

**Retrieve.** `incremental` (default) searches the SRU (`--since`), `full` fetches all,
`--identifiers` fetches given `stcrt-YYYY-N` identifiers. An empty listing fails the step
unless it has a `--since`; a page that is not XML is not stored, and 25 failed downloads in a
row fail the step.

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
`citation_title` 0.65, a BWB id found in the text 0.75.

**Semantic `bwb-publications`.** `SAME_AS` from a paper of the Staatsblad or the Staatscourant
to the publication of the BWB of the same official id (`documents/stb_stb_2019_33` →
`instruments/stb_2019_33`, `documents/stcrt_stcrt_2020_12345` → `instruments/stcrt_2020_12345`):
the one publication, as its own source gives its text and as the BWB names what it introduced,
amended or repealed (`semantic bwb-amendments`). By the keys alone, confidence 1.0,
`meta.basis` `official_id`; every run derives them in full and removes those no longer derived.

## Eerste Kamer

**Provides.** The Kamerstukken of the Eerste Kamer, about 38,000 from 1994 on, from the KOOP SRU
(`KOOP_SRU`; creator `Eerste Kamer der Staten-Generaal`, `w.publicatienaam==Kamerstuk`,
`dt.type==Kamerstuk`, so attachments `blg-*` are left out). The Eerste Kamer has no API of its
own. Per paper: identifier (`kst-<dossier>-<letter>`, some `kst-<number>`), own title
(`documenttitel`), dossier title, kind (`subrubriek`), number in the dossier (`ondernummer`),
date, session year, dossier number (every `dossiernummer` of a paper on more than one bill, as
`dossier_numbers`) and the page on zoek.officielebekendmakingen.nl. Papers
before about 2007 have no kind and no own title in the source. The votes come from
eerstekamer.nl (`eerstekamer-votes`, below); the plenary reports and PDFs are not fetched.

**Retrieve `--mode`.** `incremental` (default): `--since` on `dt.modified`; `full`: everything.
`--limit` stops early. The SRU record is stored as `ek-kamerstuk-json`.

**Normalize.** Document `ek_<identifier>`, labels `EersteKamer` and `EK` (the API `chamber`
filter), `kind`, `number`, `title`, `subject` (dossier title), `session_year`, `date`, `url`,
`dossier_number` and `dossier_suffix` (the Tweede Kamer stores the two parts of `35925 VII`
separately), `dossier_numbers` (the label of every dossier the paper names, the first first:
`36600-VII`; a value without a leading number, `CXIX`, is left out; a record stored before the
client kept them all gives only its one number). A Roman numeral instead of a number (the own
dossiers of the Eerste Kamer, 525 papers) sets neither. A dossier no node holds (the Tweede
Kamer's OData has none before about 2005: thousands of the papers of 1995-2006 name one) is
written from its papers: `dossiers/<label>`, labels `EK`, `number`, `suffix`, `label`,
`title` (the dossier title its papers give most; of equal counts, that of the newest paper;
`title_source` `eerstekamer`), `source` `eerstekamer`, and no kind, phases or opening day (the
stage backfill runs over the Tweede Kamer's dossiers only). A dossier the Tweede Kamer has is
never written here; one it delivers later takes the node over (its props, `source` `tk`). No
edges here.

**Semantic `eerstekamer`.** `PART_OF` from the paper to the dossier (of the Tweede Kamer, else
the one written from the papers) with the same
number and addition, and to each other dossier of `dossier_numbers` by its `label`, 0.95.

**Retrieve `eerstekamer-votes`.** The Eerste Kamer publishes its votes only on its website
(no open data; its terms allow reuse, also commercial, with the source and the day it was taken
over; `robots.txt` allows these pages). `clients/eerstekamer_site.py` reads, a page every two
seconds with the `Concordans` User-Agent:

- `/stemmingen_per_vergaderdag?filter=alles`: every vote since June 2015, on a bill and on a
  motion, newest first, 25 to a page, grouped by the day of the meeting; a day
  that runs over a page starts the next one again (`(vervolg)`). One record per day
  (`ek-votes-day-html`, external id the date), from one page or two. `--since` stops at the
  first page that ends before it; `--mode full`, or a run without `--since`, reads the whole
  list. (`filter=wetsvoorstellen`, the bills alone, shows a vote on a motion as one on its
  bill, under the bill's name and number; the site has no list of motions alone.)
- `/verworpen_in_de_eerste_kamer`: every rejected bill since 1996 (two pages), stored whole on
  every run (`ek-rejected-html`).

**Normalize `eerstekamer-votes`.** `core/ek_votes.py` reads the structure of the pages,
never a sentence. A vote on a bill (`/wetsvoorstel/`) becomes a decision `ek_<date>_<label>_<n>`
(the n-th on that bill that day), a vote on a motion (`/motiedossier/`, `37.020, M`) a decision
`ek_<date>_<label>_<letter>` with `kind` `Motie`, `letter` and `motion_url`, `subject` the
motion's name (`Motie-Beukering (Fractie-Beukering) c.s. over …`) and also `ABOUT` the motion,
the Kamerstuk of the Eerste Kamer with that letter in its dossier (`Kamerstuk I 37020, M`, one
not in the graph is skipped); both labels `EK`, `chamber` `EK`: `result` (the outcome the Kamer shows, the `alt` of its
image: `Aangenomen`, `Verworpen`), `passed`, `method` (the text of the link to the report:
`Hamerstuk`, `Stemming bij zitten en opstaan, aangenomen`, `Hoofdelijke stemming, verworpen`,
`Algemene stemmen`, `Zonder stemmen`), `factions_for`, `factions_against`, `factions_noted`
(`aantekening gevraagd`), `subject` (the bill's name), `dossier_numbers` (the number as the
Tweede Kamer labels it: `36.600 VII` is `36600-VII`, `36.455 (R2188)` is `36455-(R2188)`),
`bill_url`, `source_url` (the part of the report) and `retrieved_on`; `ABOUT` the dossier, and
`VOTED` from each faction it names (the faction `ek_<slug>` whose `abbreviation` is the name; of
several, the one the composition observed that day, else the last before it), `choice` `Voor`,
`Tegen` or `Aantekening gevraagd`, `seats` of the faction when the vote falls in the period it
was observed, else 0; derived in full per decision, a name no faction has makes none (skipped). The votes
of a day are derived in full every time the day is read: a decision of that day the list no
longer gives goes, with its edges (logged per day); a day not read, or whose page gives no
vote, is skipped and left as it is. A vote
on a motion decides no bill (`semantic tk-dossier-outcomes` reads the votes on the bill). A
rejected bill gives its dossier
`ek_rejected` (`date`, `source_url`, `retrieved_on`); a rejected bill of a day read that no vote
of that day rejects is logged.

**Retrieve `eerstekamer-agenda`.** The agendas of the Eerste Kamer: each plenary sitting
(`/plenaire_vergadering/<yyyymmdd>`, record `ek-plenary-html`, external id the path) and each
day of committee meetings (`/commissievergaderingen_op`, record `ek-committee-day-html`,
external id the day). From the next sitting and the next day of meetings the pages are walked
forward (`latere`) to the last one planned and back (`eerdere`) to `--since`; a run without it
goes back to June 2015, and keeps where its walk back has got to in `pipeline_state`
(`retrieve eerstekamer-agenda`), once the pages before it are stored, so a run that broke off
goes on from there. One page at a time on the lane of eerstekamer.nl.

**Normalize `eerstekamer-agenda`.** `core/ek_agenda.py` reads the pages' structure:
the blocks of a sitting (the site's id, time, title, and the bills and notes linked, each by
the number it names) and the meetings of a day (committees, kind, time, and the decision
points: number, reference such as `28.973 / 29.683 / 32.793, AA`, subject and the decision as
the committee words it, kept, not read). Each is an activity (label `EK`) with `source_url`
and `retrieved_on`, `ABOUT` the dossiers it names and `LED_BY` the committees of the Eerste
Kamer a meeting names by abbreviation, each when the graph holds it. The site gives no status.

**Retrieve `eerstekamer-bills`.** The page of each bill of the Eerste Kamer
(`/wetsvoorstel/<number>_<words>`), one record each (`ek-bill-html`, external id the path,
`meta.status` the heading it was listed under). The bills are found on the list of every
committee (`/wetsvoorstellen_bij_commissie?key=…`, linked from its page; `robots.txt` allows
it, `/zoeken` it does not) and in the list of votes (`bill_url` of the decisions of `normalize
eerstekamer-votes`). A run over a window reads the bills a committee still handles and those
voted on since `--since`; a run without it every listed bill, the older pages of the lists
too. Pages are read one at a time on the lane of eerstekamer.nl.

**Normalize `eerstekamer-bills`.** `core/ek_bills.py` reads the page's structure:
its number from the title (`(36.945 XXII)` is dossier `36945-XXII`), `ingediend` under
`Kerngegevens`, and the progress module block by block (phase, house, the state class the
page gives it, and its papers with kind, date and number); never a sentence. The result is
`ek_bill` on the dossier of that number, when the graph holds it (else the page is skipped).

**Retrieve `eerstekamer-composition`.** The pages of eerstekamer.nl on who sits where today:
`/fracties` (every faction with its seats), `/commissies` (every committee), and the page of each
(`/fractie/<slug>`: its board and members; `/commissies/<slug>`: its members with faction and
role), and `/wie_zit_waar` (the plan of the hall), about 40 pages. The site gives today's
composition only, so every run reads it all. A page that differs from its newest stored version
is stored as a new version (`ek-composition-html`, external id `<path>@<day>`, `read_on` that
day); an unchanged one only gets `last_read_on` on that version. Raw so holds every
composition read, and from when to when.

**Retrieve `eerstekamer-composition-observed`.** Once: the composition the graph holds
(the factions and committees with `chamber` `EK`, the members with an `ek` prop, the
`MEMBER_OF` edges into them, with their periods) and the external ids of the versions of
`ek-composition-html` stored at that moment, which it covers, in one record
(`ek-composition-observed`, external id `observed`). It keeps the periods observed before the
pages were stored per version. It makes no request, stores nothing once the record is there or
when the graph holds no composition, and runs before `retrieve eerstekamer-composition` in the
lane of the site.

**Retrieve `eerstekamer-mutations`.** The lists of `/personele_mutaties`, the changes in the
composition per term (`ek-mutations-html`, external id the path: the current term and each
earlier term it links), the current term's on every run and that of a term that ended once (it
does not change), and the page of each change they list
(`ek-mutation-html`, external id the path, `meta.date` and `meta.headline` as the list gives
them), once.

**Retrieve `eerstekamer-persons`.** The page of each member of the Eerste Kamer
(`/persoon/<slug>`, `ek-person-html`, external id the path): those the stored composition
lists and every person a stored change of `retrieve eerstekamer-mutations` links (every term
since 2003). A page not stored is fetched, and one again when a change that links the person
was fetched after it; with `--sitting` (`weekly.sh`) every sitting member's.

**Retrieve `kiesraad`.** The page of each election of the Eerste Kamer since 2003 in the
Kiesraad's databank (`kiesraad-ek-result-html`, external id the code, `EK20230530`), once:
the seats each list won (`core/kiesraad.py` reads the data in the page).

**Normalize `eerstekamer-mutations`.** The seats of the Eerste Kamer day by day
(`lg_ek_terms`, `lg_ek_seats`, written whole). A term begins on the day the new Kamer was
installed (the Tuesday two weeks after the week of the election, as every one since 2003)
with the seats each list won. A faction is known by its names: today's factions by their
abbreviation and the full name their page's path spells; each list of the term (its name,
the abbreviation in brackets) as the faction of today it is one of, else as a faction of its
own; and each name in full the items write with its abbreviation (`Onafhankelijke
Senaatsfractie (OSF)`). A faction of the past goes by the name the items call it most. Then
the changes (`core/ek_mutations.py`), each read from a text by pattern (`basis`
`tekst`, the headline or sentence as `words`):
- of an item of `/personele_mutaties`: a member sworn in (and the one they succeed or follow
  gone, when no item of their own says when, in the faction of the one sworn in), a member
  gone (on the day the text names: `vertrekt per`, `treedt terug per`, `per … gestopt`, the
  day after `tot en met`), from one faction to another or to a faction of their own
  (`Fractie-<name>`), several together (two who join a faction, the members a new faction
  lists, those who leave for the Tweede Kamer), a faction renamed (`tot voor kort de … geheten`);
  where the text says no more, its headline; a member standing in for one on leave or ill
  changes no seat, nor does a chair, a clerk or a debate; one sworn in within the term's
  first 60 days with no seat open was elected and sworn in late;
- of a faction's own page (`retrieve eerstekamer-composition`): two factions merged and a
  faction renamed (`Van … tot … was de naam van de fractie …`).
The walk (`core/ek_seat_walk.py`) takes a member's faction from the change, else the one it
last saw them in. A term
is `checked` when every change's faction is known, no faction goes below zero and no day has
more than 75 seats; a past term also when it ends on 75, the current term when its last
stretch is today's composition, per faction. What does not add up is listed in
`mismatches`.

**Normalize `eerstekamer-persons`.** `core/ek_persons.py` reads a member's page: their
periods in the factions of the Eerste Kamer, the current first, as its opening says them ("is
vanaf 11 juni 2019 lid van de D66-fractie", "was van 28 juli 2019 tot 13 juni 2023 lid en
voorzitter van de Fractie-Otten", "Eerder was hij van … tot …"; the last day the one before
its "tot", the day the next began), and their birth date (a sitting member's page only). A
page is the member's the composition gave it (`ek.path`), else the member of the Tweede
Kamer born that day whose surname ends its name without the faction after it, when exactly
one is (`core/ek_persons.match_member`, as the composition matches a person); else none (a
former member who never sat in the Tweede Kamer has no member), and the page is skipped. The
periods go
to `ek_faction_memberships` of the member, as `faction_memberships`: `faction_id`,
`faction_key` (the faction of the Eerste Kamer of that abbreviation or name observed on the
first day, as the votes match it; null for one gone before the composition was first read),
`abbreviation`, `name`, `from_date`, `to_date`, `chamber` `EK`. A member's votes read them
with those of the Tweede Kamer. Each period's start and end are checked against the changes
of `normalize eerstekamer-mutations` of that member and the first days of the terms (within
a week): those no change dates are counted and named in the log, not changed.

**Retrieve `eerstekamer-motions`.** The page of every motion of the Eerste Kamer the list of
votes named (`/motiedossier/…`, the `motion_url` of its decisions on a motion; record
`ek-motion-html`, external id the path), each once: a motion's page does not change after its
vote. `--limit` caps the pages of one run; the log says how many are left after it.

**Normalize `eerstekamer-motions`.** `core/ek_motions.py` reads the page by its structure: the
sentence that says what the motion asks ("In deze motie wordt de regering verzocht …"), the link
to its PDF, and its key data (`nummer`: the number of its dossier and its letter, `37.020, M`;
`ingediend`; `bij`; `behandelstatus`; `indiener(s)` and `mede ondertekend door`, each a link to
the page of the person with their name and faction). It writes on the motion's Kamerstuk of the
Eerste Kamer (the paper with that letter in its dossier, `Kamerstuk I 37020, M`): `summary`,
`submitted_on`, `debate`, `status`, `motion_url`, `pdf_url`, and `actors` as the Tweede Kamer
gives the signatures of a motion (`name`, `faction`, `role` `Eerste ondertekenaar` or `Mede
ondertekenaar`, `person_id` the Tweede Kamer's id of their member), so a motion of either
chamber names its signers alike; and `AUTHORED` from each member. A signer is the member of
their page as `normalize eerstekamer-persons` matches a page; one whose page is not stored, or
of no member, is a name without a member and no `AUTHORED` (skipped). A motion whose Kamerstuk
is not in the graph is skipped, and nothing is written of it.

**Normalize `eerstekamer-composition`.** `core/ek_composition.py` reads the pages'
structure and labelled fields (`Anciënniteit`, `Woonplaats`, `Geboortedatum`, `<function>:
<name> (sinds <date>)`), never a sentence. A snapshot is the composition on a day a version
was read: the newest version of every page read on or before it. The snapshots are walked in
order, from the composition of `ek-composition-observed` when it is stored (the versions it
covers are not walked again), else from nothing; the graph is not read, so a rebuild from raw
gives the same periods. A faction `ek_<slug>` with its seats and board, a committee `ek_<slug>`, and a
member for every person on a faction page: the member of the Tweede Kamer born that day whose
surname ends the name as the Eerste Kamer writes it (`match_member`, as for a member's page),
when exactly one is, else one of its own
`ek_<slug>`; a member keeps the node it was first given, and its `ek.seat` is where the plan
of `/wie_zit_waar` draws it (its places, each linked to a faction's page and, through the
member's biography, to `/persoon/<slug>`; an empty place is `l-virt`). `MEMBER_OF` from the
member to its faction and committees (`role` in a committee). Periods are
as observed: `observed_from` the day of the first snapshot that shows a faction, committee,
membership or seat, `observed_until` the day of the first that no longer does.

## ECHR

**Provides.** HUDOC judgments (`HUDOC`, `/app/query/results`), filtered by
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

**Retrieve.** `--since` (`kpdate >=`; from the day of the latest judgment against `--respondent`
that is stored when that is earlier, so a missed run leaves no hole), `--limit` (default 10,000); `--mode full`
reads up to 50,000 and fetches every text again; `--mode gaps` the judgments cited by ECLI,
against any state (the English item, else the French one). After the judgments, every run
fetches the text of each stored or fetched judgment that has none: of its English item, else
its French one (none for a judgment in neither), 0.5 s apart. An item HUDOC has no text for is
skipped and remembered as missing, and asked for again after 30 days: HTTP 404, HTTP 204 (an
empty answer, as for 001-168072), an answer that is no DOCX, or an HTTP 5xx that outlasted
the retries (HUDOC answers HTTP 500, run after run, for an item it cannot convert, such as
001-208029). A 5xx counts toward the failures in a
row that end the run as a host that is down. The 200 judgments against the Netherlands take
about 100 s the first time (on average 170 KB of XML, 22 KB compressed, the largest about
1 MB); a daily run fetches only the texts of new judgments.

**Normalize.** Judgment per judgment: by its ECLI (the node a Dutch judgment that cites it
has), else by item (`echr_<itemid>`); the English item's record, else the French one's, else
another; `appno`, `title`, `date`, `articles`, `conclusion` (and from it what the Court found
per article, `echr_findings`, and `outcome`: `core/echr_findings.py`), `importance` (a number;
another value is a problem and is left out). A text
record adds
`text` and `paragraphs` to the node of its `meta.ecli` (see [data model](data-model.md),
"Judgment").

**Semantic `echr-versions`.** HUDOC holds a decision once per language. One with an ECLI is
one node already; one without is a node per item. Those with the same application numbers
(`appno`, in any order) and the same date are one decision: the English version is kept (else
the French, else the lowest key), every other is `SAME_AS` it (`meta.basis` `appno_and_date`,
1.0) and names its HUDOC item id in `same_as`, so the lists show the decision once. The other
documents of a case (admissibility, Chamber, Grand Chamber) have another date and stay apart.
Derived in full each run.

**Semantic `echr`.** `REFERS_TO` from a judgment to the articles of the Convention it
applies, at 0.95, and to a BWB instrument whose id its `conclusion` names, at 0.80. The
Convention is the BWB treaty `BWBV0001000`, whose articles are numbered as HUDOC numbers them:
HUDOC's `8;8-1;8-2;41;P1-1` is article 8 (`meta.leden` `["1", "2"]`) and article 41. `P1-1`, an article of a Protocol, is article 1 of
the Protocol's own BWB treaty: the curated list `echr-protocols` gives it (P1 is
`BWBV0001001`, P4 `BWBV0001029`, P6, P7, P12, P13), from the titles and the place and date of
signing the BWB gives. A Dutch judgment that cites "art. 8
EVRM" reaches the same article. While a treaty is not loaded its cited articles are stubs
(`bwbv0001000_8`, `bwbv0001001_1`; `bwb_id` and `article_number`), as the cited articles of any
law that is not loaded, and `retrieve bwb --bwb-id BWBV0001000` loads it. The text of a
judgment (its DOCX) cites other decisions of the Court by application number ("Kılıç v. Turkey,
no. 22492/93, § 62"; "(dec.), no. 12345/01, 3 May 2005"): `REFERS_TO` to the decision of that
number and of the date that follows within the citation, or without one to the only decision of
the number, as for a Dutch judgment (`rechtspraak-citations`); its own numbers are no citation.
The edges of a judgment are derived in full: one it no longer supports is removed.

**Known limits.** An article of a Protocol the list does not have (11, 14, 15, 16: they change
the procedure of the Court) is not linked; `lawgraph check` counts them, and `semantic echr`
logs how many it left out.

## Verdragenbank

**Provides.** Treaties the Netherlands is party to, from the KOOP SRU
(`KOOP_SRU`, `c.product-area==vd AND w.documenttype==verdrag`, 250 per page):
titles (nl and en are separate records with the same id and are joined), signing and
in-force dates, type (`Bilateraal`, `Multilateraal`, `Plurilateraal`), status
(`Inwerkinggetreden`, `Buitenwerkinggetreden`, `Totstandgekomen`, ...) and the six-digit
Verdragenbank id (`verdragsnummer`), about 8,800 treaties. Records of amendments
(`wijziging`) are not read. An empty result raises: the endpoint or its data model has changed.

**The item XML.** The SRU record links (`gzd:url`) to the item XML of the treaty
(`repository.overheid.nl/frbr/vd/<id>/1/xml-nl/<id>.xml`), which holds the rest of the
register's page: the place of signing, the Tractatenblad publications ("1951, 154" with what
they publish), the parties with the dates of signature, ratification (or another consent),
provisional application, entry into force, denunciation and termination and whether they made
reservations or objections, the parts of the Kingdom it applies to and from when, the dossiers
of its approval, and the treaties it belongs to (a Protocol to its Convention) or that belong
to it. The text of a reservation is not kept, only that there is one.

**Retrieve.** The SRU records (`verdrag-json`), then the item XML (`verdrag-xml`) of every
treaty that is not stored yet or that the register `modified` since; a 404 is remembered as
missing, a page that is no XML is not kept. The register has no fetch per treaty, so every run
reads it in full; `--mode gaps` does so only when a treaty is referred to that is not loaded.
`--limit` stops early (and bounds the item XML to those treaties); `--only-stored` keeps
the run to the treaties whose record is stored already (a small database).

**Normalize.** Instrument `verdrag_<id>` (`kind` `verdrag`, `multilateraalverdrag` or
`bilateraalverdrag`, `jurisdiction: int`, `in_force` only for `Inwerkinggetreden`,
`treaty_number` its id), and what the item XML registers on the same node
([its props](data-model.md#instrument)).

**Semantic (`semantic verdragenbank`).** From what the register names, source `verdragenbank`:
`PUBLISHED_IN` to each Tractatenblad (`trb_<year>_<number>`, `meta.description` as the register
writes it; one not in the graph yet becomes a publication with what its id says, one the BWB
loaded is left as it is); `LEGISLATED_IN` to the dossier of its approval when that dossier is
in the graph (the leading digits of `DossierNummer`: "8689 (R542)" is 8689, which names the
dossier `8689-(R542)` as `queries/dossier_keys` resolves it);
`PART_OF` to the treaty it belongs to (`Moederverdrag`) when that treaty is in the graph, which
the article count and the citation count of that treaty leave out; `SAME_AS` into it from the BWB
text of the treaty (`BWBV…`) whose `treaty_number` it has. Derived in full on every run.

**Joined to the BWB by number.** The toestand of a BWB treaty names its Verdragenbank id
(`<wetgeving soort="verdrag" verdragnummer="005132">`, the EVRM), which `normalize bwb` writes
as `treaty_number`; the Verdragenbank record has no BWB id. The number is the join: the
instrument detail lists the other instruments with it (`same_treaty`), and `lawgraph check`
counts the BWB treaties whose number the Verdragenbank has, does not have, or that name none.
The BWB has 3,703 treaties and the Verdragenbank 8,774 (September 2026). Titles are not
compared.

## Rijksoverheid

**Provides.** Every cabinet since 1945 (32 pages; Rijksoverheid describes Biesheuvel I and II
as one cabinet), from `rijksoverheid.nl/regering/over-de-regering/kabinetten-sinds-1945`
(`RIJKSOVERHEID`), published under CC0. A page names each seat (`Minister van
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
minister-president and the minister of Algemene Zaken are one seat (`az/minister-president`),
every viceminister-president sits in the shared seat `viceminister-president`. A heading can
name several posts (`Vice-minister-president en minister van Financiën`, `Minister-president,
tot 15 sept. 1947 tevens minister van Binnenlandse Zaken`), each with the days it gives. The
rules of a seat:

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
(`core/signatories.py`):

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
  held it (`core/signatories.match_by_function`); two such members match none. The log says
  how many were found so.

A holder who matches no member or several, or a member two people match, is left out (and
logged). The member gets its posts and names ([its props](data-model.md#member-members)); a
member who holds no post any more loses them. A holder no Tweede Kamer person matches becomes a
member of their own, key `rijksoverheid_<initials>_<surname>`, label `Rijksoverheid`; once a
later run matches them, that member is removed. Every page is read on every run. Needs
`normalize tk-dossiers` (the members, their signatures and the factions).

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

Every cabinet becomes a node of `cabinets` ([its props](data-model.md#cabinet-cabinets)): it
ends at the beëdiging of the next, its `prime_minister` is the member who held
`az/minister-president` first, its `parties` are those of the bewindspersonen sworn in on the
first day, the one with most first, each with the faction of its name. The cabinets are derived
in full: one no source names any more is removed. Each member gets an edge `SERVED_IN` to each
cabinet they held a post in, `meta.posts` the posts; the edges are derived in full on every run.

`lawgraph verify cabinets` ([operations](operations.md#other-commands)) checks the result
against the rules of `core/cabinet_checks.py`: no post outside its cabinet, no two holders of a
seat at once without `overlaps_with`, phases that follow each other from start to end.

## Courts

**Provides.** The Instanties value list of the Rechtspraak
(`https://data.rechtspraak.nl/Waardelijst/Instanties`, `RECHTSPRAAK`): every court an ECLI
can name, with its code (`Afkorting`, the court part of the ECLI), official name, `Type` and the
days it existed; 261 courts, of which 237 have a code (the military and colonial courts before
ECLI have none). A free public service of the Rechtspraak, like its judgments.

**Retrieve.** `retrieve rechtspraak-instanties`: the list, one `rs-instanties-xml` record
(external id `Instanties`, meta `url` and `read_on`), on the lane of `retrieve rechtspraak`.

**The court table.** `src/lawgraph/data/courts.json` (`lawgraph courts build` and `check`, see
[operations](operations.md#other-commands)) is made from the stored list
(`core/court_sources.build_courts`); run `semantic graph-list-stats` when a tier or kind changed.
Per court: `code`, `name`, `type`, `tier`, `court_kind`, `from`, `until`, and `owms_term` (the
`creator` by which the index of the Rechtspraak names it).

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
own code, the codes of the courts of the EU (`C`, `T`, `F` of `ECLI:EU:…`: tier and court_kind
`hvj_eu`) and the courts published under `XX` by the name their metadata gives (`KB` the Kroon,
the EHRM, the Court of Justice of the EU under both its names); `decision_kinds.json`, the kind
of decision a kind of court gives when neither the metadata nor the kop names one.

## TOOI

**Provides.** The value list `rwc_ministeries_compleet` of TOOI (Thesauri en Ontologieën
voor Overheidsinformatie, KOOP; `TOOI`): every ministry since about 2010 with its code
(`mnre1045`), abbreviation, begin and end, its former names (`HistorischeVersie` with the
last day of each) and the events between them (`Oprichting`, `Samenvoeging`,
`Afsplitsing`, `Toestandswijziging`), each with the Staatscourant decree it rests on. The
content of the TOOI registers and value lists may be used by anyone without restriction
(TOOI beheerplan, 2.3 Rechtenbeleid). Numbered versions; the page of the list links each.

Also the thesauri of the BWB: `scw_bwb_rechtsgebieden` (104 legal areas, 32 main areas, SKOS
`broader`) and `scw_bwb_themas` (21 government themes), the concepts the WTI of a regulation
files it under by label (see BWB, `legal_areas`).

**Retrieve.** The latest version, one `tooi-ministries-jsonld` record (external id
`rwc_ministeries_compleet`, `payload_json.items`, `meta.url`, `meta.read_on`), and one
`tooi-thesaurus-jsonld` record per thesaurus (external id the name of the list). Two requests
per list; always in full. A page without versions, or a version without a ministry or a
concept, raises.

**The ministry table.** `src/lawgraph/data/ministries.json` (`lawgraph ministries build` and
`check`, see [operations](operations.md#other-commands)) is made from the stored TOOI list, the
stored Rijksoverheid cabinet pages and the curated list
`src/lawgraph/data/curated/ministries.json` (`core/ministry_sources.py`). Per ministry name (the
key, `ez`): the name, the TOOI code and abbreviation, and its periods, each with `from`, `until`
(the last day), `successor`, `basis` (the decree) and `source`:

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

`normalize all` and `semantic all` run in registry order; each row needs what is above it. A
retrieve that needs a normalize step names it in the registry (`reads`), and warns when the
graph holds none of what it chooses from. A normalize step reads the raw records of the
retrieve of its own name, and of those its `fed_by` names: `normalize bwb` also the TOOI
thesaurus of `retrieve tooi`, `normalize rijksoverheid` also `retrieve staatscourant-posts`.
`lawgraph bootstrap --plan` shows every step of a build with what it waits for.

| Step | Needs |
|------|-------|
| normalize `bwb-history` | `normalize bwb` (articles and instruments) and stored `bwb-toestand-xml-all` |
| normalize `tk-dossiers` | `normalize tk` (the case-to-dossier links read `cases`) |
| normalize `rijksoverheid` | `normalize tk-dossiers` (the members, their names and signatures, the factions a party is matched to, and the commitments) and `retrieve staatscourant-posts` |
| normalize `tk-document-links` | `normalize tk-dossiers` (the documents and activities it links) and stored `tk-document-links` |
| normalize `tk-case-actors` | `normalize tk` (the cases) and `normalize tk-dossiers` (the members and committees it links), and stored `tk-case-actors` |
| normalize `tk-content` | `normalize tk-dossiers` (it writes on the Documents that step made) and stored `tk-kamerstuk-xml` |
| normalize `staatsblad-laws` | `normalize bwb` (the regulations the BWB holds, `enacted_publication`) and `normalize tk-dossiers` (the dossiers of its publications), and stored `stb-wet-xml` |
| retrieve `staatsblad` (from-graph) | `retrieve bwb`; for the laws the outcome of the dossiers (`semantic tk-dossier-outcomes` of an earlier run) |
| retrieve `staatscourant-posts` | `retrieve rijksoverheid` (the posts whose function names no ministry) |
| retrieve `tk-content` | `normalize tk-dossiers` (the TK documents whose XML it fetches) |
| semantic `tk-transposition-tables` | stored `tk-transposition-table-pdf`, `tk-transposition-document-xml` and `stb-transposition-xml`; the `eu-celex-html` of the EU acts whose articles `normalize eurlex` wrote, with those acts and articles; the laws and articles of `normalize bwb` and `normalize staatsblad-laws`, the historical identities of `normalize bwb-history`, and the `LEGISLATED_IN`, `ESTABLISHES` and `INTRODUCES` of their publications (`normalize staatsblad-laws`, `semantic bwb-amendments`) |
| retrieve `eerstekamer-bills` | `normalize eerstekamer-votes` (the bills the EK decisions name, `bill_url`); the bills its committees list come from the site |
| retrieve `eurlex` (incremental, `com`) | `normalize eurlex` (the EU instruments with a CELEX number) |
| semantic `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `bwb-relation-types` | normalized articles; `bwb-amendments` also `bwb-history` versions and the dossiers of `normalize tk-dossiers`; `bwb-relation-types` runs after `bwb` |
| semantic `bwb-definitions`, `staatsblad-law-references` | `normalize staatsblad-laws` (the laws of the Staatsblad and their articles); `bwb-definitions` also stored `bwb-toestand-xml` and `stb-wet-xml`, `staatsblad-law-references` the instruments and articles of `normalize bwb` (the laws it cites) |
| semantic `bwb-publications` | `bwb-amendments` (the publications of the BWB) and `normalize staatsblad` and `staatscourant` (their papers) |
| semantic `tk-amendment-articles` | `tk-amends` (the document-to-instrument `AMENDS` edges), document text and sections from `normalize tk-content`, instrument names |
| semantic `tk-mvt` | `bwb-amendments` (`LEGISLATED_IN` and the change edges it walks), `normalize tk-dossiers` (the document-to-dossier `PART_OF` edges) and `tk-dossier-relations` (`SECOND_READING_OF`) |
| semantic `tk-mvt-articles` | as `tk-mvt`, and the sections of `normalize tk-content` |
| semantic `eerstekamer` | `normalize tk-dossiers` and `normalize eerstekamer` |
| semantic `tk-dossier-titles` | `normalize tk-dossiers` (documents, activities and their edges to the dossier) and every source that makes a dossier (`normalize eerstekamer`, `eerstekamer-bills`) |
| semantic `tk-dossier-outcomes` | `bwb-amendments`, `normalize staatsblad-laws` and `verdragenbank` (`LEGISLATED_IN`), `normalize tk-dossiers` (documents, decisions and their edges to the dossier) and `normalize eerstekamer-votes` (the votes of the Eerste Kamer, `ek_rejected`) |
| normalize `eerstekamer-composition` | `normalize tk-dossiers` (the members of the Tweede Kamer its members are matched to) |
| normalize `eerstekamer-mutations` | `normalize eerstekamer-composition` (the factions of today and their history) |
| normalize `eerstekamer-persons` | `normalize eerstekamer-composition` (the members and factions of the Eerste Kamer) and `normalize eerstekamer-mutations` (the changes its periods are checked against) |
| normalize `eerstekamer-motions` | `normalize eerstekamer` (the Kamerstukken of the Eerste Kamer it writes on) and `normalize eerstekamer-persons` (a page of a person matched to a member as there) |
| normalize `eerstekamer-agenda` | `normalize tk-dossiers` (the cases and dossiers its activities are about) and `normalize eerstekamer-composition` (the committees that lead a meeting) |
| normalize `eerstekamer-bills` | `normalize tk-dossiers` (the dossiers it writes the bill pages on) |
| normalize `eerstekamer-votes` | `normalize tk-dossiers` (the dossiers the votes are about) |
| semantic `tk-government` | `normalize rijksoverheid` (cabinets and posts), `normalize tk-dossiers` (commitments, documents, `AUTHORED` and `PART_OF` edges) |
| semantic `tk-person-duplicates` | `normalize tk-dossiers` (the members), `normalize rijksoverheid` and `normalize eerstekamer-persons` (their roles) |
| semantic `tk-coalition-votes` | `normalize rijksoverheid` (cabinets and posts), `normalize tk-dossiers` (the votes and the seats of the members) |
| semantic `tk-motion-kinds` | `normalize tk-dossiers` (the motions and the decisions with their subject) |
| semantic `tk-paper-outcomes` | `normalize tk-dossiers` (the decisions, the papers and their `PART_OF` cases), `normalize eerstekamer-votes` and `normalize eerstekamer-motions` (the votes and the status of a motion of the Eerste Kamer) and `tk-dossier-relations` (`REVISES`) |
| semantic `tk-cited-papers` | `normalize tk-dossiers` (the papers with their dossier number, suffix and sequence, and the dossiers) and `normalize tk-content` (the text and footnotes of the letters) |
| semantic `tk-dossier-relations` | `normalize tk` (`related_cases` of the cases, the agendas of the activities and the decisions taken in them), `normalize tk-dossiers` (the dossiers and their titles, the papers of the cases) and `normalize tk-content` (the text of the memoranda) |
| semantic `graph-article-terms` | `graph-light` (the light summaries) and every citation of an article by a judgment (`rechtspraak`, `rechtspraak-citations`). With `--since` (`semantic all --since`, `daily.sh`) the articles cited since then, against the counts of the last whole run; without it (by hand after its first deploy, and `weekly.sh` on Sunday) the counts of every summary again and every article cited 3 or more times |
| semantic `graph-list-stats` (last step of `semantic all`) | backfills what the list endpoints sort and filter on: instruments (`jurisdiction`, `article_count` (its articles in force without stubs: the `total` of `/articles`), `kind`, `inbound_citation_count`, `amending`: a BWB regulation whose articles are numbered `I`, `II`, ... and of which one or more changes another regulation, or of which most do: the BWB puts "Wijzigt <regulation>." in place of such an article), judgments (`court_code`, `tier`, `court_kind`, `date_eff`, `inbound_citation_count`, `outbound_citation_count`; `decision_kind` where it is null, from the kind of court, and the curated `names` of a stub), articles (`inbound_citation_count`), committees (`active_dossier_count`, after `tk-dossier-outcomes`). `--instruments-only`, `--judgments-only`, `--articles-only` or `--committees-only` does one of them; `--dry-run` writes nothing |
