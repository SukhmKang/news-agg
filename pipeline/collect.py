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

from config import ARTICLE_DAYS_WINDOW, GOOGLE_NEWS_QUERIES, LOG_COLLECTED_TITLES, MAX_ARTICLES_PER_FEED, MENA_KEYWORDS, RSS_FEEDS, TAVILY_DAYS, TAVILY_MAX_RESULTS, TAVILY_STATIC_QUERIES
from utils import is_within_window, load_clients, tavily_search

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
    skipped_existing = 0
    for entry in feed.entries:
        link = entry.get("link", "") or entry.get("id", "")
        if not link:
            continue
        if link in existing_urls:
            skipped_existing += 1
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

    # Sort newest-first by pub_date; articles with no date go to the end.
    new_articles.sort(key=lambda a: a["pub_date"] or "", reverse=True)

    if len(new_articles) > MAX_ARTICLES_PER_FEED:
        new_articles = new_articles[:MAX_ARTICLES_PER_FEED]
        logger.info(f"  {source}: {len(new_articles)} new articles (capped at {MAX_ARTICLES_PER_FEED}), {skipped_existing} skipped (already in store)")
    else:
        logger.info(f"  {source}: {len(new_articles)} new articles, {skipped_existing} skipped (already in store)")
    if LOG_COLLECTED_TITLES and new_articles:
        for a in new_articles:
            logger.info(f"    | {a['title']}")
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


def run_tavily_collection(existing_urls: set) -> List[Dict]:
    """
    Step 1b: Run static Tavily queries + per-client queries and return new articles.

    Static queries target the three BD categories (market entry, SWF outbound,
    PR/policy risk). Client queries surface any news connecting known clients to
    the UAE/Saudi/MENA region.

    Args:
        existing_urls: Set of URLs already in the article store; updated in place.

    Returns:
        List of new article dicts (not yet scored or enriched).
    """
    run_date = datetime.now(timezone.utc).date().isoformat()

    # Build client queries: two per client using the primary name
    client_queries: List[str] = []
    for c in load_clients():
        name = c["name"]
        client_queries.append(f"{name} UAE OR Saudi Arabia OR MENA OR Gulf")
        client_queries.append(f"{name} Middle East")

    all_queries = TAVILY_STATIC_QUERIES + client_queries
    logger.info(
        f"Step 1b — {len(TAVILY_STATIC_QUERIES)} static + {len(client_queries)} client "
        f"Tavily queries ({len(all_queries)} total):"
    )

    new_articles: List[Dict] = []
    for query in all_queries:
        results = tavily_search(query, days=TAVILY_DAYS, max_results=TAVILY_MAX_RESULTS)
        added = 0
        skipped = 0
        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            if url in existing_urls:
                skipped += 1
                logger.debug(f"  Skipped (already in store): {url}")
                continue
            existing_urls.add(url)
            new_articles.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", "")[:1000],
                "source": r.get("source", "tavily"),
                "pub_date": r.get("pub_date"),
                "score": None,
                "score_reason": None,
                "category": None,
                "client_match": [],
                "full_text": None,
                "corroboration": [],
                "enriched": False,
                "run_date": run_date,
            })
            added += 1
        logger.info(f"  [{added} new, {skipped} skipped] {query}")

    logger.info(f"Step 1b complete: {len(new_articles)} new articles from Tavily")
    return new_articles
