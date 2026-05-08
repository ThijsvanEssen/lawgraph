"""
Comprehensive audit of judgment paragraph structures in ArangoDB.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from arango import ArangoClient
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("ARANGO_URL", "http://localhost:8529")
db_name = os.getenv("ARANGO_DB_NAME", "lawgraph")
user = os.getenv("ARANGO_USER", "root")
pwd = os.getenv("ARANGO_PASSWORD", "")
client = ArangoClient(hosts=url)
db = client.db(db_name, username=user, password=pwd)


def q(aql, bind_vars=None):
    return list(db.aql.execute(aql, bind_vars=bind_vars or {}))


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print("=" * 70)


def subsection(title):
    print(f"\n--- {title} ---")


# ─────────────────────────────────────────────────────────────────────────────
# Q1: How many judgments have paragraphs?
# ─────────────────────────────────────────────────────────────────────────────
section("Q1: Coverage — judgments with/without paragraphs")

total = q("FOR j IN judgments COLLECT WITH COUNT INTO n RETURN n")[0]
has_paras = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
no_paras = total - has_paras
print(f"Total judgments:           {total}")
print(f"With props.paragraphs:     {has_paras}  ({has_paras/total*100:.1f}%)")
print(f"Without props.paragraphs:  {no_paras}  ({no_paras/total*100:.1f}%)")

# Break down by court label
for court in ["HR", "GH", "RB"]:
    ct = q(
        f"""
    FOR j IN judgments FILTER '{court}' IN j.labels
    COLLECT WITH COUNT INTO n RETURN n
    """
    )
    ct = ct[0] if ct else 0
    wp = q(
        f"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        COLLECT WITH COUNT INTO n RETURN n
    """
    )
    wp = wp[0] if wp else 0
    pct = f"{wp/ct*100:.1f}%" if ct else "n/a"
    print(f"  {court}: {ct} total, {wp} with paragraphs ({pct})")


# ─────────────────────────────────────────────────────────────────────────────
# Q2: First subheading structure
# ─────────────────────────────────────────────────────────────────────────────
section("Q2: First subheading structure (kind=subheading, index 0 or 1)")

for court in ["HR", "GH", "RB"]:
    subsection(f"{court} — first subheading analysis (sample 50)")
    rows = q(
        f"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        LIMIT 50
        RETURN {{
            ecli: j.props.ecli,
            paras: j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT]
        }}
    """
    )

    has_subheading = 0
    has_parketnummer = 0
    has_datum_kv = 0
    has_strafzaak_marker = 0
    has_tegen_marker = 0
    no_defendant_in_subheading = 0
    has_inhoudsopgave = 0
    examples_no_defendant = []
    examples_subheading = []

    for row in rows:
        paras = row.get("paras") or []
        if not paras:
            continue
        has_subheading += 1
        text = paras[0].get("text", "") or ""
        if len(examples_subheading) < 2:
            examples_subheading.append((row["ecli"], text[:300]))

        if "parketnummer" in text.lower():
            has_parketnummer += 1
        if re.search(r"\bdatum\b", text, re.IGNORECASE):
            has_datum_kv += 1
        if "in de strafzaak tegen" in text.lower():
            has_strafzaak_marker += 1
        if re.search(r"\btegen\b", text, re.IGNORECASE):
            has_tegen_marker += 1
        if "inhoudsopgave" in text.lower():
            has_inhoudsopgave += 1

        # Defendant name: expect something after "tegen" or "strafzaak tegen"
        m = re.search(
            r"(?:in de strafzaak tegen|tegen)\s*\n?\s*([A-Z][^\n]{2,60})", text
        )
        if not m:
            no_defendant_in_subheading += 1
            if len(examples_no_defendant) < 3:
                examples_no_defendant.append((row["ecli"], text[:200]))

    print(f"  Sampled: {len(rows)}, has subheading: {has_subheading}")
    print(f"  Contains 'parketnummer':          {has_parketnummer}/{has_subheading}")
    print(f"  Contains 'datum' KV:              {has_datum_kv}/{has_subheading}")
    print(
        f"  Contains 'in de strafzaak tegen': {has_strafzaak_marker}/{has_subheading}"
    )
    print(f"  Contains 'tegen' (any):           {has_tegen_marker}/{has_subheading}")
    print(f"  Contains 'Inhoudsopgave':         {has_inhoudsopgave}/{has_subheading}")
    print(
        f"  Defendant NOT found in subheading:{no_defendant_in_subheading}/{has_subheading}"
    )
    if examples_subheading:
        print(f"\n  Example subheading text ({court}):")
        ecli, txt = examples_subheading[0]
        print(f"    ECLI: {ecli}")
        print(f"    TEXT: {repr(txt[:250])}")
    if examples_no_defendant:
        print("\n  Examples with no defendant detected:")
        for ecli, txt in examples_no_defendant[:2]:
            print(f"    ECLI: {ecli}")
            print(f"    TEXT: {repr(txt[:200])}")

# Inhoudsopgave — confirm only GH?
inhoudsopgave_rows = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER CONTAINS(LOWER(para.text), 'inhoudsopgave')
        LIMIT 10
        RETURN {ecli: j.props.ecli, labels: j.labels, text: LEFT(para.text, 100)}
"""
)
print("\n  Judgments with 'Inhoudsopgave' paragraph:")
for r in inhoudsopgave_rows:
    print(f"    {r['ecli']} labels={r['labels']} text={repr(r['text'][:80])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q3: Embedded headings — body paragraph ending with "\n\nN.\tSection title"
# ─────────────────────────────────────────────────────────────────────────────
section("Q3: Embedded headings in body paragraphs (\\n\\nN.\\tTitle pattern)")

embedded_heading_rows = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '\\n\\n[0-9]+\\.?\\t[A-Z]')
        LIMIT 100
        RETURN {ecli: j.props.ecli, labels: j.labels, text: para.text}
"""
)

total_body_paras = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]

print(
    f"Body paragraphs with embedded heading pattern: {len(embedded_heading_rows)} (sample cap 100)"
)
print(f"Total body paragraphs in DB: {total_body_paras}")

# Count uncapped
embedded_total = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '\\n\\n[0-9]+\\.?\\t[A-Z]')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(
    f"Exact count (uncapped): {embedded_total} ({embedded_total/total_body_paras*100:.1f}% of body paras)"
)

# What number formats?
formats = Counter()
for row in embedded_heading_rows:
    text = row["text"]
    matches = re.findall(r"\n\n(\S+)\t[A-Z]", text)
    for m in matches:
        formats[m] += 1

print("\n  Number format samples (up to 20):")
for fmt, cnt in formats.most_common(20):
    print(f"    {repr(fmt):20s} x{cnt}")

print("\n  Examples:")
for row in embedded_heading_rows[:3]:
    # show just the tail of the paragraph
    tail = row["text"][-200:]
    print(f"    ECLI: {row['ecli']} labels={row['labels']}")
    print(f"    tail: {repr(tail)}")


# ─────────────────────────────────────────────────────────────────────────────
# Q4: Packed sub-sub paragraphs
# ─────────────────────────────────────────────────────────────────────────────
section("Q4: Packed sub-sub paragraphs (multiple \\d+\\.\\d+\\.? in one body element)")

packed_rows = q(
    r"""
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
        LIMIT 60
        RETURN {ecli: j.props.ecli, labels: j.labels, text: para.text}
"""
)

packed_total = q(
    r"""
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]

print(f"Body paragraphs with multiple sub-section numbers: {packed_total}")
print(f"(As fraction of total body paras: {packed_total/total_body_paras*100:.1f}%)")

# Count per court
for court in ["HR", "GH", "RB"]:
    ct = q(
        rf"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null
        FOR para IN j.props.paragraphs
            FILTER para.kind == 'body'
            FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
            COLLECT WITH COUNT INTO n RETURN n
    """
    )
    ct = ct[0] if ct else 0
    print(f"  {court}: {ct} packed body paragraphs")

print("\n  Examples:")
for row in packed_rows[:3]:
    text = row["text"]
    # count sub-sub matches
    matches = re.findall(r"\d+\.\d+\.?\s*\n", text)
    print(f"    ECLI: {row['ecli']} — {len(matches)} sub-para markers found")
    print(f"    first 300 chars: {repr(text[:300])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q5: para.number field
# ─────────────────────────────────────────────────────────────────────────────
section("Q5: para.number field — is it ever populated?")

number_populated = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.number != null AND para.number != ''
        LIMIT 20
        RETURN {ecli: j.props.ecli, number: para.number, kind: para.kind, text: LEFT(para.text, 80)}
"""
)
print(f"Paragraphs with non-null para.number: {len(number_populated)} (sample cap 20)")
if number_populated:
    for r in number_populated[:5]:
        print(f"  ECLI: {r['ecli']}  number={repr(r['number'])}  kind={r['kind']}")
        print(f"  text: {repr(r['text'])}")
else:
    print("  -> para.number is NEVER populated in the DB.")

# Check what fields paragraphs actually have
sample_para_keys = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 3
    LIMIT 5
    RETURN j.props.paragraphs[0]
"""
)
print("\n  Paragraph object keys (from first 5 docs):")
for p in sample_para_keys:
    print(f"    keys: {sorted(p.keys()) if p else '(null)'}")


# ─────────────────────────────────────────────────────────────────────────────
# Q6: para.kind values
# ─────────────────────────────────────────────────────────────────────────────
section("Q6: Distinct para.kind values")

kind_rows = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        COLLECT kind = para.kind WITH COUNT INTO cnt
        RETURN {kind: kind, cnt: cnt}
"""
)
print(f"{'kind':30s}  {'count':>10s}")
print("-" * 45)
for r in sorted(kind_rows, key=lambda x: -x["cnt"]):
    print(f"  {repr(r['kind']):28s}  {r['cnt']:>10,d}")


# ─────────────────────────────────────────────────────────────────────────────
# Q7: Subheading structure variation per court; judgments with NO subheading
# ─────────────────────────────────────────────────────────────────────────────
section("Q7: Subheading structure variation per court")

for court in ["HR", "RB", "GH"]:
    subsection(f"{court}")
    # judgments with paragraphs but NO subheading
    no_subheading = q(
        f"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        FILTER LENGTH(j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' RETURN 1]) == 0
        LIMIT 10
        RETURN {{ecli: j.props.ecli, first_para_kind: j.props.paragraphs[0].kind, first_text: LEFT(j.props.paragraphs[0].text, 100)}}
    """
    )
    total_with_paras = q(
        f"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        COLLECT WITH COUNT INTO n RETURN n
    """
    )
    total_with_paras = total_with_paras[0] if total_with_paras else 0
    print(f"  Total with paragraphs: {total_with_paras}")
    print("  Judgments with NO subheading at all: (sample ≤10)")
    for r in no_subheading[:5]:
        print(
            f"    {r['ecli']}  first_kind={r['first_para_kind']}  text={repr(r['first_text'][:80])}"
        )

    # For HR specifically: does subheading always start with court name header?
    if court == "HR":
        print("\n  HR: checking if subheading starts with court name header")
        hr_subheading_starts = q(
            """
        FOR j IN judgments
            FILTER 'HR' IN j.labels
            FILTER j.props.paragraphs != null
            LET sub = j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT][0]
            FILTER sub != null
            LIMIT 30
            RETURN {ecli: j.props.ecli, first100: LEFT(sub.text, 150)}
        """
        )
        starts_hoge_raad = sum(
            1
            for r in hr_subheading_starts
            if "hoge raad" in (r.get("first100") or "").lower()
        )
        print(
            f"  HR subheadings starting with 'Hoge Raad': {starts_hoge_raad}/{len(hr_subheading_starts)}"
        )
        for r in hr_subheading_starts[:2]:
            print(f"    ECLI: {r['ecli']}")
            print(f"    text: {repr(r.get('first100', ''))}")

    if court == "RB":
        print("\n  RB: checking subheading start")
        rb_samples = q(
            """
        FOR j IN judgments
            FILTER 'RB' IN j.labels
            FILTER j.props.paragraphs != null
            LET sub = j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT][0]
            FILTER sub != null
            LIMIT 10
            RETURN {ecli: j.props.ecli, first100: LEFT(sub.text, 150)}
        """
        )
        for r in rb_samples[:3]:
            print(f"    ECLI: {r['ecli']}")
            print(f"    text: {repr(r.get('first100', ''))}")


# ─────────────────────────────────────────────────────────────────────────────
# Q8: Weird patterns
# ─────────────────────────────────────────────────────────────────────────────
section("Q8: Weird patterns")

# 8a: Very short body paragraphs (< 20 chars)
subsection("8a: Very short body paragraphs (< 20 chars)")
short_body = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER LENGTH(para.text) < 20
        LIMIT 40
        RETURN {ecli: j.props.ecli, labels: j.labels, text: para.text, len: LENGTH(para.text)}
"""
)
short_body_total = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER LENGTH(para.text) < 20
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"Total body paras < 20 chars: {short_body_total}")
text_counter = Counter(r["text"] for r in short_body)
print("  Most common texts:")
for txt, cnt in text_counter.most_common(20):
    print(f"    {repr(txt):30s}  x{cnt}")
print("  Sample ECLIs:")
for r in short_body[:5]:
    print(f"    {r['ecli']}  len={r['len']}  text={repr(r['text'])}")

# 8b: Body paragraphs starting with a bare number like "3 " (no dot) — possible embedded heading
subsection("8b: Body paragraphs starting with 'N ' (number, space, no dot)")
bare_number_start = q(
    r"""
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[0-9]+\s+[A-Z]')
        LIMIT 40
        RETURN {ecli: j.props.ecli, labels: j.labels, first80: LEFT(para.text, 80)}
"""
)
print(f"Sampled: {len(bare_number_start)}")
for r in bare_number_start[:5]:
    print(f"  {r['ecli']}  text={repr(r['first80'])}")

# 8c: Body paragraphs starting with ALL CAPS (possible misclassified heading)
subsection("8c: Body paragraphs starting with ALL-CAPS word")
allcaps_body = q(
    r"""
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[A-Z]{3,}(\s|$)')
        LIMIT 40
        RETURN {ecli: j.props.ecli, labels: j.labels, first80: LEFT(para.text, 80)}
"""
)
print(f"Sampled: {len(allcaps_body)}")
text_ctr = Counter(r["first80"][:40] for r in allcaps_body)
for txt, cnt in text_ctr.most_common(10):
    print(f"  {repr(txt):45s}  x{cnt}")

# 8d: Large quoted blocks (look for lines starting with '"' or long runs with quotes)
subsection("8d: Body paragraphs with large quoted blocks (> 300 chars in quotes)")
quoted_body = q(
    r"""
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '"[^"]{300,}"')
        LIMIT 20
        RETURN {ecli: j.props.ecli, labels: j.labels, len: LENGTH(para.text), first200: LEFT(para.text, 200)}
"""
)
print(f"Sampled: {len(quoted_body)}")
for r in quoted_body[:3]:
    print(f"  {r['ecli']}  total_len={r['len']}  text={repr(r['first200'])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q9: props.text for judgments without paragraphs
# ─────────────────────────────────────────────────────────────────────────────
section("Q9: props.text for judgments WITHOUT paragraphs")

no_para_with_text = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.text != null AND j.props.text != ''
    LIMIT 5
    RETURN {ecli: j.props.ecli, labels: j.labels, text_len: LENGTH(j.props.text), text_preview: LEFT(j.props.text, 200)}
"""
)
no_para_no_text = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER (j.props.text == null OR j.props.text == '')
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
no_para_with_text_count = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.text != null AND j.props.text != ''
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]

print(f"No-para judgments with props.text:    {no_para_with_text_count}")
print(f"No-para judgments with NO text either: {no_para_no_text}")

print("\n  Samples with text:")
for r in no_para_with_text:
    print(f"  ECLI: {r['ecli']}  labels={r['labels']}  text_len={r['text_len']}")
    print(f"  preview: {repr(r['text_preview'])}")

# Check what fields do exist on a no-para judgment
no_para_fields = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    LIMIT 3
    RETURN j.props
"""
)
print("\n  Props keys for no-para judgments:")
for p in no_para_fields:
    if p:
        print(f"  keys: {sorted(p.keys())}")


# ─────────────────────────────────────────────────────────────────────────────
# Q10: Advocate/AG extraction in HR judgments
# ─────────────────────────────────────────────────────────────────────────────
section("Q10: Advocate/AG info in HR judgments")

hr_sample = q(
    """
FOR j IN judgments
    FILTER 'HR' IN j.labels
    FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) >= 3
    LIMIT 50
    RETURN {
        ecli: j.props.ecli,
        paras: j.props.paragraphs[* RETURN {kind: CURRENT.kind, text: LEFT(CURRENT.text, 300)}]
    }
"""
)

raadsman_in_index2 = 0
raadsman_elsewhere = 0
no_raadsman = 0
raadsman_index_counter = Counter()
ag_index_counter = Counter()

for row in hr_sample:
    paras = row.get("paras") or []
    found_raadsman = False
    found_ag = False
    for i, para in enumerate(paras):
        text = (para.get("text") or "").lower()
        if "raadsman" in text or "advocaat" in text or "raadsvrouw" in text:
            raadsman_index_counter[i] += 1
            found_raadsman = True
        if "advocaat-generaal" in text or "procureur-generaal" in text:
            ag_index_counter[i] += 1
            found_ag = True

    if not found_raadsman:
        no_raadsman += 1

print(f"HR sample: {len(hr_sample)} judgments (min 3 paragraphs)")
print(f"No 'raadsman'/'advocaat' mention at all: {no_raadsman}")
print("\n  Paragraph index where 'raadsman' appears:")
for idx, cnt in sorted(raadsman_index_counter.items()):
    print(f"    index {idx}: {cnt} judgments")

print("\n  Paragraph index where 'advocaat-generaal' appears:")
for idx, cnt in sorted(ag_index_counter.items()):
    print(f"    index {idx}: {cnt} judgments")

# Show a concrete HR example: first 5 paragraphs
print("\n  HR example — first 5 paragraphs structure:")
example_hr = hr_sample[0]
print(f"  ECLI: {example_hr['ecli']}")
for i, para in enumerate(example_hr["paras"][:6]):
    print(f"    [{i}] kind={para['kind']}  text={repr(para.get('text','')[:120])}")


# ─────────────────────────────────────────────────────────────────────────────
# BONUS: para.kind distribution per court
# ─────────────────────────────────────────────────────────────────────────────
section("BONUS: para.kind distribution per court")
for court in ["HR", "GH", "RB"]:
    kind_dist = q(
        f"""
    FOR j IN judgments
        FILTER '{court}' IN j.labels
        FILTER j.props.paragraphs != null
        FOR para IN j.props.paragraphs
            COLLECT kind = para.kind WITH COUNT INTO cnt
            RETURN {{kind: kind, cnt: cnt}}
    """
    )
    print(f"\n  {court}:")
    for r in sorted(kind_dist, key=lambda x: -x["cnt"]):
        print(f"    {repr(r['kind']):20s}  {r['cnt']:>8,d}")


# ─────────────────────────────────────────────────────────────────────────────
# BONUS 2: Paragraph count distribution
# ─────────────────────────────────────────────────────────────────────────────
section("BONUS: Paragraph count per judgment distribution")

para_counts = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    LET n = LENGTH(j.props.paragraphs)
    COLLECT bucket = FLOOR(n / 5) * 5 INTO grp
    RETURN {bucket: bucket, count: LENGTH(grp)}
"""
)
print(f"  {'#paragraphs':>12}  {'# judgments':>12}")
for r in sorted(para_counts, key=lambda x: x["bucket"])[:25]:
    print(f"  {r['bucket']:>5}-{r['bucket']+4:<5}     {r['count']:>8,d}")

print("\n\nAudit complete.")
