# Data model

The graph is a set of document collections (nodes) and one edge collection (`edges`).
Concepts, collections, relations and property names are English throughout; Dutch appears only
in values that a source owns (a document `kind` such as `memorie van toelichting`, an edge
`status` such as `voorgesteld`).

## Nodes

A node is a document `{id, key, type, labels, props}`:

- `key` is deterministic (`make_node_key(...)`: parts joined with `_`, lower-cased, ASCII,
  non-alphanumerics replaced by `_`), so every pipeline can be re-run. A query makes the
  same key in SQL with `lg_node_key(text)`.
- `type` is the `NodeType` (`instrument`, `article`, `instrument_version`, `article_version`,
  `annex`, `judgment`, `dossier`, `case`, `document`, `activity`, `decision`, `commitment`,
  `member`, `faction`, `committee`, `cabinet`). Every type has its own collection and every
  collection holds one type, so the collection in an id says the type. Each collection is
  declared once, with its type, concept, props schema and whether it takes stubs
  (`core.models.COLLECTIONS`); `Node.type` is read from the collection.
- `labels` tag the origin (`BWB`, `EU`, `TK`, `Rechtspraak`, `ECHR`, `CJEU`, `EersteKamer`, ...). Upserts
  union labels.
- `props` of a node built as a `Node` are validated against the strict Pydantic schema of its
  collection (`core/props.py`); an unknown field is rejected, also in a nested object. Upserts
  merge props (shallow), so several pipelines can add fields to one node.
- `display_name` is the name to show. A name longer than its limit (a paper's title 120
  characters, a commitment 80, a Staatscourant title 100, other titles `MAX_TITLE_CHARS`) is cut
  with an ellipsis (`core/display.shorten`) at the last word boundary, or at the limit when
  that boundary lies in the first half; the full title stays in `title`.
- `stub: true` marks a placeholder created because something referred to it before its own
  source was ingested. A stub judgment has a valid ECLI (`core/ecli.is_valid_ecli`) and an edge
  at it; `semantic rechtspraak-citations` removes one that has none.

The props of each collection are a table below, made from the docstrings of its schema
(`python -m lawgraph.core.props_catalogue`; a test fails while a table differs). A field of a
nested object follows the field that holds it (`ek_bill.progress[].phase`). The fields every
collection shares:

<!-- props:common:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `display_name` | `str` | The name to show; a long name is cut with an ellipsis (`core/display.shorten`), the full title stays in `title`. |
| `source` | `str` | The source the node was read from: `bwb`, `eurlex`, `rechtspraak`, `echr`, `cjeu`, `tk`, `eerstekamer`, `verdragenbank`, `rijksoverheid`, ... |
| `stub` | `bool` | `true` for a placeholder made because something referred to it before its own source was loaded. |

<!-- props:common:end -->

Other collections: `raw_sources` (the records as fetched, their XML and HTML in the payload
store) and `pipeline_state`: per phase when its last complete `<phase> all` began (for
`--since last`), where a long retrieve broke off (`retrieve eerstekamer-agenda`), what the last
run did with each source (`source <name>`, docs/api.md "Completeness") and the marks of
`lawgraph bootstrap` (`bootstrap <step>`). `lg_heat` keeps the heat of the whole graph (`semantic
graph-heat`): per window of 3, 6, 12 and 24 months the 50,000 nodes with the highest count, and
`lg_heat_state` when it was counted; writing them raises no data version. `lg_judgment_light` holds per
judgment what a neighbour, a node of a neighbourhood or of a path shows of it (its ecli, names,
summary to 401 characters, date, court, case number, source, jurisdiction, stub, translation,
advocate-general, and how it ended: `outcome`, `conclusion_outcome` with their sentences and
`echr_findings`), kept by triggers on every write of `judgments` and filled once by
`semantic graph-light`; it raises no data version either. `lg_judgment_persons` holds per
judgment the persons it names (`parties` not anonymised, and their `representatives` with the
party's alias or name), with its `date_eff` and `words`, the name folded with every run of
other characters a space (" mr drs r van gelder "), under a trigram index: the search finds a
judgment by them. A trigger keeps it on every write of a judgment's props and `semantic
graph-light` fills it for the judgments written before; it raises no data version. `lg_document_light` holds per paper
what the signals of its dossier read (`schema.DOCUMENT_LIGHT_PROPS`: kind, date, titles,
dossier numbers, case kinds, sequence, a motion's dictum, an amendment's explanation, and
how a motion or an amendment ended: `outcome`, `decided_on`, `tally`, `decision`) and `has_text`, whether its text is
in the data (which a row of the feed opens on), without its text, kept and filled the same way
from `documents`; indexed by dossier number, suffix and sequence, which `/api/lookup` finds a
paper by. `lg_instrument_names` holds per instrument its `title` and `short_title` as text
(`''` for none), which the laws a dossier title names are found by besides the column
`citation_title`, kept and filled the same way from `instruments`. `lg_faction_votes` holds
every `VOTED` edge from a faction with its decision's `date`, key and `vote_kind`, with an
index on `(faction_id, date DESC, decision_key)`, kept by triggers on `edges` and `decisions`
and filled once: the votes of a member are read from it (`get_member_votes`). `lg_authored`
holds every `AUTHORED` edge from a member with the `role`, `function` and `capacity` of the
signature, the `dossiers` of its paper (directly, or through its case: `lg_dossiers_of`) and
the `date` of its paper or case (`lg_signed_date`), with indexes on `member_id` and on
`(member_id, capacity, date)` that includes the `dossiers`, kept by triggers on `edges` (a
signature, and a paper or a case placed in or taken out of a dossier or a case), `documents`
and `cases`, and filled once: the dossiers of a member or a faction (`get_actor_dossiers`) and
the counts of a cabinet's members (`get_cabinet`) are read from it. `lg_led` holds every `LED_BY` edge into a committee (from an activity or a case) with the `date` of that item (`lg_led_date`) and its `dossiers`, those an activity is `ABOUT` or a case `PART_OF` (`lg_led_dossiers`), with an index on `(committee_id, item_collection, date DESC, item_id)` that includes the `dossiers`, kept by triggers on `edges`, `activities` and `cases` and filled once: the pages of a committee read it (`get_committee_detail`, `get_committee_activities`). `lg_cited_by` holds every `REFERS_TO` edge from a judgment into an article with its number of `mentions`, the `leden` each mention names (in their order), and the judgment's `date_eff`, `ecli`, `court_code`, `tier`, `inbound_citation_count` (as `cited`) and main areas of law (`areas`, `lg_subject_areas` of its `subjects`; null for a row written before they were kept, `semantic graph-light --only cited-by --every` writes them), with an index (`lg_cited_by_article_areas`) on `article_id` that includes all but the `leden`, kept by triggers on `edges` and `judgments` (a row for each edge of a judgment that is there) and filled once: the passages citing an article (`get_article_cited_by`) and the judgments citing a law (`get_citing_judgments`) are counted, filtered (by year, tier and main area of law) and sorted from it, and only the edges and judgments of the page are read. `lg_article_terms` holds per article its terms (`semantic graph-article-terms`):
the stems that recur in the light summaries of the judgments that cite it, in at least 3 of
them, 5 times as often as in all summaries, and in a fifth of them or in a fifth of the
summaries that hold the stem, at most 20, the most telling first ("noodwer" of art. 41 Sr,
whose words do not hold it; "wanprestatie" of art. 6:74 BW, cited on every subject), with a
GIN index, and per term its `strengths` (in the same order): the share of the summaries that
hold it that cite the article (the lower bound of its 95 % Wilson interval, so that a share
of few summaries weighs less), 0 where its citers hold it under 50 times as often as all
summaries ("bestemmingsplan" of art. 3:2 Awb, cited on every subject of the Raad van State);
a query each of whose words is a term of 0.15 or more of an article names it (null until the
first whole run after the column came); `lg_summary_stems`
in how many light summaries each stem is (the stems in 3 or more, and under `''` how many
summaries there are), which a run after a poll weighs the terms against. The step raises the
data version of `articles` when terms changed. `lg_search_candidates` holds, per type
(`judgments`, `articles`, `documents`) and word searched most (`lawgraph search-candidates`),
the hits a search of that word ranks (the first 1,000 in the order of their columns), in that
order (`pos`), with what their rank reads of each: the frequency of every term (`tf`), the
length of every field it weighs (`len`) and, of an article, its citations;
`lg_search_candidates_state` the version of the type's table they were read at
(`lg_data_version`), the signature of the search they were read for, and how many hits the
word has. A search of the word takes them while both are those of now, and finds its hits
itself otherwise.

## Node types and relation catalogue

The tables below are generated from `src/lawgraph/core/relations.py`, which holds the whole
vocabulary: `config/constants.py` has exactly one `RELATION_*` constant per entry and no other
relation name exists. Refresh them with `python -m lawgraph.core.relations` (it writes
`tests/data/relations.json` too); a test fails when they are out of date. Do not edit inside
the markers.

<!-- relations:begin (generated: python -m lawgraph.core.relations) -->

| Node type | Collection |
|-----------|-----------|
| Instrument | `instruments` |
| Article | `articles` |
| InstrumentVersion | `instrument_versions` |
| ArticleVersion | `article_versions` |
| Case | `cases` |
| Document | `documents` |
| Judgment | `judgments` |
| Dossier | `dossiers` |
| Activity | `activities` |
| Decision | `decisions` |
| Commitment | `commitments` |
| Committee | `committees` |
| Member | `members` |
| Faction | `factions` |
| Cabinet | `cabinets` |
| Annex | `annexes` |

| Relation | From → To | Meaning |
|----------|-----------|---------|
| `PART_OF` | Article → Instrument, Annex → Instrument, Document → Case, Document → Dossier, Case → Dossier, Instrument → Instrument | Containment. Article/Annex → Instrument; Document → Case or Dossier; Case → Dossier; a treaty → the treaty it belongs to, as the Verdragenbank registers it (a Protocol → its Convention, `Moederverdrag`). |
| `VERSION_OF` | InstrumentVersion → Instrument, ArticleVersion → Article | A dated version of an instrument or article. An article keeps one identity across versions (BWB `stam-id`); each version has valid_from / valid_until. |
| `ESTABLISHES` | Instrument → Article | A publication enacts a new regulation and so sets its articles: the BWB effect `nieuwe-regeling` of the article version it made (effective date and version in `meta`). No change of existing law: a regulation names its enacting publication in `props.enacted_publication` as well. |
| `AMENDS` | Instrument → Article, Document → Instrument, Document → Article | An instrument changes existing text (effective date and version in `meta`). A bill (Document) proposing the change carries status `voorgesteld`; a paper of the bill that made an instrument (`LEGISLATED_IN` its dossier) never amends it. |
| `INTRODUCES` | Instrument → Article, Document → Article | An instrument adds a new article; a bill proposing it is `voorgesteld`. |
| `REPEALS` | Instrument → Article, Document → Article | An instrument withdraws an article; a bill proposing it is `voorgesteld`. |
| `TRANSPOSED_TO` | Article → Article, Article → Instrument | An article of the old law → the article of the new law that takes its place in a recodification (of Dutch law, or a codification or recast of EU law), as an official source gives it (`meta.basis`; `meta.source` the identifier of that source: `blg-1081574`, `kst-34986-3`, the CELEX number of the EU act: `32017R1001`). `meta.parts` pairs each part of the old article (`from`: `2`, `2 a`, `eerste lid`, empty for the whole; `via` the division of the old law the source names: `§ 1.2`) with the place in the new law as the source writes it (`to`: `2.8.6, 1`, `8.2.26, vierde lid`), read: the number of the new article of the edge (`article`) and the leden it names (`leden`: `["1"]`; empty for the whole). The article of another law the source names (`afdeling 3.5 Awb`) is one too. An article of the old law → the new law (Instrument): what the source says of the parts it places in no article (`parts[].outcome`: `vervallen`, `niet_overgenomen`, `blijft_in:<law>`, `naar:<law>`), and of an old article no source places, its parts as the source writes them (`meta.outcome` `gat`). A row the source gives that the text of the laws does not hold is no edge to an article: `lawgraph succession-gaps` lists it. In a table of an old regulation, the column of a law beside the regulations under it (`Artikel Omgevingswet` beside `Artikel AMvB`, Stb. 2020, 400) names their delegation basis, no place: no edge (the basis is the new regulation's `BASED_ON`). An edge to the new law is read from the old article: the neighbours, the neighbourhood and the buckets of the law leave it out (`lg_transposition_outcome`). |
| `BASED_ON` | Instrument → Article | The legal basis (delegation basis) an instrument is issued under: 'Gelet op artikel …' in the preamble; a range ('artikelen 26 tot en met 30') to each article in force in it. `meta.text` is the reference without list word and law ('16, eerste en zevende lid'); `meta.basis_kind` `delegates` when the leden named give the power (a delegation formula, 'bij besluit', 'kan regels stellen'), `mentioned` when the article is only named (Awb 3:4 by a policy rule). |
| `IMPLEMENTS` | Instrument → Instrument | A national instrument implements an EU act, by an implementation source (`meta.bases`): a publication EUR-Lex lists as a national implementing measure of the act, and the regulations it enacted or changed (`national_implementing_measure`, `meta.publications`, and `meta.measures`: each with `citation`, and `title` and `type` as EUR-Lex gives them), or a regulation whose considerans says it implements the act (`considerans`). Not per article: no source names the implementing article. |
| `LEGISLATED_IN` | Instrument → Dossier | The parliamentary dossier in which an instrument was legislated (the `dossierref` of the BWB or of the law in the Staatsblad), or in which a treaty was approved (the Verdragenbank's `Kamerstukken`). |
| `PUBLISHED_IN` | Instrument → Instrument | A treaty → a Tractatenblad that publishes it or something about it, as the Verdragenbank registers it: its text, its approval, its entry into force, its parties (`meta.description`, as the register writes it). |
| `REFERS_TO` | Article → Article, Article → Instrument, Document → Article, Document → Instrument, Document → Document, Judgment → Article, Judgment → Instrument, Judgment → Judgment, Instrument → Article, Instrument → Instrument | A text refers to an article, instrument, judgment or Kamerstuk: the reference is in the text, never only in metadata (a judgment's earlier instance or conclusion is `APPEAL_OF` or `ADVISES_ON`), and two judgments of one case tied by `APPEAL_OF`, `CONTINUES`, `REFERRED_BY`, `ADVISES_ON` or `ANSWERS` have that edge only. The source node says who refers; article → article edges also carry a `semantic_type`. From an instrument: a regulation whose text names the CELEX number of an EU act it does not `IMPLEMENTS`, or an EU act → an article or act its text names. Judgment → instrument: a law the conclusion of an ECHR judgment names by its BWB id. Document → document: its subject names the paper by dossier and number, "(Kamerstuk 36945-XIV-1)" (`meta.basis` `subject`, `meta.text` as written), unless it `ANSWERS` it. |
| `EXPLAINS` | Document → ArticleVersion, Document → Article, Document → Instrument | A document (MvT, NvT) explains the article version or instrument it introduced or changed. Written per dossier: every MvT and NvT of a dossier explains everything its law changed; an MvT edge carries `meta.section_anchor` when one of its sections is about that article. |
| `APPEAL_OF` | Judgment → Judgment | An appeal or cassation judgment → the judgment it appeals: an earlier instance its metadata names (`meta.basis` `formal_relation`), else the decision its text says it appeals, by date and case number (`appeal_text`). |
| `CONTINUES` | Judgment → Judgment, Activity → Activity | A judgment → an earlier one of the same court in the same case (an interim judgment followed by the final one): an earlier instance its metadata names that shares its court and case number. An activity → the moved activity it replaced (`Activiteit.VervangenDoor`; `meta.reason` `verplaatst`). |
| `REFERRED_BY` | Judgment → Judgment | A decision after referral (verwijzing) → the ruling of the Hoge Raad that set aside the earlier decision and sent the case to it: an earlier instance its metadata names that is a Hoge Raad ruling (not a preliminary ruling). |
| `ADVISES_ON` | Judgment → Judgment | The conclusion of an advocate-general (Parket bij de Hoge Raad, or of the court itself) → the judgment in its case, one way only: the formal relation of either, when the side it calls the conclusion is one (`meta.basis` `formal_relation`), else a case number the two share (`case_number`). |
| `ANSWERS` | Judgment → Judgment, Document → Commitment, Document → Document | A preliminary ruling (prejudiciële beslissing) → the decision that asked its questions: the earlier instance its metadata names (`meta.basis` `formal_relation`), else the ECLI or the case number and date its text names (`referral_text`). A letter → the commitment it fulfils (`Toezegging.KamerbriefNakoming`). A letter of the government → a motion its subject names by dossier and number, "Uitvoering van de motie … (Kamerstuk 25424-795)" (`meta.basis` `subject`, `meta.text` the whole subject, `meta.reference` the reference as written), or its text or a footnote names: "Kamerstuk 36 764, nr. 28", "de motie-Kathmann (36764, nr. 31)" (`meta.basis` `text` or `footnote`, `meta.text` the line or footnote, confidence 0.9). |
| `SAME_AS` | Judgment → Judgment, Instrument → Instrument, Document → Instrument, Member → Member | A publication of a decision → the publication of the same decision that replaces it (an old arrest published again under a new ECLI): the ECLI its metadata names as `dcterms:isReplacedBy`. The lists show the decision once, by the one kept. The BWB text of a treaty (`BWBV…`) → its Verdragenbank treaty, by the treaty number the text names (`wetgeving@verdragnummer`). A paper of the Staatsblad or the Staatscourant → the publication of the BWB of the same official id (`stb-2019-33`, `stcrt-2020-12345`), by their keys. A bare `Persoon` of the Tweede Kamer → the member with a role who is the same person: the same birth date, surname and initials (`tk-person-duplicates`). |
| `SCOPED_BY` | Article → Annex | An article whose scope is defined by an annex. |
| `ABOUT` | Activity → Case, Activity → Dossier, Decision → Case, Decision → Dossier, Decision → Document, Commitment → Dossier | The subject of an activity, decision or commitment: Activity/Decision → Case and Dossier; Commitment → Dossier. A vote of the Eerste Kamer on a motion → the motion, its Kamerstuk with that letter (`Kamerstuk I 37020, M`): a paper of the Eerste Kamer has no case, where a decision of the Tweede Kamer is about the case of its motion. A commitment fulfilled by a letter in a dossier is about that dossier (`meta.basis` `nakoming`), one without is about the dossiers on the agenda of its debate (`agenda`). |
| `LED_BY` | Activity → Committee, Case → Committee | The lead committee (`voortouwcommissie`) of an activity or case; absent for plenary. |
| `MADE_IN` | Commitment → Activity, Document → Activity, Decision → Activity | The activity in which a commitment (toezegging) was made, or a decision taken (the activity of its agenda item: `Agendapunt.Activiteit`), or of which a document is the record (a stenogram of its debate: `Document.Activiteit`), or a motion submitted: the debate held on the day its case started that has the case on its agenda and took no decision on it (`meta.reason` `ingediend`). |
| `MEMBER_OF` | Member → Committee, Member → Faction | Membership of a committee or faction, with from/to dates and role. |
| `SERVED_IN` | Member → Cabinet | The posts a member held in a cabinet, one edge per member and cabinet, `meta.posts` as in the member's `government_functions`. |
| `AUTHORED` | Member → Document, Member → Case, Member → Commitment | A person signed or submitted a document or case; `role` says how (first signatory, co-signatory, …), `function` as what (`Functie`) and `capacity` in which capacity (`kamerlid`, `bewindspersoon`, `overig`). A bewindspersoon made a commitment (`role` `toezegger`). |
| `RELATED_TO` | Case → Case, Dossier → Dossier, Judgment → Judgment | Case → case: the Kamer relates the two (`Zaak.GerelateerdNaar`, `meta.case_kinds`). Dossier → dossier: the Kamer relates a case of this dossier to a case of the other (`Zaak.GerelateerdNaar`), mostly a letter of the government to the motion it answers; `meta.cases` counts the pairs of cases, `meta.case_kinds` names them, `meta.pairs` gives the papers of the 5 newest pairs (`{kinds, from, to}`, a side `{case, paper, kind, dossier_number, dossier_suffix, sequence, date}`). Judgment → judgment: its summary names the other as a connected case, "Samenhang met 24/03860 E", "Zie ook: ECLI:NL:GHDHA:2025:1539" (`meta.basis` `summary_text`, `meta.text` the sentence as written); only on an exact match of the ECLI, or of the case number among the judgments of the same court (the Hoge Raad's type letter is not part of the comparison). |
| `REVISES` | Dossier → Dossier, Document → Document | A supplementary budget or a slotwet revises the budget of its chapter and year (`meta.rule`: `begrotingswijziging` or `slotwet`; Dossier → Dossier); an amended amendment or motion replaces the one it names, "ter vervanging van nr. 21" (`meta.rule` `vervanging`, `Zaak.VervangenVanuit`; Document → Document). |
| `ACCOMPANIES` | Dossier → Dossier, Document → Document | A budget change is submitted with the Voorjaarsnota, Najaarsnota or Miljoenennota (`meta.nota`) that its title names (Dossier → Dossier); an attachment is sent with its letter (Document → Document: `BijlageDocument`). |
| `SECOND_READING_OF` | Dossier → Dossier | A change in the Grondwet in its second reading → the dossier of its first reading, to whose papers its memorandum refers for the explanation (Kamerstukken 35 418). |
| `VOTED` | Member → Decision, Faction → Decision | A vote on a decision: per member for roll-call votes, per faction otherwise (`choice`, `seats`). |

<!-- relations:end -->

### Provenance of an edge

Where an edge comes from is in its `meta`: `basis` (or, of an `IMPLEMENTS`, the list
`bases`) for an edge one source names, `reason` for a citation read from a text. The values
are those of `src/lawgraph/core/provenance.py` alone (`Basis`, `Reason`); a test fails when a
pipeline writes another, or when the table below is out of date. Refresh it with
`python -m lawgraph.core.provenance`.

<!-- provenance:begin (generated: python -m lawgraph.core.provenance) -->

| Meta | Value | Relations | Meaning |
|------|-------|-----------|---------|
| `basis` | `formal_relation` | `APPEAL_OF`, `CONTINUES`, `REFERRED_BY`, `ADVISES_ON`, `ANSWERS` | The metadata of the judgment names the other (`dcterms:relation`). |
| `basis` | `later_instance` | `APPEAL_OF`, `CONTINUES`, `REFERRED_BY` | The metadata of the earlier judgment names the later one. |
| `basis` | `appeal_text` | `APPEAL_OF` | The text says which decision it appeals, by date and case number. |
| `basis` | `case_number` | `ADVISES_ON` | The conclusion and the judgment share a case number. |
| `basis` | `referral_text` | `ANSWERS` | The text of the preliminary ruling names the referring decision: its ECLI, or its case number and date. |
| `basis` | `national_decision` | `ANSWERS` | CELLAR names the national decision that referred the questions to the Court of Justice (`case-law_national-judgement`): its ECLI, or its date and case number. |
| `basis` | `summary_text` | `RELATED_TO` | The summary names the other as a connected case (`meta.text`). |
| `basis` | `is_replaced_by` | `SAME_AS` | The metadata names the publication that replaces it (`dcterms:isReplacedBy`). |
| `basis` | `appno_and_date` | `SAME_AS` | Two language versions of an ECHR decision: the same application numbers and date. |
| `basis` | `official_id` | `SAME_AS` | A publication of the Staatsblad or Staatscourant and the BWB publication of the same official id. |
| `basis` | `birth_date_surname_initials` | `SAME_AS` | A bare `Persoon` of the Tweede Kamer and a member with the same birth date, surname and initials. |
| `basis` | `subject` | `ANSWERS`, `REFERS_TO` | The subject of the Kamerstuk names the paper by dossier and number. |
| `basis` | `text` | `ANSWERS` | A line of the text of the letter names the motion. |
| `basis` | `footnote` | `ANSWERS` | A footnote of the letter names the motion. |
| `basis` | `transposition_table` | `TRANSPOSED_TO` | The table of the recodification places the old article in the new law (the transposition table sent with the bill, a bijlage of its memorie van toelichting or a table in it; the concordance table of an EU act that codifies or recasts others), and the text of the new law holds that article and lid. |
| `basis` | `nakoming` | `ABOUT` | A commitment and the dossier of the letter that fulfils it (`Toezegging.KamerbriefNakoming`, its `Kamerstukdossier`): the dossier the Kamer files its answer in. |
| `basis` | `agenda` | `ABOUT` | A commitment no letter in a stored dossier fulfils, and a dossier on the agenda of the debate it was made in: discussed there, not necessarily its subject. |
| `bases` | `national_implementing_measure` | `IMPLEMENTS` | EUR-Lex lists the publication as a national implementing measure of the act. |
| `bases` | `considerans` | `IMPLEMENTS` | The considerans of the regulation says it implements the act. |
| `reason` | `bwb_article` | `REFERS_TO` | The text cites an article of a law (BWB). |
| `reason` | `celex_article` | `REFERS_TO` | The text cites an article of an EU act. |
| `reason` | `bwb_instrument` | `REFERS_TO` | The text cites a law (BWB) as a whole. |
| `reason` | `celex_instrument` | `REFERS_TO` | The text cites an EU act as a whole. |
| `reason` | `unknown` | `REFERS_TO` | A citation that names neither a law nor an EU act. |
| `reason` | `bwb_xml_ref` | `REFERS_TO` | A reference the BWB XML of the article records (`intref`, `extref`). |
| `reason` | `amendment_text` | `AMENDS`, `INTRODUCES`, `REPEALS` | The text of the amendment names the article it changes (`meta.snippet`). |
| `reason` | `ingediend` | `MADE_IN` | The motion was submitted in the debate held on the day its case started. |
| `reason` | `verplaatst` | `CONTINUES` | The activity replaced a moved one (`Activiteit.VervangenDoor`). |

<!-- provenance:end -->

## Keys

| Collection | Key |
|------------|-----|
| `instruments` (BWB) | `bwbr0001854` (`bwb_id`; treaties `bwbv...`) |
| `instruments` (EU) | `32016l0680` (`celex`) |
| `instruments` (Verdragenbank treaty) | `verdrag_<id>` |
| `instruments` (amending publication) | `stb_2019_33` (publication identifier) |
| `instruments` (law of the Staatsblad the BWB does not hold) | `wet_stb_2026_56` (`wet_` and the publication that enacted it) |
| `articles` | `<bwb_id>_<article_number>` (a book of the Burgerlijk Wetboek is a regulation of its own: `bwbr0005289_162` is 6:162 BW; an article of an annex `bwbr0005537_bijlage_2_artikel_9`; the one article of a regulation of one article `<bwb_id>_enig_artikel`; an article without a number `<bwb_id>_stam_<stam_id>`: `bwbr0001840_stam_16464063`); EU `<celex>_<article_number>`; of a law of the Staatsblad `<official_id>_<article_number>` (`stb_2026_56_2_8_6`); historical `<bwb_id>_<number>_stam_<stam_id>` |
| `instrument_versions` | `<bwb_id>_<valid_from>` |
| `article_versions` | `<bwb_id>_av_<stam_id>_<versie_id>` |
| `annexes` | `<bwb_id>_annex_<label>` (`<bwb_id>_annex` without a label) |
| `judgments` | `ecli_nl_hr_2023_1234`; ECHR its ECLI, else `echr_<itemid>`; a court of the EU its ECLI (`ecli_eu_c_2020_559`) |
| `dossiers` | `<number>` or `<number>_<suffix>` |
| `cases`, `documents` (TK), `activities`, `commitments`, `committees`, `members` | TK GUID (`Id`); a bewindspersoon only Rijksoverheid knows `rijksoverheid_<initials>_<surname>` |
| `documents` (other) | `stb_<identifier>`, `stcrt_<identifier>`, `ek_<id>` |
| `decisions` | `decision_<Besluit_Id>`; Eerste Kamer `ek_<date>_<label>_<n>` |
| `factions` | abbreviation, else name (`vvd`, `d66`) |
| `edges` | `SHA-1(from_id:relation:to_id)`: one edge per (from, relation, to) |
| `raw_sources` | `SHA-1(source:kind:external_id)`; random UUID when `external_id` is null |

## Edge document

| Field | Meaning |
|-------|---------|
| `from_id`, `to_id` | node ids (`collection/key`) |
| `relation` | a catalogue name |
| `source` | the pipeline that wrote the edge (`bwb-amendments`, `tk-article-linker`, ...) |
| `status` | `canoniek` (default) or `voorgesteld` — a change a bill proposes but has not enacted, written by `tk-amendment-articles` and by `tk-amends` |
| `confidence` | 0-1; absent on structural edges; 1.0 when read from source XML |
| `created_at` | set on insert only |
| `meta` | evidence and context, per relation as in the table below; upserts merge `meta` |

An edge is one per (`from_id`, `relation`, `to_id`); a second write replaces `source`, `status` and
`confidence` and merges `meta` into the stored keys the model of the relation has (below): a key
the model lacks goes on the next write of the edge, so a run of the step that writes it clears
what an earlier version left. `EXPLAINS` from a memorandum has two writers that share its
key: `semantic tk-mvt` (a change of the dossier, `confidence` 0.5, no section) and `semantic
tk-mvt-articles` (a section that is about the article; `source` `mvt-section-linker`, the
`confidence` of the surest section). The second wins whichever ran first.

The keys `meta` may hold are those of the model of its relation in `src/lawgraph/core/relations.py`
(`RelationSpec.meta`): every key of every writer of the relation, since two writers of one
edge merge theirs. A nested key is written `parent[].key` for an item of a list. Refresh the
table with `python -m lawgraph.core.relations`; a test fails when it is out of date.
`make_edge_doc` logs a key the model lacks, once per relation, source and key in a process
(`Edge meta: … a key its model lacks`); in the tests every edge is held to the whole model,
types included, and a test that makes one that does not fit fails. The `UPDATE` of
`_CLASSIFICATIONS_SQL` (`db/queries/semantic/bwb.py`) writes outside it; a unit test holds
its keys to the model of `REFERS_TO`.

<!-- edge-meta:begin (generated: python -m lawgraph.core.relations) -->

| Relation | Key | Type | Meaning |
|----------|-----|------|---------|
| `ESTABLISHES` | `effective_date` | `str` | The day the version takes effect. |
|  | `article_version` | `str` | The key of the article version the publication made. |
|  | `effect` | `str` | The effect as the BWB writes it: `wijziging`, `nieuwe-regeling`, `vervallen`. |
|  | `source_publication` | `str` | The publication that made the change: `stb-2019-33`. |
| `AMENDS` | `effective_date` | `str` | The day the version takes effect. |
|  | `article_version` | `str` | The key of the article version the publication made. |
|  | `effect` | `str` | The effect as the BWB writes it: `wijziging`, `nieuwe-regeling`, `vervallen`. |
|  | `source_publication` | `str` | The publication that made the change: `stb-2019-33`. |
|  | `reason` | `Reason` | `amendment_text` (core/provenance.py). |
|  | `snippet` | `str` | The words of the amendment that name the article. |
| `INTRODUCES` | `effective_date` | `str` | The day the version takes effect. |
|  | `article_version` | `str` | The key of the article version the publication made. |
|  | `effect` | `str` | The effect as the BWB writes it: `wijziging`, `nieuwe-regeling`, `vervallen`. |
|  | `source_publication` | `str` | The publication that made the change: `stb-2019-33`. |
|  | `reason` | `Reason` | `amendment_text` (core/provenance.py). |
|  | `snippet` | `str` | The words of the amendment that name the article. |
| `REPEALS` | `effective_date` | `str` | The day the version takes effect. |
|  | `article_version` | `str` | The key of the article version the publication made. |
|  | `effect` | `str` | The effect as the BWB writes it: `wijziging`, `nieuwe-regeling`, `vervallen`. |
|  | `source_publication` | `str` | The publication that made the change: `stb-2019-33`. |
|  | `reason` | `Reason` | `amendment_text` (core/provenance.py). |
|  | `snippet` | `str` | The words of the amendment that name the article. |
| `TRANSPOSED_TO` | `basis` | `Basis` | `transposition_table` (core/provenance.py). |
|  | `source` | `str` | The paper that gives the table: `blg-1081574`, `kst-34986-3`. |
|  | `parts` | `list[object]` | Each part of the old article with its place in the new law. |
|  | `parts[].from` | `str` | The part of the old article: `2`, `2 a`, `eerste lid`; empty for the whole. |
|  | `parts[].to` | `str` | The place in the new law as the source writes it: `2.8.6, 1`, `vervallen (mvt)`. |
|  | `parts[].article` | `str` | The number of the new article of the edge (an edge to an article). |
|  | `parts[].leden` | `list[str]` | The leden of it the place names; empty for the whole (an edge to an article). |
|  | `parts[].outcome` | `str` | What the source says of a part it places in no article (an edge to the new law): `vervallen`, `niet_overgenomen`, `blijft_in:<law as written>`, `naar:<law as written>` (to another law, no article of it named); `gat` for a part that does not hold. |
|  | `parts[].via` | `str` | The division of the old law the source names for the old article: `§ 1.2`. |
|  | `outcome` | `str` | Of an edge to the new law: the outcome of the old article its parts share, `gat` for an old article no source places (`lawgraph succession-gaps`). |
| `BASED_ON` | `text` | `str` | The reference without list word and law: `16, eerste en zevende lid`. |
|  | `basis_kind` | `str` | `delegates` when the leden named give the power, `mentioned` when the article is only named. |
| `IMPLEMENTS` | `bases` | `list[str]` | The implementation sources: `national_implementing_measure`, `considerans`. |
|  | `publications` | `list[str]` | The publications EUR-Lex lists as national implementing measures. |
|  | `measures` | `list[object]` | Those measures as EUR-Lex lists them. |
|  | `measures[].citation` | `str` | How EUR-Lex cites the measure. |
|  | `measures[].publication` | `str` | The publication of the measure. |
|  | `measures[].title` | `str` | Its title as EUR-Lex gives it. |
|  | `measures[].type` | `str` | Its type as EUR-Lex gives it. |
| `LEGISLATED_IN` | `dossier_number` | `str` | The number of the dossier. |
| `PUBLISHED_IN` | `description` | `str` | What it publishes, as the register writes it. |
| `REFERS_TO` | `leden` | `list[str]` | The leden the reference names: `["1", "3"]`. |
|  | `onderdelen` | `list[str]` | The onderdelen it names: `["a"]`. |
|  | `aanhef` | `bool` | It names the aanhef of the article. |
|  | `start` | `int` | Where the reference starts in the text of the source node. |
|  | `end` | `int` | Where it ends. |
|  | `reason` | `Reason` | What the citation names or how it was read (core/provenance.py). |
|  | `text` | `str` | The reference as written (`bwb-article-references`, `staatsblad-law-references`, `tk-cited-papers`). |
|  | `reference_kind` | `str` | `intref` or `extref`, as the BWB XML writes the link. |
|  | `footnote` | `int` | The footnote of the citing article it stands in, its place in `footnotes` (`bwb-article-references`); it then has no `start` and `end` in the text. |
|  | `semantic_pattern` | `str` | The pattern that typed the reference (`semantic_type`). |
|  | `semantic_confidence` | `float` | How sure that typing is. |
|  | `raw_match` | `str` | The citation as written. |
|  | `snippet` | `str` | The words around it. |
|  | `qualifier` | `str` | The leden or onderdelen as written: `derde lid`. |
|  | `place` | `object` | Where the citation stands in the paper; null for one over two parts. |
|  | `place.part` | `str` | `title`, `text` or `footnote`. |
|  | `place.start` | `int` | Where the citation starts in that part. |
|  | `place.end` | `int` | Where it ends. |
|  | `place.section_id` | `str` | The innermost section of the text it stands in. |
|  | `place.footnote` | `str` | The footnote as printed. |
|  | `place.footnote_id` | `str` | The id of the footnote. |
|  | `mention_count` | `int` | How many places of the judgment cite it. |
|  | `mentions` | `list[object]` | The first of those places. |
|  | `mentions[].leden` | `list[str]` | The leden the reference names: `["1", "3"]`. |
|  | `mentions[].onderdelen` | `list[str]` | The onderdelen it names: `["a"]`. |
|  | `mentions[].aanhef` | `bool` | It names the aanhef of the article. |
|  | `mentions[].paragraph_id` | `str` | The paragraph of the judgment. |
|  | `mentions[].paragraph_number` | `str` | Its number as printed. |
|  | `mentions[].start` | `int` | Where the mention starts in the paragraph (or the footnote). |
|  | `mentions[].end` | `int` | Where it ends. |
|  | `mentions[].raw_match` | `str` | The mention as written. |
|  | `mentions[].snippet` | `str` | The words around it. |
|  | `mentions[].snippet_start` | `int` | Where the snippet starts in the paragraph. |
|  | `mentions[].confidence` | `float` | How sure the reading is. |
|  | `mentions[].qualifier` | `str` | The leden or onderdelen as written: `derde lid`. |
|  | `mentions[].footnote` | `str` | The label of the footnote that cites it. |
|  | `paragraphs` | `list[str]` | The numbers of the paragraphs that cite it, each once. |
|  | `cited_ecli` | `str` | The ECLI the judgment cites. |
|  | `cited_appno` | `str` | The application number of the ECHR decision it cites. |
|  | `basis` | `Basis` | `subject` (core/provenance.py). |
| `EXPLAINS` | `section_anchor` | `str` | The `id` of the surest section (`props.sections` of the Document); the keys below up to `sections` are that section's. |
|  | `char_start` | `int` | Where it starts in `props.text` of the Document. |
|  | `char_end` | `int` | Where it ends. |
|  | `heading` | `str` | Its heading. |
|  | `sections` | `list[object]` | Every section about the article, in the order of the memorandum. |
|  | `sections[].section_anchor` | `str` | The section of the memorandum. |
|  | `sections[].heading` | `str` | Its heading. |
|  | `sections[].char_start` | `int` | Where it starts in the text of the memorandum. |
|  | `sections[].char_end` | `int` | Where it ends. |
|  | `sections[].match_type` | `str` | How the section names the article: `heading_target`, `body_named_law`, `own_number`, `inferred_law`, `bill_part` or `amendment` (`docs/pipelines.md`). |
|  | `sections[].changed` | `bool` | The dossier changed the article, or established it as an article of the law it made, which corroborates the match. |
|  | `sections[].confidence` | `float` | How sure the match is. |
|  | `sections[].explanation` | `str` | What the match rests on, in Dutch. |
| `APPEAL_OF` | `basis` | `Basis` | What names the other (core/provenance.py). |
|  | `procedure_type` | `str` | The procedure as the source writes it: `Hoger beroep`, `Cassatie`. |
| `CONTINUES` | `basis` | `Basis` | What names the other (core/provenance.py). |
|  | `procedure_type` | `str` | The procedure as the source writes it: `Hoger beroep`, `Cassatie`. |
|  | `reason` | `Reason` | `verplaatst`: an activity replaced a moved one. |
| `REFERRED_BY` | `basis` | `Basis` | What names the other (core/provenance.py). |
|  | `procedure_type` | `str` | The procedure as the source writes it: `Hoger beroep`, `Cassatie`. |
| `ADVISES_ON` | `basis` | `Basis` | What names the other (core/provenance.py). |
|  | `procedure_type` | `str` | The procedure as the source writes it: `Hoger beroep`, `Cassatie`. |
| `ANSWERS` | `basis` | `Basis` | What names the other (core/provenance.py). |
|  | `text` | `str` | The subject, line or footnote that names the motion. |
|  | `reference` | `str` | The reference as written. |
| `SAME_AS` | `basis` | `Basis` | What makes the two the same (core/provenance.py). |
| `SCOPED_BY` | `scope_type` | `str` | `fixed` or `discretionary`. |
| `ABOUT` | `basis` | `Basis` | Of a commitment: `nakoming` or `agenda` (core/provenance.py). |
| `MADE_IN` | `reason` | `Reason` | `ingediend`: a motion submitted in the debate. |
| `MEMBER_OF` | `from_date` | `str` | The first day. |
|  | `to_date` | `str` | The last day; absent while it lasts. |
|  | `role` | `str` | The role as the source writes it. |
|  | `substitute` | `bool` | `true` for a substitute. |
|  | `periods` | `list[object]` | Every seat in the committee, oldest first. |
|  | `periods[].from_date` | `str` | The first day. |
|  | `periods[].to_date` | `str` | The last day; absent while it lasts. |
|  | `periods[].role` | `str` | The role as the source writes it. |
|  | `periods[].substitute` | `bool` | `true` for a substitute. |
|  | `record_ids` | `list[str]` | The `FractieZetelPersoon` records of the faction seat. |
|  | `observed_from` | `str` | The first day the Eerste Kamer site showed the seat. |
|  | `observed_until` | `str` | The day it no longer did; null while it does. |
| `SERVED_IN` | `posts` | `list[object]` | The posts held in the cabinet, as in the member's `government_functions`. |
|  | `posts[].cabinet_key` | `str` | The cabinet node. |
|  | `posts[].cabinet` | `str` | Its name: "kabinet-Rutte IV". |
|  | `posts[].function` | `str` | The post as the source writes it: "Minister van Infrastructuur en Waterstaat". |
|  | `posts[].also_named` | `list[str]` | The other names of the post. |
|  | `posts[].post` | `str` | The normalised post (`core.ministries.POSTS`). |
|  | `posts[].ministry` | `str` | The key of its ministry (`core.ministries.MINISTRIES`; `core/post_ministries.py`). |
|  | `posts[].ministry_source` | `str` | Where the ministry comes from: `page`, `tk_signatures`, `tk_commitments`, `staatscourant`. |
|  | `posts[].ministry_missing` | `str` | When `ministry` is null, why: `no_source`, `ambiguous`. |
|  | `posts[].seat` | `str` | `ienw/minister`, `-/staatssecretaris/rechtsbescherming`, `viceminister-president`. |
|  | `posts[].portfolio` | `str` | The portfolio. |
|  | `posts[].from_date` | `str` | The first day held. |
|  | `posts[].to_date` | `str` | The last day held; null while held. |
|  | `posts[].from_date_source` | `str` | The day the page gave, null when none. |
|  | `posts[].to_date_source` | `str` | Likewise. |
|  | `posts[].corrected` | `list[str]` | Which dates the rules of a seat set. |
|  | `posts[].acting` | `bool` | A stand-in (ad interim). |
|  | `posts[].acting_reason` | `str` | `source` or `held_other_seat`. |
|  | `posts[].acting_basis` | `str` | The words of the page. |
|  | `posts[].acting_other_seat` | `{str: str}` | `{seat, function}` of the seat held besides. |
|  | `posts[].party` | `object` | The party of the holder. |
|  | `posts[].party.short` | `str` | As the source writes it. |
|  | `posts[].party.faction` | `str` | Its faction key. |
|  | `posts[].overlaps_with` | `list[str]` | Member keys holding the seat at the same time. |
|  | `posts[].absent` | `list[str]` | The periods of a "tijdelijk afwezig". |
|  | `posts[].name` | `str` | The holder as the page writes them. |
|  | `posts[].source` | `object` | The page it was read from. |
|  | `posts[].source.name` | `str` | The source. |
|  | `posts[].source.url` | `str` | The page. |
|  | `posts[].source.read_on` | `str` | The day it was read. |
| `AUTHORED` | `role` | `str` | How: as the source writes it (`Eerste ondertekenaar`), or `toezegger`. |
|  | `function` | `str` | As what (`Functie`). |
|  | `capacity` | `"kamerlid" \| "bewindspersoon" \| "overig"` | In which capacity. |
| `RELATED_TO` | `basis` | `Basis` | `summary_text` (core/provenance.py). |
|  | `text` | `str` | The sentence of the summary that names the other. |
|  | `cases` | `int` | How many pairs of cases relate the dossiers. |
|  | `case_kinds` | `str \| list[str] \| NoneType` | What the cases are: of two cases one (`Brief regering → Motie`), of two dossiers each. |
|  | `pairs` | `list[object]` | The papers of the newest pairs. |
|  | `pairs[].from` | `object` | The paper of the case of this dossier. |
|  | `pairs[].from.paper` | `str` | The document of its own kind; null when the graph has none. |
|  | `pairs[].from.kind` | `str` | The kind of the paper. |
|  | `pairs[].from.dossier_number` | `str` | Its dossier. |
|  | `pairs[].from.dossier_suffix` | `str` | The suffix of that dossier. |
|  | `pairs[].from.sequence` | `int` | Its number in the dossier. |
|  | `pairs[].to` | `object` | The paper of the case of the other. |
| `REVISES` | `rule` | `str` | `begrotingswijziging`, `slotwet` or `vervanging`. |
| `ACCOMPANIES` | `nota` | `str` | The Voorjaarsnota, Najaarsnota or Miljoenennota. |
| `VOTED` | `choice` | `str` | The choice as the source writes it: `Voor`, `Tegen`. |
|  | `seats` | `int` | The seats the vote counts. |
|  | `record_ids` | `list[str]` | The `Stemming` records it is made of. |

Without meta: `PART_OF`, `VERSION_OF`, `LED_BY`, `SECOND_READING_OF`.

<!-- edge-meta:end -->

`char_start`/`char_end` are offsets into `props.text` of the Document.

Semantic layer on article-to-article `REFERS_TO` edges, orthogonal to `relation`: `relation`
says that two articles are linked, `semantic_type` says what the link means.

| Field | Values |
|-------|--------|
| `semantic_type` | `conditional_requirement`, `scope_limitation`, `prerequisite_procedure`, `definitional_reference`, `limiting_exception`, `cross_reference`, `delegated_discretion`; null for unclassified edges |
| `explanation` | the phrase that decided the type and where it stood, in words |
| `updated_at` | when the classification last changed |
| `meta.semantic_pattern` | the pattern and where its phrase stood: `limiting_exception_adjacent`, `definitional_reference_window`, `cross_reference_fallback` |
| `meta.semantic_confidence` | the share of classifications by that pattern a hand check found right ([per pattern](pipelines.md#bwb-dutch-legislation)); the edge's `confidence` (1.0) is that the reference exists |

## Instrument

An instrument is any rule with a basis in a power laid down in law. It is not limited to
statutes made by the legislator:

- BWB types ingested (`BWB_INSTRUMENT_TYPES`): `wet`, `rijkswet`, `AMvB`, `rijksAMvB`, `KB`,
  `rijksKB`, `ministeriele-regeling`, `ministeriele-regeling-archiefselectielijst`, `zbo`,
  `pbo`, `reglement`, `beleidsregel`, `verdrag`, and the `-BES` variants of `wet`, `AMvB`,
  `ministeriele-regeling` and `beleidsregel`. `circulaire` is not ingested.
- A BWB regulation also carries what its toestand says other steps link from: `basis` (the
  `Gelet op` references: `bwb_id`, `article`, `doc`, `text`), `celex_refs` (the EU acts its
  text names) and `implements_celex` (the EU acts its considerans says it implements);
  `retrieve eurlex --mode gaps` fetches the acts of `celex_refs` and `implements_celex`.
  `enacted_publication` is the publication that enacted it (`stb-2018-144`; indexed, for the
  laws a publication of the feed enacts). Its `title` is the
  citeertitel, else the intitule; `kind` is `wetgeving@soort`. `date_signed`, `date_published`
  and `dossier_numbers` are those of that publication, `date_in_force` the
  `inwerkingtreding.datum` of the `<intitule>` (each null or empty when the toestand does not say
  it): the `meta-data` of `<wetgeving>` names the last change to the structure of the law, not
  the law. `version_date_in_force` is the start of the toestand. `date_expired` is the first
  day the regulation was no longer in force (repealed or lapsed): the day after the end of the
  validity period (`geldigheidsperiode_einddatum`) of its last toestand in the SRU, when that end
  had passed as `retrieve bwb` read it (`bwb_xml.expiry_date`); null while it is in force. A
  regulation repealed before 2002 has no toestand in the BWB at all. A Celex link
  whose id has an impossible year in the source is rebuilt from the text of the link
  ("verordening (EU) 2021/784") or left out.
- Treaties are instruments, both BWB treaties (`BWBV...`) and Verdragenbank records
  (`verdrag_<id>`), two nodes for a treaty that is in both. They share `treaty_number`, the
  six-digit Verdragenbank id, which a BWB treaty names in `wetgeving@verdragnummer`; no edge
  joins them (see [pipelines](pipelines.md#verdragenbank)). A Verdragenbank treaty also
  carries what its item XML registers: `place_signed`, `tractatenblad` (`official_id`,
  `text`, `description`), `parties` (`name` and its dates, `consent`, `reservation`,
  `objection`), `kingdom_parts`, `kamerstukken` and `parent_treaties`/`child_treaties`
  (Verdragenbank `id`, `title`, `date`, `place`).
- EU directives, regulations and decisions (`celex`). `title` is the printed title
  (`Verordening (EU) 2022/868 van het Europees Parlement en de Raad van 30 mei 2022
  betreffende …`), `citation_title` the form the act is cited by in its era (`Richtlijn
  87/102/EEG`, `Richtlijn 95/46/EG`, `Verordening (EU) nr. 1093/2010`, `Verordening (EU)
  2016/679`), `short_title` the name between brackets that ends the title
  (`Datagovernanceverordening`), `display_name` the citation title, `date_signed` the day the
  title names (`van 27 april 2016`: the day the act was adopted).
- The Convention of the ECHR is the BWB treaty `BWBV0001000` (`bwbv0001000`, articles
  `bwbv0001000_<n>`), abbreviated `EVRM` in its WTI; ECHR judgments cite its articles.
- `legal_areas` and `policy_domains` of a BWB regulation are how its WTI files it: `{main,
  main_id, main_uri, main_slug, specific, specific_id, specific_uri, specific_slug}` per legal
  area ("Staats- en bestuursrecht", "Bestuursrecht") and `{label, id, uri, slug}` per
  government theme ("Overheid, bestuur en koninkrijk"), the ids and URIs those of the TOOI
  concepts (`scw_bwb_rechtsgebieden`, `scw_bwb_themas`), the slugs unique in their list.
  Written by `normalize bwb`; `lg_legal_area_keys` and `lg_policy_domain_keys` (GIN indexes)
  are what `/api/instruments` filters on.
- `abbreviation` of an instrument is the abbreviation it is cited by
  (`core.aliases.abbreviation_of`): the WTI short title of a BWB regulation or treaty
  (`EVRM`), else the first one kept by hand (`curated instrument-abbreviations`: `AVG` for
  `32016R0679`). Its articles carry it as `instrument_abbreviation` (`art. 8 EVRM`). Written
  by `normalize bwb`.
- Amending publications (Staatsblad, Tractatenblad, ...) are instruments too, of `kind`
  `publicatie` (`publication_kind`, `publication_year`, `publication_number`, `date_signed`,
  `date_published`, `dossier_numbers`; `citation_title` is their name, `Stb. 2019, 33`); they
  are the source of `ESTABLISHES`, `AMENDS`, `INTRODUCES` and `REPEALS`, and no regulation: the instrument
  lists and `/api/stats` keep them apart.
- `official_title` is the `intitule` of its toestand, `citation_title` the title it is cited
  by. `semantic graph-list-stats` writes `jurisdiction` (`nl` with a `bwb_id`, `eu` with a
  `celex`), `article_count` (its articles in force without stubs, the `total` of `/articles`) and
  `inbound_citation_count` (the `REFERS_TO` edges to it and to its articles) and `amending`
  (a regulation that changes others), which the lists sort and filter on.

- A law the Staatsblad published and the BWB does not hold (yet) is an instrument read from
  the XML of its publication (`normalize staatsblad-laws`): `instruments/wet_stb_2026_56`,
  `kind` `wet`, `official_id` and `enacted_publication` the publication that enacted it
  (`stb-2026-56`), `status` `vastgesteld` and `in_force` false (its text as published, not in
  force), `display_name` its citation title and that publication ("Wetboek van Strafvordering
  (Stb. 2026, 56)"), which tells it from a law of the BWB of the same name. Its articles carry
  `official_id`, which names the law in their routes and address (`/wetten/STB-2026-56/artikel/2.8.6`),
  and `path`, the `bwb-ng-variabel-deel` the BWB would give them, where a definition holds.
  `semantic staatsblad-law-references` keeps `unlinked_references` on the law and its articles,
  `semantic bwb-definitions` `definitions_found` on the law: what the API says of them
  (`completeness`). Once the BWB holds it, it goes.

An instrument that amends, introduces or repeals has enacted the change (`status: canoniek`).
A bill (Document) carries the same three relations with `status: voorgesteld` — a change it
proposes. Only an instrument is based on a basis article or implements a directive, and only a
document (memorie van toelichting, nota van toelichting) explains.

<!-- props:instruments:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `legal_areas` | `list[object]` | How the WTI of a BWB regulation files it by legal area (`normalize bwb`). |
| `legal_areas[].main` | `str` | The main area as the WTI names it ("Staats- en bestuursrecht"). |
| `legal_areas[].main_id` | `str` | The id of its TOOI concept (`scw_bwb_rechtsgebieden`). |
| `legal_areas[].main_uri` | `str` | The URI of that concept. |
| `legal_areas[].main_slug` | `str` | Its slug, unique in the list. |
| `legal_areas[].specific` | `str` | The specific area within it ("Bestuursrecht"). |
| `legal_areas[].specific_id` | `str` | The id of its TOOI concept. |
| `legal_areas[].specific_uri` | `str` | The URI of that concept. |
| `legal_areas[].specific_slug` | `str` | Its slug, unique in the list. |
| `policy_domains` | `list[object]` | How the WTI of a BWB regulation files it by government theme (`normalize bwb`). |
| `policy_domains[].label` | `str` | The theme as the WTI names it ("Overheid, bestuur en koninkrijk"). |
| `policy_domains[].id` | `str` | The id of its TOOI concept (`scw_bwb_themas`). |
| `policy_domains[].uri` | `str` | The URI of that concept. |
| `policy_domains[].slug` | `str` | Its slug, unique in the list. |
| `bwb_id` | `str` | The BWB id: `BWBR0001854`, a treaty `BWBV...`. |
| `celex` | `str` | The CELEX number of an EU act: `32016L0680`. |
| `title` | `str` | A BWB regulation its citeertitel, else its intitule; an EU act its printed title; a Verdragenbank treaty its Dutch title, else its English one. |
| `official_title` | `str` | The `intitule` of its toestand. |
| `citation_title` | `str` | The title it is cited by: of an EU act the form of its era (`Richtlijn 95/46/EG`), of a publication its name (`Stb. 2019, 33`), of a Verdragenbank treaty its whole title. |
| `citation_titles` | `list[str]` | Of a BWB regulation: every citation title its WTI gives, the earlier ones too (the Participatiewet was the Wet werk en bijstand; `normalize bwb`). |
| `short_title` | `str` | The WTI short title of a BWB regulation; of an EU act the name between brackets that ends its title (`Datagovernanceverordening`). |
| `official_id` | `str` | Of a publication: its id at officielebekendmakingen.nl (`stb-2019-33`); of a law the BWB does not hold (yet), that of the publication that enacted it (`stb-2026-56`). |
| `abbreviation` | `str` | The abbreviation it is cited by (`core.aliases.abbreviation_of`): `EVRM`, `AVG`. |
| `aliases` | `list[str]` | Every name it is cited by: the WTI abbreviations and, for a book of a code, the forms "Boek 6 BW", "6 BW", "BW 6", "BW6", "BW Boek 6", "BW". |
| `jurisdiction` | `str` | `nl` (BWB), `eu` (EUR-Lex) or `int` (Verdragenbank). |
| `kind` | `str` | BWB `wetgeving@soort` (`wet`, `AMvB`, ...); a Verdragenbank treaty `verdrag`, `bilateraalverdrag` or `multilateraalverdrag`; a publication `publicatie`; a law of the Staatsblad the BWB does not hold (yet) `wet`; lower-cased by `semantic graph-list-stats`. |
| `lang` | `str` | Of an EU act: the language its text was read in. |
| `meta` | `object` | Of an EU act: the `meta` of its raw record. |
| `external_id` | `str` | Of a Verdragenbank treaty: its id in the register. |
| `uri` | `str` | Of a Verdragenbank treaty: its URI in the register. |
| `title_nl` | `str` | Of a Verdragenbank treaty: its Dutch title. |
| `title_en` | `str` | Of a Verdragenbank treaty: its English title. |
| `treaty_number` | `str` | The six-digit Verdragenbank id, which a BWB treaty names in `wetgeving@verdragnummer`. |
| `treaty_type` | `str` | Of a Verdragenbank treaty: its type as the register gives it. |
| `status` | `str` | Of a Verdragenbank treaty: its status as the register gives it; of a law of the Staatsblad the BWB does not hold (yet) `vastgesteld`: its text as published, not in force. |
| `in_force` | `bool` | Of a Verdragenbank treaty: its status is `inwerkinggetreden`; of a law of the Staatsblad the BWB does not hold (yet) `false`. |
| `date_signed` | `str` | The day the instrument itself was signed (of a BWB regulation: that of the publication that enacted it; of an EU act: the day its title names), not that of an amendment. |
| `date_in_force` | `str` | The day it came into force (of a BWB regulation: `inwerkingtreding.datum` of the `<intitule>`). |
| `version_date_in_force` | `str` | BWB: the start of the toestand in force. |
| `date_expired` | `str` | BWB: the first day it was no longer in force (repealed or lapsed); null while in force. |
| `place_signed` | `str` | Of a Verdragenbank treaty: where it was signed. |
| `tractatenblad` | `list[object]` | Of a Verdragenbank treaty: its Tractatenbladen. |
| `tractatenblad[].official_id` | `str` | Its id at officielebekendmakingen.nl: `trb-1951-154`. |
| `tractatenblad[].text` | `str` | As the register writes it: "1951, 154". |
| `tractatenblad[].description` | `str` | What it publishes: "goedkeuring, inwerkingtreding". |
| `parties` | `list[object]` | Of a Verdragenbank treaty: its state parties. |
| `parties[].name` | `str` | The state. |
| `parties[].signed` | `str` | `DatumOndertekenning`. |
| `parties[].ratified` | `str` | `DatumRatificatie`. |
| `parties[].consent` | `str` | `TypeInstemming`: `R`, `T` (toetreding), `A`, ... |
| `parties[].provisional` | `str` | `DatumVoorlopigeToepassing`. |
| `parties[].in_force` | `str` | `DatumInwerkingtreding`. |
| `parties[].retroactive` | `str` | `DatumTerugwerkendeKracht`. |
| `parties[].denounced` | `str` | `DatumOpzegging`. |
| `parties[].terminated` | `str` | `DatumBuitenwerkingtreding`. |
| `parties[].reservation` | `bool` | `IsVoorbehoud`: it made a reservation. |
| `parties[].objection` | `bool` | `IsBezwaar`: it made an objection. |
| `kingdom_parts` | `list[object]` | Of a Verdragenbank treaty: the parts of the Kingdom it applies to. |
| `kingdom_parts[].part` | `str` | "Nederland (in Europa)", "Aruba". |
| `kingdom_parts[].provisional` | `str` | `DatumVoorlopigeToepassing`. |
| `kingdom_parts[].in_force` | `str` | `DatumInwerkingtreding`. |
| `kingdom_parts[].retroactive` | `str` | `DatumTerugwerkendeKracht`. |
| `kingdom_parts[].terminated` | `str` | `DatumBuitenwerkingtreding`. |
| `kamerstukken` | `list[object]` | Of a Verdragenbank treaty: the dossiers of its approval, each once. |
| `kamerstukken[].dossier` | `str` | The dossier number. |
| `kamerstukken[].rijks_number` | `str` | The number of a rijkswet (`R2188`), as the register writes it. |
| `kamerstukken[].sub_number` | `str` | The sub-number, as the register writes it. |
| `parent_treaties` | `list[object]` | Of a Verdragenbank treaty: its `Moederverdragen`. |
| `parent_treaties[].id` | `str` | The Verdragenbank id: `005132`. |
| `parent_treaties[].title` | `str` | Its title. |
| `parent_treaties[].date` | `str` | Its date, as the register gives it. |
| `parent_treaties[].place` | `str` | Its place, as the register gives it. |
| `child_treaties` | `list[object]` | Of a Verdragenbank treaty: its `Kindverdragen`. |
| `article_count` | `int` | Its articles in force, without stubs: the `total` of `/articles` (`semantic graph-list-stats`). |
| `inbound_citation_count` | `int` | The `REFERS_TO` edges to it and to its articles and annexes (`semantic graph-list-stats`). |
| `amending` | `bool` | A BWB regulation that changes other regulations rather than standing on its own: its articles are numbered as a wijzigingsregeling (`Artikel I`) and one or more of them changed another regulation, or most of them did (the BWB puts "Wijzigt <regulation>." in their place); `semantic graph-list-stats`. |
| `publication_kind` | `str` | Of a publication: its journal (`Staatsblad`, `Tractatenblad`, ...). |
| `publication_year` | `int` | Of a publication: its year. |
| `publication_number` | `str` | Of a publication: its number in that year. |
| `date_published` | `str` | The day it was published (of a BWB regulation: that of the publication that enacted it). |
| `dossier_numbers` | `list[str]` | The dossiers of the publication (of a BWB regulation: of the one that enacted it). |
| `basis` | `list[object]` | The `Gelet op` references of its toestand: `{bwb_id, article, doc, text}` (`BASED_ON`). |
| `celex_refs` | `list[str]` | The EU acts its text names. |
| `implements_celex` | `list[str]` | The EU acts its considerans says it implements (`IMPLEMENTS`). |
| `enacted_publication` | `str` | The publication that enacted it: `stb-2018-144`. |
| `unlinked_references` | `int` | Of a law of the Staatsblad: the article references in the text of its articles that `semantic staatsblad-law-references` read and could not link (0: it linked every one); absent until that step read the law. |
| `definitions_found` | `int` | Of a law of the Staatsblad: the definitions `semantic bwb-definitions` read from its text; absent until that step read the law. |

<!-- props:instruments:end -->

## Article and versions

BWB identifies an article by `stam-id`, which stays the same across versions and
renumbering; each version has a `versie-id`.

| Node | Identity |
|------|----------|
| Article | one per `(bwb_id, article_number)` for the current text, per `stam_id` for an article without a number; historical identities per `stam_id` |
| ArticleVersion | one per `(stam_id, versie_id)`, not per toestand; a republication (`tekstplaatsing`) with the label, heading, place and text (`content_digest`) of the version before it is that version |
| InstrumentVersion | one per toestand `(bwb_id, valid_from)` |

An article's `heading` is absent when the BWB prints none, as for every article of the Wetboek
van Strafrecht and the Burgerlijk Wetboek. An ArticleVersion also holds `breadcrumb`, the
divisions of the first toestand holding it, and `breadcrumb_changes` (`[{from, breadcrumb}]`,
oldest first: the toestand starts from which it stood under other divisions, as when a
hoofdstuk is renamed; null for most), which its schema does not name.

- `ArticleVersion VERSION_OF Article` and `InstrumentVersion VERSION_OF Instrument`. There are
  no membership or succession edges: "the article on date X" is the version with
  `valid_from <= X` and (`valid_until > X` or null).
- An annex (`<bijlage>`) numbers its articles on its own: Bijlage 2 and Bijlage 3 of the Awb
  each have an article 1. The number of an article of an annex names the annex as the JCI does
  (`bijlage=2&artikel=9`): `article_number` is `bijlage 2 artikel 9`, its display name
  `Artikel 9 van bijlage 2 …`, and a reference to it (`props.references`) has that number.
- A regulation of one article gives it as `<enig-artikel>` (no `<kop>`, no number; at
  `/Enig-artikel` on wetten.overheid.nl, without a JCI address of its own). Its
  `article_number` is `enig-artikel`, as the source names it, so its key
  (`bwbr0007846_enig_artikel`) and address (`/wetten/BWBR0007846/artikel/enig-artikel`)
  follow from it like any other; its `label` is `Enig artikel`.
- An article may have a heading and no number (`<kop><titel>Algemene bepaling</titel></kop>`,
  the first article of the Grondwet; the Slotbepaling of BW Boek 8). It is an article like any
  other, with its text and parts, keyed and addressed by its `stam-id`, which stays across
  versions: `article_number` is null, `label` its heading, `display_name` `Algemene bepaling
  Grondwet`. No prop ever holds the text `None`.
- Historical articles are identities that are not in the current toestand. They have no
  `article_number` (`(bwb_id, article_number)` is a unique index); the last known number is
  in `last_article_number` and their `label` is that of their newest version. They carry
  `repealed: true`.
- `repealed` is also set on a current article whose latest `effect` is `vervallen`, and is
  `false` on every other current article: it is never read from the number.
- Articles of the current toestand without text, or without a number and a `stam-id`, are not
  written.
- `parts` is the structure of the text: a list of `{id, kind, number, start, end, term}`, offsets into
  the article's own `text` (the text of a part is `text[start:end]`, without its printed
  number). `kind` is `lid`, `onderdeel`, `aanhef` or `tekst`; sentences (volzinnen) are not parts. A
  part with onderdelen spans them too, and the list is ordered by `start`, an enclosing part
  first. The `id` is stable and unique in the article: `lid-2`, `lid-2a`, `lid-2-aanhef` (the
  text of a lid before its onderdelen), `lid-2-onder-a`, `lid-2-onder-a-onder-1` (an onderdeel
  of an onderdeel), and for an article without leden `aanhef` and `onder-a`. Numbers are
  written lower case without the degree sign (`1°` is `onder-1`; `number` keeps `1°`). An
  item without a letter or digit (a dash, a definition) is `onder-_<n>`, its position among
  its siblings; a marker that repeats one before it gets `_<n>`, its occurrence
  (`onder-a_2`). In an article with parts, a paragraph in none of them (a note next to the
  leden, a line between the lists of an article of a bijlage) is a `tekst` (`tekst-1`,
  `tekst-2`), so that the parts and their printed numbers cover the whole text. A paragraph
  that is only a term (`<nadruk>adviseren:</nadruk>`, Wft 1:1) holds the list after it:
  `tekst-6-onder-a`. A list keeps its parent, also an unmarked one: `onder-_39-onder-a`.
  `term` (absent elsewhere) is the term an unmarked onderdeel or a `tekst` defines, the
  `<nadruk>` its paragraph begins with; such a definition is cited by it ("art. 1,
  definitie van 'netwerk- en informatiesysteem', onder a").
- A table (CALS `<table>`, the rates of art. 2.10 and 3.112 Wet IB 2001) stands in the text
  where the XML has it, inside the part that holds it, on lines of its own: a row a line, its
  cells separated by a tab, an empty cell an empty string, so the search finds the text of
  its cells. `tables` (absent without one) lists them as `{start, end, head_rows, columns,
  spans}`, offsets into `text`: `head_rows` the rows of its `<thead>`, the first of the span;
  `spans` (absent when none) `{row, cell, cols, rows}` per cell that covers more than one
  column (`namest`/`nameend`) or row (`morerows`); a row next to such a cell has fewer cells.
  A `<specificatielijst>` (an item and its amount, BWBR0007846) and a `<definitielijst>` (a
  term and what it means) are tables too, without a header: an item a row, its `li.nr` a
  first column when the list has them.
- A heading in the text (a `<tussenkop>`, the `<title>` of a table) stands on a line of its
  own; `headings` (absent without one) lists them as `{start, end}`, offsets into `text`.
- The marker of a footnote (`<sup>1</sup>` after `Richtlijn (EU) 2019/944`, `<sup>1)</sup>`
  in a table header) is no character of `text`: `footnote_marks` (absent without one) lists
  them as `{at, number}`, `text[:at]` the words before it and `number` without brackets
  (`1`). The footnote itself is a paragraph of `text` that opens with its number
  (`1 Richtlijn (EU) 2019/944 van het Europees Parlement …`). A `<sup>` is a marker when the
  article or annex holds such a paragraph of its number; else it is text (`m3` of `m<sup>3</sup>`).
  The site prints a mark as a superscript at `at`, linked to that paragraph.
- The BWB also writes a footnote where its marker stands: `<noot>` with its number
  (`<noot.nr>1)</noot.nr>`) and its text (`<noot.al>`), mostly in treaties and annexes
  (Bijlage I of BWBR0004054: `Dalfsen 1)`). Neither is text: the marker is a mark of
  `footnote_marks` with `footnote`, the place of the footnote in `footnotes` (absent without
  one), which lists them as `{number, text}` in text order, a paragraph of the footnote a
  line. Numbers can repeat within one article or annex; `footnote` says which is meant. A
  footnote in the title of the `<kop>` (BWBV0007162 art. 44) is left out of `heading` and
  listed first, without a mark. A link in a footnote is one of `references` with `footnote`,
  its `start` and `end` offsets into the text of that footnote; the API gives those as
  `footnote_references` beside `references`, and the `REFERS_TO` edge it makes has
  `footnote` instead of `start` and `end`. The titles of divisions, the `entries` and the
  `description` of an annex leave a `<noot>` out.
- An EU article (`celex`, `article_number`) has the same `heading`, `text` and `parts`, read
  from the CELLAR HTML (`core/eurlex_html.py`): `heading` is the line under "Artikel N"
  (`Onderwerp en toepassingsgebied`; null when the act prints none), a lid is `1. text`, a
  point is a line of its own that starts with its marker as printed (`a) text`, `i) text`,
  `— text`); `number` is the marker without its punctuation (`a`). A point laid out without
  text of its own shares its line with the first point inside it (`f) — de ontbinding`).
  Its `position` is its place in the act and its `breadcrumb` the divisions of the act
  (`hoofdstuk`, `afdeling`, `titel`, `deel`, `onderafdeling`: the first word of the label,
  written `Hoofdstuk III`, the title as printed). An EU article has no `label`, `references`
  or versions.
- `breadcrumb` is where the article stands in its regulation, outermost first:
  `{type, label, title}` per division that holds it, `type` the element of the toestand
  (`bijlage`, `boek`, `deel`, `titeldeel`, `hoofdstuk`, `afdeling`, `paragraaf`, `sub-paragraaf`,
  `divisie`), `label` as printed (`Hoofdstuk 1`, `Titel 1.1`), `title` its heading. Absent for
  an article outside every division.
- `inbound_citation_count` of an article (`semantic graph-list-stats`): its `REFERS_TO` and
  `EXPLAINS` edges in.
- An annex (`annexes`, `normalize bwb`, `PART_OF` its instrument) has `bwb_id`, `label` (`I`,
  `2`, `A`: as cited in article text), `display_name` as its heading prints it (the `<label>`
  and `<nr>` of its `<kop>`: `Bijlage 1`, `Lijst Ia`), `title` (the `<titel>` of its `<kop>`),
  `position` (its place among the annexes of the toestand), `description`, `instrument_id`,
  `instrument_citation_title` and `instrument_abbreviation` (its law's name, which its title
  cites; `normalize bwb` keeps them in step with the instrument) and `entries`, its list: `{index, name, description, heading, parent_index}` (`heading` the paragraph that
  introduces a list, `parent_index` the entry it is nested in). Its `text`, `parts`, `tables`,
  `headings`, `footnote_marks`, `footnotes` and `references` are read as those of an article (one reader,
  `core/bwb_xml.py`), without the articles of the annex, which are articles of their own; the
  heading of a division of the annex (`1.1 Structuurelement A`) is a heading of the text.
- `references` holds every `extref`/`intref` of the text that names a regulation, an annex or
  an EU act: `{kind, bwb_id, article, doc, text, start, end, leden, onderdelen, aanhef}`. The
  `doc` (JCI) of a BWB link stops at the article, so `leden`, `onderdelen` (written as in the
  part ids) and `aanhef` are read from the text of the link (`core/qualifiers.py`); a link to a
  chapter or a title has none. A link of `reeks="Celex"` has `celex`, its `doc` (an impossible
  year rebuilt from the text of the link); a link to an annex (`doc` empty) has `annex`, the
  key of the annex its `bwb-ng-variabel-deel` names, when the toestand keeps that annex under
  its label. A mention of an EU act or a Staatsblad without a link is no reference.

Articles:

<!-- props:articles:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `bwb_id` | `str` | The BWB id of its regulation. |
| `celex` | `str` | The CELEX number of its EU act. |
| `official_id` | `str` | Of an article of a law the BWB does not hold (yet): the id of the Staatsblad publication that enacted its law (`stb-2026-56`; `normalize staatsblad-laws`). |
| `unlinked_references` | `int` | Of an article of a law of the Staatsblad: the article references in its text that `semantic staatsblad-law-references` read and could not link (0: it linked every one); absent until that step read it. |
| `article_number` | `str` | As printed (`287`, `bijlage 2 artikel 9`); `enig-artikel` for the one article of a regulation of one article; null for an article with only a heading and for a historical identity. |
| `label` | `str` | `Artikel 287`, or the heading of an article without a number: `Algemene bepaling`. |
| `heading` | `str` | The `<titel>` of its `<kop>` (`Definities`), of an EU article the line under "Artikel N"; absent when the source prints none. |
| `caption` | `str` | What it is about, for its title: the deepest division title only one division of its law has ("Onrechtmatige daad" for 6:162 BW; `semantic bwb-captions`). |
| `position` | `int` | Its place in the current toestand (of an EU article: in the act): the order of the lists. |
| `text` | `str` | Its text: a lid as `1. text`, list items on their own lines, a paragraph beside the leden included. |
| `instrument_citation_title` | `str` | The citation title of its instrument. |
| `instrument_abbreviation` | `str` | The `abbreviation` of its instrument: "art. 8 EVRM" (`normalize bwb`). |
| `stam_id` | `str` | The BWB `stam-id`, the same across versions and renumbering. |
| `versie_id` | `str` | The BWB `versie-id` of its current version. |
| `path` | `str` | `bwb-ng-variabel-deel` of its current version: `/Hoofdstuk1/Artikel7`; where a definition of its law holds (`core.bwb_definitions.applies`). |
| `valid_from` | `str` | `inwerking` of its current version. |
| `source_publication` | `str` | `bron` of its current version: "Stb.2019-33"; of an article of a law of the Staatsblad the publication its text comes from: "Stb. 2026, 57". |
| `repealed` | `bool` | A historical identity, or a current article whose latest `effect` is `vervallen`. |
| `last_article_number` | `str` | Of a historical identity: its last known number. |
| `parts` | `list[object]` | The structure of its text: `{id, kind, number, start, end, term}`, offsets into `text`. |
| `tables` | `list[object]` | The tables in its text: `{start, end, head_rows, columns, spans}`, offsets into `text`, a row a line and its cells separated by a tab; absent without tables. |
| `headings` | `list[object]` | The headings in its text, each on a line of its own (a `<tussenkop>`, the title of a table): `{start, end}`, offsets into `text`; absent without headings. |
| `footnote_marks` | `list[object]` | Where the marker of a footnote (`<sup>1</sup>`, a `<noot>`) stood in its text, which leaves it out: `{at, number}`, `text[:at]` the words before it; the footnote itself is a paragraph of `text` that opens with its number, or, with `footnote`, the one of `footnotes` at that place. Absent without footnotes. |
| `footnotes` | `list[object]` | The footnotes its source writes where their marker stands (`<noot>`), not in `text`: `{number, text}`, in text order, those of its heading (without a marker) first; their links are `references` with `footnote`. Absent without one. |
| `references` | `list[object]` | Every `extref`/`intref` of its text that names a regulation, an annex or an EU act: `{kind, bwb_id, article, doc, text, start, end, leden, onderdelen, aanhef}`, `celex` of an EU act, `annex` the key of the annex linked to; one of a footnote with `footnote`, its place in `footnotes`, `start` and `end` offsets into that footnote's text. |
| `breadcrumb` | `list[object]` | The divisions that hold it, outermost first: `{type, label, title}`; absent outside every division. |
| `inbound_citation_count` | `int` | The `REFERS_TO` and `EXPLAINS` edges to it (`semantic graph-list-stats`). |

<!-- props:articles:end -->

Article versions:

<!-- props:article_versions:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `bwb_id` | `str` | The BWB id of its regulation. |
| `last_seen` | `str` | The start of the latest toestand that holds this version (`normalize bwb-history`). |
| `article_number` | `str` | As printed. |
| `label` | `str` | As on Article. |
| `heading` | `str` | As on Article. |
| `position` | `int` | Its place in one order of all versions of the law, in which the versions of every toestand keep theirs. |
| `valid_from` | `str` | The article's own `inwerking`. |
| `valid_until` | `str` | `valid_from` of the next version of the same article (the first day it no longer holds); its own `valid_from` for a version that says the article lapsed; the start of the first toestand without it for an article that left the law; null when current. |
| `current` | `bool` | It is the version in force. |
| `text` | `str` | As on Article. |
| `instrument_citation_title` | `str` | The citation title of its instrument. |
| `stam_id` | `str` | The BWB `stam-id` of its article. |
| `versie_id` | `str` | The BWB `versie-id`. |
| `path` | `str` | `bwb-ng-variabel-deel`: `/Hoofdstuk1/Artikel7`. |
| `parts` | `list[object]` | As on Article: offsets into `text`. |
| `tables` | `list[object]` | As on Article: offsets into `text`. |
| `headings` | `list[object]` | As on Article: offsets into `text`. |
| `footnote_marks` | `list[object]` | As on Article: offsets into `text`. |
| `footnotes` | `list[object]` | As on Article. |
| `effect` | `str` | BWB effect: `nieuw`, `wijziging`, `vervallen`, ... |
| `source_publication` | `str` | `bron`: "Stb.2019-33". |
| `origin_publication` | `object` | The publication it came from: id, kind, year, number, effect, signed, published, dossiers. |
| `commencement_publication` | `object` | The publication that brought it into force, likewise. |
| `content_digest` | `str` | Of label, heading, place and text: equal for a version that only repeats the one before. |
| `breadcrumb` | `list[object]` | The divisions that held it in the first toestand that holds it, outermost first: `{type, label, title}` (`normalize bwb-history`). |
| `breadcrumb_changes` | `list[object]` | The days from which it stood under other divisions, oldest first: `{from, breadcrumb}`, `from` the start of the first toestand with them; absent when it never moved. |

<!-- props:article_versions:end -->

Instrument versions:

<!-- props:instrument_versions:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `bwb_id` | `str` | The BWB id of its regulation. |
| `valid_from` | `str` | The start of the toestand. |
| `valid_until` | `str` | The day after its last day (exclusive); null when open. |
| `current` | `bool` | It is the toestand in force. |
| `state_url` | `str` | `locatie_toestand` of its SRU record: where its XML is. |

<!-- props:instrument_versions:end -->

Annexes:

<!-- props:annexes:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `bwb_id` | `str` | The BWB id of its regulation. |
| `label` | `str` | `I`, `2`, `A`: as cited in article text. |
| `title` | `str` | The title of its heading; absent where it prints none. |
| `position` | `int` | Its place among the annexes of the toestand: the order of the table of contents. |
| `description` | `str` | Its paragraphs outside its lists, a line each, cut at 2,000 characters. |
| `entries` | `list[object]` | Its list. |
| `entries[].index` | `int` | Its place in the list. |
| `entries[].name` | `str` | Its name. |
| `entries[].description` | `str` | Its description. |
| `entries[].heading` | `str` | The paragraph introducing its list: "Gemeentewet". |
| `entries[].parent_index` | `int` | The entry it is nested in. |
| `text` | `str` | Its text as that of an article, without its articles (articles of their own): a paragraph a line, list items on their own lines, a table a row a line, the heading of a division on a line of its own. |
| `parts` | `list[object]` | The structure of its text, as of an article: `{id, kind, number, start, end, term}`. |
| `tables` | `list[object]` | The tables in its text, as of an article: `{start, end, head_rows, columns, spans}`. |
| `headings` | `list[object]` | The headings in its text (of a division, a table), as of an article: `{start, end}`. |
| `footnote_marks` | `list[object]` | Where the markers of its footnotes stood in its text, as of an article: `{at, number}`. |
| `footnotes` | `list[object]` | Its `<noot>` footnotes, not in its text, as of an article: `{number, text}`. |
| `references` | `list[object]` | The links of its text to a regulation, an annex or an EU act, as of an article. |
| `instrument_id` | `str` | Its instrument. |
| `instrument_citation_title` | `str` | The citation title of its law, which its title cites (`Bijlage 1 Awb`; `normalize bwb` keeps it in step with the instrument). |
| `instrument_abbreviation` | `str` | The abbreviation of its law, likewise. |

<!-- props:annexes:end -->

## Judgment

A Rechtspraak judgment carries:

- its header: `court`, `date`, `case_number`, and `judgment_metadata` with `type`, the
  procedure, `document_type` (`Uitspraak` or `Conclusie`), `related_eclis` (earlier
  instances), `later_eclis` (later instances: `psi:aanleg` latereAanleg), `conclusion_eclis` (its conclusion, or the judgment of a conclusion) and
  `subjects`;
- derived from it: `court_code`, `tier` (the `Type` of its court in the Instanties list),
  `court_kind` (the kind of court within it), `date_eff` and `case_number_keys` (the case
  numbers as compared); see [Courts](pipelines.md#courts);
- `published_on`, "Datum publicatie": the `dcterms:issued` of the `rdf:Description` about the
  published document (its `rdf:about` is the deeplink), not that of the ECLI's own
  description; null without the document. A column, the date of the feed;
- `source` (`rechtspraak`, `echr` for an ECHR judgment, `cjeu` for one of a court of the EU),
  a column of the indexes of the judgment list;
- `summary`, `text`, `paragraphs`, `footnotes`, `parties`, `decision_kind` and `names`; a conclusion also
  `advocate_general` and `advocate_general_role`;
- how it ended (`core/judgment_outcome.py`): of a judgment `outcome`, `outcome_text` and
  `outcome_paragraph_id`, of a conclusion what it proposes as `conclusion_outcome`,
  `conclusion_outcome_text` and `conclusion_outcome_paragraph_id` (below); null when the text
  does not say it.

An ECHR judgment carries `appno`, `title`, `date`, `respondent`, `originating_body`,
`articles`, `conclusion`, `echr_findings` and `outcome` (below), `importance`, `language` (of its HUDOC record; another language version
without an ECLI is `SAME_AS` the one kept and names its item id in `same_as`: `semantic
echr-versions`) and, from the DOCX of its English item (else its French
one), `text` and `paragraphs`. Its paragraphs are read from the Word styles of the Court's
templates (`core/echr_docx.py`): `heading` for a section heading (`JuHHead`, `OpiHHead`,
`ECHRHeading1`), `subheading` for the levels below it (`JuHIRoman`, `JuHA`, `JuH1`,
`ECHRHeading2`…, and the cover lines styled so), `body` for the rest; a table of contents is left
out. A paragraph of the Court opens with its number ("12.  The applicant …"), cited as § 12:
`id` `par-12`, `number` `12`, the number not in `text` (not for a quotation or a point of the
operative part). A heading's number is read only where it is text ("I.  THE CIRCUMSTANCES",
`kop-i`); newer templates number headings by Word's list numbering, which the body does not
hold. A separate opinion numbers from 1 again (`par-1_2`). A paragraph without a number is
named by its text, as for a Rechtspraak judgment (`p-3f2a9c1e`). `text` is every paragraph as
printed, a blank line between.

A judgment of a court of the EU (the Court of Justice, the General Court, the Civil Service
Tribunal: a record of EUR-Lex whose CELEX number is of sector 6, `normalize eurlex`) is keyed by
its ECLI, so the stub a Dutch judgment that cites it made is the judgment itself. It carries
`celex` and `external_id` (its CELEX number, `62018CJ0311`), `case_number` (`C-311/18`, from the
CELEX number: the court, the number and the year the case was brought; without a letter before
1989) and `case_number_keys`, `decision_kind` (`arrest`, `beschikking` or `conclusie`, by the
document letter of the CELEX number), `court` (the name of the code of its ECLI: `C`, `T`, `F`;
tier and court_kind `hvj_eu`), and from what CELLAR says of it (`meta`: `ecli`, `date`, `title`,
`national`, `country`) `date` and `title` (its parties, the second part of the Dutch title:
"Data Protection Commissioner tegen Facebook Ireland Ltd en Maximillian Schrems", also its
`display_name`). `text` and `paragraphs` are read from its HTML (`core/cjeu.py`): a numbered
paragraph is a table row of its number and its text (since about 2014) or opens with its number
and spaces (before), `id` `par-12`; a heading by its markup; the rest named by its text.

`summary` is the inhoudsindicatie, in Dutch; null for a placeholder ("kopje volgt", "-", empty). The Rechtspraak publishes a few judgments in an
English translation too, under an ECLI of their own (ECLI:NL:HR:2019:2007 beside
ECLI:NL:HR:2019:2006, case number `19/00135 (Engels)`); their inhoudsindicatie is English. An
English inhoudsindicatie is kept as `summary_en`; the translation has `translation_of`, the ECLI
of the judgment it translates, and that judgment's Dutch `summary`, and the judgment its
`summary_en`. `summary` of a translation stays null while the judgment it translates is not
loaded.

`decision_kind` is what the decision is: `arrest`, `vonnis`, `beschikking`, `uitspraak`,
`beslissing` (the kantonrechter on a Wahv appeal, a wraking, the notariskamer), `conclusie` or
`prejudiciële beslissing` (`core.judgment_kinds.judgment_kind`; the rule is in
[pipelines](pipelines.md#rechtspraak)); null when nothing tells, as for a decision of the Kroon.
A stub has the kind its kind of court gives (`data/curated/decision_kinds.json`).

`names` is what lawyers call the judgment (`Haviltex`, `Urgenda`, `Lindenbaum/Cohen`), from the
curated list of landmark cases (`data/curated/judgment_names.json`, `lawgraph curated`); empty for most judgments, null on a
stub without one. The open data carries no names: see [pipelines](pipelines.md#rechtspraak).

The judgments of one case are tied by `APPEAL_OF` (an appeal to the judgment it appeals),
`CONTINUES` (a judgment to an earlier one of the same court in the same case), `REFERRED_BY` (a
decision after referral to the Hoge Raad ruling that sent the case back), `ADVISES_ON` (a
conclusion to its judgment) and `ANSWERS` (a preliminary ruling to the decision that asked its
questions); `docs/pipelines.md`, Rechtspraak, says how each is found. Two judgments tied so
have no `REFERS_TO` between them, even when one names the other in its text.

`unresolved_appeal_targets` lists the decisions an appeal says in its text it appeals that are
not loaded (`court` and `case_number` as written, `date` ISO; `case_number` null when the text
gives none); null when there are none. `unresolved_citations` lists the articles a judgment
cites of laws that are not in the graph, the first 100 (`semantic rechtspraak`): `law` as written (or the law a
short name the judgment defines stands for: `Aanbestedingswet` for `Aw`), `article_number` as
written, `raw_match` and `qualifier` of the first citation, `leden`, `onderdelen`, `aanhef`,
`paragraph_ids`, `mention_count`; null when there are none.

Parallel cases a court decided on one day in (nearly) the same words form a series: each
judgment of it has `series_id`, the lowest ECLI in the series, and `series_size`; outside a
series both are null (`semantic rechtspraak-series`). A series has no edges.

A publication of a decision that another publication replaces (`dcterms:isReplacedBy`, kept as
`replaced_by`) is `SAME_AS` the one kept when that is loaded, and has its ECLI as `same_as`
(`semantic rechtspraak-duplicates`); the lists leave it out, and `/api/stats` and
`/api/stats/coverage` count it apart (`replaced`), so every count of judgments counts the decision
once. One whose replacement is not loaded has `replaced_by` and no `same_as`, and is counted. `inbound_citation_count` counts
the judgments that cite a judgment or a publication `SAME_AS` it, each once;
`outbound_citation_count` the judgments it cites.

`paragraphs` is the `<uitspraak>` (of a conclusion: the `<conclusie>`) in reading order, a list
of `{id, number, kind, text, continues}`. `kind` is `heading` (a section or a bridgehead),
`subheading` (a nested section, or the kop), `body`, `toc` or `signature`. `continues` is, of a
`body` paragraph without a number, the `id` of the numbered consideration it goes on with, up to
the next number or heading (absent otherwise). The first paragraph is the kop, a `subheading` of
its lines with a blank line between: court, case number, date and parties, however the court
sets them; a judgment may have none. How the kop, the headings, a table of contents and a
signature are told apart: [pipelines](pipelines.md#judgment-paragraphs).

`footnotes` are the `<footnote>`s of that text, which are no paragraph: `{label, paragraph_id,
text, at}` in their order, `paragraph_id` the paragraph whose `<footnote-ref>` points to it (null when
none does) and `at` where that marker stands in its text (`text[:at]` the words before it; absent
when no paragraph refers to it or the paragraph's text is not the text of the elements it is read
from, as a heading made from a quote); absent without footnotes. `semantic rechtspraak` and `semantic rechtspraak-citations`
read them too: a citation in a footnote counts for that paragraph, its mention with the footnote's
`label` (`footnote`; its place among the footnotes when it has none) and its offsets in the text of
the footnote, so it is no citation span of the paragraph but one of the footnote.

A numbered unit of the XML (`<paragroup>`, however deeply nested) is one `body` paragraph with
its own text: the text of `5.3` does not hold `5.3.1`. `number` is the number as printed without
its closing dot (`5.3`), null when there is none, and is not part of `text`. `id` names the
paragraph in deep links and mentions and is unique in the judgment: `rov-5.3` for a numbered
`body` paragraph (a consideration, cited as "rov. 5.3"), `kop-5` for a numbered heading,
`p-3f2a9c1e` for a paragraph without a number (and a line of a table of contents, from its
number and text): the first 8 hex of the SHA-1 of its text, whitespace collapsed
(`core.judgment_paragraphs.text_id`), so it follows the text and not the position. An id that repeats one
before it gets `_<n>`, its occurrence (`rov-1_2`, or the same text twice).

`advocate_general` is, for a conclusion, who wrote it, as the lines before its parties name them
(`core.judgment_advocate_general.advocate_general`): a line of initials and a surname (`T. Hartlief`), or a name
behind "mr." (`mr. P.J. Wattel`, "Zaaknr: 18/04298 (Prejudicieel) mr. Wattel": `Wattel`), two
together as one ("F.F. Langemeijer en M.H. Wissink"); null when they name no one. The signature
at the end gives the office and, below it, the role they sign in: `advocate_general_role`
(`core.judgment_advocate_general.advocate_general_role`) is `advocaat-generaal` ("A-G", "AG",
"Advocaat-Generaal", "(a.-g.)"), `waarnemend advocaat-generaal` ("Wnd. A-G") or
`plaatsvervangend procureur-generaal` ("plv.") or `plaatsvervangend advocaat-generaal`
("plv. AG"); null when the signature writes none (an A-G signs so too) or one that is not
clear. The heading of the office at the top is
no role.

`outcome` is how a judgment ended, as the first clause of its decision says it: the paragraphs
after its last heading "Beslissing", "De beslissing", "Dictum" or "Uitspraak" (also "5.
Beslissing De Hoge Raad: …" in one paragraph), up to the signature or the next heading. The
clause runs from its verb up to the next `;`, line, full stop before a capital, or verb:

| Clause | `outcome` |
|--------|-----------|
| `verwerpt het beroep` | `verworpen` |
| `vernietigt …` | `vernietigd`; `gedeeltelijk vernietigd` with "voor zover", "maar uitsluitend", "behoudens" |
| `vernietigt …` or `verklaart … gegrond`, and the decision refers the case to a court (`verwijst het geding naar het gerechtshof`, `wijst … terug`) | `vernietigd en verwezen` |
| `bekrachtigt …` / `bevestigt …` | `bekrachtigd` / `bevestigd` |
| `verklaart … niet-ontvankelijk` / `… ongegrond` / `… gegrond` | `niet-ontvankelijk` / `ongegrond` / `gegrond` |
| `wijst het verzoek (de vordering, het gevorderde) af` / `… toe` | `afgewezen` / `toegewezen` |

Any other first clause (`verklaart bewezen`, `veroordeelt`, `bepaalt bij wijze van voorlopige
voorziening`, `houdt iedere verdere beslissing aan`) gives none. `outcome_text` is the clause
(at most 300 characters), `outcome_paragraph_id` its paragraph.

`conclusion_outcome` is what a conclusion proposes: the last sentence with "conclusie strekt",
"in overweging", "concludeer (ik) tot" or "concludeer ik … Uw Raad" names it by the first word
of a kind after those words: `verwerping`, `vernietiging` (`vernietiging en verwijzing` with a
(terug)verwijzing), `niet-ontvankelijkverklaring`, `ongegrondverklaring`, `gegrondverklaring`,
`beantwoording` (of preliminary questions). `conclusion_outcome_text` is the sentence.

Of an ECHR judgment `echr_findings` is what it found per article, read from `conclusion`
(`core/echr_findings.py`): per "Violation of Article 8 - …" or "No violation of …" (in French
"Violation de l'article", "Non-violation de"), split at the `;` outside parentheses, `{article,
protocol, combined_with, finding, aspect, text}`: `finding` `schending` or `geen schending`,
`combined_with` the article of `13+8-1`, `aspect` `materieel` or `procedureel`. Its `outcome`
is `schending` when one finding is, else `geen schending`, with that finding as
`outcome_text`; null without a finding on an article.

`parties` is what the kop names, in its order (`core/judgment_parties.py`), then a party the
account of the procedure hears "als partij" that the kop does not name (`core/judgment_counsel.py`),
a list of `{name, role, roles, role_stated, side, alias, representatives}`; empty when neither names
one:

How the parties are read:

- `name` is as the judgment writes it (`[eiser]`, `MAATSCHAP GRONINGEN`), without its legal
  form ("de stichting"), place or role. `role` is `Verdachte`, `Betrokkene`, `Klager`,
  `Veroordeelde` (also a terbeschikkinggestelde), `Eiser`, `Gedaagde`, `Verzoeker`,
  `Verweerder`, `Appellant`, `Geïntimeerde`, `Belanghebbende`, `Opposant`, `Wederpartij`, or
  `Partij` when none applies.
- The judgment names the role (`role_stated`) by a role line ("EISERS in eerste aanleg,", which
  holds for every party above it since the one before), a role behind the name (", eiser",
  "(appellante)", "hierna: de verdachte"), the opener ("Uitspraak op het hoger beroep van:"), a
  list of designations ("verzoekster 1 als: [X]") or an anonymised name that is a role
  (`[verdachte]`, `[klager 1]`). Otherwise the role is derived from the area of law (the first
  `subjects`) and the side: Strafrecht `Verdachte`; Civiel recht `Eiser` (`Verzoeker` in a
  beschikking) against `Verweerder` (`Geïntimeerde` against a stated `Appellant`);
  Bestuursrecht `Appellant` against `Verweerder`; `Belanghebbende` on no side.
- `side`: the verdachte of "in de strafzaak tegen" is on the `second` side too. A party of the
  case an appeal was against ("tegen de uitspraak ... in het geding tussen:") that is not an
  appellant is on the `second` side; one named again, there or in a joined case, is one party.
- `alias` is distributed over "hierna respectievelijk: de Maatschap en NAM", or a short name in
  parentheses whose letters are in the name (`(Uwv)`).
- `representatives` are read in the kop ("advocaat: mr. X", "(gemachtigde: mr. Y)", for the
  parties named since the last one) and in the account of the procedure (the paragraphs before
  the first heading that is not of the procedure, "Overwegingen": "[X], bijgestaan door mr. Y,
  advocaat te Z", "verweerder, vertegenwoordigd door mr. W, ambtenaar in dienst van de
  provincie", "de verdachte en zijn raadsman, mr. V", "Namens de verdachte heeft mr. U,
  advocaat te T, ... cassatie"), for the party named closest before it (by its name, alias,
  head, "het college", or role word; one of several of a role in the singular gets no one).

A `REFERS_TO` edge from a judgment to an article (`semantic rechtspraak`) is one per judgment and
article. Its `confidence` is that of the strongest mention, `meta.mention_count` the number of
mentions, `meta.reason` the kind of target, and `meta.mentions` the first 100 mentions in
reading order:

| Field | Meaning |
|-------|---------|
| `paragraph_id`, `paragraph_number` | the paragraph that cites the article (`number` is absent when it has none) |
| `start`, `end`, `raw_match` | the citation as written: `text[start:end]` of that paragraph |
| `qualifier` | what the citation says of the article's parts, as written: `derde lid` |
| `leden`, `onderdelen`, `aanhef` | what the qualifier names, as in the part ids of an article (`core/qualifiers.py`) |
| `snippet`, `confidence` | the text around the citation; 0.95 for a law named by its code or its title, less for a law that is found by "die wet" |
| `snippet_start` | where `snippet` starts in that text: `snippet[start - snippet_start:end - snippet_start]` is `raw_match`, so a passage shows without the text |

A `REFERS_TO` edge from a judgment to a judgment it cites (`semantic rechtspraak-citations`) has
`meta.mentions` and `meta.mention_count` in the same shape, without the qualifier fields, and
`meta.paragraphs`, the numbers of their paragraphs, each once.

A Tweede Kamer document's edge to an article or an instrument has `meta.raw_match`, `snippet`,
`reason`, `qualifier`, `leden`, `onderdelen` and `aanhef` of the first citation of it, and
`meta.place`, where that citation stands in what `/api/documents/{key}` serves (`core/document_reading.py`):

| Field | Meaning |
|-------|---------|
| `part` | `title`, `text` or `footnote` |
| `start`, `end` | the citation as written: `[start:end]` of that part (of `text`, or of the footnote's `text`) |
| `section_id` | in `text`: the innermost section it stands in |
| `footnote`, `footnote_id` | in a footnote: its number as printed, and its `id` (`fn-<n>`, unique where the number is not) |

`snippet` is of that part alone. `place` is null for a citation that runs from one part into the
next (the text read joins them with a line break).

<!-- props:judgments:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `ecli` | `str` | Its ECLI. |
| `source_kind` | `str` | The kind of the raw record it was read from (`rs-content`). |
| `meta` | `object` | The `meta` of its raw record. |
| `summary` | `str` | The inhoudsindicatie, in Dutch; null for a placeholder ("kopje volgt", "-"). |
| `summary_en` | `str` | An English inhoudsindicatie: of a translation, and of the judgment it translates. |
| `translation_of` | `str` | Of an English translation: the ECLI of the judgment it translates. |
| `names` | `list[str]` | What lawyers call it (`Haviltex`; `core.judgment_names`). |
| `decision_kind` | `str` | `arrest`, `vonnis`, `beschikking`, `uitspraak`, `beslissing`, `conclusie` or `prejudiciële beslissing` (`core.judgment_kinds.judgment_kind`). |
| `text` | `str` | Every paragraph as printed, a blank line between. |
| `judgment_metadata` | `object` | Its RDF header: `type`, the procedure, `document_type` (`Uitspraak` or `Conclusie`), `court`, `date`, `case_number`, the related ECLIs, ... |
| `subjects` | `list[str]` | Its areas of law as the metadata gives them ("Civiel recht; Verbintenissenrecht"). |
| `paragraphs` | `list[object]` | The `<uitspraak>` (of a conclusion: the `<conclusie>`) in reading order; the first is the kop. |
| `paragraphs[].id` | `str` | `rov-5.3`, `kop-5`, `p-3f2a9c1e`, `par-12`: unique in the judgment, for deep links. |
| `paragraphs[].number` | `str` | As printed, without its closing dot: "5.3"; null when it has none. |
| `paragraphs[].kind` | `"heading" \| "subheading" \| "body" \| "signature" \| "toc"` | What the paragraph is. |
| `paragraphs[].text` | `str` | Its text, without its number. |
| `paragraphs[].continues` | `str` | Of a `body` paragraph without a number: the `id` of the numbered consideration it goes on with. |
| `paragraphs[].tables` | `list[object]` | The tables in its text: `{start, end, head_rows, columns, spans}` (as on Article), offsets into `text`; absent without tables. |
| `footnotes` | `list[object]` | Its footnotes, which are no paragraph: `{label, paragraph_id, text, at}`; `paragraph_id` the paragraph that refers to it (null when none does), `at` where that marker stands in its text (`core.judgment_paragraphs.judgment_text`). |
| `parties` | `list[object]` | What the kop names, in its order, then a party the account of the procedure hears "als partij"; `[]` when neither names one, absent when not read yet. |
| `parties[].name` | `str` | As the judgment writes it, anonymised where the source is (`[eiser]`), without its legal form, place or role. |
| `parties[].role` | `str` | `Verdachte`, `Eiser`, `Verweerder`, `Appellant`, `Belanghebbende`, ...; `Partij` when none applies. |
| `parties[].roles` | `list[str]` | Every role the judgment names for the party, in its order; `[role]` when it names none. |
| `parties[].role_stated` | `bool` | The judgment names the role; false when it is derived from the area of law and the side. |
| `parties[].side` | `"first" \| "second" \| "other"` | `first` before "tegen" or "en", `second` after it, `other` for a belanghebbende that is not the first party. |
| `parties[].alias` | `str` | What the judgment calls it: `EBN` for "hierna: EBN". |
| `parties[].representatives` | `list[object]` | Who acts for the party, each person once. An expert, interpreter or witness is no representative. |
| `parties[].representatives[].name` | `str` | As written, titles and all: "mr. drs. R. van Gelder". |
| `parties[].representatives[].role` | `"advocaat" \| "gemachtigde" \| "raadsman"` | The word the text gives; else `gemachtigde` for who represents a party and `raadsman` for who assists a suspect (`raadsman` in a criminal case only). |
| `parties[].representatives[].place` | `str` | Where they practise: "Voorschoten". |
| `parties[].representatives[].capacity` | `str` | What else the text calls them: "ambtenaar in dienst van de provincie". |
| `advocate_general` | `str` | Of a conclusion: who wrote it, as its kop names them (`core.judgment_advocate_general.advocate_general`). |
| `advocate_general_role` | `str` | The role they sign in: `advocaat-generaal`, `waarnemend advocaat-generaal`, `plaatsvervangend procureur-generaal` or `plaatsvervangend advocaat-generaal` (`core.judgment_advocate_general.advocate_general_role`). |
| `court` | `str` | The court as the metadata names it. |
| `case_number` | `str` | As the metadata gives it. |
| `case_number_keys` | `list[str]` | `case_number` split and written as compared (`core.case_numbers.case_number_keys`). |
| `related_eclis` | `list[str]` | The earlier instances the metadata names (`dcterms:relation`). |
| `later_eclis` | `list[str]` | The later instances it names (`psi:aanleg` latereAanleg): the courts that ruled on appeal of it, in cassation or after it. |
| `conclusion_eclis` | `list[str]` | The conclusion of a judgment, or the judgment of a conclusion (`psi:type` conclusie). |
| `unresolved_appeal_targets` | `list[object]` | The decisions an appeal names in its text that are not loaded (`semantic rechtspraak-appeal`); null when there are none. |
| `unresolved_appeal_targets[].court` | `str` | As the text writes it: "rechtbank Gelderland". |
| `unresolved_appeal_targets[].date` | `str` | ISO. |
| `unresolved_appeal_targets[].case_number` | `str` | As the text writes it: "24/6811"; null when it gives none. |
| `unresolved_citations` | `list[object]` | The articles it cites of laws that are not in the graph, the first 100, in reading order (`semantic rechtspraak`); null when there are none. |
| `unresolved_citations[].law` | `str` | As the text writes it ("Rv", "Vw 2000"), or the law a short name the judgment defines stands for. |
| `unresolved_citations[].article_number` | `str` | As written. |
| `unresolved_citations[].raw_match` | `str` | The first citation: "art. 392 Rv". |
| `unresolved_citations[].qualifier` | `str` | Of the first citation: "derde lid". |
| `unresolved_citations[].leden` | `list[str]` | The leden it names, as in the part ids of an article. |
| `unresolved_citations[].onderdelen` | `list[str]` | The onderdelen it names, likewise. |
| `unresolved_citations[].aanhef` | `bool` | It names the aanhef. |
| `unresolved_citations[].paragraph_ids` | `list[str]` | The paragraphs that cite it. |
| `unresolved_citations[].mention_count` | `int` | How often the judgment cites it. |
| `court_code` | `str` | The court of its ECLI (`HR`, `GHAMS`). |
| `tier` | `str` | The `Type` of its court in the Instanties list. |
| `court_kind` | `str` | The kind of court within that tier. |
| `date_eff` | `str` | Its date: of the metadata, else of the raw record. |
| `published_on` | `str` | "Datum publicatie": the `dcterms:issued` of the published document (`core.judgment_metadata.published_on`); null without the document. |
| `inbound_citation_count` | `int` | The judgments that cite it or a publication `SAME_AS` it, each once (`semantic graph-list-stats`). |
| `outbound_citation_count` | `int` | The judgments it cites (`semantic graph-list-stats`). |
| `replaced_by` | `str` | `dcterms:isReplacedBy`: the ECLI of the publication of the same decision that replaces this one. |
| `withdrawn` | `str` | How the Rechtspraak withdrew it (`deleted` of its index entry): `doc` (the document is no longer published) or `ecli` (the ECLI was given in error; `replaced_by` the one the source names instead, if it names one). The judgment is then a stub with the facts of the decision that name no one: `ecli`, `court` and its codes, `date`, `date_eff`, `case_number(_keys)`, `decision_kind`, `subjects`. Null while it is published. |
| `withdrawn_on` | `str` | The day it was withdrawn (Dutch time, of the `updated` of its index entry). |
| `same_as` | `str` | That publication, when it is loaded (`semantic rechtspraak-duplicates`): this one is `SAME_AS` it and left out of the lists. Of an ECHR language version without an ECLI: the item id of the one kept (`semantic echr-versions`). |
| `series_id` | `str` | Of parallel cases of one court and day (`semantic rechtspraak-series`): the lowest ECLI of the series; null outside a series. |
| `series_size` | `int` | How many judgments the series has. |
| `external_id` | `str` | ECHR: the HUDOC item id; CJEU: the CELEX number. |
| `celex` | `str` | CJEU: the CELEX number (sector 6: `62018CJ0311`). |
| `appno` | `str` | ECHR: the application number. |
| `language` | `str` | ECHR: the language of the HUDOC record (`ENG`, `FRE`). |
| `title` | `str` | ECHR: the name of the case; CJEU: its parties as CELLAR names them. |
| `date` | `str` | The day of the decision. |
| `respondent` | `str` | ECHR: the respondent state. |
| `originating_body` | `str` | ECHR: the formation that decided. |
| `articles` | `list[str]` | ECHR: the articles of the Convention the record names. |
| `conclusion` | `str` | ECHR: the conclusion of the record ("Violation of Article 8 - ..."). |
| `importance` | `int` | ECHR: the importance level of the record. |
| `outcome` | `str` | How it ended, as the first clause of its decision says it (`verworpen`, `vernietigd`, ...; `core/judgment_outcome.py`); of an ECHR judgment `schending` or `geen schending` (`core/echr_findings.py`); null when the text does not say it. |
| `outcome_text` | `str` | The clause (at most 300 characters), or the ECHR finding. |
| `outcome_paragraph_id` | `str` | The paragraph of that clause. |
| `conclusion_outcome` | `str` | Of a conclusion: what it proposes (`verwerping`, `vernietiging`, ...). |
| `conclusion_outcome_text` | `str` | The sentence that says it. |
| `conclusion_outcome_paragraph_id` | `str` | The paragraph of that sentence. |
| `echr_findings` | `list[object]` | ECHR: what it found per article, read from `conclusion`: `{article, protocol, combined_with, finding, aspect, text}` (`core/echr_findings.py`). |

<!-- props:judgments:end -->

## Parliament

A dossier holds cases, and a case holds documents. The Tweede Kamer's records are the source;
the Eerste Kamer adds its own votes, agendas, bills, factions and committees, each marked
`chamber` `EK` (label `EK`).

### Dossier (`dossiers`)

`closed` and `outcome` leave a withdrawn bill open (see Known limits). `first_signed`, written
by `semantic tk-government`, is the first signature that `ministry` and `initiative` rest on:
`date`, `member`, `capacity`, `function` and the `paper` (its id); null when no paper is signed
so. Its schema does not name it.

<!-- props:dossiers:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Kamerstukdossier` record. |
| `number` | `str` | `37020`. |
| `suffix` | `str` | `XV`. |
| `label` | `str` | `37020-XV`; the key is made from it. |
| `order` | `str` | A text that sorts dossiers as the Kamer does: by number, then no suffix, numeric suffixes, budget chapters, the rest (`core/dossier_numbers.dossier_order`). |
| `title` | `str` | Its title. |
| `title_source` | `str` | Where the title comes from. |
| `closed` | `bool` | It has an outcome (`semantic tk-dossier-outcomes`); `false` for an open dossier. |
| `opened_on` | `str` | The date of nr. 1 of its own numbering, else of its Koninklijke boodschap, else of its first document or activity. |
| `opened_on_basis` | `str` | Where `opened_on` comes from: `first_paper`, `royal_message` or `earliest_record`. |
| `last_activity` | `str` | The day of its newest document, activity that took place or decision; refreshed by every `normalize tk-dossiers` that touches it. |
| `submitted_on_tk` | `str` | The `Zaak.GestartOp` of its own zaak of a bill (`Wetgeving`, `Initiatiefwetgeving`, `Begroting`): the day the Kamer dates its submission. |
| `closed_on` | `str` | The day of its outcome. |
| `case_kinds` | `list[str]` | The `Zaak.Soort` of its own cases. |
| `kind` | `str` | What the dossier is: the `Zaak.Soort` of its own zaak (`Wetgeving`, `Begroting`, `Verdrag`, ...; `core/dossier_stages.CARRYING_KINDS`); null without such a zaak. Never read from its papers. |
| `kind_basis` | `str` | `case` when its zaak gives the kind, else null. |
| `phases` | `list[object]` | Of a `Wetgeving`, `Initiatiefwetgeving` or `Begroting`: every phase of the curated list `phases` in its order. A phase is done when a paper, an activity that took place or a decision on the dossier's own zaak has a value the list names for it. |
| `phases[].name` | `str` | The phase, as the curated list names it. |
| `phases[].done` | `bool` | A record of the dossier marks it. |
| `phases[].date` | `str` | The first date of the records that mark it. |
| `current_phase` | `str` | The furthest done phase. |
| `outcome` | `str` | `aangenomen` when its law was published or the Eerste Kamer adopted it, `verworpen` when a chamber voted the bill down, `ingetrokken` when the government withdrew it by letter (`semantic tk-dossier-outcomes`). |
| `withdrawal_letter` | `str` | Of a withdrawn bill, the id of the letter that withdrew it: a `Brief regering` whose `Onderwerp` is the fixed title `Brief houdende intrekking van het wetsvoorstel` (`core/dossier_stages.WITHDRAWAL_LETTER_SUBJECT`). |
| `tk_decision` | `object` | The last decision of the Tweede Kamer on its bill. |
| `tk_decision.kind` | `str` | Its `BesluitSoort`. |
| `tk_decision.text` | `str` | Its text. |
| `tk_decision.date` | `str` | Its day. |
| `ek_rejected` | `object` | The Eerste Kamer's list of rejected bills names it (`normalize eerstekamer-votes`). |
| `ek_rejected.date` | `str` | The day. |
| `ek_rejected.source_url` | `str` | The list. |
| `ek_rejected.retrieved_on` | `str` | The day it was read. |
| `ek_outcome` | `object` | Its outcome in the Eerste Kamer. |
| `ek_outcome.outcome` | `str` | `Aangenomen` or `Verworpen`. |
| `ek_outcome.date` | `str` | The day. |
| `ek_outcome.method` | `str` | How it was decided, as eerstekamer.nl writes it. |
| `ek_outcome.source_url` | `str` | The page it was read from. |
| `ek_outcome.retrieved_on` | `str` | The day it was read. |
| `ek_bill` | `object` | The page of its bill on eerstekamer.nl (`normalize eerstekamer-bills`). |
| `ek_bill.url` | `str` | The page. |
| `ek_bill.read_on` | `str` | The day it was read. |
| `ek_bill.status` | `str` | The status the page gives. |
| `ek_bill.submitted_on` | `str` | The day it was submitted, as the page gives it. |
| `ek_bill.progress` | `list[object]` | The steps of its progress block. |
| `ek_bill.progress[].phase` | `str` | The phase, as the page names it. |
| `ek_bill.progress[].house` | `str` | The chamber of the step. |
| `ek_bill.progress[].state` | `str` | As the page marks it: `vol`, `geblokt`, `leeg`. |
| `ek_bill.progress[].papers` | `list[object]` | Its papers. |
| `ek_bill.progress[].papers[].kind` | `str` | As the page names it. |
| `ek_bill.progress[].papers[].date` | `str` | Its date. |
| `ek_bill.progress[].papers[].number` | `str` | Its number. |
| `ek_bill.progress[].papers[].url` | `str` | Its link. |
| `ministry` | `str` | Who brought it in (`semantic tk-government`): the ministry of the bewindspersoon who first signed its earliest signed document. |
| `initiative` | `bool` | `true` when a Kamerlid signed first. |
| `cabinet` | `str` | The cabinet in office that day. |
| `first_signed` | `object` | The signature `ministry`, `initiative` and `cabinet` are read from (`semantic tk-government`): the first of the earliest document of the dossier signed first by a Kamerlid or a bewindspersoon, `{date, member, capacity, function, paper}` (`member` its key, `capacity` `kamerlid` or `bewindspersoon`, `paper` the id of the document). |
| `same_number_count` | `int` | The other dossiers with the same number (`normalize tk-dossiers`). |

<!-- props:dossiers:end -->

### Case (`cases`)

Every Zaak of the Tweede Kamer, whatever its kind.

<!-- props:cases:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Zaak` record. |
| `title` | `str` | `Zaak.Titel`; of a motie, amendement, letter or report its `Onderwerp` (its `Titel` is its dossier's). |
| `citation_title` | `str` | As the Kamer writes it. |
| `number` | `str` | As the Kamer writes it. |
| `kind` | `str` | `Zaak.Soort`: `Wetgeving`, `Motie`, `Brief regering`, ... |
| `dossier_numbers` | `list[str]` | Its dossiers. |
| `started_on` | `str` | `Zaak.GestartOp`. |
| `related_cases` | `list[object]` | `Zaak.GerelateerdNaar`: each case the Kamer relates it to (read by `semantic tk-dossier-relations`). |
| `related_cases[].id` | `str` | The TK id of the case. |
| `related_cases[].kind` | `str` | Its `Zaak.Soort`. |
| `related_cases[].dossier_numbers` | `list[str]` | Its dossiers. |
| `replaces_cases` | `list[str]` | `Zaak.VervangenVanuit`: the TK ids of the cases this one replaces ("ter vervanging van nr. 21"). |
| `done` | `bool` | `Zaak.Afgedaan`: whether the Kamer is done with it. An amendment or motion done with and without a decision was replaced or withdrawn; one not done with is still open. |

<!-- props:cases:end -->

### Document (`documents`)

A paper of the Tweede Kamer, a Staatsblad or Staatscourant publication, or a paper of the Eerste
Kamer; the chamber is in `labels` (`TK`; `EersteKamer` and `EK`). A `kind` that contains
`toelichting` makes a document explanatory.

`outcome` of a motion or an amendment (`semantic tk-paper-outcomes`, `core/votes.py`): of the
decisions taken on it (the paper is the oldest of the case a decision singled out, or the
Kamerstuk a vote of the Eerste Kamer is `ABOUT`) a vote before a decision without one, the
latest first: `aangenomen` or `verworpen` by `passed`, else `ingetrokken`, `aangehouden` or
`vervallen` by its `BesluitSoort` (`Stemmen - uitstellen` is none); without a decision the
outcome its `status` names (a motion of the Eerste Kamer); else `vervangen` when a newer paper
replaces it (`REVISES`, rule `vervanging`). The signers of a motion of the Eerste Kamer are its
`actors` and `AUTHORED` from each member.

<!-- props:documents:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its record (TK `Document.Id`). |
| `raw` | `object` | The record of the Tweede Kamer as it came. |
| `dictum` | `str` | Of a motion, what it asks or says as it writes it: the lines from the first that begins with `verzoekt`, `roept`, `spreekt`, `draagt` or `vraagt` to `en gaat over tot de orde van de dag`, joined (`core/motion_dictum.py`); absent for any other paper and for a text without that closing formula. Also kept by `semantic tk-dictum` for the motions whose text was read before. |
| `explanation` | `str` | Of an amendment, what it is for: the first paragraph of its "Toelichting", whole sentences up to 400 characters, else cut at a word with "…" (`core/amendment_explanation.py`); absent for any other paper and for one without a Toelichting. |
| `outcome` | `str` | Of a motion or an amendment, how it ended (`semantic tk-paper-outcomes`, `core/votes.py`): `aangenomen`, `verworpen`, `ingetrokken`, `aangehouden`, `vervallen` or `vervangen`. |
| `decided_on` | `str` | The day of the decision that gave the outcome; null without one. |
| `tally` | `{str: int}` | The seats per choice of that decision. |
| `decision` | `str` | The key of that decision. |
| `motion_kind` | `str` | Of a motion of censure `censure` (motie van afkeuring), of no confidence `no_confidence` (motie van wantrouwen), from the fixed wording of its subject (`semantic tk-motion-kinds`, `core/motion_kinds.py`); absent for any other paper. |
| `summary` | `str` | Of a motion of the Eerste Kamer (`normalize eerstekamer-motions`): what it asks as its page opens. |
| `submitted_on` | `str` | Of such a motion: the day it was submitted. |
| `debate` | `str` | Of such a motion: the debate it was submitted at. |
| `status` | `str` | Of such a motion: its `behandelstatus` as the Kamer writes it. |
| `motion_url` | `str` | Of such a motion: its page. |
| `pdf_url` | `str` | Of such a motion: its PDF. |
| `title` | `str` | `Titel`; of a motie, amendement, letter or report its own `Onderwerp`, else that of its zaak. |
| `dossier_title` | `str` | Of a document named by its own subject: its `Titel`, the title of its dossier. |
| `subject` | `str` | Its `Onderwerp`. |
| `kind` | `str` | `Document.Soort`; one that contains `toelichting` makes it explanatory. |
| `date` | `str` | Its date. |
| `number` | `str` | Its own number: a Kamerstuk number, or that of a Staatsblad or Staatscourant. |
| `text` | `str` | Its text (`normalize tk-content`): one line per heading, paragraph, list item or table row (cells tab-separated), whitespace collapsed; footnotes, header and signature are not in it. Cut at a whole line at 2,000,000 characters (`MAX_TEXT_CHARS`). |
| `text_source` | `str` | `kst-xml`. |
| `text_truncated` | `bool` | `true` when the text was cut. |
| `xml_dialect` | `str` | `kamerwrk` (1995-2009) or `officiele-publicatie` (2010 on). |
| `structure_quality` | `str` | `explicit` (an artikelsgewijs opener and article headings after it), `implicit` (article headings, no opener) or `none`. |
| `budget` | `bool` | A budget or annual report (a dossier chapter such as `XV`, or a title that says so): its numbered articles are policy articles, not law articles, so a consumer that links articles skips it. |
| `sections` | `list[object]` | The headings of the paper in document order, each spanning its body and what is nested under it: `{id, heading, level, parent, kind, number, number_scheme, article_refs, law, char_start, char_end}`. |
| `footnotes` | `list[object]` | `{number, text, at}` in document order; `at` is where its marker stood in `text` (`text[:at]` the words before it), absent for a footnote without a marker in the text kept (one of the header, a legacy `voetnoot` no `voetref` names). |
| `paragraphs` | `list[object]` | Each line of `text` in order (`core/document_paragraphs.py`): `{id, number, kind, char_start, char_end}`. `kind` is `head` (title and date of the stuk), `heading`, `formula` (of a motion: `De Kamer, gehoord de beraadslaging,` and from `en gaat over tot de orde van de dag` on), `table` (its title and rows) or `body`; `number` the alinea, from 1, of a `body` line and of a table (all its lines one number), null for the others; `id` `p-` and 8 hex of its text, `_<n>` for its n-th repeat. |
| `tables` | `list[object]` | The tables in its text: `{start, end, head_rows, columns, spans}` (as on Article), offsets into `text`; null without tables. |
| `dossier_number` | `str` | `Document.Kamerstukdossier`: the one dossier it is a Kamerstuk of; null for a paper that is none. |
| `dossier_suffix` | `str` | The addition to the dossier number: the chapter `VII` of `35925 VII`. |
| `dossier_numbers` | `list[str]` | The dossiers of its cases and its own, as labels. |
| `case_ids` | `list[str]` | Its cases. |
| `case_kinds` | `list[str]` | The `Zaak.Soort` of those cases (`Wetgeving`, `Motie`, `Brief regering`, ...). |
| `sequence` | `int` | Its number within `dossier_number`. |
| `session_year` | `str` | Its vergaderjaar. |
| `document_number` | `str` | `DocumentNummer` (`2026D44984`), by which tweedekamer.nl finds it. |
| `actors` | `list[object]` | Every signature. |
| `actors[].name` | `str` | As the source writes it. |
| `actors[].person_id` | `str` | The member who signed. |
| `actors[].faction_id` | `str` | The faction signed for. |
| `actors[].faction` | `str` | That faction as the source writes it. |
| `actors[].role` | `str` | `DocumentActor.Relatie`; of a motion of the Eerste Kamer `Eerste ondertekenaar` or `Mede ondertekenaar`. |
| `actors[].function` | `str` | The function they signed in (`DocumentActor.Functie`) as the source writes it: `Tweede Kamerlid`, `minister-president`. |
| `actors[].capacity` | `str` | What that makes the signature (`tk_records.actors.signing_capacity`): `bewindspersoon`, `kamerlid` or `overig`. |
| `activity_ids` | `list[str]` | `Document.Activiteit`: the activities it is the record of (a stenogram: its debate; `MADE_IN`). |
| `attachment_ids` | `list[str]` | `BijlageDocument`: its attachments (`ACCOMPANIES`). |
| `attached_to_ids` | `list[str]` | `BronDocument`: the letters it is an attachment of. |
| `url` | `str` | Of a document of the Eerste Kamer: its page on officielebekendmakingen.nl, as the source gives it. |
| `identifier` | `str` | Of a Staatsblad or Staatscourant publication: its identifier. |
| `year` | `str` | Of such a publication: its year. |
| `bwb_id` | `str` | Of such a publication: the regulation it is about. |

<!-- props:documents:end -->

### Activity (`activities`)

An activity of the Eerste Kamer (`normalize eerstekamer-agenda`) has the key `ek_<id>` of a
plenary block or `ek_<yyyymmdd>_<committees>` of a committee meeting.

<!-- props:activities:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Activiteit` record. |
| `date` | `str` | Its date. |
| `precision` | `str` | `Activiteit.DatumSoort`, how precise `date` is: `Dag`, `Weeknummer` (planned for the week of that Monday), `Meerdaags` (its first day); none of the Eerste Kamer. |
| `agenda_title` | `str` | Its `Onderwerp`; of the Eerste Kamer the block's title, or the committees. |
| `kind` | `str` | Its kind (a debate, a hearing); of the Eerste Kamer `plenaire vergadering` or the kind of a meeting as its agenda gives it. |
| `status` | `str` | `Activiteit.Status` as the Kamer writes it: `Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; none of the Eerste Kamer. |
| `committee_id` | `str` | Its committee; null for a plenary activity. |
| `case_ids` | `list[str]` | The cases it is about. |
| `dossier_numbers` | `list[str]` | The dossiers it is about. |
| `case_kinds_by_dossier` | `{str: list[str]}` | The `Zaak.Soort` of its cases per dossier. |
| `number` | `str` | `Activiteit.Nummer`, by which tweedekamer.nl finds it. |
| `replaced_by` | `list[str]` | `Activiteit.VervangenDoor`: the numbers of the activities that replace it. |
| `chamber` | `str` | `EK` for the Eerste Kamer (`normalize eerstekamer-agenda`). |
| `time` | `str` | Of the Eerste Kamer: the time as its agenda gives it. |
| `decision_points` | `list[object]` | Of a committee meeting of the Eerste Kamer: its decision points. |
| `decision_points[].id` | `str` | Its id on the agenda. |
| `decision_points[].number` | `str` | Its number on the agenda. |
| `decision_points[].reference` | `str` | The reference the agenda gives it. |
| `decision_points[].dossiers` | `list[str]` | The dossiers it is about. |
| `decision_points[].subject` | `str` | What it is about. |
| `decision_points[].decision` | `str` | The decision, as the committee words it. |
| `source_url` | `str` | Of the Eerste Kamer: the page it was read from. |
| `retrieved_on` | `str` | Of the Eerste Kamer: the day it was read. |

<!-- props:activities:end -->

### Decision (`decisions`)

One node per `Besluit` of the Tweede Kamer, key `decision_<Besluit_Id>`.

A vote of the Eerste Kamer (`normalize eerstekamer-votes`) has the key `ek_<date>_<label>_<n>`
(a vote on a bill) or `ek_<date>_<label>_<letter>` (a vote on a motion, `kind` `Motie`, also
`ABOUT` the motion's Kamerstuk).

<!-- props:decisions:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `decision_id` | `str` | The `Besluit`. |
| `agenda_item_id` | `str` | Its agendapunt. |
| `activity_id` | `str` | The activity of its agendapunt, the meeting it was taken in (`MADE_IN`). |
| `date` | `str` | The day. |
| `subject` | `str` | What the decision is about. |
| `agenda_item_subject` | `str` | What its agendapunt is about. |
| `decision_text` | `str` | Its text. |
| `decision_kind` | `str` | `BesluitSoort` as the Kamer writes it: `Stemmen - aangenomen`, `Stemmen - zonder stemming aannemen`, `Stemmen - uitstellen`, ... |
| `decision_order` | `int` | Its order on the agendapunt (`AgendapuntZaakBesluitVolgorde`). |
| `meeting_kind` | `str` | The kind of meeting (`Vergadering_Soort`). |
| `case_ids` | `list[str]` | The cases it is about. |
| `primary_case_id` | `str` | The zaak it decided. |
| `primary_case_kind` | `str` | The `Zaak.Soort` of that zaak: `Wetgeving` on the vote on a bill itself. |
| `dossier_numbers` | `list[str]` | The dossiers it is about. |
| `vote_kind` | `str` | `member` on a roll call (every row a member), `faction` otherwise; null for a decision on a bill without votes (a hamerstuk, from a `tk-besluit` record, which has no `tally` either). |
| `tally` | `{str: int}` | Seats per choice: a member one, a faction its seats without its members who voted apart. Who voted how is on the `VOTED` edges. |
| `voters` | `{str: int}` | How many rows cast each choice. |
| `passed` | `bool` | From the `BesluitSoort`, else the tally; null for a decision that is no vote. |
| `external_id` | `str` | The id of its `Besluit` record. |
| `kind` | `str` | What was decided on: the `Zaak.Soort` of the primary case, else the one Soort of the cases on its agendapunt (`tk_records.decisions.decided_case_kind`); of the Eerste Kamer the kind of the bill's dossier, or `Motie`. Never read from the subject. |
| `chamber` | `str` | `TK`, or `EK` for a vote of the Eerste Kamer (`normalize eerstekamer-votes`). |
| `motion_kind` | `str` | Of a vote on a motion of censure `censure`, of no confidence `no_confidence`, from the fixed wording of its subject (`semantic tk-motion-kinds`, `core/motion_kinds.py`); absent for any other decision. |
| `result` | `str` | Of a vote of the Eerste Kamer: the outcome eerstekamer.nl shows (`Aangenomen`, `Verworpen`). |
| `method` | `str` | How it was decided (`Hamerstuk`, `Stemming bij zitten en opstaan, aangenomen`). |
| `factions_for` | `list[str]` | The factions for. |
| `factions_against` | `list[str]` | The factions against. |
| `factions_noted` | `list[str]` | The factions that asked to have their vote recorded. |
| `bill_url` | `str` | The page of the bill. |
| `source_url` | `str` | The page of the report it was read from. |
| `retrieved_on` | `str` | The day it was read. |
| `bill_decision` | `bool` | It is the vote that decided the bill (`semantic tk-dossier-outcomes`). |
| `letter` | `str` | Of a vote on a motion: the motion's letter in its dossier. |
| `motion_url` | `str` | Of a vote on a motion: its page (`/motiedossier/...`). |

<!-- props:decisions:end -->

### Commitment (`commitments`)

<!-- props:commitments:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Toezegging` record. |
| `text` | `str` | The commitment. |
| `minister_name` | `str` | Who made it, as the Kamer writes it. |
| `minister_role` | `str` | Their role, as the Kamer writes it. |
| `ministry_name` | `str` | The ministry the Kamer gives it (`Toezegging.Ministerie`). |
| `made_on` | `str` | The day it was made: that of its activity (`Activiteit.Datum`, the debate), else `registered_on`. |
| `registered_on` | `str` | The day the Kamer registered it (`Aanmaakdatum`, often weeks after the debate). |
| `expected_resolution` | `str` | The day it is due; `0001-01-01` when the Kamer names none. |
| `status` | `str` | `Toezegging.Status` as the Kamer gives it: `Openstaand`, `Afgedaan`, `Deels Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Vervallen`. |
| `activity_number` | `str` | The number of its activity. |
| `number` | `str` | `TZ202603-130`, how the Kamer cites it. |
| `letter_ids` | `list[str]` | `Toezegging.KamerbriefNakoming`: the letters that fulfil it (TK ids); each stored one `ANSWERS` it. |
| `letter_dossiers` | `list[str]` | The dossiers those letters are numbered in (`37020`, `36600-VII`): it is `ABOUT` the stored ones, before the agenda of its debate. |
| `member_key` | `str` | Who made it (`semantic tk-government`; also an `AUTHORED` edge, `role` `toezegger`). |
| `post` | `str` | The post they made it in. |
| `ministry` | `str` | The ministry of that post. |
| `cabinet` | `str` | The cabinet in office that day. |

<!-- props:commitments:end -->

### Member (`members`)

Every `Persoon` of the Tweede Kamer, members and ministers. A minister who never sat in
parliament has no name or date of birth there, and a few records are empty: such a member takes
the name its roll-call votes or signatures give for its `Persoon_Id` ("Nobel, J.N.J." becomes
`J.N.J. Nobel`); an early member whom the Kamer knows only by initials and surname is named by
them (`W.B. Buma`). A bewindspersoon without a `Persoon` is a member of their own (label
`Rijksoverheid`, key `rijksoverheid_<initials>_<surname>`).

A member of the Eerste Kamer (`ek`) is the member of the Tweede Kamer born that day whose
surname ends its name, when exactly one is; else a member of its own (`ek_<slug>`, label `EK`,
with `name` and `birth_date` from the page).

<!-- props:members:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Persoon` record. |
| `name` | `str` | The name they go by: `Persoon.Roepnaam` and the surname. |
| `full_name` | `str` | `Persoon.Voornamen` and the surname. |
| `initials` | `str` | `Persoon.Initialen`: "S.Th.M.". |
| `party` | `str` | The party. |
| `faction_memberships` | `list[object]` | Every period in a faction of the Tweede Kamer, with its dates. |
| `faction_memberships[].faction_id` | `str` | The faction node. |
| `faction_memberships[].faction_key` | `str` | Its key. |
| `faction_memberships[].name` | `str` | Its name. |
| `faction_memberships[].abbreviation` | `str` | Its abbreviation. |
| `faction_memberships[].aliases` | `list[str]` | Its other names. |
| `faction_memberships[].from_date` | `str` | The first day. |
| `faction_memberships[].to_date` | `str` | The last day (`TotEnMet`); null while it lasts. |
| `faction_memberships[].role` | `str` | `FractieZetelPersoon.Functie`. |
| `faction_memberships[].chamber` | `str` | `EK` for the Eerste Kamer. |
| `ek_faction_memberships` | `list[object]` | The periods in the factions of the Eerste Kamer, as their page says them (`normalize eerstekamer-persons`), in the shape of `faction_memberships`. |
| `family_name` | `str` | `Persoon.Achternaam`, without the tussenvoegsel. |
| `name_prefix` | `str` | `Persoon.Tussenvoegsel`: "van der". |
| `number` | `str` | `Persoon.Nummer`. |
| `slug` | `str` | The name as the API gives it, lower-case ASCII with hyphens (`core/member_slugs.py`); given once and never changed; a later namesake gets the year they were born, else `number`, else a number of its own. `lawgraph check` fails on a slug two members share. |
| `birth_date` | `str` | The date of birth. |
| `death_date` | `str` | The date of death (`Overlijdensdatum`). |
| `government_name` | `str` | As Rijksoverheid writes it: "S.Th.M. Hermans". |
| `known_as` | `str` | "Sophie Hermans": the first name Rijksoverheid gives; null when none. |
| `government_functions` | `list[object]` | Every post in a cabinet since 1945, oldest first (`normalize rijksoverheid`). |
| `government_functions[].cabinet_key` | `str` | The cabinet node. |
| `government_functions[].cabinet` | `str` | Its name: "kabinet-Rutte IV". |
| `government_functions[].function` | `str` | The post as the source writes it: "Minister van Infrastructuur en Waterstaat". |
| `government_functions[].also_named` | `list[str]` | The other names of the post. |
| `government_functions[].post` | `str` | The normalised post (`core.ministries.POSTS`). |
| `government_functions[].ministry` | `str` | The key of its ministry (`core.ministries.MINISTRIES`; `core/post_ministries.py`). |
| `government_functions[].ministry_source` | `str` | Where the ministry comes from: `page`, `tk_signatures`, `tk_commitments`, `staatscourant`. |
| `government_functions[].ministry_missing` | `str` | When `ministry` is null, why: `no_source`, `ambiguous`. |
| `government_functions[].seat` | `str` | `ienw/minister`, `-/staatssecretaris/rechtsbescherming`, `viceminister-president`. |
| `government_functions[].portfolio` | `str` | The portfolio. |
| `government_functions[].from_date` | `str` | The first day held. |
| `government_functions[].to_date` | `str` | The last day held; null while held. |
| `government_functions[].from_date_source` | `str` | The day the page gave, null when none. |
| `government_functions[].to_date_source` | `str` | Likewise. |
| `government_functions[].corrected` | `list[str]` | Which dates the rules of a seat set. |
| `government_functions[].acting` | `bool` | A stand-in (ad interim). |
| `government_functions[].acting_reason` | `str` | `source` or `held_other_seat`. |
| `government_functions[].acting_basis` | `str` | The words of the page. |
| `government_functions[].acting_other_seat` | `{str: str}` | `{seat, function}` of the seat held besides. |
| `government_functions[].party` | `object` | The party of the holder. |
| `government_functions[].party.short` | `str` | As the source writes it. |
| `government_functions[].party.faction` | `str` | Its faction key. |
| `government_functions[].overlaps_with` | `list[str]` | Member keys holding the seat at the same time. |
| `government_functions[].absent` | `list[str]` | The periods of a "tijdelijk afwezig". |
| `government_functions[].name` | `str` | The holder as the page writes them. |
| `government_functions[].source` | `object` | The page it was read from. |
| `government_functions[].source.name` | `str` | The source. |
| `government_functions[].source.url` | `str` | The page. |
| `government_functions[].source.read_on` | `str` | The day it was read. |
| `ek` | `object` | A member of the Eerste Kamer. |
| `ek.name` | `str` | As its page writes it. |
| `ek.path` | `str` | The path of that page. |
| `ek.url` | `str` | The page. |
| `ek.faction` | `str` | The faction key. |
| `ek.abbreviation` | `str` | The faction's abbreviation. |
| `ek.seniority_days` | `int` | `Anciënniteit`: no start date. |
| `ek.residence` | `str` | The place of residence, as the page gives it. |
| `ek.seat` | `object` | Their place in the hall. |
| `ek.seat.block` | `str` | The block of the hall. |
| `ek.seat.row` | `int` | The row in it. |
| `ek.seat.column` | `int` | The place in the row. |
| `ek.observed_from` | `str` | The first day a snapshot showed the seat. |
| `ek.observed_until` | `str` | The first day a snapshot no longer did. |
| `ek.retrieved_on` | `str` | The day the page was read. |
| `ek.data_since` | `str` | The day of the first snapshot of the Eerste Kamer. |

<!-- props:members:end -->

A member has a role when the sources give them a seat or a post: `faction_memberships`, `government_functions` or `ek_faction_memberships` not empty, or `ek` set (`core/member_role.py`, in SQL `db/queries/member_role.py`; a column of its own when the database is built again). One without is a person of the Tweede Kamer's records (`Persoon`) whose seat the data does not hold: the sitemap leaves them out, their page is not indexed, and search lists them after the members with one.

The posts in `government_functions` are read by `normalize rijksoverheid` ([pipelines](pipelines.md#rijksoverheid)).

### Faction (`factions`)

A faction of the Eerste Kamer has the key `ek_<slug>`.

<!-- props:factions:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The current Fractie record. |
| `external_ids` | `list[str]` | Every Fractie record of the faction: one that returns gets a new record, and votes and seats name either. |
| `name` | `str` | Its name; of the Eerste Kamer the heading of its page (`D66-fractie`). |
| `abbreviation` | `str` | Its abbreviation; the key is made from it, else from the name. |
| `aliases` | `list[str]` | Its other names. |
| `active_from` | `str` | The first day its seats were held, where the seats date it (from 30 November 2006); else the Fractie record's. |
| `active_until` | `str` | The last day, likewise. |
| `seats` | `int` | `AantalZetels` (0 once the faction has ended); of the Eerste Kamer as `/fracties` lists them. |
| `seats_changed_on` | `str` | The day one of its seats last changed (`FractieZetel.GewijzigdOp`). |
| `vacancies` | `list[object]` | The periods a seat of it was held by no member (`FractieZetelVacature`): only the days no member held that seat (a seat is held or vacant, never both); both days inclusive, the last the one before the successor took it. `/api/cabinets/{key}/seats` counts them among its seats. |
| `vacancies[].from_date` | `str` | The first day. |
| `vacancies[].to_date` | `str` | The last day; null while it lasts. |
| `active` | `bool` | A Fractie record of it has no end (`DatumInactief`); of the Eerste Kamer: the latest snapshot shows it. |
| `chamber` | `str` | `EK` for the Eerste Kamer (`normalize eerstekamer-composition`). |
| `url` | `str` | Of the Eerste Kamer: its page on eerstekamer.nl. |
| `retrieved_on` | `str` | The day that page was read. |
| `observed_from` | `str` | The first day a snapshot showed it (not the day it began). |
| `observed_until` | `str` | The first day a snapshot no longer did (not the day it ended). |
| `data_since` | `str` | The day of the first snapshot of the Eerste Kamer. |
| `board` | `list[object]` | Its board, as the page gives it. |
| `board[].function` | `str` | The function. |
| `board[].name` | `str` | The holder, as the page writes them. |
| `board[].member` | `str` | The member key. |
| `board[].since` | `str` | The day they hold it from. |

<!-- props:factions:end -->

### Committee (`committees`)

Only a Commissie with a name; the plenary is no committee.

A committee of the Eerste Kamer has the key `ek_<slug>` and the slug `ek-<slug>`.

<!-- props:committees:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `external_id` | `str` | The id of its `Commissie` record. |
| `name` | `str` | Its name. |
| `abbreviation` | `str` | Its abbreviation. |
| `slug` | `str` | Unique (`GET /api/committees`); of the Eerste Kamer `ek-<slug>`. |
| `kind` | `str` | By its name, else `Commissie.Inhoudsopgave`. |
| `started_on` | `str` | `DatumActief`. |
| `ended_on` | `str` | `DatumInactief`. |
| `active_dossier_count` | `int` | The open dossiers it leads, none once dissolved (`semantic graph-list-stats`). |
| `chamber` | `str` | `EK` for the Eerste Kamer (`normalize eerstekamer-composition`). |
| `url` | `str` | Of the Eerste Kamer: its page on eerstekamer.nl. |
| `retrieved_on` | `str` | The day that page was read. |
| `observed_from` | `str` | The first day a snapshot showed it (not the day it began). |
| `observed_until` | `str` | The first day a snapshot no longer did (not the day it ended). |
| `data_since` | `str` | The day of the first snapshot of the Eerste Kamer. |
| `title` | `str` | The heading of its page: `Commissie voor Financiën (FIN)`. |

<!-- props:committees:end -->

### Cabinet (`cabinets`)

A Dutch cabinet since 1945, from its Rijksoverheid page; key from its name (`rutte_asscher`,
`den_uyl`).

<!-- props:cabinets:begin (generated: python -m lawgraph.core.props_catalogue) -->

| Prop | Type | Meaning |
|------|------|---------|
| `name` | `str` | `kabinet-Rutte IV`. |
| `from_date` | `str` | The beëdiging. |
| `to_date` | `str` | The last day; null while in office. |
| `prime_minister` | `str` | The member key of its prime minister. |
| `previous` | `str` | The key of the cabinet before it. |
| `parties` | `list[object]` | The parties of the bewindspersonen sworn in on the first day. |
| `parties[].short` | `str` | As the source writes it. |
| `parties[].faction` | `str` | Its faction key. |
| `factions` | `list[str]` | The faction keys of its parties. |
| `phases` | `list[object]` | Its phases. |
| `phases[].kind` | `str` | `formatie`, `in_functie`, `demissionair`, `dubbel_demissionair`, `missionair`; null: unknown. |
| `phases[].from_date` | `str` | The first day. |
| `phases[].to_date` | `str` | The last day. |
| `phases[].label` | `str` | The source's own words. |
| `phases[].source` | `object` | Where it was read. |
| `phases[].source.name` | `str` | The source. |
| `phases[].source.url` | `str` | The page. |
| `phases[].source.read_on` | `str` | The day it was read. |
| `demissionary_from` | `str` | The day it went demissionary. |
| `origin` | `object` | The page or the record it was read from. |

<!-- props:cabinets:end -->

`MEMBER_OF` into a faction or committee of the Eerste Kamer has `meta.observed_from`,
`observed_until`, and `role` (committee).

No link to tweedekamer.nl is stored. The site finds a document by its `document_number` and an
activity by its `number`, never by the GUID of the record (`external_id`), so the API derives
`tk_url` from those when it answers (`core/tk_links.py`): a template that turns out wrong is
fixed by a release, not by a migration. The Eerste Kamer papers keep the `url` of their page on
officielebekendmakingen.nl as the source gives it.

Dossiers of different numbers are tied by four edges, written by `semantic
tk-dossier-relations` (the rules: [pipelines](pipelines.md#semantic-tk-dossier-relations)):
`REVISES` (a supplementary budget or slotwet → the budget of its chapter and year), `ACCOMPANIES`
(a budget change → the Voorjaarsnota, Najaarsnota or Miljoenennota it is submitted with),
`RELATED_TO` (the Kamer relates a case of the one to a case of the other) and `SECOND_READING_OF`
(a change in the Grondwet in its second reading → its first reading, whose memorandum explains
it). The dossiers of one
number are found by the number itself (`GET /api/dossiers?number=`), not by an edge.

### Text and sections of a Kamerstuk

`normalize tk-content` reads the Kamerstuk XML that `retrieve tk-content` stored and writes,
on the Document of the paper (`meta.document` of the raw record), `text`, `text_truncated`,
`text_source`, `xml_dialect`, `structure_quality`, `budget`, `footnotes`, `dictum` (also kept
in `lg_document_light`), `explanation` and `sections` (the documents table above).

The XML has no element for an article: the artikelsgewijs part of a memorandum is a run of
headings with the paragraphs after them. Every heading is a section, so `sections` covers the
whole paper; a section spans its heading, its body and everything nested under it:
`text[char_start:char_end]`. A child lies inside its parent.

| Field | Meaning |
|-------|---------|
| `id` | `s-` and the first 8 hex of the SHA-1 of its heading line and the line after it, `_<n>` for the n-th occurrence of the same two lines: it rests on the text, not on the outline, so it stays when the nesting or a section elsewhere changes |
| `heading` | the heading as printed (`ARTIKEL II (Huisvestingswet 2014)`) |
| `level` | 1 for a section without parent, else the level of the parent plus 1 |
| `parent` | id of the enclosing section, or `null` |
| `kind` | `algemeen` (the general part: every heading before the opener); `artikelsgewijs` (the heading that opens the article-by-article part: "Artikelsgewijs", "Artikelsgewijze toelichting", "Artikelen"); `article` ("Artikel 3", "Artikelen 3 en 4", "Artikel I, onderdeel B (artikel 1a)"); `onderdeel` ("Onderdeel B", "Ad a.", "A, B en D"); `lid` ("Eerste lid", "Ad 1"); `chapter` ("Hoofdstuk 2", "Afdeling 3"); `other`. `onderdeel` and `lid` only inside an article; an article heading is one wherever it stands |
| `number` | the number as printed in the heading (`3`, `II`, `3:159n`, `1.6.20`, `B`); of the first article for a heading with several; `lid` numbers are digits (`Eerste lid` is `1`); `null` when the heading has none |
| `number_scheme` | `arabic`, `roman`, `book_article` (`3:159n`, `1.6.20`), `letter` (`B`), or `null` |
| `article_refs` | `[{number, of}]`: every article number the heading names (`Artikelen 3 en 4` gives two; `1 tot en met 3` gives 1, 2, 3), empty for other kinds. `of`: `self` (an article of the bill the memorandum accompanies), `named_law` (of the law `law` names: `Artikel 1a van de Woningwet`), `unknown` (of a law that is implied and not named: the `(artikel 1a)` of `Artikel I, onderdeel B (artikel 1a)`, or the parenthesis of `Onderdeel A (artikel 1)`) |
| `law` | another law the heading names, in parentheses or after `van de` (`Huisvestingswet 2014`, `Boek 7 van het Burgerlijk Wetboek`), else `null`; on an `article` whose number is the bill's own it is the law that bill article changes |
| `char_start`, `char_end` | offsets into `text` |

A paper that cannot be read gives no text and the record is skipped; a paper whose structure
cannot be read gives its text, no sections and `structure_quality` `none`.

Votes: TK returns one row per voter per `Besluit`. A roll-call (`Hoofdelijk`) names every
member, so its `VOTED` edges start at the member; any other vote is cast per faction and the
edge starts at the faction. A member who votes apart from their faction has a row of their
own beside the faction's: their edge starts at the member with one seat, and the faction's
carries its seats without them. The decision carries `vote_kind` (`member` when every row is
a member's, else `faction`), `tally` (seats per choice), `voters` (how many rows cast each
choice) and `passed`; each edge carries `meta.choice`, `meta.seats` (the seats of the faction
without its members who voted apart; 1 for a member, whose row carries the size of the
faction) and `meta.record_ids` (the Stemming it is made of). The API derives a member's
non-roll-call votes from the faction they belonged to at the time, using
`members.props.faction_memberships`.

Authorship is stored on the document (`props.actors` with `person_id`, `faction_id`, `name`,
`faction`, `role`, `function`, `capacity`) and as `AUTHORED` edges from the signatory, with
`meta.role`, `meta.function` and `meta.capacity`. Only people get an edge; which faction signed
follows from the signatory's faction membership.

A person's role changes over time: R.A.A. Jetten signed as Tweede Kamerlid until 2025 and as
minister-president in 2026, S. van Haersma Buma, once a Kamerlid, signs the advices of the Raad
van State as its vice-president. So each signature keeps what it was signed as:

- `function` is `DocumentActor.Functie` as the source writes it (`Tweede Kamerlid`,
  `minister-president`, `staatssecretaris van Financiën`, `griffier`, `vicepresident van de Raad
  van State`, `voorzitter van de vaste commissie voor …`);
- `capacity` is derived from it (`tk_records.actors.signing_capacity`), the first that holds:
  `bewindspersoon` when the function begins with `minister`, `minister-president`,
  `viceminister-president` or `staatssecretaris` (not `gevolmachtigde minister van Aruba`, who
  speaks for Aruba); `kamerlid` when the signature is for a faction (`Fractie_Id` or
  `ActorFractie`: a member, also as the chair of a committee, a formateur or verkenner); `overig`
  otherwise (the griffier, the Raad van State, the Algemene Rekenkamer, the Nationale
  ombudsman). No minister or staatssecretaris signs for a faction in the source.

`MEMBER_OF` edges run from a member to a committee (`meta` = the seat that represents the membership: `from_date`, `to_date`, `role` (`Functie` of `CommissieZetelVastPersoon` or `CommissieZetelVervangerPersoon` in one spelling, its words run together without dots: `Lid`, `Voorzitter`, `OnderVz`, `PlvLid`, also for the `Plv. lid` of older seats), `substitute` for a substitute's seat, and `periods`, every seat oldest first, when there is more than one or it has a role; an open seat represents before a closed one, a member's before a substitute's) and to a
faction (`meta.from_date`, `meta.to_date`, `meta.role`, `meta.record_ids`: the
FractieZetelPersoon records it is made of). Edge keys are one per pair, so a
member who leaves and rejoins keeps one edge with the latest period, whatever order the records
are read in: the latest `from_date`, of two that start the same day the one without an end,
then the later `to_date`; the full timeline is in `members.props.faction_memberships`. `to_date` is the last day held (`TotEnMet`), so periods
that follow each other touch without overlap. Where the Kamer's dates do not hold together its
later dates are read (`core/seat_periods.py`): an end before the start ends the day before the
person's next seat (without one the seat is left out), and a fractievoorzitter still chairing
when the next one starts chairs until the day before and holds the rest of that seat as `Lid`,
and a person sits in one faction a day: a seat running into the start of the person's seat in
another faction ends the day before.

## raw_sources

`{_key, source, kind, external_id, fetched_at, changed_at, payload_json, payload_ref, payload_chars, payload_sha1, meta}`.
`fetched_at` is the last fetch of a record, `changed_at` the fetch its content (payload, the
SHA-1 of a text payload, meta) last changed at: a record fetched again as it was keeps it. A run
`--since` of the phases after retrieve reads the records whose `changed_at` is not earlier
(`queries/raw.CHANGED_SINCE`, on the index by `fetched_at`); a retrieve that resumes or asks
what is newer than the source's own change reads `fetched_at`.
JSON sources keep their payload in `payload_json`, in the database, where queries filter on it.
The XML or HTML of the other sources (most of what LawGraph stores; nothing queries inside it)
is an object in the payload store (`db/payloads.py`, `LAWGRAPH_PAYLOAD_STORE`: a directory or an
S3 bucket), gzip-compressed, named `<database>/<source>/<kind>/<key>.gz`; the document keeps
that name in `payload_ref` and the length of the text in `payload_chars` and its SHA-1 in `payload_sha1`. The object is written
before the document. `store.with_payloads(records)` reads the objects of a stream of records,
side by side, and puts each text back in `payload_text`; a missing object is logged and the
record is skipped like one without a payload.

| Source | Kinds |
|--------|-------|
| `tk` | `tk-zaak`, `tk-document`, `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-besluit`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-kamerstuk-xml` (the XML of a paper, external id `kst-<dossier>-<n>`, `meta.document` the key of its Document), `tk-transposition-table-pdf` (the PDF of a transposition table, base64, external id `blg-1081574`; `meta` its title, dossier, main document, URL and when it was modified), `tk-transposition-document-xml` (the XML of a Kamerstuk whose text names a transposition table, external id `kst-<dossier>-<n>`, without a payload when no table is read in it; `meta` its title, dossier, URL, when it was modified and `tables`, the number read) |
| `rechtspraak` | `rs-content` (of a judgment the Rechtspraak withdrew: `meta.withdrawn` and its RDF alone, or no payload), `rs-instanties-xml` (the Instanties value list) |
| `eurlex` | `eu-celex-html` (`meta.modified`: when CELLAR last changed the act), `eu-nim-json` (the Dutch implementing measures of an act) |
| `bwb` | `bwb-toestand-xml` (current), `bwb-toestand-xml-all` (every toestand, external id `<bwb_id>@<start_date>`), `bwb-wti-algemene-informatie-xml` (the first element of the WTI file: official abbreviations, citation titles, legal areas) |
| `staatsblad` | `stb-amvb-xml`, `stb-transposition-xml` (a publication whose text names a transposition table, external id `stb-<year>-<n>`: its XML when a table is read in it, `meta.tables` how many) |
| `staatscourant` | `stcrt-regeling-xml`, `stcrt-post-creators-json` (per cabinet post, the ministries that issued the publications naming it) |
| `eerstekamer` | `ek-kamerstuk-json`, `ek-votes-day-html`, `ek-rejected-html`, `ek-composition-html`, `ek-composition-observed`, `ek-bill-html`, `ek-plenary-html`, `ek-committee-day-html` |
| `echr` | `echr-judgment-json` (one per HUDOC item: a judgment in one language), `echr-judgment-docx-xml` (the `word/document.xml` of the DOCX of the item whose text a judgment gets, external id its item id, `meta.ecli` and `meta.language`) |
| `verdragenbank` | `verdrag-json` (the SRU record), `verdrag-xml` (the item XML: parties, Tractatenbladen, dossiers, related treaties; `meta.item_url` and `meta.modified`) |
| `rijksoverheid` | `rijksoverheid-cabinet-html` (the page of one cabinet since 1945, external id its slug, `meta.url` and `meta.read_on`) |
| `tooi` | `tooi-ministries-jsonld` (the ministries list, external id `rwc_ministeries_compleet`), `tooi-thesaurus-jsonld` (a thesaurus of the BWB, external id `scw_bwb_rechtsgebieden` or `scw_bwb_themas`); each `meta.url` and `meta.read_on` |

A document the source answered HTTP 404 for is remembered as a record without payload of
kind `<kind>-missing` (`eu-celex-html-missing`, `rs-content-missing`, ...), which no other phase
reads. A retrieve does not ask for it again for 30 days, or for 3 when the source itself listed
it (an index, an SRU listing: its file is probably on its way); `pipelines/retrieve/base.py`.

## Tables, indexes and search

Defined in `db/schema.py` and created when the store starts (`ensure_schema`). The store refuses
a database whose tables this version cannot run on (`SchemaOutdated`: a column of the schema the
table lacks and the schema does not add itself, or a required column it does not know), and one that does not sort
strings by the ICU collation `und-u-kf-upper` of `create_database_sql` (`CollationMismatch`): the
queries compare and sort strings by it. Either is built again.

### Tables

Every node collection is a table of the same shape: `id` (`collection/key`),
`key`, `type`, `labels` and `props` (`json`, so the API serves the keys in their stored
order). `edges` holds `key`, `from_id`, `to_id` and the rest of the edge as `doc`;
`raw_sources` and `pipeline_state` hold their documents as `doc`, `raw_sources` with the
generated columns `source`, `kind`, `external_id` and `fetched_at` and the indexes
`(source, kind, key)` and `(source, fetched_at)`. The view `nodes` unions the node tables for a
lookup by id. A query never joins it on an id alone, which would look the id up in every table:
it names the node's table (`n.collection = 'documents'`), or reads the node through
`schema.node_of`, which reads from the table the id's collection names only
(`tests/test_nodes_view_joins.py` keeps it so).

`lg_feed_events` holds one light row per event of the feed (`kind`, `id`, `date`, `chamber`,
`ministry`, `factions`, `labels`, and its title (of a publication with the names of the laws it
changes or enacts, and the official title of a law it enacts) and that of its first dossier in
lower case, with `words`, their tokens of letters and digits, `lg_alnum_tokens`), written by `lawgraph
feed-events` from the feed's own reading of the events; `GET /api/feed/periods` counts it, and `GET
/api/feed` under `q` its total and facets.
Indexes on `(date, kind)`, `words` (GIN: `lg_word_query` makes the query of a word of `q`, a
superset the feed's pattern then checks) and `factions` (GIN). `lg_feed_events_state` keeps
when it was written. `lg_amendment_chains` holds the chains of the amendments (a row per chain, named by its last paper, and paper of it, with the day of its first paper and its outcome), written whole with the events. Not tables of the graph: writing them raises no data version.

`lg_unlinked_references` holds per node a step read the references of how many its text makes
that the step recognized and could not link (`id`, `step`: the edge source of the step,
`count`; 0 when it linked every one): `semantic bwb`, `semantic eurlex`, `semantic rechtspraak`
and `semantic tk` write a row per article, judgment or paper read, only where it changed, and a
run over all removes the rows of its step it did not read. On the row of a judgment `semantic
rechtspraak-citations` keeps `ljns`: how many LJNs its text cites that no one judgment in the
graph has (null for none), counted as not linked with `count`. The detail routes read it by `id`, with the
`REFERS_TO` edges of the node to a stub (`completeness.references`). Apart from the props, so a run that counts every judgment
rewrites no texts.

`lg_data_version` holds a counter per table of the graph, and one each for
`lg_instrument_definitions`, whose definitions the article routes mark, and
`lg_unlinked_references`, which the detail routes read. A statement trigger on each
(`<table>_version_insert`, `_update`, `_delete`) raises it with every statement that changes
the table; a retrieve changes none of them. `lg_article_terms` has no trigger: `semantic
graph-article-terms` raises the counter of `articles` once, at the end of a run that changed
terms (`raise_articles_version`), since the search finds an article by them; a trigger would
raise it with every batch and empty the cached search answers that often during a run. The API's `ETag` is made from these counters
(`GraphStore.data_version`). An answer the API keeps names the tables it reads
(`version_cache.cached(tables=...)`) and is kept while their counters stand still, an hour at
most; one that names none is kept until any counter moves.

### Derived columns

What a query filters, sorts or counts on is a column of its own: a
string, number, boolean or list of strings from one prop, or a prop as stored (`pj_<prop>`)
where the props are large (a judgment's text). A trigger of the table (`<table>_derive`) fills
them from `props` when a row is written, reading the props once. A release that changes how a
table derives them leaves the rows written before as they were: `pipeline_state` keeps per table
the digest of the derivation its rows hold (`derive <table>`), the API names a table whose digest
is not its own at its start, and `semantic graph-derive <table>` derives its rows again. Of an edge, `relation`,
`source`, `status`, `confidence`, `semantic_type`, `meta.record_ids` and `created_at`, and the
collections of both ends, are generated columns of `doc`.

### Indexes

B-tree indexes on those columns, as `INDEXES` in `db/schema.py` lists them per
table: the identifiers (unique where they are: `bwb_id`, `celex`, `ecli`; of an article
`(bwb_id, article_number)`, `(celex, article_number)` and `(official_id, article_number)`), the fields the
lists filter and sort on, and for `/api/judgments` one index per filter that holds the tier,
the kind of court, the source, the date, `stub` and `same_as`, so its facets count from the
index alone, `(tier, published_on)` for the judgments of the feed, a page per tier, and a GIN index on `lg_subject_areas(subjects)` (each subject up to its first `;`, each main area once) for `subject_area`. A GIN index on each list column (`labels`, `subjects`, `case_number_keys`,
`dossier_numbers`, `cabinet_keys` of members). Ordered indexes for the instruments list (partial: without the
publications), the documents newest first, and the member lists in name order. A member by their slug (`members_slug`), a committee by its slug or its key (`committees_slug`, `committees_lower_key`) a zaak by its number (`cases_number`) and an activity by its number (`activities_number`). For a period on the instruments list: the day it came into force (`instruments_date_in_force`, on `lg_str(props -> 'date_in_force')`) and the day it was published (`instruments_list_date_published`), both without the publications. For the words of the feed (`q`): a trigram index on the title the feed shows of a paper, its subject or else its title, folded (`documents_feed_title_g`), and a GIN index on the dossier numbers of an instrument (`instruments_dossier_numbers`, the publications of a dossier). `edges`:
`(from_id, relation, to_collection, key)` and `(to_id, relation, from_collection, key)`, each
with the other end and collection included (`edges_from_cover`, `edges_to_cover`: a level of
`/api/paths` reads a node's edges from the index alone, and a page of a node's neighbours
reads its keys from it in key order, stopping after its limit, and only those edges whole;
the only indexes by end, so that the planner cannot take a smaller one without `key` and
read the table for every edge of a hub), `relation`,
`(status, relation)`, `(created_at, to_id)` (the edges written since a poll), a GIN index on `record_ids`, and
`semantic_type` and `(from_id, semantic_type)` where `semantic_type` is set.

### Search

`/api/search` reads search columns of `articles`, `instruments`, `judgments`,
`dossiers`, `documents` and `committees`, a few per field, each for one way of matching
(`s_<field>_<suffix>`):

| Suffix | Holds | Finds |
|---|---|---|
| `t` | the words, folded and stemmed as the Dutch `text_nl` (`lg_tokens`: `uitspraken` → `uitspraak`; English texts such as ECHR summaries are stemmed as Dutch too) | a word |
| `v` | the values whole | an identifier as written |
| `n` | the values lower-cased, without accents | an identifier in any case |
| `g` | the values folded, joined | a part of a word (`vordering` finds `Strafvordering`), through a trigram index |
| `p` | every value after a separator | a value by its beginning |

GIN indexes back the `t` and `n` columns, trigram indexes the `g` and `p` columns. A hit is
ranked by BM25 over the words it matches (`queries/_bm25.py`, each field weighed by its
boost); until the statistics of a table are kept (after a start, before the warm-up
computed them) a search does not wait for them: it ranks on the rows the planner counts and
weighs no length. The columns are written with the row, so a fresh
insert is found at once. `members` and `factions` are searched by their names
(`search_names`, a trigram index); `cabinets` by their name, `commitments` by their text and
number, and `decisions` by their subject and kind, each through a trigram index on those
words lower-cased (`<table>_search_words`).
`articles` are searched by their `display_name`, `heading`, the `title` of every division in
the `breadcrumb` (`breadcrumb.title`), `text`, `article_number` and `bwb_id`; `instruments`
by their titles, `short_title`, `aliases` and `bwb_id`; `judgments` by each of their `names`
as words, whole and in parts, besides their `display_name`, `summary`, `ecli` and `appno`.

An instrument's `aliases` are every name it is cited by: the official WTI abbreviations
(`Sr`, `WvS`, `WvSr`) and, for a book of a code in `core/code_families.CODE_FAMILIES` (from the WTI), `Boek 6 BW`, `6 BW`,
`BW 6`, `BW6`, `BW Boek 6` and `BW`. Unlike `short_title` an alias may be shared: `BW` is one
of every book. A `short_title` is never shared, except by a base regulation and its variants (title = its title plus a parenthesised addition): the base gets it (`Rv`), and by the versions of one regulation (the same citation title, case, spacing and a trailing year ignored): the one in force gets it, else the one that expired last (`BBBB`). Its `citation_titles` are every citation title its WTI gives, the earlier ones
too (`Participatiewet`, `Wet werk en bijstand` until 2015): the linkers know a law by an earlier
title where no law is called so now. Both written by `normalize bwb`.

## Known limits

What the graph deliberately does not hold, because no official source gives it:

- Cabinets before 1945: Rijksoverheid describes the cabinets since 1945 only, and no other
  official source gives the posts or phases of the earlier ones.
- Who followed whom in an unnamed seat: where the Rijksoverheid page names no portfolio (two
  staatssecretarissen of one ministry, two ministers without portfolio), it does not say who
  succeeded whom: the holders are put in lanes by date (`fin/staatssecretaris`,
  `fin/staatssecretaris#2`), and a successor in such a seat is the next holder in its lane.
- Bewindspersonen without a TK person: a post holder whom no Tweede Kamer `Persoon`
  matches is a member of their own (label `Rijksoverheid`, key `rijksoverheid_<initials>_<surname>`),
  with the name Rijksoverheid gives and no parliamentary record; `lawgraph verify cabinets`
  counts them per cabinet (`own`).
- Posts without a ministry: a post whose ministry no source settles keeps `ministry` null,
  with `ministry_missing` `no_source` or `ambiguous` (see
  [pipelines](pipelines.md#rijksoverheid)); `lawgraph verify cabinets` counts and lists them.
- Versions of EU articles: an EU act is loaded as CELLAR serves its CELEX number, the text as
  adopted. Consolidated versions are not fetched, so an EU article has no `article_versions`
  and does not show the changes of a later act.
- The text of a law of the Staatsblad the BWB does not hold yet: as its publications enacted
  it, with the divisions a later law of the Staatsblad gave a whole new text; a change of
  single words by a later law is not applied (no source consolidates it before the BWB does).
- The Eerste Kamer before the first snapshot: eerstekamer.nl shows who sits in its factions
  and committees today, and gives the start and end of a membership only in sentences (and the
  seats since 1946 only as a PDF). The graph keeps what each snapshot shows: a membership, a
  faction or a committee runs from the first snapshot that shows it (`observed_from`) to the
  first that no longer does (`observed_until`). Nothing before the first snapshot is known,
  and `seniority_days` (`Anciënniteit`) is no start date.
- Withdrawal of a bill as data: the Tweede Kamer keeps the zaak of a withdrawn bill at
  `Status` `Vrijgegeven` and takes no `BesluitSoort` for it. What records it is the letter of
  the government (`Brief regering`) whose `Onderwerp` is the fixed title `Brief houdende
  intrekking van het wetsvoorstel`: that letter closes the dossier as `ingetrokken`
  (`semantic tk-dossier-outcomes`, see [pipelines](pipelines.md)). A withdrawal the Kamer
  gave another subject ("Intrekking Wetsvoorstel beroep bij niet tijdig beslissen (30 435)",
  or the title with the bill's name after it) is not read: the dossier stays open, and
  `completeness.outcome` says only that no end is recorded since its last activity.
