"""Fill forward prices and returns on logged decisions.

Exit prices come from Alpaca 1-minute bars, so a 5-minute or 15-minute
horizon lands on the first bar that closes at that time, within one minute.
Returns are percent, matching change_5m. The net return subtracts one full
quoted spread, clipped at SPREAD_CAP_BPS. price_later is the 15-minute price.

Run from the project root:

    python label_outcomes.py
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, DB_PATH, SPREAD_CAP_BPS
from logger import init_db

BAR_LENGTH = timedelta(minutes=1)
HORIZON_5 = timedelta(minutes=5)
HORIZON_15 = timedelta(minutes=15)


def parse_ts(value: str) -> datetime:
    """Decision timestamps are stored as naive UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def match_close(bars: list[tuple[datetime, float]], target: datetime) -> float | None:
    """Close of the first bar that ends at or after target.

    Bars are (start, close) sorted by start. A bar is one minute long.
    A match that would land more than one minute late is rejected, so a
    missing minute does not get filled with a much later price.
    """
    target = target.astimezone(timezone.utc)
    for start, close in bars:
        start_utc = start.astimezone(timezone.utc)
        end = start_utc + BAR_LENGTH
        if end < target:
            continue
        if end > target + BAR_LENGTH:
            return None
        return close
    return None


def percent_change(entry: float | None, future: float | None) -> float | None:
    if entry is None or future is None or entry <= 0:
        return None
    return (future - entry) / entry * 100.0


def round_trip_cost_pct(spread_bps: float | None) -> float:
    """Full quoted spread in percent, clipped at the stale-quote cap."""
    if spread_bps is None:
        return 0.0
    clipped = min(max(float(spread_bps), 0.0), SPREAD_CAP_BPS)
    return clipped / 100.0


def directional_pnl_pct(action: str, gross_pct: float, cost_pct: float) -> float | None:
    """Long net is price change minus spread. Short net is the reverse, minus spread."""
    if action == "buy":
        return gross_pct - cost_pct
    if action == "sell":
        return -gross_pct - cost_pct
    return None


def outcome_label(pnl_pct: float | None) -> str | None:
    if pnl_pct is None:
        return None
    if pnl_pct > 0:
        return "win"
    if pnl_pct < 0:
        return "loss"
    return "scratch"


def label_decision(row, bars: list[tuple[datetime, float]]) -> dict:
    decided_at = parse_ts(row["ts"])
    entry = row["price_at_decision"]
    state = json.loads(row["state_json"])
    cost = round_trip_cost_pct(state.get("spread_bps"))

    price_5m = match_close(bars, decided_at + HORIZON_5)
    price_15m = match_close(bars, decided_at + HORIZON_15)
    ret_5m = percent_change(entry, price_5m)
    ret_15m = percent_change(entry, price_15m)
    ret_5m_net = None if ret_5m is None else ret_5m - cost
    ret_15m_net = None if ret_15m is None else ret_15m - cost
    pnl_15m = None if ret_15m is None else directional_pnl_pct(row["action"], ret_15m, cost)

    return {
        "price_5m": price_5m,
        "price_15m": price_15m,
        "ret_5m": ret_5m,
        "ret_15m": ret_15m,
        "ret_5m_net": ret_5m_net,
        "ret_15m_net": ret_15m_net,
        "cost_pct": cost,
        "price_later": price_15m,
        "outcome": outcome_label(pnl_15m),
    }


def fetch_bars(client, ticker: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        start=start - BAR_LENGTH,
        end=end + timedelta(minutes=2),
    )
    barset = client.get_stock_bars(request)
    try:
        raw_bars = barset[ticker]
    except KeyError:
        return []

    bars = []
    for bar in raw_bars:
        start_ts = bar.timestamp
        if start_ts.tzinfo is None:
            start_ts = start_ts.replace(tzinfo=timezone.utc)
        else:
            start_ts = start_ts.astimezone(timezone.utc)
        bars.append((start_ts, float(bar.close)))
    bars.sort(key=lambda item: item[0])
    return bars


def write_labels(conn, labeled: list[tuple[int, dict]]) -> None:
    conn.executemany(
        """
        UPDATE decisions SET
            price_5m = ?,
            price_15m = ?,
            ret_5m = ?,
            ret_15m = ?,
            ret_5m_net = ?,
            ret_15m_net = ?,
            cost_pct = ?,
            price_later = ?,
            outcome = ?
        WHERE id = ?
        """,
        [
            (
                fields["price_5m"],
                fields["price_15m"],
                fields["ret_5m"],
                fields["ret_15m"],
                fields["ret_5m_net"],
                fields["ret_15m_net"],
                fields["cost_pct"],
                fields["price_later"],
                fields["outcome"],
                decision_id,
            )
            for decision_id, fields in labeled
        ],
    )


def main():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute("SELECT * FROM decisions ORDER BY id"))
        if not rows:
            print("No decisions to label.")
            return

        by_ticker: dict[str, list] = {}
        for row in rows:
            by_ticker.setdefault(row["ticker"], []).append(row)

        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        labeled: list[tuple[int, dict]] = []
        tickers_with_bars = 0

        for ticker, group in by_ticker.items():
            times = [parse_ts(row["ts"]) for row in group]
            bars = fetch_bars(client, ticker, min(times), max(times) + HORIZON_15)
            print(f"{ticker}: {len(bars)} one-minute bars")
            if bars:
                tickers_with_bars += 1
                print(f"  {bars[0][0].isoformat()} -> {bars[-1][0].isoformat()}")
            else:
                print(f"  No bars for {ticker}. Leaving stored labels unchanged.")
                continue
            for row in group:
                labeled.append((row["id"], label_decision(row, bars)))

        if tickers_with_bars == 0:
            raise SystemExit("Alpaca returned no bars. Labels were not changed.")

        write_labels(conn, labeled)
        conn.commit()
    finally:
        conn.close()

    labeled_15 = sum(1 for _, fields in labeled if fields["price_15m"] is not None)
    labeled_5 = sum(1 for _, fields in labeled if fields["price_5m"] is not None)
    print(f"Updated {len(labeled)} decisions.")
    print(f"  5-minute prices: {labeled_5}")
    print(f"  15-minute prices: {labeled_15}")
    print(f"  missing 15-minute price: {len(labeled) - labeled_15}")
    print("Next: python calibrate.py")


if __name__ == "__main__":
    main()
