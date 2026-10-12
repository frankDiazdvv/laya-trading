from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

def calculate_rsi(closes: list, period: int = 14) -> float:
    """Simple RSI calculation. Returns 50.0 if not enough data."""
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_state(ticker: str) -> dict:
    """
    Build a clean state for Laya System-1.
    Uses 5-minute bars + longer look-back for more stable features.
    """
    now = datetime.now(ZoneInfo("America/New_York"))

    # --- Latest quote ---
    quote_req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
    quote = client.get_stock_latest_quote(quote_req)[ticker]

    price = float(quote.ask_price or quote.bid_price or 0)
    bid = float(quote.bid_price or 0)
    ask = float(quote.ask_price or 0)
    spread_bps = ((ask - bid) / price * 10000) if price > 0 else 0.0

    # Defaults
    change_1m = 0.0
    change_5m = 0.0
    change_15m = 0.0
    volume_ratio = 1.0
    rsi_14 = 50.0

    try:
        # Request 5-minute bars for the last ~2 hours
        bars_req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=now - timedelta(hours=2),
            limit=30
        )
        bars = client.get_stock_bars(bars_req).df

        if not bars.empty:
            # Flatten multi-index if present
            if isinstance(bars.index, pd.MultiIndex):
                closes = bars["close"].droplevel(0).tolist()
                volumes = bars["volume"].droplevel(0).tolist()
            else:
                closes = bars["close"].tolist()
                volumes = bars["volume"].tolist()

            # Price changes
            if len(closes) >= 2:
                change_5m = (closes[-1] - closes[-2]) / closes[-2] * 100
            if len(closes) >= 4:
                change_15m = (closes[-1] - closes[-4]) / closes[-4] * 100
            if len(closes) >= 2:
                # Approximate 1-min change from latest 5-min bar (rough)
                change_1m = change_5m / 5

            # Volume ratio (latest vs average of previous bars)
            if len(volumes) >= 5:
                avg_vol = sum(volumes[-6:-1]) / 5
                volume_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

            # RSI
            rsi_14 = calculate_rsi(closes, period=14)

    except Exception as e:
        print(f"  [data_feed warning] {e}")

    # Simple regime
    regime = "trending" if abs(change_15m) > 0.4 else "range"

    state = {
        "ticker": ticker,
        "price": round(price, 4),
        "change_1m": round(change_1m, 3),
        "change_5m": round(change_5m, 3),
        "change_15m": round(change_15m, 3),
        "rsi_14": round(rsi_14, 1),
        "volume_ratio": round(volume_ratio, 2),
        "spread_bps": round(spread_bps, 1),
        "news_snippet": "",
        "time_of_day": now.strftime("%H:%M ET"),
        "regime": regime
    }
    return state