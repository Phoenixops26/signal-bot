"""
Run the bot hour-by-hour over a simulated market to check every rule works.

    python tests/simulate.py --days 30

Uses fake prices only. Results say nothing about real-market profitability.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run  # noqa: E402
from bot import portfolio  # noqa: E402
from bot.config import CONFIG as CFG  # noqa: E402
from bot.data import HOUR, MockClient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=30)
ap.add_argument("--start", type=int, default=1776000000)
ap.add_argument("--out", default="sim_report.json")
args = ap.parse_args()

run.QUIET = True
start = args.start // HOUR * HOUR
end = start + args.days * 24 * HOUR
tickers = sorted({t for m in CFG["narratives"].values() for t in m}
                 | set(CFG["benchmarks"]) | {f"ALT{i}" for i in range(15)})
client = MockClient(tickers, now=start, horizon=end)
state = portfolio.new_state(CFG, start)
all_actions = []
t0 = time.time()
for now in range(start, end + 1, HOUR):
    client.now = now
    rep, actions = run.run_once(client, state, now)
    all_actions += actions
    # Invariants - the rules must never be broken
    eq = portfolio.equity(state)
    assert state["cash"] >= -1e-6, f"negative cash at {now}"
    assert len(state["positions"]) <= CFG["max_open_positions"], "too many positions"
    if any(a["action"] == "BUY" for a in actions):
        assert portfolio.exposure(state) <= eq * CFG["max_total_exposure_pct"] / 100 + 1, "exposure cap"
        for n, v in portfolio.narrative_exposure(state).items():
            assert v <= eq * CFG["max_narrative_exposure_pct"] / 100 + 1, f"narrative cap {n}"
        for a in actions:
            if a["action"] == "BUY":
                assert a["confidence"] > CFG["min_confidence"] and a["risk_reward"] > CFG["min_rr"]
                assert a["value_usd"] <= eq * CFG["max_position_pct"] / 100 * 1.01, "position cap"
with open(args.out, "w") as fh:
    json.dump(rep, fh, indent=1)

kinds = {}
for a in all_actions:
    kinds[a["action"]] = kinds.get(a["action"], 0) + 1
reasons = {}
for c in state["closed"]:
    reasons[c["exit_reason"]] = reasons.get(c["exit_reason"], 0) + 1
p = rep["portfolio"]
print(f"Simulated {args.days} days ({(end-start)//HOUR+1} hourly runs) in {time.time()-t0:.0f}s")
print("Actions:", kinds)
print("Exit reasons:", reasons)
print(f"Final ${p['portfolio_value']:,.2f}  all-time {p['pnl']['all_time']}  "
      f"win rate {p['win_rate_pct']}%  avg R {p['avg_r_multiple']}  "
      f"open {len(p['open_positions'])}  closed {p['closed_trades']}")
print("All rule checks passed every hour.")
