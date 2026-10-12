# Loads the .env and holds shared constants (tickers, sleep interval, confidence thresholds, etc.).

import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca paper keys
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# Trading settings
TICKERS = ["AAPL"]          # start with one ticker
SLEEP_SECONDS = 30          # how often to poll
MIN_CONVICTION = 1.8        # only act when Laya score is high enough
MIN_BUY_PROB = 0.70         # only act when P(action) is high enough
MAX_SKIP_NEWS = 0.40        # block when the news score is above this
MAX_GAP_RISK = 0.50         # block when the gap-risk score is above this
SPREAD_CAP_BPS = 15.0       # wider quotes are treated as stale


def passes_gate(decision: dict) -> bool:
    """True when the live loop would paper-trade this decision."""
    action = decision.get("action")
    if action not in ("buy", "sell"):
        return False
    conviction = decision.get("conviction")
    if conviction is None or conviction < MIN_CONVICTION:
        return False
    probability = (decision.get("probs") or {}).get(action) or 0
    if probability < MIN_BUY_PROB:
        return False
    if (decision.get("skip_news") or 0) > MAX_SKIP_NEWS:
        return False
    if (decision.get("gap_risk") or 0) > MAX_GAP_RISK:
        return False
    return True

# Paths
DB_PATH = "data/decisions.db"