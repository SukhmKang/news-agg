
## Setup

**Requirements:** Python 3.11, conda or venv

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Multiple Tavily keys (recommended) — rotated round-robin to spread rate limit load
TAVILY_API_KEYS=tvly-key1,tvly-key2,tvly-key3

# Single key fallback (used if TAVILY_API_KEYS is not set)
# TAVILY_API_KEY=tvly-...
```

Create a `clients.json` file (gitignored) listing your tracked clients:

```json
[
  {"name": "Acme Corp", "aliases": ["Acme"]},
  {"name": "Example Ltd", "aliases": []}
]
```

## Running the pipeline

**Daily — collect, score, and enrich new articles:**

```bash
python run_daily.py
```

Safe to run multiple times; already-seen URLs are skipped automatically.

**Weekly — generate the report from the last 7 days of stored articles:**

```bash
python run_weekly.py
```

Output is written to `reports/weekly_report_YYYY-MM-DD.md`.

## Project structure

```
├── run_daily.py          # Daily pipeline runner
├── run_weekly.py         # Weekly report generator
├── config.py             # All configuration (feeds, queries, models, thresholds)
├── utils.py              # Shared helpers (Tavily, OpenAI/Anthropic clients, date utils)
├── pipeline/
│   ├── collect.py        # Step 1: RSS + Google News + Tavily collection
│   ├── dedup.py          # Step 1c: semantic deduplication
│   ├── filter.py         # Step 2: keyword pre-filter + GPT-4o scoring
│   ├── enrich.py         # Step 3: Tavily corroboration for score 4–5 articles
│   └── report.py         # Steps 4–5: markdown report generation
├── data/
│   └── articles.json     # Persistent article store (append-only)
└── reports/              # Generated weekly reports
```

## Key configuration (`config.py`)

| Variable | Default | Description |
|---|---|---|
| `SCORE_THRESHOLD` | 3 | Articles below this score are dropped |
| `REPORT_MIN_SCORE` | 4 | Minimum score for AI-written sections (score 3s go to appendix) |
| `HIGH_SCORE_THRESHOLD` | 4 | Minimum score to trigger Tavily corroboration |
| `ARTICLE_DAYS_WINDOW` | 7 | Days back to accept articles at collection time |
| `MAX_ARTICLES_PER_FEED` | 80 | Cap per RSS/Google News feed (most recent kept) |
| `DEDUP_SIMILARITY_THRESHOLD` | 92 | rapidfuzz similarity threshold (0–100); higher = stricter |
| `MODEL_FILTER` | `gpt-4o` | Scoring model |
| `MODEL_REPORT_BATCH` | `gpt-4o` | Report section writing model |
| `MODEL_REPORT_SYNTH` | `gpt-4.1` | Report synthesis and executive summary model |
