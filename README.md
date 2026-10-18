# Altcoin Signal Bot (paper trading)

Every hour this bot scans the 100 most-traded altcoins on Coinbase. It scores each coin on trend, relative strength, narrative, volume and risk. It filters out risky coins and generates STRONG BUY / BUY / HOLD / REDUCE / SELL signals. It then **paper-trades** the best ones under strict rules. The results go to a dashboard you can open on your phone.

**It never places real orders and never needs your Coinbase login.** It reads public market data only.

---

## Setup (about 15 minutes, no coding)

### 1. Make a GitHub account
Go to github.com and sign up. The free plan is all you need.

### 2. Create a repository
- Click **+** (top right) → **New repository**.
- Name it `signal-bot`.
- Choose **Public**. That lets the free dashboard hosting work, and only paper-trading numbers are in there. If you'd rather keep it private, see "Private option" below.
- Tick **Add a README file** → **Create repository**.

### 3. Upload the files
- Unzip `signal-bot.zip` on your computer.
- In your new repository click **Add file → Upload files**.
- Drag in **everything inside** the unzipped folder: `bot`, `docs`, `tests`, `run.py` and `README.md`. Then click **Commit changes**.

### 4. Add the hourly schedule (one file, by hand)
Macs and Windows hide folders starting with a dot, so the schedule file usually doesn't upload. Add it like this:
- **Add file → Create new file**.
- In the name box type exactly: `.github/workflows/hourly.yml`
- Open `hourly.yml` from the zip in a text editor. On a Mac, press Cmd+Shift+. in Finder to show hidden files. Copy all of it and paste it in.
- Click **Commit changes**.

### 5. Let the bot save its results
**Settings → Actions → General →** scroll to **Workflow permissions** → choose **Read and write permissions** → **Save**.

### 6. Run it the first time
**Actions** tab → **Hourly signal run** → **Run workflow** → **Run workflow**. A green tick means it worked, after about 2 minutes. After that it runs by itself at 7 minutes past every hour.

### 7. Turn on the dashboard
**Settings → Pages →** Source: **Deploy from a branch** → Branch: **main**, folder **/docs** → **Save**.
After a minute your dashboard is at `https://YOUR-USERNAME.github.io/signal-bot/`. Add it to your phone's home screen.

### Private option
Make the repository **Private** and skip step 7. Instead, in Cloudflare go to **Workers & Pages → Create → Pages → Connect to Git**. Pick the repo, leave the build command empty and set the output folder to `docs`. Cloudflare can also put the dashboard behind a login (Zero Trust → Access).

---

## Changing how it trades

Every setting is in **`bot/config.py`**, with a comment on each line. Edit it on GitHub with the pencil icon. Common ones:

| Setting | Default | Meaning |
|---|---|---|
| `starting_capital` | 10,000 | Fake USD the paper account starts with |
| `min_confidence` / `min_rr` | 80 / 2.5 | Only buy above these (your Step 7) |
| `risk_per_trade_pct` | 1% | Most you lose if a stop is hit |
| `max_position_pct` | 15% | Biggest single coin |
| `max_narrative_exposure_pct` | 30% | Biggest single narrative |
| `max_total_exposure_pct` | 80% | Always keeps 20% in cash |
| `min_24h_volume_usd` | $5M | Liquidity threshold |
| `max_spread_pct` | 0.30% | Spread threshold |
| `unlock_blocklist` | empty | **You fill this in.** See below |
| `narratives` | lists | Which coins count as AI, DeFi, Meme… |

To reset the paper account, delete `data/state.json`.

---

## How each step works

1. **Market scan.** Ranks every Coinbase USD altcoin by 24h dollar volume and keeps the top 100. Stablecoins, wrapped coins, BTC, ETH and SOL are excluded. BTC, ETH and SOL are used as benchmarks.
2. **Narratives.** Each narrative scores 0–100 from three parts:
   - its coins' 7-day momentum (40%)
   - the share of its coins in an uptrend (30%)
   - volume expansion (30%)
   Narratives with fewer than 3 coins are pulled toward neutral. Unlisted coins count as "Other" (a neutral 50).
3. **Relative strength.** Compares each coin's 24h and 7-day return with BTC, ETH, SOL and its own sector's median, then ranks the coins 0–100.
4. **Ranking.** Combines the scores as 30% trend, 25% relative strength, 20% narrative, 15% volume expansion and 10% risk profile.
   - Trend comes from moving averages on hourly and daily charts.
   - Risk profile rewards low volatility and tight spreads.
5. **Risk filter.** Rejects a coin for low liquidity, a wide spread, an upcoming unlock on your list, or abnormal selling.
6. **Signals.** Confidence = the combined score.
   - 80+ is STRONG BUY, 65+ BUY, 45+ HOLD, 30+ REDUCE, and below 30 SELL.
   - A rejected coin is never a buy.
   - Stop loss = the wider of 2× the hourly ATR or just under the 24h low, kept between 1.5% and 12%.
   - Target 1 = 2R, or the 14-day high if that is closer. Target 2 = 4R.
   - R:R is the blended reward if half the position exits at each target.
7. **Execution (paper).** Buys only a STRONG BUY with confidence above 80, R:R above 2.5, a passed risk filter and room under every exposure limit. Each paper trade includes Coinbase's 0.6% fee and 0.1% slippage.
8. **Management.** Every hour the bot replays the last hour's price bars against each open trade:
   - It moves the stop to breakeven at +1R.
   - It sells 50% at Target 1, then trails the rest at 3× ATR.
   - A SELL signal closes the trade. A REDUCE signal sells half.
   - If one bar touched both the stop and a target, it assumes the stop came first.
9. **Reporting.** Writes `docs/report.json` with every number your dashboard shows.

---

## Know the limits

- **Token unlocks aren't automatic.** Coinbase doesn't publish them. Check token.unlocks.app weekly and add big upcoming ones to `unlock_blocklist`, e.g. `"ARB": "16 Nov - 3% supply unlock"`.
- **Whale selling is estimated from price and volume.** The bot flags heavy-volume dump bars and days when most volume is selling. It does not see on-chain wallets.
- **Narrative lists are fixed.** New coins land in "Other" until you add them.
- **GitHub's hourly schedule can run 5–20 minutes late** at busy times. That's fine for this strategy.
- **The simulator (`tests/simulate.py`) uses fake prices.** It proves the rules work, not that the strategy makes money.
- Run it on paper for at least 2–3 months before trusting it. Before any real money goes near it, it would need real-order code, exchange API keys and a careful review. It deliberately has none of that.

This is a mechanical scoring model, not financial advice.

## Files

```
run.py                     one hourly run (python run.py, or --mock for test data)
bot/config.py              all settings
bot/data.py                Coinbase public data + simulated test market
bot/analysis.py            steps 1-6
bot/portfolio.py           steps 7-8 (paper trades)
bot/report.py              step 9 (dashboard JSON)
docs/index.html            the dashboard
docs/report.json           latest results (written every hour)
data/state.json            paper account (written every hour)
tests/simulate.py          hour-by-hour test over a simulated market
.github/workflows/hourly.yml   the hourly schedule
```
