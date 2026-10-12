# AGENTS.md – Laya Day-Trader

## Project Goal

Build and study a **System-1 decision loop** for paper day-trading using Laya.

Laya is a non-autoregressive System-1 model (https://huggingface.co/convaiinnovations/laya).  
It takes a structured market state + typed questions and returns calibrated probabilities / scores in one forward pass. It does **not** generate text and does not “understand” the market — it only scores the features we feed it.

We use Alpaca **paper** account only.  
No real money. No live order submission until explicitly decided.

## Core Principles

- Keep Laya pure: `decisions.py` must stay free of network, database, or order logic.
- Prefer simple, structured numerical features over complex ones.
- Confidence gating is intentional and strict. Do not lower thresholds just to generate more trades.
- Logging every decision is more important than acting on them right now.
- Measure calibration later using real outcomes (`price_later`).

## Architecture

| File              | Responsibility                                      |
|-------------------|-----------------------------------------------------|
| `main.py`         | Orchestration loop                                  |
| `data_feed.py`    | Alpaca quotes + bars → clean state dict             |
| `decisions.py`    | Laya Router + questions + pure `decide(state)`      |
| `logger.py`       | SQLite logging                                      |
| `config.py`       | Keys, tickers, thresholds, paths                    |
| `paper_trader.py` | Stub only (no order logic yet)                      |

## Important Conventions

- State dict keys must stay stable (ticker, price, change_5m, change_15m, rsi_14, volume_ratio, spread_bps, etc.).
- Always clip extreme spreads (e.g. `min(spread_bps, 15.0)`).
- Prefer 5-minute bars over 1-minute for cleaner features.
- Never place real or paper orders unless the user explicitly asks to implement and enable them.
- When adding features, keep them simple and explainable.

## Current Status (as of 2026-10-01)

- Live loop works and logs every decision.
- 500+ decisions collected on AAPL.
- Confidence gate correctly rejects almost all calls (low conviction / low probability).
- RSI and 15-minute change are working after the data_feed fix.
- `price_later` and `outcome` columns exist but are never filled.
- No order submission code exists yet.

## Preferred Next Steps (in order)

1. Offline script to fill `price_later` (5 min and 15 min) from historical bars.
2. Basic calibration analysis (hit rate vs conviction).
3. Only then consider feature improvements or threshold adjustments.
4. Paper order submission is low priority until we have evidence of edge.

## How to Help

- When asked to change code, prefer small, focused diffs.
- Always keep `decisions.py` free of side effects.
- If suggesting new features, explain why they would help a System-1 model.
- Prefer free / cheap solutions (Alpaca paper, local Laya, SQLite).
- When in doubt, ask before implementing order logic or lowering the confidence gate.

## Running the Project

Activate venv first
python main.py

## Database 

data/decisions.db