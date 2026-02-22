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
    ("al-monitor.com",      "https://www.al-monitor.com/rss",            None),
    # Al Jazeera: native feed works, Google News RSS returns 0. Title-filtered here.
    ("aljazeera.com",       "https://aljazeera.com/xml/rss/all.xml",     "MENA_KEYWORDS"),
]

# Keywords used to pre-filter broad RSS feeds before Claude scoring.
# Any single match on the article title (case-insensitive) passes the article through.
MENA_KEYWORDS = [
    # Geography
    "UAE", "Dubai", "Abu Dhabi", "Saudi", "Riyadh", "GCC", "MENA", "Gulf",
    "Qatar", "Doha", "Kuwait", "Bahrain", "Oman",
    # BD-relevant actions
    "invest", "sovereign wealth", "headquarters", "market entry", "expand",
    # Key entities
    "PIF", "Mubadala", "ADIA", "ADQ", "QIA", "Aramco", "NEOM", "Vision 2030",
]

# General-purpose sources scoped with targeted search terms via Google News RSS.
# Format: (source_label, site, search_terms)
# Multiple entries per site = multiple queries, giving broader category coverage.
GOOGLE_NEWS_QUERIES = [

    # --- Asharq Al-Awsat (moved from full feed — output too broad) ---
    ("aawsat.com", "english.aawsat.com",
        'UAE OR "Saudi Arabia" foreign company expand headquarters invest'),
    ("aawsat.com", "english.aawsat.com",
        'Dubai OR Riyadh foreign company expand headquarters invest'),
    ("aawsat.com", "english.aawsat.com",
        'PIF OR Mubadala OR ADIA OR ADQ'),
    ("aawsat.com", "english.aawsat.com",
        '"Vision 2030" OR NEOM foreign company invest'),

    # --- Times of Israel ---
    ("timesofisrael.com", "timesofisrael.com",
        'UAE OR "Saudi Arabia" business invest expand headquarters'),
    ("timesofisrael.com", "timesofisrael.com",
        'Dubai OR Riyadh business invest expand headquarters'),
    ("timesofisrael.com", "timesofisrael.com",
        '"Abraham Accords" UAE business deal invest expand'),

    # --- Jerusalem Post ---
    ("jpost.com", "jpost.com",
        'UAE OR "Saudi Arabia" MENA business invest expand foreign company'),
    ("jpost.com", "jpost.com",
        'Dubai OR Riyadh business invest expand foreign company'),
    ("jpost.com", "jpost.com",
        '"Abraham Accords" OR Gulf invest business normalize'),

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

    # --- Anadolu Agency ---
    ("aa.com.tr", "aa.com.tr",
        'UAE OR "Saudi Arabia" MENA business invest expand headquarters foreign company'),
    ("aa.com.tr", "aa.com.tr",
        'Dubai OR Riyadh business invest expand headquarters foreign company'),
    ("aa.com.tr", "aa.com.tr",
        'PIF OR Mubadala OR ADIA OR ADQ'),
    ("aa.com.tr", "aa.com.tr",
        'QIA OR Kuwait OR Mumtalakat sovereign wealth invest'),

    # Amwaj Media: no native RSS feed and not indexed on Google News RSS.
    # Occasional articles may surface via Tavily dynamic search (Step 1b).
]

# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 3        # Articles below this score are dropped
ARTICLE_DAYS_WINDOW = 7    # Only keep articles published within this many days
FILTER_BATCH_SIZE = 30     # Articles per Claude scoring call
FILTER_MAX_WORKERS = 1     # Concurrent Claude calls during scoring

# ---------------------------------------------------------------------------
# Dynamic search (Step 1b)
# ---------------------------------------------------------------------------

DYNAMIC_HEADLINE_BATCH = 50   # Headlines per Claude call (all batches are processed)
DYNAMIC_QUERIES_PER_BATCH = 7 # Max queries Claude generates per batch
DYNAMIC_MAX_TOTAL_QUERIES = 100 # Global cap on Tavily searches across all batches

# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

FULL_TEXT_MAX_CHARS = 3000   # Truncation limit for Jina-fetched text in prompts
HIGH_SCORE_THRESHOLD = 4     # Minimum score for Tavily corroboration search
TAVILY_DAYS = 7
TAVILY_MAX_RESULTS = 8

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

MODEL_QUERY_GEN = "claude-haiku-4-5"   # Step 1b: generate follow-up search queries
MODEL_FILTER = "claude-sonnet-4-6"     # Step 2:  relevance scoring
MODEL_REPORT = "claude-sonnet-4-6"     # Step 4:  report writing
