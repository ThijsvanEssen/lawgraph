# G18 Sister cases: research report

Read-only on `lawgraph_small` (8529): 14,446 Rechtspraak judgments that are not stubs, 7,712 court days, 2,393 of them with two judgments or more, 41,933 same-day pairs. I scored every pair with `core.judgment_series` and hand-checked 69 pairs or series.

## What develop does today

`semantic rechtspraak-series` already exists. It compares judgments of one court, one day and one `document_type`. Each text becomes 8-word shingles, and 1 in 8 is kept. Two judgments are a pair when they share no case number, neither is a rectification, and the shingle Jaccard is:

- at least 0.85, or
- at least 0.7 when both texts have 600 words or more, or
- at least 0.5 (0.3 for two long texts) when the summaries share at least 97% of their words and the summary is not a template.

A series is the connected pairs. Each judgment in it gets `series_id` (the lowest ECLI) and `series_size`. The API shows `series_id`, `series_size` and `series` (the other members).

- Stored on lawgraph_small: 158 series, 456 judgments. Recomputing with the current rule gives 159 series and 455 judgments; 157 of the series are identical, so the stored values are slightly stale.
- Sizes: 116 pairs, 16 of 3, 7 of 4, 9 of 5, and larger series of 6 to 15 judgments (the Dexia batches).

**The examples:**

- ECLI:NL:GHAMS:2026:2678/2679/2680 are **already caught**: series `ECLI:NL:GHAMS:2026:2673` of 5, with 2673 and 2676 (the Martinair freight pilots against KLM). Side finding: the text of 2679 names case number 200.344.457/01, which is 2680's number, while its metadata says 200.343.752. It may be a double publication by the court.
- ECLI:NL:HR:2022:969/970 are **not caught**: Jaccard 0.34, summaries 66% the same. These are not parallel cases in the same words. They are co-defendants (a member and the stichting of the Hells Angels Haarlem chapter) with shared overwegingen on art. 140 Sr. The court links them explicitly: "Samenhang met 21/01312, …". That is a different relation (connected cases), not a series.

## Precision of the current rule (hand-checked)

**Random sample of 24 series: 24/24 are real sister cases.**

| Series | Judgments | What they are |
| --- | --- | --- |
| GHDHA:2025:563 | 2 | authorisation, same party |
| GHARL:2026:5630 | 13 | Dexia |
| RBDHA:2022:4381 | 2 | Harnaschpolder expropriation |
| HR:2019:911 | 2 | box 3, 2013 and 2014 |
| GHSHE:2024:3107 | 3 | Wabo co-defendants |
| GHDHA:2026:2596 | 4 | Dexia |
| RBOBR:2024:5247 | 2 | co-defendants, art. 197a Sr |
| RBOVE:2024:1566 | 3 | De Lutte farmers |
| RVS:2026:5627 | 2 | school funding |
| RBNHO:2021:9975 | 2 | same authorised representative, different facts; borderline but same holding |
| HR:2011:BQ8215 | 2 | complaint about seizure |
| RBDHA:2025:27989 | 2 | detention |
| GHSHE:2026:2533 | 2 | Warenwet |
| RVS:2026:5176 | 4 | wildlife damage |
| GHSHE:2026:2073 | 2 | WOZ authorisation |
| GHARL:2026:5537 | 3 | parking tax |
| HR:2017:292 | 2 | reasonable time |
| RVS:2018:1585 | 2 | refused authorised representative |
| GHDHA:2025:1536 | 3 | liquidator |
| GHSHE:2023:246 | 2 | commuter tax |
| GHDHA:2025:1424 | 2 | Dexia |
| RVS:2023:4198 | 2 | asylum |
| GHDHA:2026:2600 | 3 | Dexia |
| HR:2024:704 | 2 | box 3 under the Herstelwet |

**All 21 series with a text under 600 words:** 18 are real (same litigant, co-defendants, or consecutive case numbers). Three are **boilerplate of unrelated cases**. They are true in the "same words" sense but are not sister cases:

- ECLI:NL:RVS:2026:3620 (5): asylum "not decided in time"
- ECLI:NL:RVS:2026:3897 (2): the same kind of case
- ECLI:NL:RVS:2026:5066 (2): costs requests from the same lawyer

That is about 2% of the series, and they are harmless.

**False negatives inside the rule:** ECLI:NL:HR:2026:1380 (9) and 1389 (11) are 20 inadmissibility rulings (unpaid court fee) against the same [X] B.V. on one day. They are split into two series because the texts are short (300 words) and a letter date differs, which keeps Jaccard at 0.70–0.80.

**Not covered:** all 1,197 conclusions (PHR) on lawgraph_small have an empty `text`, so they can never be in a series.

## Candidate rules

Counts are over the whole of lawgraph_small. "New links" are pairs that join judgments not already in one series. Checked means pairs I read by hand.

| Rule | Series | Judgments | Checked (new links) | Real sister cases |
| --- | --- | --- | --- | --- |
| current | 159 | 455 | 24 series | 24/24 |
| long texts: Jaccard ≥ 0.5 (was 0.7) | 195 | 543 | 15 in [0.5, 0.7) | 14/15; 1 asylum boilerplate (RVS:2015:3663/3664) |
| long texts: Jaccard ≥ 0.4 | 227 | 623 | 6 in [0.4, 0.5), plus 6 in [0.4, 0.7) | 10/12; 2 related but on another question |
| long texts: Jaccard ≥ 0.3 | 270 | 716 | 6 in [0.3, 0.4) | 3/6; 2 related, 1 false |
| short texts below 0.85 (0.3 to 0.85) | +16 to +68 | | 9 | 1/9; the rest are art. 81/80a RO or detention templates |
| explicit "Samenhang met" / "Zie ook: ECLI" in the summary | 240 | 651 | read | related cases, not the same words (median Jaccard 0.03) |

**Examples per band:**

- **Jaccard 0.5 to 0.7, real:** GHARL:2026:5638/5650 and 5633/5650 (Dexia), GHLEE:2006:AU9916/AU9921/AU9919, RBROT:2021:8600/8603 (pulse fishers), RBZWB:2022:5755/5756, RVS:2026:5181/5185 and 5180/5185 (wildlife damage), RVS:2024:2040/2045 (private debts), RVS:2026:5483/5530 and 5298/5299 (MOB), RBDHA:2025:136/139 (preliminary questions), RVS:2025:1827/1829 (Ukraine).
- **Jaccard 0.4 to 0.5, related but on another question:** HR:2023:184/182 (same director, another question), RVS:2026:4164/4162 (same stichting, other enforcement requests).
- **Jaccard 0.3 to 0.4, false positive:** RBZWB:2024:5360/5361 (two WOZ cases from one firm of representatives).
- **Short texts below 0.85, false positives:** HR:2026:1373/1372, 1420/1419, 1365/1364, 1451/1468, HR:2024:332/337, RVS:2026:5275/5273, 4844/4891, 2601/2631.
- **Explicit links:** 407 case numbers are named after "Samenhang met". Only 126 resolve to a judgment of the same day in the database; many are "(niet gepubliceerd)". Of the 143 explicit same-day pairs, only 9 are pairs under the current rule.

## Recommendation

**The step is already built and its signal is strong (24/24 in the sample). Keep it. Make one small change: lower `LONG_TEXT_JACCARD` from 0.7 to 0.5.**

In long judgments, each parallel case tells its own parties, facts and amounts, so real sister cases often share only 50–70% of their shingles. Between 0.5 and 0.7, 14 of 15 new links are real. Below 0.5, precision drops (10/12 at 0.4, 3/6 at 0.3). For short texts it collapses, because the Hoge Raad and the Raad van State publish templates. The change adds 36 series and 88 judgments on lawgraph_small (159 → 195 series, 455 → 543 judgments). No series grows past 15.

**Done on this branch (minimal):**

- `core/judgment_series.LONG_TEXT_JACCARD = 0.5`
- a failing-then-passing integration test on 8530, `test_long_parallel_cases_with_their_own_facts_are_a_series`, modelled on RVS:2026:5181/5185
- the unit test moved to the new band
- `docs/pipelines.md` updated

**Not recommended:**

- **Adding HR:2022:969/970 to a series.** It is not "the same text", and forcing it in would take the thresholds down to where precision falls. If connected cases are wanted, they are a separate relation (e.g. `RELATED_CASE` from "Samenhang met <case number>" and "Zie ook: ECLI" in the summary). That needs its own item: it gives 143 same-day pairs on lawgraph_small, and more across dates.
- **Merging short template rulings.** An optional later refinement is to require the same party or representative line for texts under 600 words. That would drop RVS:2026:3620, 3897 and 5066. It is not worth it now.

**API:** unchanged. `series_id`, `series_size` and `series` are right as they are. The front end can label them as parallel judgments (same court, same day, nearly the same text).

**The owner must run:** `lawgraph semantic rechtspraak-series` without `--since`, because the threshold affects every day. Run it on lawgraph_small after the merge, then on the full database. I ran nothing on 8529.
