import itertools
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Article store
# ---------------------------------------------------------------------------

def load_articles() -> List[Dict]:
    from config import ARTICLES_FILE
    if not os.path.exists(ARTICLES_FILE):
        return []
    with open(ARTICLES_FILE, "r") as f:
        return json.load(f)


def save_articles(articles: List[Dict]) -> None:
    from config import ARTICLES_FILE, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ARTICLES_FILE, "w") as f:
        json.dump(articles, f, indent=2, default=str)


def get_existing_urls() -> set:
    return {a["url"] for a in load_articles()}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def is_within_window(date_str: str, days: int = 7) -> bool:
    """Return True if date_str falls within the last `days` days."""
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return dt >= cutoff
    except Exception:
        # If we cannot parse the date, include the article (fail open)
        return True


# ---------------------------------------------------------------------------
# Client list
# ---------------------------------------------------------------------------

def load_clients() -> List[Dict]:
    if not os.path.exists("clients.json"):
        return []
    with open("clients.json", "r") as f:
        data = json.load(f)
    return data.get("clients", [])


def get_client_names() -> List[str]:
    """Return a flat list of all client names and their aliases."""
    names: List[str] = []
    for client in load_clients():
        names.append(client["name"])
        names.extend(client.get("aliases", []))
    return names


# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------

def build_url_aliases(urls: List[str]) -> tuple:
    """
    Map each URL to a short alias (REF001, REF002, …) for use in prompts.

    Returns:
        (url_to_alias, alias_to_url) — both dicts.
    """
    url_to_alias = {url: f"REF{i + 1:03d}" for i, url in enumerate(urls)}
    alias_to_url = {v: k for k, v in url_to_alias.items()}
    return url_to_alias, alias_to_url


def get_anthropic_client() -> Anthropic:
    return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Token / cost tracking
# ---------------------------------------------------------------------------

class TokenTracker:
    """Accumulates token usage across all model calls in a run.

    Pricing is approximate and should be verified against provider pricing pages.
    """

    # (input $/1M, output $/1M)
    _PRICING = {
        "gpt-4o":            (2.50, 10.00),
        "gpt-4.1":           (2.00,  8.00),
        "claude-haiku-4-5":  (1.00,  5.00),
        "claude-sonnet-4-6": (3.00, 15.00),
    }
    _DEFAULT_PRICING = (3.00, 15.00)

    def __init__(self):
        self._by_model: dict = {}

    def track(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if model not in self._by_model:
            self._by_model[model] = {"input": 0, "output": 0, "calls": 0}
        self._by_model[model]["input"]  += input_tokens
        self._by_model[model]["output"] += output_tokens
        self._by_model[model]["calls"]  += 1

    def summary(self) -> str:
        if not self._by_model:
            return "Token usage: no model calls recorded"
        lines = ["Token usage summary:"]
        total_cost = 0.0
        for model, stats in self._by_model.items():
            price_in, price_out = self._PRICING.get(model, self._DEFAULT_PRICING)
            cost = (stats["input"] * price_in + stats["output"] * price_out) / 1_000_000
            total_cost += cost
            lines.append(
                f"  {model}: {stats['input']:,} in + {stats['output']:,} out "
                f"({stats['calls']} call{'s' if stats['calls'] != 1 else ''}) ≈ ${cost:.4f}"
            )
        lines.append(f"  ── Total estimated cost: ${total_cost:.4f}")
        return "\n".join(lines)


token_tracker = TokenTracker()


def get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _load_tavily_keys() -> List[str]:
    """Load Tavily API keys from env. Supports a comma-separated TAVILY_API_KEYS
    (multiple keys) or falls back to a single TAVILY_API_KEY."""
    multi = os.getenv("TAVILY_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    if not keys:
        single = os.getenv("TAVILY_API_KEY", "").strip()
        if single:
            keys = [single]
    if not keys:
        raise EnvironmentError("No Tavily API key found. Set TAVILY_API_KEYS or TAVILY_API_KEY in .env")
    logger.info(f"Loaded {len(keys)} Tavily API key(s)")
    return keys


_tavily_key_cycle = itertools.cycle(_load_tavily_keys())


def get_tavily_client() -> TavilyClient:
    """Return a TavilyClient using the next key in the round-robin rotation."""
    return TavilyClient(api_key=next(_tavily_key_cycle))


# ---------------------------------------------------------------------------
# External search / fetch helpers
# ---------------------------------------------------------------------------

_TAVILY_TIMEOUT = 15  # seconds before a hanging Tavily query is skipped


def tavily_search(query: str, days: int = 7, max_results: int = 8) -> List[Dict]:
    """Run a Tavily search and return simplified article dicts.

    Skips the query (returns []) if Tavily doesn't respond within _TAVILY_TIMEOUT seconds.
    """
    client = get_tavily_client()
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    def _search():
        return client.search(query=query, topic="news", start_date=start_date, max_results=max_results)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_search)
            response = future.result(timeout=_TAVILY_TIMEOUT)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": "tavily",
                "pub_date": r.get("published_date"),
                "tavily_score": r.get("score", 0.0),
            }
            for r in response.get("results", [])
            if r.get("url")
        ]
    except FuturesTimeoutError:
        logger.warning(f"Tavily search timed out after {_TAVILY_TIMEOUT}s for '{query}' — skipping")
        return []
    except Exception as e:
        logger.warning(f"Tavily search failed for '{query}': {e}")
        return []


