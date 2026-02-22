"""
Step 3 — Enrichment.

For articles scoring 4–5, runs one targeted Tavily search per article
to gather corroborating sources and additional context.
"""

import logging
from typing import Dict, List

from config import HIGH_SCORE_THRESHOLD, TAVILY_DAYS
from utils import tavily_search

logger = logging.getLogger(__name__)


def run_enrichment(articles: List[Dict]) -> List[Dict]:
    """
    Step 3: For high-scoring articles, fetch corroborating sources via Tavily.

    Modifies article dicts in place. Sets `enriched = True` on completion.

    Args:
        articles: Articles that passed Step 2 filtering (score >= SCORE_THRESHOLD).

    Returns:
        The same list with corroboration and enriched fields populated.
    """
    if not articles:
        return []

    high_score = [a for a in articles if a.get("score", 0) >= HIGH_SCORE_THRESHOLD]
    logger.info(f"Step 3 — Corroboration search for {len(high_score)}/{len(articles)} articles (score {HIGH_SCORE_THRESHOLD}+)...")

    for i, article in enumerate(high_score, 1):
        url = article.get("url", "")
        query = article.get("title", "")[:200]
        title_short = query[:60]
        logger.info(f"  [{i}/{len(high_score)}] {title_short}...")
        results = tavily_search(query, days=TAVILY_DAYS, max_results=5)
        article["corroboration"] = [
            r for r in results
            if r.get("url") != url and r.get("tavily_score", 0.0) >= 0.8
        ][:4]

    for article in articles:
        article["enriched"] = True

    logger.info(f"Step 3 complete")
    return articles
