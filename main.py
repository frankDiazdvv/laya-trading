import time
from datetime import datetime
from config import TICKERS, SLEEP_SECONDS, passes_gate
from data_feed import get_state
from decisions import decide
from logger import init_db, log_decision

def main():
    init_db()
    print("Laya System-1 paper loop started. Press Ctrl+C to stop.")
    print(f"Tickers: {TICKERS} | Poll every {SLEEP_SECONDS}s\n")

    while True:
        for ticker in TICKERS:
            try:
                state = get_state(ticker)
                decision = decide(state)

                print(f"{datetime.now().strftime('%H:%M:%S')} | {ticker}")
                print(f"  price={state['price']}  chg_5m={state['change_5m']}%  chg_15m={state['change_15m']}%  rsi={state['rsi_14']}")
                print(f"  action={decision['action']}  P={decision['probs'][decision['action']]:.3f}  conviction={decision['conviction']:.2f}")
                print(f"  skip_news={decision['skip_news']:.3f}  gap_risk={decision['gap_risk']:.3f}  vol_ratio={state['volume_ratio']}")

                if passes_gate(decision):
                    print("  → HIGH CONFIDENCE — would paper-trade here")
                    # later: call paper_trader here
                else:
                    print("  → low confidence / hold")

                log_decision(state, decision)
                print()

            except Exception as e:
                print(f"Error on {ticker}: {e}")
                print("This error got triggered from main file")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()