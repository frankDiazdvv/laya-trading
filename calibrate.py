"""Calibration report for labeled decisions.

One row per ticker per 5-minute bar: the earliest poll whose spread is at
or under SPREAD_CAP_BPS. Wider quotes stay in the database and stay out of
the hit rates, because those asks are often stale.

The 15-minute net return is the result that matters. A buy wins when that
net return is positive. A sell wins when the price falls by more than the
spread. P(buy) buckets use the long return on every bar, so a higher score
can be checked against a higher forward return.

Run from the project root after label_outcomes.py:

    python calibrate.py
"""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from config import (
    DB_PATH,
    MAX_GAP_RISK,
    MAX_SKIP_NEWS,
    MIN_BUY_PROB,
    MIN_CONVICTION,
    SPREAD_CAP_BPS,
    passes_gate,
)
from label_outcomes import directional_pnl_pct, parse_ts

ET = ZoneInfo("America/New_York")
REPORT_PATH = Path("data/calibration_report.txt")
CSV_PATH = Path("data/csv_export/calibration_bars.csv")

# Fixed edges so later sessions land in the same buckets.
CONVICTION_EDGES = (0.0, 1.0, 1.2, 1.4, 1.8, 10.0)
P_BUY_EDGES = (0.0, 0.35, 0.38, 0.40, 0.50, 0.70, 1.01)
HEADERS = ["bucket", "n", "hit", "gross_bps", "net_bps", "median_net_bps"]


def floor_five_minutes(ts: datetime) -> datetime:
    ts = ts.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return ts.replace(minute=(ts.minute // 5) * 5)


def load_observations() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        raw_rows = list(conn.execute("SELECT * FROM decisions ORDER BY ts, id"))
    finally:
        conn.close()

    observations = []
    for row in raw_rows:
        state = json.loads(row["state_json"])
        probs = json.loads(row["probs_json"])
        action = row["action"]
        gross = row["ret_15m"]
        gross_5 = row["ret_5m"]
        cost = row["cost_pct"]
        pnl = None
        gross_pnl = None
        pnl_5 = None
        if gross is not None and cost is not None:
            pnl = directional_pnl_pct(action, gross, cost)
            gross_pnl = directional_pnl_pct(action, gross, 0.0)
        if gross_5 is not None and cost is not None:
            pnl_5 = directional_pnl_pct(action, gross_5, cost)
        observations.append({
            "id": row["id"],
            "ts": parse_ts(row["ts"]),
            "ticker": row["ticker"],
            "action": action,
            "conviction": row["conviction"],
            "probs": probs,
            "p_buy": probs.get("buy"),
            "p_action": probs.get(action),
            "skip_news": row["skip_news"],
            "gap_risk": row["gap_risk"],
            "spread_bps": state.get("spread_bps"),
            "change_5m": state.get("change_5m"),
            "rsi_14": state.get("rsi_14"),
            "price": row["price_at_decision"],
            "price_15m": row["price_15m"],
            "ret_15m": gross,
            "ret_15m_net": row["ret_15m_net"],
            "cost_pct": cost,
            "pnl": pnl,
            "gross_pnl": gross_pnl,
            "pnl_5": pnl_5,
            "outcome": row["outcome"],
        })
    return observations


def is_clean(obs: dict) -> bool:
    spread = obs["spread_bps"]
    return obs["pnl"] is not None and spread is not None and spread <= SPREAD_CAP_BPS


def select_primary(rows: list[dict]) -> list[dict]:
    """Earliest clean quote inside each 5-minute bar."""
    chosen = {}
    for obs in rows:
        if not is_clean(obs):
            continue
        key = (obs["ticker"], floor_five_minutes(obs["ts"]))
        if key not in chosen:
            chosen[key] = obs
    return [chosen[key] for key in sorted(chosen)]


def decision_view(obs: dict) -> dict:
    return {
        "action": obs["action"],
        "conviction": obs["conviction"],
        "probs": obs["probs"],
        "skip_news": obs["skip_news"],
        "gap_risk": obs["gap_risk"],
    }


def bucket_key(value, edges: tuple[float, ...]):
    if value is None:
        return None
    for low, high in zip(edges, edges[1:]):
        if low <= value < high:
            return low, high
    return None


def bucket_label(low: float, high: float) -> str:
    return f"[{low:.2f}, {high:.2f})"


def stats_cells(label: str, net_pnls: list[float], gross_pnls: list[float]) -> list[str]:
    n = len(net_pnls)
    if n == 0:
        return [label, "0", "-", "-", "-", "-"]
    hits = sum(1 for pnl in net_pnls if pnl > 0)
    return [
        label,
        str(n),
        f"{100.0 * hits / n:.1f}%",
        f"{100.0 * mean(gross_pnls):+.1f}",
        f"{100.0 * mean(net_pnls):+.1f}",
        f"{100.0 * median(net_pnls):+.1f}",
    ]


def table(headers: list[str], rows: list[list[str]]) -> str:
    columns = list(zip(*([headers] + rows)))
    widths = [max(len(cell) for cell in column) for column in columns]

    def format_row(cells: list[str]) -> str:
        parts = []
        for index, (cell, width) in enumerate(zip(cells, widths)):
            parts.append(cell.ljust(width) if index == 0 else cell.rjust(width))
        return "  ".join(parts)

    lines = [format_row(headers), format_row(["-" * width for width in widths])]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def collect(rows: list[dict], net_of, gross_of) -> tuple[list[float], list[float]]:
    net_pnls = []
    gross_pnls = []
    for obs in rows:
        net = net_of(obs)
        gross = gross_of(obs)
        if net is None or gross is None:
            continue
        net_pnls.append(net)
        gross_pnls.append(gross)
    return net_pnls, gross_pnls


def directional_pair(rows: list[dict]) -> tuple[list[float], list[float]]:
    return collect(rows, lambda obs: obs["pnl"], lambda obs: obs["gross_pnl"])


def group_rows(rows: list[dict], value_of, net_of, gross_of, edges) -> list[list[str]]:
    groups = {(low, high): [] for low, high in zip(edges, edges[1:])}
    for obs in rows:
        key = bucket_key(value_of(obs), edges)
        if key is not None:
            groups[key].append(obs)
    rendered = []
    for (low, high), group in groups.items():
        rendered.append(stats_cells(bucket_label(low, high), *collect(group, net_of, gross_of)))
    return rendered


def side_momentum(obs: dict) -> str | None:
    change = obs["change_5m"]
    if change is None or change == 0:
        return None
    return "buy" if change > 0 else "sell"


def side_rsi(obs: dict) -> str | None:
    rsi = obs["rsi_14"]
    if rsi is None:
        return None
    if rsi < 30:
        return "buy"
    if rsi > 70:
        return "sell"
    return None


def apply_side(rows: list[dict], side_of) -> tuple[list[float], list[float]]:
    net_pnls = []
    gross_pnls = []
    for obs in rows:
        side = side_of(obs)
        if side is None or obs["ret_15m"] is None or obs["cost_pct"] is None:
            continue
        net_pnls.append(directional_pnl_pct(side, obs["ret_15m"], obs["cost_pct"]))
        gross_pnls.append(directional_pnl_pct(side, obs["ret_15m"], 0.0))
    return net_pnls, gross_pnls


def render(rows: list[dict], primary: list[dict]) -> str:
    labeled = [obs for obs in rows if obs["pnl"] is not None]
    wide = [
        obs for obs in labeled
        if obs["spread_bps"] is not None and obs["spread_bps"] > SPREAD_CAP_BPS
    ]
    sessions = sorted({obs["ts"].astimezone(ET).date().isoformat() for obs in primary})
    tickers = sorted({obs["ticker"] for obs in primary})
    generated = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    gate_rows = sum(1 for obs in rows if passes_gate(decision_view(obs)))
    gate_bars = sum(1 for obs in primary if passes_gate(decision_view(obs)))

    lines = [
        "Laya calibration",
        f"Generated: {generated}",
        f"Database: {DB_PATH}",
        "",
        "Sample",
        f"  Logged decisions: {len(rows)}",
        f"  With a 15-minute label: {len(labeled)}",
        f"  Spread above {SPREAD_CAP_BPS:.0f} bps (excluded): {len(wide)}",
        f"  Deduped bars in this report: {len(primary)}",
        f"  Sessions: {', '.join(sessions) if sessions else '-'}",
        f"  Tickers: {', '.join(tickers) if tickers else '-'}",
        "",
        "Price basis",
        "  Entry is the logged ask. Exit is the 1-minute bar close at 5 and 15 minutes.",
        "  Net deducts the full quoted spread, clipped at "
        f"{SPREAD_CAP_BPS:.0f} bps. Returns in the database are percent.",
        "  Because the entry is already the ask, that full-spread deduction is heavy by about half the spread.",
        "  Polls inside one 5-minute bar count once, using the first quote at or under the cap.",
        "  gross_bps ignores spread. net_bps deducts it. hit is the share of net results above zero.",
        "",
    ]

    if len(sessions) < 5:
        lines.append(
            "  These averages check the pipeline. A profitability read needs many regular sessions."
        )
        lines.append("")

    by_action = []
    for action in ("buy", "sell"):
        group = [obs for obs in primary if obs["action"] == action]
        by_action.append(stats_cells(action, *directional_pair(group)))
    by_action.append(stats_cells("buy+sell", *directional_pair(primary)))

    lines.append("Follow the model, 15-minute directional result")
    lines.append(table(HEADERS, by_action))
    lines.append("")

    net_5 = [obs["pnl_5"] for obs in primary if obs["pnl_5"] is not None]
    if net_5:
        hits = sum(1 for pnl in net_5 if pnl > 0)
        lines.append(
            f"Same bars, 5-minute directional net: n={len(net_5)}  "
            f"hit={100.0 * hits / len(net_5):.1f}%  "
            f"mean={100.0 * mean(net_5):+.1f} bps  "
            f"median={100.0 * median(net_5):+.1f} bps"
        )
    else:
        lines.append("Same bars, 5-minute directional net: no labels")
    lines.append("")

    lines.append("By conviction, 15-minute directional result")
    lines.append(table(HEADERS, group_rows(
        primary,
        lambda obs: obs["conviction"],
        lambda obs: obs["pnl"],
        lambda obs: obs["gross_pnl"],
        CONVICTION_EDGES,
    )))
    lines.append("")

    lines.append("By P(buy), 15-minute long result on every bar")
    lines.append(table(HEADERS, group_rows(
        primary,
        lambda obs: obs["p_buy"],
        lambda obs: obs["ret_15m_net"],
        lambda obs: obs["ret_15m"],
        P_BUY_EDGES,
    )))
    lines.append("")

    lines.append("Baselines on the same bars, 15-minute directional result")
    lines.append(table(HEADERS, [
        stats_cells("Laya action", *directional_pair(primary)),
        stats_cells("sign of change_5m", *apply_side(primary, side_momentum)),
        stats_cells("RSI <30 buy, >70 sell", *apply_side(primary, side_rsi)),
    ]))
    lines.append("")

    spread_values = [obs["spread_bps"] for obs in primary if obs["spread_bps"] is not None]
    if spread_values:
        lines.append(
            f"Mean quoted spread on the deduped bars: {mean(spread_values):.1f} bps"
        )
        lines.append("")

    lines.append("Confidence gate")
    lines.append(
        f"  Conviction >= {MIN_CONVICTION}, P(action) >= {MIN_BUY_PROB}, "
        f"skip_news <= {MAX_SKIP_NEWS}, gap_risk <= {MAX_GAP_RISK}"
    )
    lines.append(f"  Logged rows that pass: {gate_rows}")
    lines.append(f"  Deduped bars that pass: {gate_bars}")
    lines.append("")
    return "\n".join(lines)


def write_csv(primary: list[dict]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id", "ts", "ticker", "bar_utc", "action", "conviction", "p_buy", "p_action",
        "spread_bps", "change_5m", "rsi_14", "price", "price_15m", "ret_15m",
        "ret_15m_net", "cost_pct", "directional_net_pct", "outcome",
    ]
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for obs in primary:
            writer.writerow({
                "id": obs["id"],
                "ts": obs["ts"].isoformat(),
                "ticker": obs["ticker"],
                "bar_utc": floor_five_minutes(obs["ts"]).isoformat(),
                "action": obs["action"],
                "conviction": obs["conviction"],
                "p_buy": obs["p_buy"],
                "p_action": obs["p_action"],
                "spread_bps": obs["spread_bps"],
                "change_5m": obs["change_5m"],
                "rsi_14": obs["rsi_14"],
                "price": obs["price"],
                "price_15m": obs["price_15m"],
                "ret_15m": obs["ret_15m"],
                "ret_15m_net": obs["ret_15m_net"],
                "cost_pct": obs["cost_pct"],
                "directional_net_pct": obs["pnl"],
                "outcome": obs["outcome"],
            })


def main():
    rows = load_observations()
    if not rows:
        raise SystemExit("No decisions in the database.")
    if not any(obs["pnl"] is not None for obs in rows):
        raise SystemExit("No 15-minute labels yet. Run: python label_outcomes.py")

    primary = select_primary(rows)
    report = render(rows, primary)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    write_csv(primary)
    print(report)
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {CSV_PATH}")


if __name__ == "__main__":
    main()
