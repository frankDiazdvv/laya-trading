import sqlite3
import json
from datetime import datetime
from pathlib import Path
from config import DB_PATH

def init_db():
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            ticker TEXT,
            state_json TEXT,
            action TEXT,
            probs_json TEXT,
            conviction REAL,
            skip_news REAL,
            gap_risk REAL,
            price_at_decision REAL,
            price_5m REAL,
            price_15m REAL,
            ret_5m REAL,
            ret_15m REAL,
            ret_5m_net REAL,
            ret_15m_net REAL,
            cost_pct REAL,
            price_later REAL,
            outcome TEXT
        )
    """)
    _ensure_outcome_columns(conn)
    conn.commit()
    conn.close()

# Filled by label_outcomes.py. Returns are percent, same units as change_5m.
OUTCOME_COLUMNS = (
    ("price_5m", "REAL"),
    ("price_15m", "REAL"),
    ("ret_5m", "REAL"),
    ("ret_15m", "REAL"),
    ("ret_5m_net", "REAL"),
    ("ret_15m_net", "REAL"),
    ("cost_pct", "REAL"),
)

def _ensure_outcome_columns(conn):
    have = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
    for name, column_type in OUTCOME_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {name} {column_type}")

def log_decision(state: dict, decision: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO decisions
        (ts, ticker, state_json, action, probs_json, conviction, skip_news, gap_risk, price_at_decision)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.utcnow().isoformat(),
            state["ticker"],
            json.dumps(state),
            decision["action"],
            json.dumps(decision["probs"]),
            decision["conviction"],
            decision["skip_news"],
            decision["gap_risk"],
            state["price"]
        )
    )
    conn.commit()
    conn.close()