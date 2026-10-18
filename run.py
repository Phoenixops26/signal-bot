"""
Phoenix Altcoin Signal Bot - one hourly run.

    python run.py            live Coinbase data, paper trades
    python run.py --mock     simulated market (for testing, no internet needed)

Each run: scan -> score -> filter -> signal -> manage open paper trades ->
open new paper trades -> write docs/report.json for the dashboard.
"""
import argparse
import json
import os
import sys
import time

from bot import analysis, portfolio, report
from bot.config import CONFIG as CFG
from bot.data import DAY, HOUR, CoinbaseClient, MockClient

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
REPORT_PATH = os.path.join(ROOT, "docs", "report.json")


QUIET = False


def log(msg):
    if not QUIET:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def load_state(path, now):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return portfolio.new_state(CFG, now)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def pick_universe(client, held):
    """Step 1: top-N most liquid Coinbase USD alts, plus anything we hold."""
    skip = set(CFG["stablecoins"]) | set(CFG["exclude"]) | set(CFG["benchmarks"])
    prods = [p for p in client.products()
             if p.get("quote_currency") == CFG["quote_currency"]
             and p.get("status") == "online" and not p.get("trading_disabled")
             and p.get("base_currency") not in skip]
    log(f"{len(prods)} tradeable USD alts listed - ranking by 24h volume")
    vols = []
    for p in prods:
        s = client.stats(p["id"])
        if not s:
            continue
        try:
            usd = float(s.get("volume") or 0) * float(s.get("last") or 0)
        except (TypeError, ValueError):
            continue
        vols.append((usd, p["base_currency"], p["id"]))
    vols.sort(reverse=True)
    chosen = vols[:CFG["universe_size"]]
    names = {b for _, b, _ in chosen}
    for usd, b, pid in vols:
        if b in held and b not in names:
            chosen.append((usd, b, pid))
    return chosen


def run_once(client, state, now):
    """One full hourly cycle. Updates `state` in place, returns (report, actions)."""
    universe = pick_universe(client, set(state["positions"]))
    log(f"Scanning {len(universe)} coins")

    bench = {}
    for b in CFG["benchmarks"]:
        h1 = client.candles(f"{b}-USD", HOUR)
        if len(h1) > 170:
            c = [x["close"] for x in h1]
            bench[b] = {"price": c[-1], "ret_24h": c[-1] / c[-25] - 1, "ret_7d": c[-1] / c[-169] - 1}

    feats, hourly = [], {}
    for usd, base, pid in universe:
        try:
            h1 = client.candles(pid, HOUR)
            d1 = client.candles(pid, DAY)
            tk = client.ticker(pid)
        except Exception as e:          # one bad coin shouldn't stop the run
            log(f"  skip {base}: {e}")
            continue
        hourly[base] = h1
        f = analysis.features(base, h1, d1, tk, usd, CFG)
        if f:
            feats.append(f)
    log(f"{len(feats)} coins had enough history to score")
    if not feats:
        log("No data - aborting without changing anything")
        sys.exit(1)

    ranked, narratives = analysis.analyse(feats, bench, CFG)
    by_ticker = {f["ticker"]: f for f in ranked}

    actions = portfolio.manage_positions(state, hourly, by_ticker, now, CFG)
    new, skipped = portfolio.open_positions(ranked, state, hourly, now, CFG)
    actions += new
    portfolio.record_equity(state, now, CFG)
    state["last_run"] = now

    rep = report.build(state, ranked, narratives, bench, actions, skipped, now, CFG, client.name)
    return rep, actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use simulated market data")
    ap.add_argument("--now", type=int, help="(testing) pretend the time is this unix timestamp")
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--report", default=REPORT_PATH)
    args = ap.parse_args()

    if args.mock:
        tickers = sorted({t for m in CFG["narratives"].values() for t in m}
                         | set(CFG["benchmarks"]) | {f"ALT{i}" for i in range(15)})
        client = MockClient(tickers, now=args.now)
    else:
        client = CoinbaseClient(CFG["requests_per_second"])
    now = client.now // HOUR * HOUR if args.mock else int(time.time())

    state = load_state(args.state, now)
    rep, actions = run_once(client, state, now)
    save_json(args.state, state)
    save_json(args.report, rep)

    p = rep["portfolio"]
    log(f"Signals: {rep['signals_summary']}")
    for a in actions:
        log(f"  {a['action']:>17} {a['ticker']:<8} @ {a.get('price', 0):.6g}  {a.get('reason', '')}")
    log(f"Portfolio ${p['portfolio_value']:,.2f} | open {len(p['open_positions'])} | "
        f"closed {p['closed_trades']} | win rate {p['win_rate_pct']}")


if __name__ == "__main__":
    main()
