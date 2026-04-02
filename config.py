import os

# ---------------------------------------------------------------------------
# RSS sources
# ---------------------------------------------------------------------------

# RSS feeds.
# Format: (source_label, feed_url, keyword_filter)
# keyword_filter = None  → pull full feed, let Claude handle filtering in Step 2
# keyword_filter = [...]  → only keep articles whose title contains at least one keyword
#                           (case-insensitive). Use for broad sources to cut volume.
RSS_FEEDS = [
    ("arabianbusiness.com", "https://www.arabianbusiness.com/feed",       None),
    ("gulfbusiness.com",    "https://gulfbusiness.com/feed/",             None),

]

# Keywords used to:
#   (a) pre-filter broad RSS feeds at collection time (e.g. Al Jazeera title filter), and
#   (b) pre-filter articles before Claude scoring to cut token spend.
# Any single match on the article title + opening snippet passes the article through.
MENA_KEYWORDS = [
    # ---- UAE ----
    "UAE", "Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "RAK", "DIFC",
    # ---- Saudi Arabia ----
    "Saudi", "Riyadh", "Jeddah", "NEOM", "Vision 2030", "Qiddiya", "Diriyah",
    # ---- Broader MENA geography ----
    "GCC", "MENA", "Gulf", "Middle East",
    "Qatar", "Doha",
    "Kuwait",
    "Bahrain", "Manama",
    "Oman", "Muscat",
    "Egypt", "Cairo",
    "Jordan", "Amman",
    "Iraq", "Baghdad",
    "Morocco", "Casablanca",
    "Lebanon", "Beirut",
    "Libya", "Tunisia", "Algeria",
    # ---- SWFs & state-owned entities ----
    "PIF", "Mubadala", "ADIA", "ADQ", "QIA", "KIA",
    "Mumtalakat", "TAQA", "Senaat",
    "ADNOC", "Aramco", "SABIC",
    "DP World", "Masdar", "Aldar", "ACWA Power", "ACWA",
    "ICD", "Invest Abu Dhabi",
    "Emirates Investment", "Abu Dhabi Investment",
    # ---- BD-relevant actions ----
    "invest", "investment",
    "expand", "expansion",
    "headquarters",
    "market entry",
    "launch",
    "establish",
    "acquire", "acquisition",
    "merger",
    "stake",
    "sovereign wealth",
    "sovereign fund",
    "state-owned",
    "regional hub",
    "regional office",
    "foreign company",
    "foreign firm",
    "foreign investor",
    "Western company",
    # ---- Diplomatic / strategic ----
    "Abraham Accords",
    "normalization",
    "RHQP",
]

# General-purpose sources scoped with targeted search terms via Google News RSS.
# Format: (source_label, site, search_terms)
# Multiple entries per site = multiple queries, giving broader category coverage.
GOOGLE_NEWS_QUERIES = [

    # --- Zawya (highest-yield) ---
    ("zawya.com", "zawya.com",
        'foreign company expand headquarters "market entry" launch UAE OR "Saudi Arabia" OR MENA'),
    ("zawya.com", "zawya.com",
        'foreign company expand headquarters "market entry" launch Dubai OR Riyadh'),
    ("zawya.com", "zawya.com",
        'regional headquarters Saudi Arabia foreign company'),
    ("zawya.com", "zawya.com",
        'PIF OR Mubadala OR ADIA OR ADQ invest acquisition stake'),
    ("zawya.com", "zawya.com",
        'QIA OR Kuwait OR Mumtalakat OR Senaat OR TAQA sovereign wealth invest'),
    ("zawya.com", "zawya.com",
        '"Vision 2030" OR NEOM foreign company invest'),
    ("zawya.com", "zawya.com",
        'UAE OR "Saudi Arabia" foreign company announce launch 2026'),
    ("zawya.com", "zawya.com",
        'Dubai OR Riyadh foreign company announce launch 2026'),

]

# ---------------------------------------------------------------------------
# Static Tavily searches (Step 1b)
# ---------------------------------------------------------------------------
# Deterministic, targeted queries run against Tavily with a 7-day window.
# These should be specific enough that most results are BD-relevant.
# Client-based queries are generated dynamically from clients.json at runtime.

TAVILY_STATIC_QUERIES = [

    # --- SWF / state entity outbound investment ---
    "PIF investment acquisition stake",
    "Mubadala investment acquisition outside MENA",
    "ADIA investment stake acquisition",
    "ADQ investment acquisition",
    "QIA Qatar Investment Authority investment acquisition stake",
    "Kuwait Investment Authority deal investment",
    "Mumtalakat investment deal",
    "Gulf sovereign wealth fund outbound investment deal",
    "sovereign wealth fund UAE Saudi Arabia acquisition investment",

    # --- Saudi strategic programs ---
    "Vision 2030 foreign company investment",
    "RHQ Regional Headquarters Program foreign company announcements",
    "Saudi giga-project foreign company partnerships or investment",

    # --- Category 1: foreign company market entry ---
    "U.S. company UAE or Saudi Arabia regional headquarters",
    "European company UAE or Saudi Arabia regional headquarters",
    "U.S. company Dubai or Abu Dhabi office launch",
    "European company Dubai or Abu Dhabi office launch",
    "U.S. company Saudi Arabia expansion or market entry",
    "European company Saudi Arabia expansion or market entry",
    "U.S. company UAE market entry",
    "European company UAE market entry",
    "U.S. company Riyadh regional hub establishment",
    "European company Riyadh regional hub establishment",

    # --- Category 3: PR / policy friction ---
    "foreign company Saudi Arabia controversy backlash",
    "foreign company UAE policy obstacle regulatory",
    "company banned Saudi Arabia",
    "company controversy Gulf region",
]

# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 3        # Articles below this score are dropped
ARTICLE_DAYS_WINDOW = 7    # Only keep articles published within this many days
FILTER_BATCH_SIZE = 30     # Articles per Claude scoring call
FILTER_MAX_WORKERS = 1     # Concurrent Claude calls during scoring
MAX_ARTICLES_PER_FEED = 80 # Cap per RSS/Google News feed — keeps the most recent ones
LOG_COLLECTED_TITLES = False  # Print every collected article title — useful for tuning exclusion keywords

# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

HIGH_SCORE_THRESHOLD = 4     # Minimum score for Tavily corroboration search
TAVILY_DAYS = 7
TAVILY_MAX_RESULTS = 8

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

DEDUP_SIMILARITY_THRESHOLD = 92   # rapidfuzz token_set_ratio threshold (0–100) — 92 is very strict

REPORT_MIN_SCORE = 4      # Minimum score for AI-written category sections (score 3s go to appendix)
REPORT_BATCH_SIZE = 15    # Max articles per category sub-batch — larger categories are split and merged

CATEGORY_ORDER = [
    ("market_entry",   "Market Entry & Regional HQ Announcements"),
    ("swf_outbound",   "SWF & State Capital Flows"),
    ("signed_mou",     "Signed Government MOUs"),
    ("pr_policy_risk", "Policy & PR Risk Watch"),
]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = "data"
ARTICLES_FILE = os.path.join(DATA_DIR, "articles.json")
REPORTS_DIR = "reports"

# ---------------------------------------------------------------------------
# Claude models
# Use claude-haiku-3-5 for lightweight generation tasks (cheaper/faster).
# Use claude-sonnet-4-6 for scoring and report writing (better judgment).
# ---------------------------------------------------------------------------

MODEL_QUERY_GEN    = "claude-haiku-4-5"  # Step 1b: generate follow-up search queries
MODEL_FILTER       = "gpt-5.2"          # Step 2:  relevance scoring
MODEL_REPORT_BATCH = "gpt-4o"           # Step 4:  sub-batch section writing (article → prose)
MODEL_REPORT_SYNTH = "gpt-4.1"         # Step 4:  section merging + executive summary synthesis
