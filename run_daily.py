#!/usr/bin/env python3
"""
Daily pipeline runner — Steps 1a, 1b, 2, 3.

Collects, scores, and enriches articles, then appends the survivors to the
local article store. Safe to run multiple times per day; already-seen URLs
are skipped.

Usage:
    python run_daily.py
"""

import logging
import os
import sys

from utils import load_articles, save_articles
from pipeline.collect import run_collection, run_tavily_collection
from pipeline.dedup import deduplicate_articles
from pipeline.filter import run_filter
from pipeline.enrich import run_enrichment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _check_env() -> None:
    """Fail fast if required API keys are missing."""
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        missing.append("ANTHROPIC_API_KEY")
    if not os.getenv("TAVILY_API_KEYS", "").strip() and not os.getenv("TAVILY_API_KEY", "").strip():
        missing.append("TAVILY_API_KEYS (or TAVILY_API_KEY)")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )


def run() -> None:
    _check_env()
    logger.info("=== Daily pipeline starting ===")

    # Load existing store and build a URL set for deduplication
    existing = load_articles()
    existing_urls = {a["url"] for a in existing}
    logger.info(f"Loaded {len(existing)} existing articles from store")

    # Step 1a: RSS + Google News RSS collection
    rss_articles = run_collection(existing_urls)

    # Step 1b: static Tavily queries + client queries
    tavily_articles = run_tavily_collection(existing_urls)

    new_articles = rss_articles + tavily_articles
    if not new_articles:
        logger.info("No new articles found — nothing to do")
        return

    logger.info(f"Total new candidates: {len(new_articles)} ({len(rss_articles)} RSS, {len(tavily_articles)} Tavily)")

    # Step 1c: semantic deduplication — merge near-identical stories
    new_articles = deduplicate_articles(new_articles)

    # Step 2: keyword pre-filter + Claude relevance scoring; drop below threshold
    passing = run_filter(new_articles)
    if not passing:
        logger.info("No articles passed filtering — nothing to store")
        return

    # Step 3: full-text fetch + corroboration
    enriched = run_enrichment(passing)

    # Persist
    updated = existing + enriched
    save_articles(updated)

    logger.info(
        f"=== Daily pipeline complete: {len(enriched)} articles added, "
        f"{len(updated)} total in store ==="
    )


if __name__ == "__main__":
    run()
