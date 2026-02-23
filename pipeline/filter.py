"""
Step 2 — Stage 1 filtering.

Claude scores every article 1–5 on relevance and actionability against the
brief. Articles below the configured threshold are dropped. Each surviving
article has its score, one-line reason, category, and any client matches
written back onto the dict.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from config import FILTER_BATCH_SIZE, FILTER_MAX_WORKERS, MENA_KEYWORDS, MODEL_FILTER, SCORE_THRESHOLD
from utils import build_url_aliases, get_anthropic_client, get_openai_client, get_client_names, token_tracker

logger = logging.getLogger(__name__)


def _build_scoring_prompt(articles: List[Dict], client_names: List[str], url_to_alias: Dict, openai_mode: bool = False) -> str:
    articles_payload = json.dumps(
        [
            {
                "url": url_to_alias.get(a["url"], a["url"]),
                "title": a.get("title", ""),
                "snippet": a.get("snippet", "")[:200],
                "source": a.get("source", ""),
            }
            for a in articles
        ],
        indent=2,
    )

    clients_str = ", ".join(client_names) if client_names else "None"

    return f"""You are a senior analyst for a business development consultancy focused on the UAE and Saudi Arabia.

Score each article 1–5 on relevance and actionability for our BD team.

=== GEOGRAPHIC PRIORITY ===
Primary markets: UAE (Dubai, Abu Dhabi) and Saudi Arabia (Riyadh, Jeddah, NEOM).
Secondary markets: broader GCC (Qatar, Kuwait, Bahrain, Oman) and wider MENA.
- Articles exclusively about secondary/broader MENA markets are capped at score 3 unless they involve a named UAE or Saudi actor, capital flow, or direct strategic implication for our primary markets.

=== INCLUDE (score 3–5) ===
- Foreign (primarily Western) companies publicly announcing entry into UAE or Saudi Arabia, or establishing a regional headquarters there
- UAE or Saudi sovereign wealth funds or state-owned entities (PIF, Mubadala, ADIA, ADQ, Aramco, ADNOC, DP World, etc.) investing capital outside the region; intergovernmental agreements that result in investments
- Foreign companies facing policy obstacles or requiring PR assistance following public fallout in UAE or Saudi Arabia
- Big-picture Saudi or UAE strategic positioning relevant to market entry or capital flows

=== EXCLUDE (score 1–2) ===
- Bond, stock, or equities market news
- Partnership or MOU announcements between companies
- Executive appointments or resignations
- Financial performance disclosures or earnings reports
- Overly technical Saudi regulatory filings
- Government-corporate meetings with no investment outcome
- News exclusively about non-GCC MENA countries (Egypt, Jordan, Iraq, Morocco, etc.) with no UAE or Saudi angle

=== SCORING GUIDE ===
5 — Directly actionable: names a specific company, UAE or Saudi target market, and either a concrete capital deployment or a clearly defined problem. A BD team member could cite this in a pitch next week.
4 — Strong signal: clearly fits one of the three categories above with named actors, meaningful detail, and a UAE or Saudi focus.
3 — Moderate signal: relevant territory but lacks specificity; or a strong signal about a secondary GCC/MENA market with no direct UAE/Saudi angle.
2 — Weak: loosely MENA business news, not BD-relevant.
1 — Not relevant: falls squarely into the exclusion list.

=== CATEGORIES ===
Use one of: "market_entry", "swf_outbound", "pr_policy_risk", "none"

=== CLIENT MONITORING ===
If any of the following names appear in the article, list them in client_match: {clients_str}

=== ARTICLES TO SCORE ===
{articles_payload}

Return ONLY a valid JSON object with a single key "results" containing the array — no explanation, no markdown — one object per article in the same order:
{{"results": [{{"url": "...", "score": 4, "reason": "one sentence max", "category": "market_entry", "client_match": []}}]}}""" if openai_mode else \
"""
Return ONLY a valid JSON array — no explanation, no markdown — one object per article in the same order:
[{{"url": "...", "score": 4, "reason": "one sentence max", "category": "market_entry", "client_match": []}}]"""


def _score_batch(batch: List[Dict], client_names: List[str], client) -> List[Dict]:
    """Score one batch of articles via a single model call. Returns the batch with scores applied."""
    is_openai = MODEL_FILTER.startswith("gpt-")
    url_to_alias, alias_to_url = build_url_aliases([a["url"] for a in batch])
    prompt = _build_scoring_prompt(batch, client_names, url_to_alias, openai_mode=is_openai)

    if is_openai:
        response = client.chat.completions.create(
            model=MODEL_FILTER,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8096,
            response_format={"type": "json_object"},
        )
        token_tracker.track(MODEL_FILTER, response.usage.prompt_tokens, response.usage.completion_tokens)
        text = response.choices[0].message.content.strip()
        parsed = json.loads(text)
        results = parsed.get("results", [])
    else:
        response = client.messages.create(
            model=MODEL_FILTER,
            max_tokens=8096,
            messages=[{"role": "user", "content": prompt}],
        )
        token_tracker.track(MODEL_FILTER, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"Claude scoring response was truncated (max_tokens reached) on a batch of "
                f"{len(batch)} articles. Reduce FILTER_BATCH_SIZE in config.py."
            )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        results = json.loads(text)

    # Restore real URLs from aliases before building the score map
    score_map = {
        alias_to_url.get(r["url"], r["url"]): r
        for r in results if isinstance(r, dict) and "url" in r
    }

    for article in batch:
        scored = score_map.get(article["url"], {})
        article["score"] = scored.get("score", 1)
        article["score_reason"] = scored.get("reason", "")
        article["category"] = scored.get("category", "none")
        article["client_match"] = scored.get("client_match", [])

    return batch


def run_filter(articles: List[Dict]) -> List[Dict]:
    """
    Step 2: Score all articles and return only those at or above SCORE_THRESHOLD.

    Args:
        articles: Unscored articles from Steps 1a + 1b.

    Returns:
        Articles with score >= SCORE_THRESHOLD, each carrying score, reason, category,
        and client_match fields.
    """
    if not articles:
        return []

    # Pre-filter: drop articles with no BD-relevant keyword in title + opening snippet.
    # This avoids paying Claude to score articles that are clearly out of scope.
    _kw_lower = [kw.lower() for kw in MENA_KEYWORDS]
    def _passes_prefilter(a: Dict) -> bool:
        text = (a.get("title", "") + " " + a.get("snippet", "")[:200]).lower()
        return any(kw in text for kw in _kw_lower)

    pre_filtered = [a for a in articles if _passes_prefilter(a)]
    dropped_pre = len(articles) - len(pre_filtered)
    if dropped_pre:
        logger.info(f"  Pre-filter: dropped {dropped_pre}/{len(articles)} articles with no BD-relevant keywords")
    articles = pre_filtered

    if not articles:
        logger.info("Step 2: no articles remain after pre-filter")
        return []

    client = get_openai_client() if MODEL_FILTER.startswith("gpt-") else get_anthropic_client()
    client_names = get_client_names()

    batches = [articles[i : i + FILTER_BATCH_SIZE] for i in range(0, len(articles), FILTER_BATCH_SIZE)]
    total_batches = len(batches)
    logger.info(
        f"Step 2 — Scoring {len(articles)} articles in {total_batches} batches "
        f"of {FILTER_BATCH_SIZE} ({FILTER_MAX_WORKERS} workers)..."
    )

    # Score all batches in parallel; preserve original order via index
    results: List[List[Dict]] = [None] * total_batches

    with ThreadPoolExecutor(max_workers=FILTER_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_score_batch, batch, client_names, client): idx
            for idx, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()  # re-raises any exception from the thread
            logger.info(f"  Batch {idx + 1}/{total_batches} complete")

    scored = [article for batch in results for article in batch]
    passing = [a for a in scored if (a.get("score") or 0) >= SCORE_THRESHOLD]
    dropped = len(scored) - len(passing)
    logger.info(
        f"Step 2 complete: {len(passing)} articles pass (score ≥ {SCORE_THRESHOLD}), {dropped} dropped"
    )

    return passing
