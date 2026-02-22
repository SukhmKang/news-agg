"""
Tests for pipeline/dedup.py
Run with: python3.11 test_dedup.py
"""

import sys
sys.path.insert(0, ".")

from rapidfuzz import fuzz
from pipeline.dedup import deduplicate_articles, _normalize

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

def article(title, snippet="x", url=None, source="rss"):
    return {
        "title": title,
        "snippet": snippet,
        "url": url or f"http://example.com/{title[:20].replace(' ','-')}",
        "source": source,
        "corroboration": [],
    }

results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    results.append(condition)


# ---------------------------------------------------------------------------
print("\n── _normalize ──")
# ---------------------------------------------------------------------------

check("lowercase",          _normalize("ADNOC") == "adnoc")
check("$ → usd",            "usd" in _normalize("$3bn deal"))
check("3 bn → 3b",          _normalize("3 bn deal") == "3b deal")
check("3 billion → 3b",     _normalize("3 billion deal") == "3b deal")
check("strip punctuation",  _normalize("UAE: deal!") == "uae deal")


# ---------------------------------------------------------------------------
print("\n── deduplicate_articles ──")
# ---------------------------------------------------------------------------

# 1. Exact same title
arts = [article("ADNOC signs deal with BP", snippet="short"),
        article("ADNOC signs deal with BP", snippet="longer snippet here")]
out = deduplicate_articles(arts)
check("1. Exact title → merged", len(out) == 1)

# 2. Same story, slight wording difference
arts = [article("ADNOC signs deal with BP"), article("ADNOC and BP sign a deal")]
out = deduplicate_articles(arts)
s = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[1]["title"]))
check("2. Slight wording difference", len(out) == 1, f"similarity={s}")

# 3. Source attribution suffix differs
arts = [article("Mubadala acquires stake in European firm - Reuters"),
        article("Mubadala acquires stake in European firm - Bloomberg")]
out = deduplicate_articles(arts)
s = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[1]["title"]))
check("3. Source suffix differs → merged", len(out) == 1, f"similarity={s}")

# 4. Dollar amount normalisation
arts = [article("PIF announces $3bn investment in tech"),
        article("PIF announces $3 billion investment in tech")]
out = deduplicate_articles(arts)
s = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[1]["title"]))
check("4. $3bn vs $3 billion → merged", len(out) == 1, f"similarity={s}")

# 5. Completely different stories → NOT merged
arts = [article("ADNOC signs deal with BP"),
        article("Saudi Arabia opens new airport in Riyadh")]
out = deduplicate_articles(arts)
s = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[1]["title"]))
check("5. Different stories → NOT merged", len(out) == 2, f"similarity={s}")

# 6. Three articles same story → one group with two corroborations
arts = [
    article("Chipotle opens first Dubai restaurant with Alshaya",          snippet="x"),
    article("Chipotle opens its first restaurant in Dubai with Alshaya Group", snippet="xx"),
    article("Chipotle's first Dubai restaurant opens with Alshaya",        snippet="xxx"),
]
out = deduplicate_articles(arts)
check("6. Three same-story articles → one group", len(out) == 1)
check("6. Two duplicates in corroboration", len(out[0]["corroboration"]) == 2)

# 7. Transitive grouping
arts = [
    article("UAE sovereign wealth fund invests in US tech company"),
    article("UAE sovereign wealth fund invests in US technology firm"),
    article("UAE SWF invests in US technology firm deal"),
]
out = deduplicate_articles(arts)
s_ab = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[1]["title"]))
s_bc = fuzz.token_set_ratio(_normalize(arts[1]["title"]), _normalize(arts[2]["title"]))
s_ac = fuzz.token_set_ratio(_normalize(arts[0]["title"]), _normalize(arts[2]["title"]))
check("7. Transitive grouping → one group", len(out) == 1,
      f"A~B={s_ab}, B~C={s_bc}, A~C={s_ac}")

# 8. Empty input
check("8. Empty input → []", deduplicate_articles([]) == [])

# 9. Single article → unchanged
a = article("Some unique headline", snippet="snippet text")
out = deduplicate_articles([a])
check("9. Single article → unchanged",
      len(out) == 1 and out[0]["title"] == a["title"])

# 10. Representative = longest snippet
arts = [
    article("PIF invests in European company", snippet="short"),
    article("PIF invests in European company", snippet="this is a much longer snippet with more detail"),
    article("PIF invests in European company", snippet="medium length snippet here"),
]
out = deduplicate_articles(arts)
check("10. Representative has longest snippet",
      out[0]["snippet"] == "this is a much longer snippet with more detail")


# ---------------------------------------------------------------------------
print("\n── Similarity spot-checks (informational, threshold=92) ──")
# ---------------------------------------------------------------------------
pairs = [
    ("ADNOC signs strategic deal with BP worth $2bn",
     "BP and ADNOC sign $2 billion strategic deal"),
    ("Saudi Arabia's PIF acquires stake in French luxury brand",
     "PIF takes stake in French luxury brand"),
    ("UAE announces new foreign company registration rules",
     "Dubai launches new rules for foreign business registration"),
    ("Vision 2030: Saudi Arabia attracts foreign investment",
     "Saudi Vision 2030 draws in overseas investors"),
    ("Chipotle opens in Dubai - Reuters",
     "Chipotle opens in Dubai - Bloomberg"),
]
for a, b in pairs:
    s = fuzz.token_set_ratio(_normalize(a), _normalize(b))
    verdict = "MERGE" if s >= 92 else "separate"
    print(f"  {s:5.1f}  [{verdict}]  {a[:55]}")
    print(f"                  {b[:55]}")


# ---------------------------------------------------------------------------
passed = sum(results)
total = len(results)
print(f"\n{'─'*50}")
print(f"  {passed}/{total} tests passed")
if passed < total:
    sys.exit(1)
