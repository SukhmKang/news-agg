"""
Step 1a — Static collection.

Fetches all configured RSS feeds and Google News RSS queries, filters to the
last 7 days by pubDate, deduplicates against the existing article store, and
returns a list of new article dicts ready for downstream processing.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List
from urllib.parse import urlencode

import feedparser

from config import ARTICLE_DAYS_WINDOW, GOOGLE_NEWS_QUERIES, MENA_KEYWORDS, RSS_FEEDS
from utils import is_within_window

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def _parse_entry(entry: dict, source_name: str) -> Dict:
    """Convert a feedparser entry into our standard article dict."""
    pub_date = None
    if getattr(entry, "published_parsed", None):
        try:
            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception as e:
            logger.warning(f"Could not parse date for '{entry.get('title', 'unknown')}': {e}")

    snippet = ""
    if getattr(entry, "summary", None):
        snippet = entry.summary
    elif getattr(entry, "description", None):
        snippet = entry.description

    return {
        "url": entry.get("link", "") or entry.get("id", ""),
        "title": entry.get("title", ""),
        "snippet": _strip_html(snippet)[:1000],
        "source": source_name,
        "pub_date": pub_date,
        # Fields populated by later pipeline steps
        "score": None,
        "score_reason": None,
        "category": None,
        "client_match": [],
        "full_text": None,
        "corroboration": [],
        "enriched": False,
        "run_date": datetime.now(timezone.utc).date().isoformat(),
    }


def _passes_keyword_filter(title: str, keywords: List[str]) -> bool:
    """Return True if the title contains at least one keyword (case-insensitive)."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def _fetch_feed(
    url: str, source: str, existing_urls: set, keywords: List[str] = None
) -> List[Dict]:
    """Fetch one RSS feed and return new articles within the time window.

    Args:
        keywords: If provided, only articles whose title matches at least one
                  keyword are kept. Pass None for full-feed pulls.
    """
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.warning(f"Failed to fetch feed {url}: {e}")
        return []

    new_articles = []
    for entry in feed.entries:
        link = entry.get("link", "") or entry.get("id", "")
        if not link or link in existing_urls:
            continue

        article = _parse_entry(entry, source)
        if not article["url"]:
            continue

        if article["pub_date"] and not is_within_window(article["pub_date"], ARTICLE_DAYS_WINDOW):
            continue

        if keywords and not _passes_keyword_filter(article["title"], keywords):
            continue

        existing_urls.add(link)
        new_articles.append(article)

    logger.info(f"  {source}: {len(new_articles)} new articles")
    return new_articles


def _google_news_rss_url(site: str, terms: str) -> str:
    """Build a Google News RSS URL combining a site: filter, search terms, and a 7-day window."""
    params = {
        "q": f"site:{site} {terms} when:7d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"https://news.google.com/rss/search?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_collection(existing_urls: set) -> List[Dict]:
    """
    Step 1a: Pull from all RSS feeds and Google News RSS queries.

    Args:
        existing_urls: Set of URLs already in the article store; updated in place.

    Returns:
        List of new article dicts (not yet scored or enriched).
    """
    all_articles: List[Dict] = []

    keyword_map = {"MENA_KEYWORDS": MENA_KEYWORDS}

    logger.info("Step 1a — Full RSS feeds (regionally focused):")
    for label, feed_url, kw_ref in RSS_FEEDS:
        keywords = keyword_map.get(kw_ref) if kw_ref else None
        all_articles.extend(_fetch_feed(feed_url, label, existing_urls, keywords=keywords))

    logger.info(f"Step 1a — Google News RSS ({len(GOOGLE_NEWS_QUERIES)} targeted queries):")
    for label, site, terms in GOOGLE_NEWS_QUERIES:
        url = _google_news_rss_url(site, terms)
        all_articles.extend(_fetch_feed(url, label, existing_urls))

    logger.info(f"Step 1a complete: {len(all_articles)} new articles collected")
    return all_articles
