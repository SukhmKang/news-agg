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
from pipeline.collect import run_collection
from pipeline.dynamic_search import run_dynamic_search
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
    required = ["ANTHROPIC_API_KEY", "TAVILY_API_KEY"]
    missing = [k for k in required if not os.getenv(k, "").strip()]
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

    # Step 1a: static RSS + Google News collection
    new_articles = run_collection(existing_urls)

    # Step 1b: Claude-driven dynamic Tavily queries
    dynamic_articles = run_dynamic_search(new_articles, existing_urls)

    all_new = new_articles + dynamic_articles
    if not all_new:
        logger.info("No new articles found — nothing to do")
        return

    logger.info(f"Total new candidates: {len(all_new)}")

    # Step 2: relevance + actionability scoring; drop below threshold
    passing = run_filter(all_new)
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
