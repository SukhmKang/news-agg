"""
Step 1b — Dynamic queries.

Claude reads the headlines from Step 1a and generates targeted follow-up
Tavily search queries for stories worth chasing. Results are merged and
deduplicated against the existing article set.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List

from config import (
    DYNAMIC_HEADLINE_BATCH,
    DYNAMIC_MAX_TOTAL_QUERIES,
    DYNAMIC_QUERIES_PER_BATCH,
    MODEL_QUERY_GEN,
    TAVILY_DAYS,
    TAVILY_MAX_RESULTS,
)
from utils import get_anthropic_client, tavily_search

logger = logging.getLogger(__name__)


def _generate_queries_for_batch(headlines: List[str], client) -> List[str]:
    """Ask Claude to generate follow-up Tavily queries for one batch of headlines."""
    headlines_block = "\n".join(f"- {h}" for h in headlines)

    prompt = f"""You are a research assistant for a MENA-focused business development team.

Below are news headlines. Identify the stories most worth following up on and generate targeted search queries to find corroborating articles, additional context, or related developments.

Focus only on stories about:
- Foreign (primarily Western) companies publicly announcing entry into the MENA region or establishing a regional headquarters
- MENA sovereign wealth funds or state-owned entities investing capital outside the region
- Foreign companies facing policy obstacles or requiring PR assistance following public fallout in the MENA region

Generate up to {DYNAMIC_QUERIES_PER_BATCH} search queries. If no headlines are relevant, return an empty array.
Return ONLY a valid JSON array of query strings — no explanation, no markdown, just the JSON array.

Headlines:
{headlines_block}"""

    response = client.messages.create(
        model=MODEL_QUERY_GEN,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if Claude wrapped the JSON
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    if not text:
        raise ValueError("Claude returned an empty response for query generation")
    queries = json.loads(text)
    if isinstance(queries, list):
        return [q for q in queries if isinstance(q, str)][:DYNAMIC_QUERIES_PER_BATCH]
    return []


def run_dynamic_search(collected_articles: List[Dict], existing_urls: set) -> List[Dict]:
    """
    Step 1b: Generate follow-up search queries from Step 1a headlines and run them.

    Args:
        collected_articles: Articles returned by Step 1a.
        existing_urls:      Set of known URLs; updated in place with any new finds.

    Returns:
        List of additional article dicts from Tavily (not yet scored or enriched).
    """
    if not collected_articles:
        logger.info("Step 1b: No articles from Step 1a — skipping dynamic search")
        return []

    headlines = [a["title"] for a in collected_articles if a.get("title")]
    total_batches = (len(headlines) - 1) // DYNAMIC_HEADLINE_BATCH + 1
    logger.info(
        f"Step 1b — {len(headlines)} headlines across {total_batches} batch(es) "
        f"of {DYNAMIC_HEADLINE_BATCH}"
    )

    client = get_anthropic_client()
    all_queries: List[str] = []

    for i in range(0, len(headlines), DYNAMIC_HEADLINE_BATCH):
        batch = headlines[i : i + DYNAMIC_HEADLINE_BATCH]
        batch_num = i // DYNAMIC_HEADLINE_BATCH + 1
        logger.info(f"  Batch {batch_num}/{total_batches} ({len(batch)} headlines)...")
        all_queries.extend(_generate_queries_for_batch(batch, client))

    # Deduplicate and apply global cap
    seen: set = set()
    unique_queries: List[str] = []
    for q in all_queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)
        if len(unique_queries) >= DYNAMIC_MAX_TOTAL_QUERIES:
            break

    if not unique_queries:
        logger.info("Step 1b: No queries generated")
        return []

    logger.info(f"Step 1b — Running {len(unique_queries)} deduplicated Tavily queries:")
    for q in unique_queries:
        logger.info(f"  • {q}")

    run_date = datetime.now(timezone.utc).date().isoformat()
    new_articles: List[Dict] = []

    for query in unique_queries:
        results = tavily_search(query, days=TAVILY_DAYS, max_results=TAVILY_MAX_RESULTS)
        for r in results:
            if r["url"] and r["url"] not in existing_urls:
                existing_urls.add(r["url"])
                # Normalise Tavily result to match our article schema
                new_articles.append({
                    "url": r["url"],
                    "title": r["title"],
                    "snippet": r["snippet"][:1000],
                    "source": r["source"],
                    "pub_date": None,
                    "score": None,
                    "score_reason": None,
                    "category": None,
                    "client_match": [],
                    "full_text": None,
                    "corroboration": [],
                    "enriched": False,
                    "run_date": run_date,
                })

    logger.info(f"Step 1b complete: {len(new_articles)} additional articles from dynamic search")
    return new_articles
