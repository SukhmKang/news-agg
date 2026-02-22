"""
Steps 4 + 5 — Report writing and output.

Claude reads the week's enriched articles and writes a structured markdown
report grouped by category. Articles scoring 4–5 receive full write-ups with
BD actionability notes; articles scoring 3 receive lighter treatment.
The finished report is saved to the reports/ directory.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import MODEL_REPORT, REPORTS_DIR
from utils import get_anthropic_client

logger = logging.getLogger(__name__)

CATEGORY_ORDER = [
    ("market_entry", "Market Entry & Regional HQ Announcements"),
    ("swf_outbound", "SWF & State Capital Flows"),
    ("pr_policy_risk", "Policy & PR Risk Watch"),
]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _format_article(article: Dict) -> str:
    """Render a single article's data block for the Claude prompt."""
    score = article.get("score", 0)
    lines = [
        f"**Title:** {article.get('title', '')}",
        f"**URL:** {article.get('url', '')}",
        f"**Score:** {score}/5 — {article.get('score_reason', '')}",
    ]

    content = (article.get("full_text") or article.get("snippet", "")).strip()
    if content:
        lines.append(f"**Content:**\n{content[:3000]}")

    if score >= 4 and article.get("corroboration"):
        corr_lines = [
            f"- {c['title']} ({c['url']}): {c.get('snippet', '')[:200]}"
            for c in article["corroboration"][:3]
        ]
        lines.append(f"**Corroboration:**\n" + "\n".join(corr_lines))

    return "\n".join(lines)


def _build_report_prompt(
    articles_by_category: Dict[str, List[Dict]],
    client_articles: List[Dict],
    week_end: str,
) -> str:
    section_blocks: List[str] = []

    for cat_key, cat_label in CATEGORY_ORDER:
        cat_articles = articles_by_category.get(cat_key, [])
        if not cat_articles:
            continue
        entries = "\n\n---\n\n".join(_format_article(a) for a in cat_articles)
        section_blocks.append(f"=== {cat_label} ===\n\n{entries}")

    if client_articles:
        entries = "\n\n---\n\n".join(
            f"[Clients mentioned: {', '.join(a.get('client_match', []))}]\n{_format_article(a)}"
            for a in client_articles
        )
        section_blocks.append(f"=== Client Intelligence ===\n\n{entries}")

    articles_block = "\n\n\n".join(section_blocks) if section_blocks else "No articles found this week."

    return f"""You are writing a weekly MENA Business Development Intelligence Report for a BD consultancy team.

Write in clear, professional prose. Every section should help a BD team member understand what happened and why it matters for pitching or client development.

=== REPORT FORMAT (output valid GitHub-flavoured markdown) ===

# MENA BD Intelligence — Week Ending {week_end}

## Executive Summary
(3–5 bullet points of the week's most significant developments)

## Market Entry & Regional HQ Announcements
(Foreign companies entering MENA or establishing regional HQ)

## SWF & State Capital Flows
(MENA sovereign wealth and state-entity outbound investments)

## Policy & PR Risk Watch
(Foreign companies facing regulatory friction or reputational trouble in the region)

## Client Intelligence
(Only if relevant articles exist; omit this section entirely otherwise)

=== WRITING RULES ===
- Articles scoring 4–5: write a full paragraph per story — what happened, who the key actors are, and a "**BD note:**" sentence explaining why this matters for pitching.
- Articles scoring 3: write 2–3 sentences summarising the development only.
- If a section has no articles, omit it entirely from the output.
- Do not invent or extrapolate details not present in the source material.
- Render source URLs as inline markdown hyperlinks using the article title as anchor text.
- Week ending: {week_end}

=== SOURCE ARTICLES ===

{articles_block}"""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def write_report(articles: List[Dict], week_end_date: Optional[str] = None) -> str:
    """
    Steps 4 + 5: Generate the weekly markdown report and save it to disk.

    Args:
        articles:       Enriched articles for the reporting week.
        week_end_date:  ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Filepath of the saved report.
    """
    if not week_end_date:
        week_end_date = datetime.now(timezone.utc).date().isoformat()

    logger.info(f"Step 4 — Writing report for week ending {week_end_date} ({len(articles)} articles)...")

    # Group articles by category; sort each group so 4-5 scores lead
    articles_by_category: Dict[str, List[Dict]] = {k: [] for k, _ in CATEGORY_ORDER}
    client_articles: List[Dict] = []

    for article in articles:
        cat = article.get("category", "none")
        if cat in articles_by_category:
            articles_by_category[cat].append(article)
        if article.get("client_match"):
            client_articles.append(article)

    for cat in articles_by_category:
        articles_by_category[cat].sort(key=lambda a: a.get("score", 0), reverse=True)

    prompt = _build_report_prompt(articles_by_category, client_articles, week_end_date)

    client = get_anthropic_client()
    response = client.messages.create(
        model=MODEL_REPORT,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    report_md = response.content[0].text.strip()

    # Step 5: persist to disk
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"weekly_report_{week_end_date}.md"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w") as f:
        f.write(report_md)

    logger.info(f"Step 5 — Report saved to {filepath}")
    return filepath
