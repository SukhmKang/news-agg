#!/usr/bin/env python3
"""
Weekly report compiler — Steps 4 + 5.

Reads the last 7 days of enriched articles from the local store and
generates a structured markdown report grouped by category.

Usage:
    python run_weekly.py
"""

import logging
import os
import sys
from datetime import datetime, timezone

from utils import load_articles, is_within_window, token_tracker
from pipeline.report import write_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _check_env() -> None:
    missing = [k for k in ["ANTHROPIC_API_KEY"] if not os.getenv(k, "").strip()]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )


def run() -> None:
    _check_env()
    logger.info("=== Weekly report compilation starting ===")

    all_articles = load_articles()
    logger.info(f"Loaded {len(all_articles)} articles from store")

    # Only include enriched articles published (or collected) within the last 7 days
    week_articles = [
        a for a in all_articles
        if a.get("enriched")
        and is_within_window(
            a.get("pub_date") or a.get("run_date", ""),
            days=7,
        )
    ]

    if not week_articles:
        logger.info(
            "No enriched articles found for this week. "
            "Run run_daily.py first to populate the store."
        )
        return

    logger.info(f"Found {len(week_articles)} articles for this week's report")

    week_end = datetime.now(timezone.utc).date().isoformat()
    filepath = write_report(week_articles, week_end_date=week_end)

    logger.info(f"=== Weekly report complete: {filepath} ===")
    logger.info(token_tracker.summary())


if __name__ == "__main__":
    run()
