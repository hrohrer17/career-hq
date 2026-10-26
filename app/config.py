"""Settings for Career HQ: where the keys and database live, which model, and the spending limits.

The model is fixed on purpose. The course key only allows gpt-6-luna, so there is no setting that
could switch the agent to a different (and more expensive) model.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR.parent
DATA_DIR = REPO / "data"
STATIC_DIR = APP_DIR / "static"
SAMPLE_SEED = DATA_DIR / "sample_seed.json"   # the fictional example user behind "Load sample data"

# The key file can sit in the repo folder or one folder above it (where the teaching staff keep
# theirs). The repo's own .env wins; values already set in the shell win over both.
for folder in (REPO, REPO.parent):
    if (folder / ".env").is_file():
        load_dotenv(folder / ".env", override=False)

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

# The app starts blank. Point CAREER_HQ_DB elsewhere to keep separate databases;
# data/*.sqlite3 and data/private/ are ignored by Git.
DB_PATH = Path(os.getenv("CAREER_HQ_DB") or DATA_DIR / "career_hq.sqlite3")
if not DB_PATH.is_absolute():
    DB_PATH = REPO / DB_PATH  # relative paths are relative to the repo, not wherever you ran the command

MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# USD per 1M tokens for gpt-6-luna, standard short context (same table as Lecture 11).
PRICE_PER_M = {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50}

# ---- Spending and safety limits ----
MAX_NOTE_CHARS = 8000          # one conversation's notes
MIN_NOTE_CHARS = 30
MAX_REQUESTS_PER_RUN = 6       # model calls in one analysis (first answer + tool round trips)
MAX_TOOL_CALLS_PER_RUN = 8
MAX_TOKENS_PER_RUN = 40_000    # input + output across the whole run
MAX_OUTPUT_TOKENS = 4000       # per model call
MAX_RUNS_PER_HOUR = int(os.getenv("CAREER_HQ_MAX_RUNS_PER_HOUR", "20"))
DAILY_BUDGET_USD = float(os.getenv("CAREER_HQ_DAILY_BUDGET_USD", "0.25"))
MAX_PROPOSALS = 12

# Target Scout: one call that writes ~15 employer profiles, so it needs more output room and time.
SCOUT_MAX_OUTPUT_TOKENS = 14_000
SCOUT_MAX_TOKENS_PER_RUN = 45_000
SCOUT_TIMEOUT_S = 240.0

# The Portkey gateway replays cached responses to byte-identical requests. Evaluations set this so
# every run is a fresh model answer (otherwise repeated runs just measure the cache).
BYPASS_GATEWAY_CACHE = os.getenv("CAREER_HQ_BYPASS_GATEWAY_CACHE", "") == "1"


def api_credentials() -> tuple[str, str] | None:
    """(key, base_url) for the model gateway, or None when no key is configured.

    The course key (PORTKEY_API_KEY) is preferred. OPENAI_API_KEY is the personal-key fallback.
    """
    portkey = os.getenv("PORTKEY_API_KEY", "").strip()
    if portkey:
        return portkey, PORTKEY_BASE_URL
    own = os.getenv("OPENAI_API_KEY", "").strip()
    if own:
        return own, OPENAI_BASE_URL
    return None


def key_source() -> str:
    if os.getenv("PORTKEY_API_KEY", "").strip():
        return "PORTKEY_API_KEY"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "OPENAI_API_KEY"
    return "none"
