"""
Comprehensive audit of judgment paragraph structures in ArangoDB.
Court type is derived from ECLI code (e.g. ECLI:NL:HR:... or ECLI:NL:GHAMS:...).
"""

from __future__ import annotations

import collections
import os
import re

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


def court_filter(court):
    """AQL FILTER expression for court category by ECLI prefix."""
    if court == "HR":
        return "SPLIT(j.props.ecli, ':')[2] == 'HR'"
    elif court == "GH":
        return "LIKE(SPLIT(j.props.ecli, ':')[2], 'GH%')"
    elif court == "RB":
        return "LIKE(SPLIT(j.props.ecli, ':')[2], 'RB%')"
    return ""


def section(title):
    print(f"\n{'='*72}")
    print(f"  {title}")
    print("=" * 72)


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

for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    ct = q(f"FOR j IN judgments FILTER {cf} COLLECT WITH COUNT INTO n RETURN n")[0]
    wp = q(
        f"""
    FOR j IN judgments
        FILTER {cf}
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        COLLECT WITH COUNT INTO n RETURN n
    """
    )[0]
    pct = f"{wp/ct*100:.1f}%" if ct else "n/a"
    print(f"  {court}: {ct} total, {wp} with paragraphs ({pct})")

# PHR (Parket — AG conclusions)
phr_total = q(
    "FOR j IN judgments FILTER SPLIT(j.props.ecli, ':')[2] == 'PHR' COLLECT WITH COUNT INTO n RETURN n"
)[0]
phr_with_p = q(
    """
FOR j IN judgments
    FILTER SPLIT(j.props.ecli, ':')[2] == 'PHR'
    FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"  PHR (AG-conclusies): {phr_total} total, {phr_with_p} with paragraphs")


# ─────────────────────────────────────────────────────────────────────────────
# Q2: First subheading structure
# ─────────────────────────────────────────────────────────────────────────────
section("Q2: First subheading structure")

for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    subsection(f"{court} — first subheading analysis (sample 50)")
    rows = q(
        f"""
    FOR j IN judgments
        FILTER {cf}
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
            examples_subheading.append((row["ecli"], text[:400]))

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

        # Defendant name: expect something after "tegen" marker
        m = re.search(
            r"(?:in de strafzaak tegen|tegen)\s*[\n\r]?\s*([A-Z][^\n]{2,60})", text
        )
        if not m:
            no_defendant_in_subheading += 1
            if len(examples_no_defendant) < 3:
                examples_no_defendant.append((row["ecli"], text[:300]))

    print(f"  Sampled: {len(rows)}, has subheading: {has_subheading}")
    print(f"  Contains 'parketnummer':          {has_parketnummer}/{has_subheading}")
    print(f"  Contains 'datum' KV:              {has_datum_kv}/{has_subheading}")
    print(
        f"  Contains 'in de strafzaak tegen': {has_strafzaak_marker}/{has_subheading}"
    )
    print(f"  Contains 'tegen' (any):           {has_tegen_marker}/{has_subheading}")
    print(f"  Contains 'Inhoudsopgave':         {has_inhoudsopgave}/{has_subheading}")
    print(
        f"  Defendant NOT extracted:          {no_defendant_in_subheading}/{has_subheading}"
    )
    if examples_subheading:
        ecli, txt = examples_subheading[0]
        print(f"\n  Example subheading ({court}):")
        print(f"    ECLI: {ecli}")
        print(f"    TEXT: {repr(txt[:350])}")
    if examples_no_defendant:
        print("\n  No-defendant examples:")
        for ecli, txt in examples_no_defendant[:2]:
            print(f"    ECLI: {ecli}")
            print(f"    TEXT: {repr(txt[:250])}")

# Inhoudsopgave: confirm only in which courts?
print("\n  Inhoudsopgave: which courts?")
inhoudsopgave_rows = q(
    """
FOR j IN judgments
    FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER CONTAINS(LOWER(para.text), 'inhoudsopgave')
        LIMIT 20
        RETURN {ecli: j.props.ecli, text: LEFT(para.text, 120)}
"""
)
for r in inhoudsopgave_rows:
    parts = (r["ecli"] or "").split(":")
    code = parts[2] if len(parts) > 2 else "?"
    print(f"    {code:12s}  {r['ecli']}  {repr(r['text'][:80])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q3: Embedded headings — body paragraph containing \n\nN.\tSection title
# ─────────────────────────────────────────────────────────────────────────────
section("Q3: Embedded headings in body paragraphs")

# Total body paragraphs
total_body = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs FILTER para.kind == 'body'
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]

# The pattern: text ends with \n\nN.\tSomething
# ArangoDB regex: \n\n[0-9]+\.?\t
embedded_total = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '\n\n[0-9]+\.?\t[A-Z]')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]

print(f"Total body paragraphs: {total_body}")
print(
    f"Body paras with embedded heading pattern (\\n\\nN.\\tTitle): {embedded_total} ({embedded_total/total_body*100:.2f}%)"
)

# Sample to analyze number formats
embedded_samples = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '\n\n[0-9]+\.?\t[A-Z]')
        LIMIT 100
        RETURN {ecli: j.props.ecli, text: para.text}
"""
)

formats = collections.Counter()
for row in embedded_samples:
    text = row["text"]
    # Find all embedded heading markers
    matches = re.findall(r"\n\n(\S+)\t[A-Z]", text)
    for m in matches:
        formats[m] += 1

print(f"\n  Number format distribution (from {len(embedded_samples)} samples):")
for fmt, cnt in formats.most_common(25):
    print(f"    {repr(fmt):20s} x{cnt}")

# Also look for simpler pattern: paragraph that starts with "N.\t" (a heading disguised as body)
embedded_start = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[0-9]+\.?\t[A-Z]')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"\n  Body paras starting directly with 'N.\\tTitle': {embedded_start}")

# Sample examples
print("\n  Examples of embedded heading bodies:")
for row in embedded_samples[:3]:
    tail = row["text"][-300:] if len(row["text"]) > 300 else row["text"]
    print(f"    ECLI: {row['ecli']}")
    print(f"    tail: {repr(tail[:250])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q4: Packed sub-sub paragraphs
# ─────────────────────────────────────────────────────────────────────────────
section("Q4: Packed sub-sub paragraphs (multiple \\d+\\.\\d+ in one body element)")

packed_total = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(
    f"Body paras with multiple sub-section numbers: {packed_total} ({packed_total/total_body*100:.1f}% of body paras)"
)

packed_samples = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
        LIMIT 60
        RETURN {ecli: j.props.ecli, text: para.text}
"""
)

# Court breakdown
for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    ct = q(
        rf"""
    FOR j IN judgments FILTER {cf} FILTER j.props.paragraphs != null
        FOR para IN j.props.paragraphs
            FILTER para.kind == 'body'
            FILTER REGEX_TEST(para.text, '[0-9]+\.[0-9]+\.?\s*\n.*[0-9]+\.[0-9]+\.?\s*\n')
            COLLECT WITH COUNT INTO n RETURN n
    """
    )[0]
    print(f"  {court}: {ct} packed body paragraphs")

print("\n  Examples (sub-para marker counts):")
for row in packed_samples[:4]:
    matches = re.findall(r"\d+\.\d+\.?\s*\n", row["text"])
    print(f"    ECLI: {row['ecli']} — {len(matches)} sub-para markers")
    print(f"    first 250: {repr(row['text'][:250])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q5: para.number field
# ─────────────────────────────────────────────────────────────────────────────
section("Q5: para.number field — is it ever populated?")

number_populated = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.number != null AND para.number != '' AND para.number != false
        LIMIT 20
        RETURN {ecli: j.props.ecli, number: para.number, kind: para.kind, text: LEFT(para.text, 80)}
"""
)
print(f"Paragraphs with non-null para.number: {len(number_populated)} (cap 20)")
if number_populated:
    for r in number_populated[:5]:
        print(f"  number={repr(r['number'])}  kind={r['kind']}  ecli={r['ecli']}")
        print(f"  text: {repr(r['text'])}")
else:
    print("  -> para.number is NEVER populated in the DB.")

# What keys does a paragraph object have?
sample_para = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 3
    LIMIT 3
    RETURN j.props.paragraphs[0]
"""
)
print("\n  Paragraph object keys (first 3 docs, para[0]):")
for p in sample_para:
    print(f"    {sorted(p.keys()) if p else '(null)'}")

# Also sample a body paragraph
sample_body = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs FILTER para.kind == 'body'
    LIMIT 1
    RETURN para
"""
)
if sample_body:
    print(f"  Body paragraph keys: {sorted(sample_body[0].keys())}")
    for k, v in sample_body[0].items():
        if k != "text":
            print(f"    {k}: {repr(str(v)[:100])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q6: Distinct para.kind values
# ─────────────────────────────────────────────────────────────────────────────
section("Q6: Distinct para.kind values")

kind_rows = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        COLLECT kind = para.kind WITH COUNT INTO cnt
        SORT cnt DESC
        RETURN {kind: kind, cnt: cnt}
"""
)
print(f"{'kind':30s}  {'count':>12s}")
print("-" * 46)
for r in kind_rows:
    print(f"  {repr(r['kind']):28s}  {r['cnt']:>12,d}")


# ─────────────────────────────────────────────────────────────────────────────
# Q7: Subheading structure variation per court; judgments with NO subheading
# ─────────────────────────────────────────────────────────────────────────────
section("Q7: Subheading structure variation & no-subheading cases")

for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    subsection(f"{court}")

    total_with_paras = q(
        f"""
    FOR j IN judgments FILTER {cf}
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        COLLECT WITH COUNT INTO n RETURN n
    """
    )[0]

    no_subheading_sample = q(
        f"""
    FOR j IN judgments FILTER {cf}
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        FILTER LENGTH(j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' RETURN 1]) == 0
        LIMIT 10
        RETURN {{
            ecli: j.props.ecli,
            first_kind: j.props.paragraphs[0].kind,
            first_text: LEFT(j.props.paragraphs[0].text, 100)
        }}
    """
    )

    no_subheading_count = q(
        f"""
    FOR j IN judgments FILTER {cf}
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        FILTER LENGTH(j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' RETURN 1]) == 0
        COLLECT WITH COUNT INTO n RETURN n
    """
    )[0]

    print(f"  Total with paragraphs: {total_with_paras}")
    print(
        f"  With NO subheading:    {no_subheading_count} ({no_subheading_count/total_with_paras*100:.1f}%)"
    )
    for r in no_subheading_sample[:4]:
        print(
            f"    {r['ecli']}  first_kind={r['first_kind']}  {repr(r['first_text'][:80])}"
        )

    if court == "HR":
        print(
            "\n  HR: first 30 chars of each subheading (to detect court-header pattern):"
        )
        hr_subs = q(
            """
        FOR j IN judgments FILTER SPLIT(j.props.ecli, ':')[2] == 'HR'
            FILTER j.props.paragraphs != null
            LET sub = j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT][0]
            FILTER sub != null
            LIMIT 40
            RETURN {ecli: j.props.ecli, text: LEFT(sub.text, 200)}
        """
        )
        starts = collections.Counter()
        for r in hr_subs:
            txt = (r.get("text") or "").strip()
            # first non-blank line
            first_line = next((ln.strip() for ln in txt.split("\n") if ln.strip()), "")
            starts[first_line[:60]] += 1
        print("  Most common first-line of HR subheading (top 10):")
        for line, cnt in starts.most_common(10):
            print(f"    {repr(line):55s} x{cnt}")

        print("\n  HR subheading example:")
        if hr_subs:
            r = hr_subs[0]
            print(f"    ECLI: {r['ecli']}")
            print(f"    TEXT: {repr(r['text'][:400])}")

    if court == "RB":
        rb_subs = q(
            """
        FOR j IN judgments FILTER LIKE(SPLIT(j.props.ecli, ':')[2], 'RB%')
            FILTER j.props.paragraphs != null
            LET sub = j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT][0]
            FILTER sub != null
            LIMIT 10
            RETURN {ecli: j.props.ecli, text: LEFT(sub.text, 250)}
        """
        )
        print("\n  RB subheading examples:")
        for r in rb_subs[:3]:
            print(f"    ECLI: {r['ecli']}")
            print(f"    TEXT: {repr(r['text'][:250])}")

    if court == "GH":
        gh_subs = q(
            """
        FOR j IN judgments FILTER LIKE(SPLIT(j.props.ecli, ':')[2], 'GH%')
            FILTER j.props.paragraphs != null
            LET sub = j.props.paragraphs[* FILTER CURRENT.kind == 'subheading' LIMIT 1 RETURN CURRENT][0]
            FILTER sub != null
            LIMIT 10
            RETURN {ecli: j.props.ecli, text: LEFT(sub.text, 250)}
        """
        )
        print("\n  GH subheading examples:")
        for r in gh_subs[:3]:
            print(f"    ECLI: {r['ecli']}")
            print(f"    TEXT: {repr(r['text'][:250])}")


# ─────────────────────────────────────────────────────────────────────────────
# Q8: Weird patterns
# ─────────────────────────────────────────────────────────────────────────────
section("Q8: Weird patterns")

# 8a: Very short body paragraphs (< 20 chars)
subsection("8a: Very short body paragraphs (< 20 chars)")
short_body_total = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body' AND LENGTH(para.text) < 20
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
short_body_samples = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body' AND LENGTH(para.text) < 20
        LIMIT 60
        RETURN {ecli: j.props.ecli, text: para.text, len: LENGTH(para.text)}
"""
)
print(f"Total body paras < 20 chars: {short_body_total}")
text_ctr = collections.Counter(r["text"] for r in short_body_samples)
print("  Most common texts (sample of 60):")
for txt, cnt in text_ctr.most_common(20):
    print(f"    {repr(txt):35s}  x{cnt}")
print("  Samples with ECLI:")
for r in short_body_samples[:5]:
    print(f"    {r['ecli']}  len={r['len']}  {repr(r['text'])}")

# 8b: Body paragraphs that start with "N " (digit, space, no dot) — bare number heading
subsection("8b: Body paragraphs starting with bare number 'N ' (no dot)")
bare_num = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[0-9]+\s+[A-Z]')
        LIMIT 40
        RETURN {ecli: j.props.ecli, first80: LEFT(para.text, 80)}
"""
)
print(f"  Sampled: {len(bare_num)}")
for r in bare_num[:5]:
    print(f"  {r['ecli']}  {repr(r['first80'])}")

# 8c: Body paragraphs starting with ALL-CAPS (likely misclassified heading)
subsection("8c: Body paragraphs starting with ALL-CAPS (misclassified heading?)")
allcaps = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[A-Z]{4,}(\s|$)')
        LIMIT 60
        RETURN {ecli: j.props.ecli, first60: LEFT(para.text, 60)}
"""
)
allcaps_total = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '^[A-Z]{4,}(\s|$)')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"  Total: {allcaps_total}")
ctr = collections.Counter(r["first60"][:40] for r in allcaps)
for txt, cnt in ctr.most_common(12):
    print(f"  {repr(txt):45s}  x{cnt}")

# 8d: Large quoted blocks
subsection("8d: Body paragraphs with large quoted blocks (> 300 chars in quotes)")
quoted_total = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '"[^"]{300,}"')
        COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"  Total: {quoted_total} ({quoted_total/total_body*100:.1f}% of body paras)")
quoted_samples = q(
    r"""
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER REGEX_TEST(para.text, '"[^"]{300,}"')
        LIMIT 10
        RETURN {ecli: j.props.ecli, len: LENGTH(para.text), first200: LEFT(para.text, 200)}
"""
)
for r in quoted_samples[:3]:
    print(f"  {r['ecli']}  total_len={r['len']}")
    print(f"  {repr(r['first200'])}")

# 8e: Sub-titles — short lines between decimal number and body (kind=body, text < 60, no sentence structure)
subsection(
    "8e: Potential sub-title paragraphs (body, 20-60 chars, no period or sentence end)"
)
subtitles = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null
    FOR para IN j.props.paragraphs
        FILTER para.kind == 'body'
        FILTER LENGTH(para.text) >= 20 AND LENGTH(para.text) <= 60
        FILTER NOT CONTAINS(para.text, '.')
        LIMIT 40
        RETURN {ecli: j.props.ecli, text: para.text}
"""
)
print(f"  Sampled: {len(subtitles)}")
ctr = collections.Counter(r["text"] for r in subtitles)
for txt, cnt in ctr.most_common(15):
    print(f"  {repr(txt):55s}  x{cnt}")


# ─────────────────────────────────────────────────────────────────────────────
# Q9: props.text vs props.paragraphs
# ─────────────────────────────────────────────────────────────────────────────
section("Q9: props.text for judgments WITHOUT paragraphs")

no_para_with_text_count = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.text != null AND j.props.text != ''
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
no_para_no_text = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER (j.props.text == null OR j.props.text == '')
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"No-para judgments with props.text:     {no_para_with_text_count}")
print(f"No-para judgments with no text either: {no_para_no_text}")

# Stub vs. non-stub
stub_no_para = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.stub == true
    COLLECT WITH COUNT INTO n RETURN n
"""
)[0]
print(f"No-para judgments that are stubs:      {stub_no_para}")

no_para_samples = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.text != null AND j.props.text != ''
    LIMIT 5
    RETURN {ecli: j.props.ecli, text_len: LENGTH(j.props.text), preview: LEFT(j.props.text, 200), props_keys: ATTRIBUTES(j.props)}
"""
)
print("\n  Samples with text:")
for r in no_para_samples:
    print(f"  ECLI: {r['ecli']}  text_len={r['text_len']}")
    print(f"  props_keys: {r['props_keys']}")
    print(f"  preview: {repr(r['preview'])}")

# What do the stub-only no-para records look like?
stub_sample = q(
    """
FOR j IN judgments
    FILTER (j.props.paragraphs == null OR LENGTH(j.props.paragraphs) == 0)
    FILTER j.props.stub == true
    LIMIT 3
    RETURN {ecli: j.props.ecli, props_keys: ATTRIBUTES(j.props)}
"""
)
print("\n  Stub no-para samples:")
for r in stub_sample:
    print(f"  {r['ecli']}  keys={r['props_keys']}")


# ─────────────────────────────────────────────────────────────────────────────
# Q10: Advocate/AG extraction in HR judgments
# ─────────────────────────────────────────────────────────────────────────────
section("Q10: Advocate/AG info location in HR judgments")

hr_sample = q(
    """
FOR j IN judgments
    FILTER SPLIT(j.props.ecli, ':')[2] == 'HR'
    FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) >= 3
    LIMIT 60
    RETURN {
        ecli: j.props.ecli,
        paras: j.props.paragraphs[* RETURN {kind: CURRENT.kind, text: LEFT(CURRENT.text, 400)}]
    }
"""
)

raadsman_idx_ctr = collections.Counter()
ag_idx_ctr = collections.Counter()
no_raadsman_count = 0

for row in hr_sample:
    paras = row.get("paras") or []
    found_raadsman = False
    for i, para in enumerate(paras):
        text = (para.get("text") or "").lower()
        if any(
            kw in text for kw in ["raadsman", "raadsvrouw", "advocaat mr.", "advocaat:"]
        ):
            raadsman_idx_ctr[i] += 1
            found_raadsman = True
        if "advocaat-generaal" in text or "procureur-generaal" in text:
            ag_idx_ctr[i] += 1
    if not found_raadsman:
        no_raadsman_count += 1

print(f"HR sample: {len(hr_sample)} judgments")
print(f"No raadsman/advocaat mention: {no_raadsman_count}")

print("\n  Paragraph index where 'raadsman'/'raadsvrouw'/'advocaat' appears:")
for idx, cnt in sorted(raadsman_idx_ctr.items()):
    print(f"    index {idx}: {cnt} judgments")

print("\n  Paragraph index where 'advocaat-generaal' appears:")
for idx, cnt in sorted(ag_idx_ctr.items()):
    print(f"    index {idx}: {cnt} judgments")

# Show a concrete example of HR paragraph layout
print("\n  HR judgment — full paragraph layout (3 examples):")
for example in hr_sample[:3]:
    print(f"\n  ECLI: {example['ecli']}")
    for i, para in enumerate(example["paras"][:7]):
        print(
            f"    [{i}] kind={para['kind']}  len={len(para.get('text',''))}  {repr((para.get('text') or '')[:100])}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BONUS: Paragraph count distribution per court
# ─────────────────────────────────────────────────────────────────────────────
section("BONUS: para.kind distribution per court")
for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    kind_dist = q(
        f"""
    FOR j IN judgments FILTER {cf} FILTER j.props.paragraphs != null
        FOR para IN j.props.paragraphs
            COLLECT kind = para.kind WITH COUNT INTO cnt
            SORT cnt DESC
            RETURN {{kind: kind, cnt: cnt}}
    """
    )
    print(f"\n  {court}:")
    for r in kind_dist:
        print(f"    {repr(r['kind']):20s}  {r['cnt']:>10,d}")


# ─────────────────────────────────────────────────────────────────────────────
# BONUS 2: GH — does Inhoudsopgave appear in subheading or separate paragraph?
# ─────────────────────────────────────────────────────────────────────────────
section("BONUS: GH Inhoudsopgave — which paragraph kind?")
inhouds_gh = q(
    """
FOR j IN judgments FILTER LIKE(SPLIT(j.props.ecli, ':')[2], 'GH%')
    FILTER j.props.paragraphs != null
    FOR i IN 0..LENGTH(j.props.paragraphs)-1
        LET para = j.props.paragraphs[i]
        FILTER CONTAINS(LOWER(para.text), 'inhoudsopgave')
        LIMIT 20
        RETURN {ecli: j.props.ecli, idx: i, kind: para.kind, text: LEFT(para.text, 200)}
"""
)
for r in inhouds_gh[:10]:
    print(f"  {r['ecli']}  idx={r['idx']}  kind={r['kind']}  {repr(r['text'][:120])}")


# ─────────────────────────────────────────────────────────────────────────────
# BONUS 3: Overall paragraph count distribution
# ─────────────────────────────────────────────────────────────────────────────
section("BONUS: Max/min/avg paragraph count per judgment")
stats = q(
    """
FOR j IN judgments FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
    LET n = LENGTH(j.props.paragraphs)
    COLLECT AGGREGATE mn = MIN(n), mx = MAX(n), avg = AVG(n), total = COUNT(1)
    RETURN {min: mn, max: mx, avg: avg, total: total}
"""
)
if stats:
    r = stats[0]
    print(
        f"  min={r['min']}, max={r['max']}, avg={r['avg']:.1f}, total_judgments={r['total']}"
    )

for court in ["HR", "GH", "RB"]:
    cf = court_filter(court)
    cs = q(
        f"""
    FOR j IN judgments FILTER {cf}
        FILTER j.props.paragraphs != null AND LENGTH(j.props.paragraphs) > 0
        LET n = LENGTH(j.props.paragraphs)
        COLLECT AGGREGATE mn = MIN(n), mx = MAX(n), avg = AVG(n), total = COUNT(1)
        RETURN {{min: mn, max: mx, avg: avg, total: total}}
    """
    )
    if cs:
        r = cs[0]
        print(
            f"  {court}: min={r['min']}, max={r['max']}, avg={r['avg']:.1f}, n={r['total']}"
        )

print("\n\n=== Audit complete ===")
