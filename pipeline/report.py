"""
Steps 4 + 5 — Report writing and output.

Architecture:
- One Claude/GPT call per category batch (score 4+ articles, max REPORT_BATCH_SIZE each).
  If a category exceeds the batch size it is split; the sub-drafts are merged in one
  additional call. This ensures no articles are dropped regardless of volume.
- One call for client intelligence (all articles with a client_match, score 3+).
- One synthesizer call that reads all section texts and writes the header + executive summary.
- Deterministic markdown appendix for score 3 articles — no AI.

Switch between Claude and GPT by changing MODEL_REPORT in config.py.
"""

import logging
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import CATEGORY_ORDER, MODEL_REPORT_BATCH, MODEL_REPORT_SYNTH, REPORT_BATCH_SIZE, REPORT_MIN_SCORE, REPORTS_DIR
from utils import build_url_aliases, get_anthropic_client, get_openai_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model-agnostic call
# ---------------------------------------------------------------------------

def _call_model(prompt: str, model: str, client, max_tokens: int = 4096) -> str:
    """Call Claude or GPT — provider detected from model name."""
    if model.startswith("gpt-") or model.startswith("o"):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    else:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Article formatting
# ---------------------------------------------------------------------------

def _format_article_block(article: Dict, url_to_alias: Dict) -> str:
    """Render one article's data block for a model prompt, using URL aliases."""
    score = article.get("score", 0)
    real_url = article.get("url", "")
    alias = url_to_alias.get(real_url, real_url)
    pub_date = article.get("pub_date") or article.get("run_date", "")
    lines = [
        f"**Title:** {article.get('title', '')}",
        f"**URL:** {alias}",
        f"**Date:** {pub_date}",
        f"**Score:** {score}/5 — {article.get('score_reason', '')}",
    ]
    content = (article.get("full_text") or article.get("snippet", "")).strip()
    if content:
        lines.append(f"**Content:**\n{content[:1500]}")
    if score >= 4 and article.get("corroboration"):
        corr_lines = [
            f"- {c['title']} ({url_to_alias.get(c['url'], c['url'])}, {c.get('pub_date') or ''}): {c.get('snippet', '')[:200]}"
            for c in article["corroboration"][:3]
        ]
        lines.append("**Corroboration:**\n" + "\n".join(corr_lines))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Category section writing (with recursive batching)
# ---------------------------------------------------------------------------

def _restore_urls(text: str, alias_to_url: Dict) -> str:
    """Replace all REFxxx aliases in model output with real URLs."""
    for alias, url in alias_to_url.items():
        text = text.replace(alias, url)
    return text


def _write_section_batch(cat_label: str, articles: List[Dict], week_end: str, url_to_alias: Dict, alias_to_url: Dict, client) -> str:
    """Single model call for one batch of articles within a category."""
    entries = "\n\n---\n\n".join(_format_article_block(a, url_to_alias) for a in articles)

    prompt = f"""You are writing part of a section called "{cat_label}" in a weekly MENA Business Development Intelligence Report.

Week ending: {week_end}

=== WRITING RULES ===
- Output markdown starting with the section articles directly — no section header, no preamble.
- Write each story as a single bullet point (starting with "-").
- Each bullet: one or two concise sentences covering what happened and who the key actors are, followed by a "**BD note:**" sentence explaining why it matters for pitching.
- End each bullet with the source citation(s) as inline markdown hyperlinks in parentheses, including the publication date: e.g. ([Reuters](URL), 14 Feb 2025) or ([Reuters](URL1), 14 Feb 2025; [FT](URL2), 15 Feb 2025).
- If multiple articles cover the same underlying event, write ONE consolidated bullet and list all source URLs in the citation.
- Do not invent or extrapolate details not present in the source material.
- Escape all dollar signs as \$ (e.g. \$1.25tn, \$3bn) to avoid markdown math rendering.

=== ARTICLES ===
{entries}"""

    return _restore_urls(_call_model(prompt, MODEL_REPORT_BATCH, client), alias_to_url)


def _merge_section_drafts(cat_label: str, drafts: List[str], client) -> str:
    """Merge multiple sub-batch drafts into one coherent section."""
    combined = "\n\n---\n\n".join(drafts)

    prompt = f"""You are finalising the "{cat_label}" section of a weekly MENA Business Development Intelligence Report.

The section was drafted in {len(drafts)} batches. Merge them into a single, coherent markdown section.

=== RULES ===
- Start with "## {cat_label}"
- Remove any duplicate stories that appear across batches — keep the best-written version and merge sources.
- Preserve all BD notes.
- Do not add new information not present in the drafts.

=== DRAFTS ===
{combined}"""

    return _call_model(prompt, MODEL_REPORT_SYNTH, client)


def _write_category_section(cat_label: str, articles: List[Dict], week_end: str, url_to_alias: Dict, alias_to_url: Dict, client) -> str:
    """Write one category section, splitting into batches if needed."""
    if not articles:
        return ""

    if len(articles) <= REPORT_BATCH_SIZE:
        body = _write_section_batch(cat_label, articles, week_end, url_to_alias, alias_to_url, client)
        return f"## {cat_label}\n\n{body}"

    batches = [articles[i:i + REPORT_BATCH_SIZE] for i in range(0, len(articles), REPORT_BATCH_SIZE)]
    n_batches = len(batches)
    logger.info(f"    → {len(articles)} articles split into {n_batches} sub-batches")

    drafts = []
    for idx, batch in enumerate(batches, 1):
        logger.info(f"      Sub-batch {idx}/{n_batches} ({len(batch)} articles)...")
        drafts.append(_write_section_batch(cat_label, batch, week_end, url_to_alias, alias_to_url, client))

    logger.info(f"      Merging {n_batches} sub-batches...")
    return _merge_section_drafts(cat_label, drafts, client)


# ---------------------------------------------------------------------------
# Client intelligence section
# ---------------------------------------------------------------------------

def _write_client_section(client_articles: List[Dict], week_end: str, url_to_alias: Dict, alias_to_url: Dict, client) -> str:
    """One model call for all articles with a client_match (score 3+)."""
    if not client_articles:
        return ""

    entries = "\n\n---\n\n".join(
        f"[Clients mentioned: {', '.join(a.get('client_match', []))}]\n{_format_article_block(a, url_to_alias)}"
        for a in client_articles
    )

    prompt = f"""You are writing the Client Intelligence section of a weekly MENA Business Development Intelligence Report.

Week ending: {week_end}

=== WRITING RULES ===
- Output a markdown section starting with "## Client Intelligence"
- Write each client/story as a single bullet point (starting with "-").
- Each bullet: one or two concise sentences identifying which client(s) are referenced and what the development means for that client relationship or for pitching to similar companies in the region, followed by an "**Action flag:**" sentence suggesting a concrete next step.
- End each bullet with the source citation(s) as inline markdown hyperlinks in parentheses, including the publication date: e.g. ([Reuters](URL), 14 Feb 2025).
- If the same client appears in multiple articles, consolidate into one bullet per client and list all source URLs in the citation.
- Focus on: how the client's MENA presence is evolving, any risks or opportunities, and what our BD team should know.
- Escape all dollar signs as \$ (e.g. \$1.25tn, \$3bn) to avoid markdown math rendering.

=== ARTICLES ===
{entries}"""

    return _restore_urls(_call_model(prompt, MODEL_REPORT_SYNTH, client), alias_to_url)


# ---------------------------------------------------------------------------
# Executive summary (synthesizer)
# ---------------------------------------------------------------------------

def _write_executive_summary(section_texts: List[str], week_end: str, client) -> str:
    """Reads all written sections and outputs the report header + executive summary only."""
    combined = "\n\n".join(t for t in section_texts if t)

    prompt = f"""You have read the full MENA BD Intelligence Report for the week ending {week_end}.

Based on the sections below, write exactly two things:
1. A markdown H1 header: "# MENA BD Intelligence — Week Ending {week_end}"
2. A "## Executive Summary" section with 3–5 bullet points covering the week's most significant BD-relevant developments. Each bullet should be one punchy sentence naming the key actor and the development.

Return ONLY the H1 header and the Executive Summary — nothing else.

=== REPORT SECTIONS ===
{combined}"""

    return _call_model(prompt, MODEL_REPORT_SYNTH, client, max_tokens=1024)


# ---------------------------------------------------------------------------
# Deterministic score 3 appendix
# ---------------------------------------------------------------------------

def _write_score3_appendix(articles_by_category: Dict[str, List[Dict]]) -> str:
    """Pure deterministic markdown for score 3 articles — no AI."""
    lines = ["## Appendix — Moderate Signals (Score 3)", ""]
    has_content = False

    for cat_key, cat_label in CATEGORY_ORDER:
        cat_articles = [a for a in articles_by_category.get(cat_key, []) if a.get("score") == 3]
        if not cat_articles:
            continue
        has_content = True
        lines.append(f"### {cat_label}")
        lines.append("")
        for a in cat_articles:
            title = a.get("title", "Untitled")
            url = a.get("url", "")
            reason = a.get("score_reason", "")
            pub_date = a.get("pub_date") or a.get("run_date", "")
            link = f"[{title}]({url})" if url else title
            date_str = f" ({pub_date})" if pub_date else ""
            lines.append(f"- {link}{date_str} — {reason}")
        lines.append("")

    return "\n".join(lines) if has_content else ""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def write_report(articles: List[Dict], week_end_date: Optional[str] = None) -> str:
    """
    Steps 4 + 5: Generate the weekly markdown report and save it to disk.

    Args:
        articles:       Enriched articles for the reporting week (all scores).
        week_end_date:  ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Filepath of the saved report.
    """
    if not week_end_date:
        week_end_date = datetime.now(timezone.utc).date().isoformat()

    # Split into 4+ (AI sections) and all (for appendix + client monitoring)
    high_articles = [a for a in articles if (a.get("score") or 0) >= REPORT_MIN_SCORE]
    score3_articles = [a for a in articles if (a.get("score") or 0) == 3]

    # Group 4+ articles by category, sorted best-first
    articles_by_category: Dict[str, List[Dict]] = {k: [] for k, _ in CATEGORY_ORDER}
    for article in high_articles:
        cat = article.get("category", "none")
        if cat in articles_by_category:
            articles_by_category[cat].append(article)
    for cat in articles_by_category:
        articles_by_category[cat].sort(key=lambda a: a.get("score", 0), reverse=True)

    # Group all articles by category for score 3 appendix
    all_by_category: Dict[str, List[Dict]] = {k: [] for k, _ in CATEGORY_ORDER}
    for article in articles:
        cat = article.get("category", "none")
        if cat in all_by_category:
            all_by_category[cat].append(article)

    # Client articles: score 3+ with any client_match
    client_articles = [a for a in articles if a.get("client_match")]

    total_high = sum(len(v) for v in articles_by_category.values())
    logger.info(
        f"Step 4 — Writing report for week ending {week_end_date} "
        f"(batch={MODEL_REPORT_BATCH}, synth={MODEL_REPORT_SYNTH}) "
        f"({total_high} articles score 4+, {len(score3_articles)} score 3 in appendix, "
        f"{len(client_articles)} client articles)..."
    )

    # Both models are OpenAI if they start with "gpt-" / "o"; otherwise Anthropic.
    # For simplicity, use OpenAI client if either model is OpenAI.
    use_openai = MODEL_REPORT_BATCH.startswith("gpt-") or MODEL_REPORT_SYNTH.startswith("gpt-") \
                 or MODEL_REPORT_BATCH.startswith("o") or MODEL_REPORT_SYNTH.startswith("o")
    model_client = get_openai_client() if use_openai else get_anthropic_client()

    # Build a single alias map for ALL article URLs across the entire report
    all_report_articles = high_articles + client_articles
    all_urls = list({a["url"] for a in all_report_articles}
                    | {c["url"] for a in all_report_articles for c in a.get("corroboration", [])})
    url_to_alias, alias_to_url = build_url_aliases(all_urls)
    logger.info(f"  Built URL alias map for {len(all_urls)} unique URLs")

    section_texts: List[str] = []

    # Category sections
    for cat_key, cat_label in CATEGORY_ORDER:
        cat_articles = articles_by_category.get(cat_key, [])
        n_batches = max(1, math.ceil(len(cat_articles) / REPORT_BATCH_SIZE))
        logger.info(f"  {cat_label}: {len(cat_articles)} articles → {n_batches} batch(es)...")
        text = _write_category_section(cat_label, cat_articles, week_end_date, url_to_alias, alias_to_url, model_client)
        section_texts.append(text)

    # Client intelligence
    logger.info(f"  Client Intelligence: {len(client_articles)} articles...")
    client_section = _write_client_section(client_articles, week_end_date, url_to_alias, alias_to_url, model_client)
    section_texts.append(client_section)

    # Executive summary
    logger.info(f"  Synthesizer: executive summary...")
    header_and_summary = _write_executive_summary(section_texts, week_end_date, model_client)

    # Deterministic appendix
    appendix = _write_score3_appendix(all_by_category)

    # Stitch together
    parts = [header_and_summary]
    parts.extend(t for t in section_texts if t)
    if appendix:
        parts.append(appendix)
    report_md = "\n\n".join(parts)

    # Save
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"weekly_report_{week_end_date}.md"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w") as f:
        f.write(report_md)

    logger.info(f"Step 5 — Report saved to {filepath}")
    return filepath
