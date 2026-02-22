"""
Step 1c — Semantic deduplication.

Groups articles that cover the same underlying story using rapidfuzz
token_set_ratio on normalised titles. DSU (union-find) gives correct
transitive grouping. The article with the longest snippet is kept as the
representative; duplicates are prepended to its corroboration list.

Threshold of 92 is intentionally strict — only near-identical headlines
(same story, different wording) are merged.
"""

import logging
import re
from typing import Dict, List

from rapidfuzz import fuzz

from config import DEDUP_SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    s = s.lower()
    s = s.replace("$", " usd ")
    s = re.sub(r"\b(\d+)\s*bn\b", r"\1b", s)       # "3 bn"      → "3b"
    s = re.sub(r"\b(\d+)\s*billion\b", r"\1b", s)  # "3 billion" → "3b"
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Disjoint Set Union (union-find)
# ---------------------------------------------------------------------------

class _DSU:
    def __init__(self, n: int):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]  # path compression
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def deduplicate_articles(articles: List[Dict]) -> List[Dict]:
    """
    Step 1c: Merge near-duplicate articles into a single representative.

    Duplicates are added to the representative's corroboration list so they
    appear as additional sources in the report alongside Tavily results.

    Args:
        articles: All new articles from Steps 1a and 1b.

    Returns:
        Deduplicated list with merged duplicates recorded as corroborations.
    """
    if not articles:
        return []

    n = len(articles)
    normalised = [_normalize(a.get("title", "")) for a in articles]
    dsu = _DSU(n)

    for i in range(n):
        for j in range(i + 1, n):
            score = fuzz.token_set_ratio(normalised[i], normalised[j])
            if score >= DEDUP_SIMILARITY_THRESHOLD:
                dsu.union(i, j)

    # Collect groups
    groups: dict = {}
    for i in range(n):
        root = dsu.find(i)
        groups.setdefault(root, []).append(i)

    result: List[Dict] = []
    merged_groups = 0

    for idxs in groups.values():
        if len(idxs) == 1:
            result.append(articles[idxs[0]])
            continue

        # Representative: longest snippet
        best_idx = max(idxs, key=lambda i: len(articles[i].get("snippet", "") or ""))
        representative = dict(articles[best_idx])

        dup_corroborations = [
            {
                "title": articles[i].get("title", ""),
                "url": articles[i].get("url", ""),
                "snippet": (articles[i].get("snippet", "") or "")[:200],
                "source": articles[i].get("source", ""),
            }
            for i in idxs if i != best_idx
        ]

        # Prepend duplicates; Tavily corroboration appends on top in Step 3
        representative["corroboration"] = dup_corroborations + representative.get("corroboration", [])

        result.append(representative)
        merged_groups += 1
        logger.info(
            f"  Merged {len(idxs)} articles → \"{articles[best_idx].get('title', '')[:70]}\""
        )

    dropped = n - len(result)
    if dropped:
        logger.info(
            f"Step 1c complete: {len(result)} articles after dedup "
            f"({dropped} duplicates folded into {merged_groups} groups)"
        )
    else:
        logger.info(f"Step 1c complete: no duplicates found ({len(result)} articles)")

    return result
