# User Guide

## Pipeline overview

Each daily run (`run_daily.py`) processes articles through five steps:

```
1a. RSS + Google News collection
1b. Tavily static + client queries
1c. Semantic deduplication
 2. Keyword pre-filter → GPT-4o scoring (1–5)
 3. Tavily corroboration (score 4–5 only)
    → saved to data/articles.json
```

The weekly report (`run_weekly.py`) reads the last 7 days of saved articles and makes five AI calls:

```
- One call per category section (market entry, SWF flows, PR risk)
- One client intelligence section
- One executive summary synthesis
→ saved to reports/weekly_report_YYYY-MM-DD.md
```

---

## Scoring rubric (1–5)

| Score | Meaning |
|---|---|
| 5 | Directly actionable: named company entering UAE/Saudi, named SWF deal, concrete BD hook |
| 4 | Strong signal: regional expansion, policy change with clear BD implication |
| 3 | Background context: relevant but no immediate action — goes to report appendix |
| 2 | Tangential: loosely MENA-related, limited BD relevance |
| 1 | Irrelevant or out of scope |

Articles scoring below 3 are dropped entirely. Articles scoring 3 appear in the score 3 appendix only. Articles scoring 4–5 appear in the main AI-written sections.

---

## Report structure

```
# Weekly MENA BD Intelligence Report — [date]

## Executive Summary

## Market Entry & Regional HQ Announcements
## SWF & State Capital Flows
## Policy & PR Risk Watch

## Client Intelligence

## Appendix — Score 3 Articles
```

Each bullet in the main sections follows this format:

> - **[What happened and who].** **BD note:** [Why it matters for pitching]. ([Source](URL), DD Mon YYYY)

---

## Adding or removing news sources

### RSS feeds
Edit the `RSS_FEEDS` list in `config.py`. Format:

```python
("label", "https://example.com/feed", keyword_filter)
```

- Set `keyword_filter = None` to pull the full feed (broad MENA sources)
- Set `keyword_filter = "MENA_KEYWORDS"` to restrict to keyword-matching titles (use for broad sources like Al Jazeera)

### Google News RSS queries
Edit `GOOGLE_NEWS_QUERIES`. Each entry targets one site with one set of search terms and a built-in 7-day window. Multiple entries per site are fine — each is a separate query.

### Static Tavily queries
Edit `TAVILY_STATIC_QUERIES`. These run against Tavily's news search with a 7-day date filter. Keep queries specific enough that most results are BD-relevant.

---

## Managing the client list

`clients.json` (gitignored) drives two things:
1. **Client queries** — two Tavily searches per client at collection time (`[Name] UAE OR Saudi Arabia OR MENA OR Gulf` and `[Name] Middle East`)
2. **Client intelligence section** — articles flagged with a `client_match` appear in the dedicated client section of the report

Format:

```json
[
  {"name": "Acme Corp", "aliases": ["Acme", "ACM"]},
  {"name": "Example Ltd", "aliases": []}
]
```

The `aliases` field is used during scoring to catch alternative names and ticker symbols.

---

## Tuning the pipeline

### Too many irrelevant articles passing scoring
- Tighten `MENA_KEYWORDS` — remove broad terms like "invest" or "launch" if they're pulling noise
- Lower `SCORE_THRESHOLD` from 3 to 2 (unlikely to help) or raise `REPORT_MIN_SCORE` from 4 to 5 to shrink the report

### Too few articles in the report
- Add more queries to `TAVILY_STATIC_QUERIES` or `GOOGLE_NEWS_QUERIES`
- Expand `MENA_KEYWORDS`
- Lower `REPORT_MIN_SCORE` to 3 (score 3 articles will appear in AI sections instead of just the appendix)

### Duplicate stories appearing in the report
- Lower `DEDUP_SIMILARITY_THRESHOLD` (e.g. 85) to merge more aggressively — note this increases the risk of merging genuinely different stories
- The deduplication merges articles by title similarity; the "winning" article gets the others listed as corroboration

### Old articles appearing
- Articles without a `pub_date` fall back to `run_date` for date filtering. This is expected for some sources. The Tavily collection uses `start_date` at query time to limit results to the last 7 days.

### Corroboration looks irrelevant
- Tavily corroboration results are filtered to a minimum relevance score of 0.8 (on Tavily's internal 0–1 scale). Adjust this threshold in `pipeline/enrich.py` if needed.

---

## Logging flags

| Flag | Location | Effect |
|---|---|---|
| `LOG_COLLECTED_TITLES = True` | `config.py` | Logs every collected article title — useful for tuning keyword filters |

Standard log levels:
- `INFO` — normal pipeline progress (articles collected, scores, steps complete)
- `WARNING` — non-fatal issues (feed fetch failures, Tavily timeouts)
- `ERROR` — failures that may affect output quality

---

## Data store

Articles are saved as a flat JSON array in `data/articles.json`. Each article includes:

| Field | Description |
|---|---|
| `url` | Source URL (primary deduplication key) |
| `title` | Article title |
| `snippet` | Lead paragraph / description (≤1000 chars) |
| `pub_date` | Publication date from source (ISO format, may be null for some Tavily results) |
| `run_date` | Date the pipeline collected the article |
| `score` | GPT-4o relevance score (1–5) |
| `score_reason` | One-line explanation of the score |
| `category` | `market_entry`, `swf_outbound`, or `pr_policy_risk` |
| `client_match` | List of matched client names |
| `corroboration` | List of corroborating articles from Tavily (score 4–5 only), each with `tavily_score` |
| `enriched` | `true` once Step 3 has run |

The store is append-only — `run_daily.py` never modifies existing records. To reset, delete or archive `data/articles.json`.
