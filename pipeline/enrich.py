"""
Step 3 — Enrichment.

For all articles scoring 3+, fetches full text via the Jina reader API
(falling back to the article snippet if paywalled or unavailable).

For articles scoring 4–5, also runs one targeted Tavily search per article
to gather corroborating sources and additional context.
"""

import logging
import os
import time
from typing import Dict, List

from config import FULL_TEXT_MAX_CHARS, HIGH_SCORE_THRESHOLD, TAVILY_DAYS
from utils import jina_fetch, tavily_search

logger = logging.getLogger(__name__)

# Free tier: 20 req/min → 3s between calls.
# Authenticated tier: 500 req/min → no meaningful throttle needed.
_JINA_FREE_INTERVAL = 3.0  # seconds between requests when no API key is present


def _jina_has_key() -> bool:
    key = os.getenv("JINA_API_KEY", "").strip()
    return bool(key) and key != "your_key_here"


def _corroboration_query(article: Dict) -> str:
    """Build a Tavily search query for corroborating an article."""
    # The title is the clearest signal; cap length for API safety
    return article.get("title", "")[:200]


def run_enrichment(articles: List[Dict]) -> List[Dict]:
    """
    Step 3: Enrich each article with full text and (for high scorers) corroboration.

    Modifies article dicts in place. Sets `enriched = True` on completion.

    Args:
        articles: Articles that passed Step 2 filtering (score >= SCORE_THRESHOLD).

    Returns:
        The same list with full_text, corroboration, and enriched fields populated.
    """
    if not articles:
        return []

    throttle = not _jina_has_key()
    if throttle:
        logger.info("  No Jina API key — throttling to 20 req/min")

    logger.info(f"Step 3 — Enriching {len(articles)} articles...")

    for i, article in enumerate(articles, 1):
        url = article.get("url", "")
        score = article.get("score", 0)
        title_short = article.get("title", url)[:60]

        logger.info(f"  [{i}/{len(articles)}] {title_short}...")

        # --- Jina full-text fetch (all 3+ articles) ---
        if throttle and i > 1:
            time.sleep(_JINA_FREE_INTERVAL)

        full_text = jina_fetch(url)
        if full_text:
            article["full_text"] = full_text[:FULL_TEXT_MAX_CHARS]
        else:
            # Paywall or fetch failure — fall back to snippet
            article["full_text"] = article.get("snippet", "")
            logger.info(f"    Jina unavailable, using snippet")

        # --- Tavily corroboration (4-5 articles only) ---
        if score >= HIGH_SCORE_THRESHOLD:
            query = _corroboration_query(article)
            logger.info(f"    Corroboration search: {query[:60]}...")
            results = tavily_search(query, days=TAVILY_DAYS, max_results=5)
            # Exclude the article's own URL from corroboration results
            article["corroboration"] = [r for r in results if r.get("url") != url][:4]

        article["enriched"] = True

    logger.info(f"Step 3 complete: {len(articles)} articles enriched")
    return articles
