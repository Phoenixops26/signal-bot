"""
Phoenix Altcoin Signal Bot - everything in one file.

    python run.py            live Coinbase data, paper trades
    python run.py --mock     simulated market (for testing, no internet needed)

PAPER TRADING ONLY. Reads public Coinbase market data. Never places orders.

Each hourly run: scan -> score -> filter -> signal -> manage open paper trades
-> open new paper trades -> write docs/report.json for the dashboard.

ALL SETTINGS ARE IN THE "CONFIG" SECTION JUST BELOW. Change numbers there.
"""
import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone



# ==========================================================================
# CONFIG - all settings (defaults are a starting point for PAPER trading)
# ==========================================================================
CONFIG = {
    # ---- Paper account ----------------------------------------------------
    "starting_capital": 10_000.0,   # fake USD the paper account starts with
    "mode": "paper",                # the bot never places real orders

    # ---- Universe ---------------------------------------------------------
    "quote_currency": "USD",
    "universe_size": 100,           # top N most-traded Coinbase USD alts
    "benchmarks": ["BTC", "ETH", "SOL"],
    "stablecoins": ["USDT", "USDC", "DAI", "PYUSD", "EURC", "GUSD", "PAX", "USDS",
                    "FDUSD", "TUSD", "RLUSD", "USD1", "GHO", "LUSD", "USDE"],
    # Wrapped / staked copies of other coins - not real alts
    "exclude": ["WBTC", "CBBTC", "CBETH", "WETH", "STETH", "WSTETH", "RETH",
                "MSOL", "JITOSOL", "LSETH", "CBDOGE", "CBXRP", "CBADA", "CBLTC"],

    # ---- Step 4: score weights (must add to 1.0) --------------------------
    "weights": {
        "trend": 0.30,
        "relative_strength": 0.25,
        "narrative": 0.20,
        "volume": 0.15,
        "risk": 0.10,
    },

    # ---- Step 5: risk filter ---------------------------------------------
    "min_24h_volume_usd": 5_000_000,  # liquidity threshold
    "max_spread_pct": 0.30,           # best ask vs best bid, percent
    # Whale-selling proxy (no on-chain data on the free feed):
    "whale_volume_mult": 4.0,   # an hourly bar with this x normal volume...
    "whale_drop_pct": 3.0,      # ...that fell at least this % = dump bar
    "whale_sell_share": 0.70,   # or 70%+ of last-24h volume on red bars
    # Token unlocks: Coinbase does not publish these. Add coins with a big
    # unlock coming up, e.g. "ARB": "2026-11-16 large team/investor unlock".
    # Check token.unlocks.app or cryptorank.io/token-unlock weekly.
    "unlock_blocklist": {},

    # ---- Step 6: signal bands (by confidence 0-100) ------------------------
    "signal_bands": [
        ("STRONG BUY", 80),
        ("BUY", 65),
        ("HOLD", 45),
        ("REDUCE", 30),
        ("SELL", 0),
    ],

    # ---- Trade levels ---------------------------------------------------
    "stop_atr_mult": 2.0,     # stop = wider of 2x hourly ATR or 24h swing low
    "min_stop_pct": 1.5,
    "max_stop_pct": 12.0,
    "t1_r": 2.0,              # Target 1 = 2R (or nearest resistance if closer)
    "t2_r": 4.0,              # Target 2 = 4R
    "trail_atr_mult": 3.0,    # trailing stop distance after Target 1

    # ---- Step 7: execution rules ---------------------------------------
    "min_confidence": 80,     # must be ABOVE this
    "min_rr": 2.5,            # must be ABOVE this
    "risk_per_trade_pct": 1.0,          # lose at most 1% of account per stop-out
    "max_position_pct": 15.0,           # no single coin above 15% of account
    "max_open_positions": 8,
    "max_total_exposure_pct": 80.0,     # always keep 20%+ in cash
    "max_narrative_exposure_pct": 30.0, # no narrative above 30% of account

    # ---- Costs (keeps paper results honest) ----------------------------
    "fee_pct": 0.60,       # Coinbase Advanced taker fee at the lowest tier
    "slippage_pct": 0.10,

    # ---- Narratives (Step 2) ------------------------------------------
    # Coins not listed here are scored as "Other" (neutral 50).
    "narratives": {
        "Artificial Intelligence": ["FET", "TAO", "GRT", "VIRTUAL", "AIOZ", "AI16Z",
                                    "IO", "OCEAN", "AGIX", "KAITO"],
        "Real World Assets": ["ONDO", "LINK", "PLUME", "SYRUP", "CFG", "POLYX",
                              "OM", "TRU", "GFI"],
        "DeFi": ["UNI", "AAVE", "CRV", "COMP", "SNX", "LDO", "PENDLE", "JUP", "MORPHO",
                 "1INCH", "SUSHI", "BAL", "ENA", "RAY", "CVX", "YFI", "SKY", "MKR",
                 "ZRX", "AERO", "DRIFT", "JTO"],
        "Gaming": ["AXS", "SAND", "MANA", "IMX", "GALA", "ILV", "APE", "BEAM", "YGG",
                   "SUPER", "RONIN", "RON", "ENJ", "GODS"],
        "Layer 1": ["ADA", "AVAX", "DOT", "ATOM", "NEAR", "APT", "SUI", "SEI", "ALGO",
                    "XLM", "XRP", "LTC", "BCH", "HBAR", "ICP", "TIA", "INJ", "ETC",
                    "XTZ", "EGLD", "KAS", "HYPE", "TON", "FLOW", "MINA", "BERA",
                    "S", "KAVA", "ROSE", "QNT", "VET", "TRX"],
        "Layer 2": ["ARB", "OP", "POL", "MATIC", "STRK", "ZK", "MNT", "METIS", "BLAST",
                    "LRC", "SKL", "ZETA", "ZORA"],
        "DePIN": ["FIL", "RENDER", "RNDR", "HNT", "AR", "IOTX", "AKT", "LPT", "THETA",
                  "GRASS", "HONEY", "MOBILE", "STORJ", "ANKR", "GLM", "W"],
        "Meme": ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "POPCAT", "MOG",
                 "PENGU", "TRUMP", "FARTCOIN", "BRETT", "TOSHI", "MEW", "SPX", "DEGEN"],
    },

    # ---- Housekeeping -------------------------------------------------
    "requests_per_second": 6.0,   # Coinbase public limit is ~10/s per IP
    "equity_history_days": 45,
    "closed_trades_kept": 500,
}
CFG = CONFIG


# ==========================================================================
# INDICATORS
# ==========================================================================
def ema(values, n):
    k = 2 / (n + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def atr(candles, n=14):
    """Average True Range (Wilder smoothing)."""
    if len(candles) < 2:
        return 0.0
    trs = []
    for prev, c in zip(candles, candles[1:]):
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev["close"]),
                       abs(c["low"] - prev["close"])))
    a = sum(trs[:n]) / min(n, len(trs))
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def ret(closes, bars_back):
    if len(closes) <= bars_back or closes[-1 - bars_back] <= 0:
        return 0.0
    return closes[-1] / closes[-1 - bars_back] - 1


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def percentile_ranks(values: dict):
    """Map {key: number} -> {key: 0..100} by rank (ties share a rank)."""
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 50.0}
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        rank = (i + j) / 2 / (n - 1) * 100
        for k in range(i, j + 1):
            out[items[k][0]] = rank
        i = j + 1
    return out


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def log2(x):
    return math.log(x, 2) if x > 0 else -10


# ==========================================================================
# MARKET DATA (Coinbase public API + simulated test market)
# ==========================================================================
HOUR = 3600
DAY = 86400


def _candle_rows(raw):
    """Coinbase returns [time, low, high, open, close, volume], newest first."""
    out = [{"t": int(c[0]), "low": float(c[1]), "high": float(c[2]),
            "open": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
           for c in raw]
    out.sort(key=lambda c: c["t"])
    return out


class CoinbaseClient:
    BASE = "https://api.exchange.coinbase.com"
    name = "Coinbase Exchange public market data"

    def __init__(self, requests_per_second=6.0):
        self.min_gap = 1.0 / requests_per_second
        self._last = 0.0
        self.now = int(time.time())

    def _get(self, path, params=None):
        url = self.BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            wait = self.min_gap - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            req = urllib.request.Request(url, headers={
                "User-Agent": "phoenix-signal-bot/1.0",
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Coinbase request kept failing: {url}")

    def products(self):
        return self._get("/products") or []

    def stats(self, product_id):
        return self._get(f"/products/{product_id}/stats")

    def ticker(self, product_id):
        return self._get(f"/products/{product_id}/ticker")

    def candles(self, product_id, granularity):
        return _candle_rows(self._get(f"/products/{product_id}/candles",
                                      {"granularity": granularity}) or [])


class MockClient:
    """Deterministic fake market. The same coin always follows the same path,
    so running hour after hour behaves like a real, continuing market."""

    name = "SIMULATED market data (test mode)"
    EPOCH = 1767225600  # 2026-01-01 UTC

    def __init__(self, tickers, now=None, horizon=None):
        self.now = int(now or time.time()) // HOUR * HOUR
        self.horizon = max(self.now, int(horizon or 0) // HOUR * HOUR)
        self.tickers = tickers
        self._paths = {}

    def _path(self, base):
        """Bars up to self.now (the last one is the hour still in progress)."""
        bars = self._full_path(base)
        n = (self.now - self.EPOCH) // HOUR + 1
        return bars[:n]

    def _full_path(self, base):
        if base in self._paths:
            return self._paths[base]
        rng = random.Random(zlib.crc32(base.encode()))
        price = {"BTC": 95000.0, "ETH": 3600.0, "SOL": 180.0}.get(
            base, math.exp(rng.uniform(math.log(0.0001), math.log(400))))
        sigma = rng.uniform(0.006, 0.022)
        base_vol_usd = math.exp(rng.uniform(math.log(2e5), math.log(4e7)))
        drift = rng.uniform(-0.0006, 0.0009)
        n = (self.horizon - self.EPOCH) // HOUR + 1
        bars = []
        t = self.EPOCH
        for i in range(n):
            if i % 240 == 0:   # new regime roughly every 10 days
                drift = rng.uniform(-0.0012, 0.0016)
            r = rng.gauss(drift, sigma)
            o = price
            c = price * math.exp(r)
            hi = max(o, c) * (1 + abs(rng.gauss(0, sigma / 2)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, sigma / 2)))
            vol_usd = base_vol_usd / 24 * math.exp(rng.gauss(0, 0.5)) * (1 + 40 * abs(r))
            if rng.random() < 0.004:      # occasional huge-volume dump bar
                c = o * 0.95
                lo = min(lo, c)
                vol_usd *= 8
            bars.append({"t": t, "open": o, "high": hi, "low": lo, "close": c,
                         "volume": vol_usd / c})
            price = c
            t += HOUR
        self._paths[base] = bars
        return bars

    def products(self):
        out = []
        for b in self.tickers:
            out.append({"id": f"{b}-USD", "base_currency": b, "quote_currency": "USD",
                        "status": "online", "trading_disabled": False})
        return out

    def stats(self, product_id):
        bars = self._path(product_id.split("-")[0])[-24:]
        return {"last": bars[-1]["close"], "volume": sum(b["volume"] for b in bars)}

    def ticker(self, product_id):
        base = product_id.split("-")[0]
        p = self._path(base)[-1]["close"]
        spread = (zlib.crc32(base.encode()) % 40) / 10000 + 0.0003  # 0.03% - 0.43%
        return {"price": p, "bid": p * (1 - spread / 2), "ask": p * (1 + spread / 2)}

    def candles(self, product_id, granularity):
        bars = self._path(product_id.split("-")[0])
        if granularity == HOUR:
            return [dict(b) for b in bars[-300:]]
        # aggregate to daily
        days = {}
        for b in bars:
            d = b["t"] // DAY * DAY
            if d not in days:
                days[d] = dict(b, t=d)
            else:
                x = days[d]
                x["high"] = max(x["high"], b["high"])
                x["low"] = min(x["low"], b["low"])
                x["close"] = b["close"]
                x["volume"] += b["volume"]
        return [days[k] for k in sorted(days)][-300:]


# ==========================================================================
# STEPS 1-6: scan, narratives, relative strength, ranking, risk filter, signals
# ==========================================================================
def narrative_of(base, cfg):
    for name, members in cfg["narratives"].items():
        if base in members:
            return name
    return "Other"


# ---------------------------------------------------------------- Step 1
def features(base, h1, d1, ticker, usd_volume_24h, cfg):
    """Everything we need to know about one coin, from its candles."""
    if len(h1) < 200 or len(d1) < 50:
        return None
    closes = [c["close"] for c in h1]
    dcloses = [c["close"] for c in d1]
    price = float(ticker.get("price") or closes[-1]) if ticker else closes[-1]
    bid = float(ticker.get("bid") or 0) if ticker else 0
    ask = float(ticker.get("ask") or 0) if ticker else 0
    spread_pct = (ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else 99.0

    e20, e50 = ema(closes, 20), ema(closes, 50)
    de20, de50 = ema(dcloses, 20), ema(dcloses, 50)
    a1 = atr(h1[-60:], 14)

    # Volume expansion: last 24h vs average day of the 7 days before
    usd = [c["volume"] * c["close"] for c in h1]
    last24 = sum(usd[-24:])
    prior7 = usd[-24 - 168:-24]
    avg_day = sum(prior7) / 7 if prior7 else 0
    vol_ratio = last24 / avg_day if avg_day > 0 else 1.0

    # Whale-selling proxy from hourly bars
    med_vol = median(usd[-168:]) or 1
    dump_bars = [c for c in h1[-24:]
                 if c["volume"] * c["close"] > cfg["whale_volume_mult"] * med_vol
                 and (c["open"] - c["close"]) / c["open"] * 100 >= cfg["whale_drop_pct"]]
    red_vol = sum(c["volume"] * c["close"] for c in h1[-24:] if c["close"] < c["open"])
    sell_share = red_vol / last24 if last24 > 0 else 0

    return {
        "ticker": base,
        "narrative": narrative_of(base, cfg),
        "price": price,
        "spread_pct": spread_pct,
        "usd_volume_24h": usd_volume_24h,
        "ret_24h": ret(closes, 24),
        "ret_3d": ret(closes, 72),
        "ret_7d": ret(closes, 168),
        "ret_30d": ret(dcloses, 30),
        "above_ema20_1h": closes[-1] > e20[-1],
        "ema20_over_ema50_1h": e20[-1] > e50[-1],
        "ema50_1h_rising": e50[-1] > e50[-25],
        "above_ema20_1d": dcloses[-1] > de20[-1],
        "ema20_over_ema50_1d": de20[-1] > de50[-1],
        "atr_1h": a1,
        "atr_pct": a1 / price * 100 if price else 0,
        "vol_ratio": vol_ratio,
        "swing_low_24h": min(c["low"] for c in h1[-24:]),
        "high_14d": max(c["high"] for c in d1[-14:]),
        "dump_bars_24h": len(dump_bars),
        "sell_volume_share_24h": sell_share,
    }


def trend_score(f):
    s = 0
    s += 15 if f["above_ema20_1h"] else 0
    s += 20 if f["ema20_over_ema50_1h"] else 0
    s += 20 if f["ema50_1h_rising"] else 0
    s += 20 if f["above_ema20_1d"] else 0
    s += 25 if f["ema20_over_ema50_1d"] else 0
    return float(s)


def volume_score(f):
    # 1x normal volume = 50, 2x = 83, ~2.8x+ = 100, 0.5x = 17
    return clamp(50 + 33.3 * log2(f["vol_ratio"]))


# ---------------------------------------------------------------- Step 3
def relative_strength(feats, bench):
    """Excess return vs BTC, ETH, SOL and sector median; ranked 0-100."""
    sector = {}
    for f in feats:
        sector.setdefault(f["narrative"], []).append(f)
    sector_med = {k: (median([x["ret_24h"] for x in v]), median([x["ret_7d"] for x in v]))
                  for k, v in sector.items()}

    raw = {}
    for f in feats:
        detail = {}
        for b in ("BTC", "ETH", "SOL"):
            if b in bench:
                detail[f"vs_{b}"] = round(
                    (0.4 * (f["ret_24h"] - bench[b]["ret_24h"])
                     + 0.6 * (f["ret_7d"] - bench[b]["ret_7d"])) * 100, 2)
        m24, m7 = sector_med[f["narrative"]]
        detail["vs_sector"] = round((0.4 * (f["ret_24h"] - m24) + 0.6 * (f["ret_7d"] - m7)) * 100, 2)
        f["rs_detail"] = detail
        raw[f["ticker"]] = sum(detail.values()) / len(detail)
    ranks = percentile_ranks(raw)
    for f in feats:
        f["rs_score"] = ranks[f["ticker"]]


# ---------------------------------------------------------------- Step 2
def narrative_scores(feats, cfg):
    mom = percentile_ranks({f["ticker"]: f["ret_7d"] for f in feats})
    groups = {}
    for f in feats:
        groups.setdefault(f["narrative"], []).append(f)
    out = {}
    for name in list(cfg["narratives"]) + ["Other"]:
        members = groups.get(name, [])
        if not members:
            out[name] = {"score": None, "members": [], "momentum": None,
                         "breadth": None, "volume": None, "avg_7d_return_pct": None}
            continue
        m = sum(mom[x["ticker"]] for x in members) / len(members)
        breadth = sum(1 for x in members if x["trend_score"] >= 60) / len(members) * 100
        vol = sum(x["volume_score"] for x in members) / len(members)
        score = 0.4 * m + 0.3 * breadth + 0.3 * vol
        if len(members) < 3:      # too few coins to trust - pull toward neutral
            score = 0.5 * score + 25
        out[name] = {
            "score": round(score, 1),
            "members": sorted(x["ticker"] for x in members),
            "momentum": round(m, 1),
            "breadth": round(breadth, 1),
            "volume": round(vol, 1),
            "avg_7d_return_pct": round(sum(x["ret_7d"] for x in members) / len(members) * 100, 2),
        }
    if out["Other"]["score"] is not None:
        out["Other"]["score"] = 50.0   # unknown sector = neutral, by design
    return out


# ---------------------------------------------------------------- Step 4
def risk_profile_score(feats, cfg):
    vol_rank = percentile_ranks({f["ticker"]: f["atr_pct"] for f in feats})
    for f in feats:
        spread_pen = clamp(f["spread_pct"] / cfg["max_spread_pct"] * 100)
        f["risk_score"] = 0.7 * (100 - vol_rank[f["ticker"]]) + 0.3 * (100 - spread_pen)


def composite(f, cfg):
    w = cfg["weights"]
    return (w["trend"] * f["trend_score"] + w["relative_strength"] * f["rs_score"]
            + w["narrative"] * f["narrative_score"] + w["volume"] * f["volume_score"]
            + w["risk"] * f["risk_score"])


# ---------------------------------------------------------------- Step 5
def risk_filter(f, cfg):
    reasons = []
    if f["usd_volume_24h"] < cfg["min_24h_volume_usd"]:
        reasons.append(f"Low liquidity: ${f['usd_volume_24h']:,.0f} 24h volume")
    if f["spread_pct"] > cfg["max_spread_pct"]:
        reasons.append(f"Wide spread: {f['spread_pct']:.2f}%")
    if f["ticker"] in cfg["unlock_blocklist"]:
        reasons.append(f"Token unlock: {cfg['unlock_blocklist'][f['ticker']]}")
    if f["dump_bars_24h"] > 0:
        reasons.append(f"Abnormal selling: {f['dump_bars_24h']} heavy-volume dump bar(s) in 24h")
    elif f["sell_volume_share_24h"] >= cfg["whale_sell_share"]:
        reasons.append(f"Abnormal selling: {f['sell_volume_share_24h']*100:.0f}% of 24h volume on red bars")
    return reasons


# ---------------------------------------------------------------- Step 6
def trade_levels(f, cfg):
    entry = f["price"]
    atr_stop = entry - cfg["stop_atr_mult"] * f["atr_1h"]
    swing_stop = f["swing_low_24h"] * 0.995
    stop = min(atr_stop, swing_stop)                # the wider of the two
    dist_pct = (entry - stop) / entry * 100
    dist_pct = max(cfg["min_stop_pct"], min(cfg["max_stop_pct"], dist_pct))
    stop = entry * (1 - dist_pct / 100)
    r = entry - stop

    t1 = entry + cfg["t1_r"] * r
    resistance = f["high_14d"]
    if entry + r < resistance < t1:                 # cap T1 at nearby resistance
        t1 = resistance
    t2 = max(entry + cfg["t2_r"] * r, t1 + r)
    # Blended R:R for the plan: half off at T1, half at T2
    rr = (0.5 * (t1 - entry) + 0.5 * (t2 - entry)) / r
    return {"entry": entry, "stop_loss": stop, "target_1": t1, "target_2": t2,
            "risk_reward": rr, "stop_distance_pct": dist_pct}


def signal_for(confidence, cfg):
    for label, floor in cfg["signal_bands"]:
        if confidence >= floor:
            return label
    return "SELL"


def analyse(feats, bench, cfg):
    """Runs steps 2-6 over all coin features. Returns (ranked list, narratives)."""
    for f in feats:
        f["trend_score"] = trend_score(f)
        f["volume_score"] = volume_score(f)
    relative_strength(feats, bench)
    narr = narrative_scores(feats, cfg)
    risk_profile_score(feats, cfg)
    for f in feats:
        f["narrative_score"] = narr[f["narrative"]]["score"] or 50.0
        f["composite"] = composite(f, cfg)
        f["confidence"] = round(f["composite"], 1)
        f["reject_reasons"] = risk_filter(f, cfg)
        f["levels"] = trade_levels(f, cfg)
        f["signal"] = signal_for(f["confidence"], cfg)
        # A coin that fails the risk filter can never be a buy
        if f["reject_reasons"] and f["signal"] in ("STRONG BUY", "BUY"):
            f["signal"] = "HOLD"
    feats.sort(key=lambda f: f["composite"], reverse=True)
    for i, f in enumerate(feats, 1):
        f["rank"] = i
    return feats, narr


# ==========================================================================
# STEPS 7-8: paper trade execution and position management
# ==========================================================================
HOUR = 3600
COOLDOWN_HOURS = 12   # don't re-buy a coin within 12h of closing it


def new_state(cfg, now):
    return {"cash": cfg["starting_capital"], "positions": {}, "closed": [],
            "equity_history": [], "created_at": now, "last_run": None}


def equity(state):
    return state["cash"] + sum(p["qty"] * p["last_price"] for p in state["positions"].values())


def exposure(state):
    return sum(p["qty"] * p["last_price"] for p in state["positions"].values())


def narrative_exposure(state):
    out = {}
    for p in state["positions"].values():
        out[p["narrative"]] = out.get(p["narrative"], 0) + p["qty"] * p["last_price"]
    return out


# ------------------------------------------------------------- helpers
def _sell(state, pos, qty, price, reason, now, cfg, log):
    qty = min(qty, pos["qty"])
    proceeds = qty * price
    fee = proceeds * cfg["fee_pct"] / 100
    entry_fee_share = pos["entry_fee"] * qty / pos["initial_qty"]
    pnl = qty * (price - pos["entry"]) - fee - entry_fee_share
    state["cash"] += proceeds - fee
    pos["qty"] -= qty
    pos["realized_pnl"] += pnl
    pos["exits"].append({"t": now, "qty": qty, "price": price, "reason": reason,
                         "pnl": round(pnl, 2)})
    log.append({"action": "SELL" if pos["qty"] <= 1e-12 else "PARTIAL SELL",
                "ticker": pos["ticker"], "qty": qty, "price": price,
                "reason": reason, "pnl_usd": round(pnl, 2), "t": now})
    if pos["qty"] <= 1e-12:
        cost = pos["initial_qty"] * pos["entry"]
        state["closed"].append({
            "ticker": pos["ticker"], "narrative": pos["narrative"],
            "opened_at": pos["opened_at"], "closed_at": now,
            "entry": pos["entry"], "initial_qty": pos["initial_qty"],
            "pnl_usd": round(pos["realized_pnl"], 2),
            "pnl_pct": round(pos["realized_pnl"] / cost * 100, 2) if cost else 0,
            "r_multiple": round(pos["realized_pnl"] / (pos["r"] * pos["initial_qty"]), 2)
            if pos["r"] else 0,
            "exit_reason": reason,
        })
        state["closed"] = state["closed"][-cfg["closed_trades_kept"]:]
        del state["positions"][pos["ticker"]]


# ------------------------------------------------------------- Step 8
def manage_positions(state, hourly_by_ticker, feats_by_ticker, now, cfg):
    """Replay every completed hourly bar since the last check against each
    open position. Conservative: if a bar touches both the stop and a target,
    we assume the stop was hit first."""
    log = []
    slip = cfg["slippage_pct"] / 100
    for ticker in list(state["positions"]):
        pos = state["positions"][ticker]
        bars = [b for b in hourly_by_ticker.get(ticker, [])
                if b["t"] > pos["last_bar_t"] and b["t"] + HOUR <= now]
        f = feats_by_ticker.get(ticker)
        if f:
            pos["atr"] = f["atr_1h"]
        for b in bars:
            pos["last_bar_t"] = b["t"]
            # 1) stop first
            if b["low"] <= pos["stop"]:
                fill = min(b["open"], pos["stop"]) * (1 - slip)
                why = ("Trailing stop" if pos["t1_hit"] else
                       "Breakeven stop" if pos["be_moved"] else "Stop loss")
                _sell(state, pos, pos["qty"], fill, why, now, cfg, log)
                break
            # 2) after +1R, stop to breakeven
            if not pos["be_moved"] and b["high"] >= pos["entry"] + pos["r"]:
                pos["stop"] = max(pos["stop"], pos["entry"])
                pos["be_moved"] = True
                log.append({"action": "STOP TO BREAKEVEN", "ticker": ticker,
                            "price": pos["entry"], "t": now})
            # 3) Target 1: take 50%
            if not pos["t1_hit"] and b["high"] >= pos["t1"]:
                _sell(state, pos, pos["initial_qty"] * 0.5, pos["t1"],
                      "Target 1 (50% profit taken)", now, cfg, log)
                if ticker not in state["positions"]:
                    break
                pos["t1_hit"] = True
                pos["highest"] = max(pos["highest"], b["high"])
            # 4) trail the rest
            pos["highest"] = max(pos["highest"], b["high"])
            if pos["t1_hit"]:
                trail = pos["highest"] - cfg["trail_atr_mult"] * pos["atr"]
                if trail > pos["stop"]:
                    pos["stop"] = trail
            pos["last_price"] = b["close"]
        if ticker in state["positions"] and f:
            pos["last_price"] = f["price"]

    # Signal-driven exits on what's still open
    for ticker in list(state["positions"]):
        pos = state["positions"][ticker]
        f = feats_by_ticker.get(ticker)
        if not f:
            continue
        price = f["price"] * (1 - slip)
        if f["signal"] == "SELL":
            _sell(state, pos, pos["qty"], price, "SELL signal", now, cfg, log)
        elif f["signal"] == "REDUCE" and not pos["t1_hit"] and not pos.get("reduced"):
            _sell(state, pos, pos["qty"] * 0.5, price, "REDUCE signal (half)", now, cfg, log)
            if ticker in state["positions"]:
                pos["reduced"] = True
                pos["stop"] = max(pos["stop"], pos["entry"])
    return log


# ------------------------------------------------------------- Step 7
def check_entry(f, state, now, cfg):
    """Returns (ok, reason). Every rule from Step 7 is checked here."""
    if f["signal"] != "STRONG BUY":
        return False, "Not a STRONG BUY"
    if not f["confidence"] > cfg["min_confidence"]:
        return False, f"Confidence {f['confidence']} not above {cfg['min_confidence']}"
    if not f["levels"]["risk_reward"] > cfg["min_rr"]:
        return False, f"R:R {f['levels']['risk_reward']:.2f} not above {cfg['min_rr']}"
    if f["reject_reasons"]:
        return False, "Failed risk filter"
    if f["ticker"] in state["positions"]:
        return False, "Already held"
    recent = [c for c in state["closed"] if c["ticker"] == f["ticker"]
              and now - c["closed_at"] < COOLDOWN_HOURS * HOUR]
    if recent:
        return False, "Cooling off after recent exit"
    if len(state["positions"]) >= cfg["max_open_positions"]:
        return False, "Max open positions reached"
    return True, ""


def size_position(f, state, cfg):
    eq = equity(state)
    lv = f["levels"]
    fill = lv["entry"] * (1 + cfg["slippage_pct"] / 100)
    r = fill - lv["stop_loss"]
    if r <= 0:
        return 0, fill, "Bad stop"
    qty = eq * cfg["risk_per_trade_pct"] / 100 / r
    caps = {
        "position cap": eq * cfg["max_position_pct"] / 100,
        "total exposure cap": eq * cfg["max_total_exposure_pct"] / 100 - exposure(state),
        "narrative cap": eq * cfg["max_narrative_exposure_pct"] / 100
                         - narrative_exposure(state).get(f["narrative"], 0),
        "cash": state["cash"] / (1 + cfg["fee_pct"] / 100),
    }
    value = qty * fill
    limiter = "risk per trade"
    for name, cap in caps.items():
        if value > cap:
            value, limiter = cap, name
    if value < 25:   # not worth a trade
        return 0, fill, f"No room left ({limiter})"
    return value / fill, fill, limiter


def open_positions(ranked, state, hourly_by_ticker, now, cfg):
    log, skipped = [], []
    for f in ranked:
        if f["signal"] != "STRONG BUY":
            continue
        ok, why = check_entry(f, state, now, cfg)
        if not ok:
            skipped.append({"ticker": f["ticker"], "reason": why})
            continue
        qty, fill, limiter = size_position(f, state, cfg)
        if qty <= 0:
            skipped.append({"ticker": f["ticker"], "reason": limiter})
            continue
        value = qty * fill
        fee = value * cfg["fee_pct"] / 100
        state["cash"] -= value + fee
        lv = f["levels"]
        bars = hourly_by_ticker.get(f["ticker"], [])
        last_done = max((b["t"] for b in bars if b["t"] + HOUR <= now), default=now)
        state["positions"][f["ticker"]] = {
            "ticker": f["ticker"], "narrative": f["narrative"], "opened_at": now,
            "entry": fill, "qty": qty, "initial_qty": qty, "entry_fee": fee,
            "stop": lv["stop_loss"], "initial_stop": lv["stop_loss"],
            "r": fill - lv["stop_loss"], "t1": lv["target_1"], "t2": lv["target_2"],
            "be_moved": False, "t1_hit": False, "highest": fill,
            "realized_pnl": 0.0, "exits": [], "last_bar_t": last_done,
            "last_price": f["price"], "atr": f["atr_1h"],
            "confidence_at_entry": f["confidence"],
        }
        log.append({"action": "BUY", "ticker": f["ticker"], "qty": qty, "price": fill,
                    "value_usd": round(value, 2), "fee_usd": round(fee, 2),
                    "stop_loss": lv["stop_loss"], "target_1": lv["target_1"],
                    "target_2": lv["target_2"], "confidence": f["confidence"],
                    "risk_reward": round(lv["risk_reward"], 2),
                    "sized_by": limiter, "t": now})
    return log, skipped


# ------------------------------------------------------------- Step 9 helpers
def record_equity(state, now, cfg):
    state["equity_history"].append({"t": now, "equity": round(equity(state), 2)})
    keep = cfg["equity_history_days"] * 24 + 24
    state["equity_history"] = state["equity_history"][-keep:]


def pnl_since(state, now, seconds, cfg):
    hist = state["equity_history"]
    eq_now = equity(state)
    past = [h for h in hist if h["t"] <= now - seconds]
    # Before the account is that old, measure from the starting capital
    base = past[-1]["equity"] if past else cfg["starting_capital"]
    usd = eq_now - base
    return {"usd": round(usd, 2), "pct": round(usd / base * 100, 2) if base else 0}


# ==========================================================================
# STEP 9: dashboard report
# ==========================================================================
HOUR, DAY = 3600, 86400


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _p(x):
    """Round a price to 6 significant figures ($90,123.4 or $0.0000123456)."""
    if not x:
        return x
    return float(f"{x:.6g}")


def opportunity_row(f):
    lv = f["levels"]
    return {
        "rank": f["rank"],
        "ticker": f["ticker"],
        "narrative": f["narrative"],
        "signal": f["signal"],
        "confidence": f["confidence"],
        "entry": _p(lv["entry"]),
        "stop_loss": _p(lv["stop_loss"]),
        "target_1": _p(lv["target_1"]),
        "target_2": _p(lv["target_2"]),
        "risk_reward": round(lv["risk_reward"], 2),
        "stop_distance_pct": round(lv["stop_distance_pct"], 2),
        "scores": {
            "trend": round(f["trend_score"], 1),
            "relative_strength": round(f["rs_score"], 1),
            "narrative": round(f["narrative_score"], 1),
            "volume_expansion": round(f["volume_score"], 1),
            "risk_profile": round(f["risk_score"], 1),
            "composite": round(f["composite"], 1),
        },
        "relative_strength_pct": f["rs_detail"],
        "market": {
            "price": _p(f["price"]),
            "change_24h_pct": round(f["ret_24h"] * 100, 2),
            "change_7d_pct": round(f["ret_7d"] * 100, 2),
            "change_30d_pct": round(f["ret_30d"] * 100, 2),
            "volume_24h_usd": round(f["usd_volume_24h"]),
            "volume_vs_7d_avg": round(f["vol_ratio"], 2),
            "volatility_atr_1h_pct": round(f["atr_pct"], 2),
            "spread_pct": round(f["spread_pct"], 3),
        },
        "risk_filter": {"passed": not f["reject_reasons"], "reasons": f["reject_reasons"]},
    }


def build_report(state, ranked, narratives, bench, actions, skipped, now, cfg, source):
    eq = equity(state)
    feats = {f["ticker"]: f for f in ranked}

    open_pos = []
    for p in state["positions"].values():
        value = p["qty"] * p["last_price"]
        unreal = p["qty"] * (p["last_price"] - p["entry"]) - p["entry_fee"] * p["qty"] / p["initial_qty"]
        total = unreal + p["realized_pnl"]
        open_pos.append({
            "ticker": p["ticker"], "narrative": p["narrative"],
            "opened_at": _iso(p["opened_at"]),
            "entry": _p(p["entry"]), "current_price": _p(p["last_price"]),
            "qty": p["qty"], "value_usd": round(value, 2),
            "weight_pct": round(value / eq * 100, 2) if eq else 0,
            "stop_loss": _p(p["stop"]), "initial_stop": _p(p["initial_stop"]),
            "target_1": _p(p["t1"]), "target_2": _p(p["t2"]),
            "stop_at_breakeven": p["be_moved"], "target_1_hit": p["t1_hit"],
            "trailing": p["t1_hit"],
            "unrealized_pnl_usd": round(unreal, 2),
            "realized_pnl_usd": round(p["realized_pnl"], 2),
            "total_pnl_usd": round(total, 2),
            "r_multiple": round(total / (p["r"] * p["initial_qty"]), 2) if p["r"] else 0,
            "current_signal": feats[p["ticker"]]["signal"] if p["ticker"] in feats else None,
        })

    closed = state["closed"]
    wins = [c for c in closed if c["pnl_usd"] > 0]
    perf = ([{"ticker": c["ticker"], "status": "closed", "pnl_usd": c["pnl_usd"],
              "pnl_pct": c["pnl_pct"], "r_multiple": c["r_multiple"]} for c in closed]
            + [{"ticker": o["ticker"], "status": "open", "pnl_usd": o["total_pnl_usd"],
                "pnl_pct": round(o["total_pnl_usd"] / (o["entry"] * state["positions"][o["ticker"]]["initial_qty"]) * 100, 2),
                "r_multiple": o["r_multiple"]} for o in open_pos])
    perf.sort(key=lambda x: x["pnl_usd"], reverse=True)

    nexp = narrative_exposure(state)
    by_signal = {k: [] for k, _ in cfg["signal_bands"]}
    for f in ranked:
        by_signal[f["signal"]].append(f["ticker"])

    narr_list = [{"narrative": k, **v} for k, v in narratives.items() if v["score"] is not None]
    narr_list.sort(key=lambda x: x["score"], reverse=True)

    return {
        "schema_version": 1,
        "generated_at": _iso(now),
        "mode": "mock" if source.startswith("SIMULATED") else cfg["mode"],
        "data_source": source,
        "disclaimer": "Paper trading only. Signals are mechanical outputs of a scoring "
                      "model, not financial advice. No real orders are placed.",
        "market": {
            "universe_size": len(ranked),
            "benchmarks": {k: {"price": _p(v["price"]),
                               "change_24h_pct": round(v["ret_24h"] * 100, 2),
                               "change_7d_pct": round(v["ret_7d"] * 100, 2)}
                           for k, v in bench.items()},
            "breadth_pct_in_uptrend": round(sum(1 for f in ranked if f["trend_score"] >= 60)
                                            / len(ranked) * 100, 1) if ranked else 0,
        },
        "narratives": narr_list,
        "signals_summary": {k: len(v) for k, v in by_signal.items()},
        "signals_by_type": by_signal,
        "opportunities": [opportunity_row(f) for f in ranked],
        "rejected": [{"ticker": f["ticker"], "reasons": f["reject_reasons"]}
                     for f in ranked if f["reject_reasons"]],
        "execution": {
            "rules": {"min_confidence": cfg["min_confidence"], "min_risk_reward": cfg["min_rr"],
                      "risk_per_trade_pct": cfg["risk_per_trade_pct"],
                      "max_position_pct": cfg["max_position_pct"],
                      "max_open_positions": cfg["max_open_positions"],
                      "max_total_exposure_pct": cfg["max_total_exposure_pct"],
                      "max_narrative_exposure_pct": cfg["max_narrative_exposure_pct"],
                      "fee_pct": cfg["fee_pct"], "slippage_pct": cfg["slippage_pct"]},
            "actions_this_run": [dict(a, t=_iso(a["t"])) for a in actions],
            "strong_buys_not_taken": skipped,
        },
        "portfolio": {
            "portfolio_value": round(eq, 2),
            "cash": round(state["cash"], 2),
            "invested": round(exposure(state), 2),
            "exposure_pct": round(exposure(state) / eq * 100, 2) if eq else 0,
            "starting_capital": cfg["starting_capital"],
            "pnl": {
                "daily": pnl_since(state, now, DAY, cfg),
                "weekly": pnl_since(state, now, 7 * DAY, cfg),
                "monthly": pnl_since(state, now, 30 * DAY, cfg),
                "all_time": {"usd": round(eq - cfg["starting_capital"], 2),
                             "pct": round((eq / cfg["starting_capital"] - 1) * 100, 2)},
            },
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "closed_trades": len(closed),
            "avg_r_multiple": round(sum(c["r_multiple"] for c in closed) / len(closed), 2) if closed else None,
            "open_positions": open_pos,
            "exposure_by_narrative": [
                {"narrative": k, "value_usd": round(v, 2), "pct_of_portfolio": round(v / eq * 100, 2)}
                for k, v in sorted(nexp.items(), key=lambda kv: -kv[1])],
            "largest_winners": [x for x in perf if x["pnl_usd"] > 0][:5],
            "largest_losers": sorted([x for x in perf if x["pnl_usd"] < 0],
                                     key=lambda x: x["pnl_usd"])[:5],
            "recent_closed_trades": [dict(c, opened_at=_iso(c["opened_at"]),
                                          closed_at=_iso(c["closed_at"])) for c in closed[-20:]][::-1],
        },
        "equity_curve": [{"t": _iso(h["t"]), "equity": h["equity"]}
                         for h in state["equity_history"][-24 * 30:]],
    }


# ==========================================================================
# HOURLY RUN
# ==========================================================================
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
    return new_state(CFG, now)


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
        f = features(base, h1, d1, tk, usd, CFG)
        if f:
            feats.append(f)
    log(f"{len(feats)} coins had enough history to score")
    if not feats:
        log("No data - aborting without changing anything")
        sys.exit(1)

    ranked, narratives = analyse(feats, bench, CFG)
    by_ticker = {f["ticker"]: f for f in ranked}

    actions = manage_positions(state, hourly, by_ticker, now, CFG)
    new, skipped = open_positions(ranked, state, hourly, now, CFG)
    actions += new
    record_equity(state, now, CFG)
    state["last_run"] = now

    rep = build_report(state, ranked, narratives, bench, actions, skipped, now, CFG, client.name)
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
