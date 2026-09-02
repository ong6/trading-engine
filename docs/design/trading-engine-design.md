
# 🏗️ Trading Engine — Specification

**Status: spec finalized 2026-07-16 — all open decisions settled (§11). No code written,
no repo created yet.** This document specifies `trading-engine` — a new sibling repo that
turns the always-on devbox into a daily market-data + screening engine feeding this store.
Next step: scaffold M0 on the devbox (build there directly — see §8).

> **Related research (2026-07-15):**
> [Retail algo trading — viability & direction](../../research/trading-engine/retail-algo-trading-direction.md) —
> multi-agent evidence review + verified backtests. Its Part 7 proposes amendments to this spec
> (regime field, daily point-in-time snapshots, 5y backfill, Stooq-blocked contingency).

## 0 · Settled decisions

These are final and baked into everything below — not up for re-litigation in review:

| Decision | Value |
|---|---|
| Repo | **`trading-engine`**, cloned as a **sibling of this store** on every machine (skills here read `../trading-engine/data/`; on Windows/WSL that's `~/coding/trading-engine`, on the devbox it sits next to wherever the store is cloned) |
| Primary data source | **Stooq** — keyless bulk EOD OHLCV |
| Split | Multi-GB DuckDB (`store/market.duckdb`) is **devbox-only and gitignored**; only compact derived outputs commit and sync |
| Runtime | **Devbox** (32 cores / 62 GB RAM / 119 GB root disk, Debian 10, always on — see [devices](../../life/tech/devices.md)) runs the engine; every other machine only pulls outputs |
| Phase 1 target | **Daily screener**: Stooq → DuckDB → Minervini trend template (all 8 checks) + IBD-style RS-rank → ranked candidate list syncing back |
| Positioning (2026-07-15, per [research](../../research/trading-engine/retail-algo-trading-direction.md)) | **Decision-support + risk-management engine** feeding the discretionary playbook process — not an autonomous alpha bot. Screener = candidate *filter* (proxies documented factors); expectations anchored to the factor literature, and past performance does not model future results |
| Capital base (2026-07-15) | **≈ S$50k (~US$39k)** reference notional, US market from Singapore. Strategy families: momentum + mean reversion, value via ETF sleeve |
| **Scope revision (2026-07-16)** | **The devbox build is a fully local MOCK trading bot + research engine — no broker connection, no credentials, no Telegram, nothing leaves the machine except public-data git pushes.** Real-money execution (moomoo) is a deferred future phase on personal hardware — see [trading-execution-design.md](trading-execution-design.md). Full scope in **§12** |
| Compute goal (2026-07-16) | **Work the box fully, never overload it**: full-US universe scanning (thousands of names, not 550), a backtest farm on idle cores, a multi-portfolio paper league, and continuous data mining/archiving (§12) — all heavy work goes through a job queue with capped workers and load/RAM/disk guards (§12.7), so the engine can never overrun the machine |

---

## 1 · Motivation — the ceiling of the current design

The trading workspace is an excellent **judgment store** (theses, levels, invalidations,
lessons). Its weak point is the **data layer**, in exactly the ways an always-on box fixes:

- **Every run re-scrapes live.** Yahoo 429s, latency, no cache. A scan is only as good as
  stockanalysis/finviz being up that minute.
- **No history = bluffed checks.** "Big move since last scan" and "3-week time stop" have no
  time series to diff against. Rolling RS, real 50d slope, base-tightening — unavailable.
- **No candidate generation.** The watchlist is hand-fed. Nothing sweeps the market *for* you.
- **Scheduling is ephemeral** (the trading README says so outright).

The devbox removes all four. First deliverable: a daily screener that pulls the market into
a local database and produces a ranked candidate list on every machine by morning.

---

## 2 · Architecture — two repos, clean split

`personal-data-store` is **synced across every machine**; only the **devbox is always
running**. So the engine and its heavy data must NOT live in the synced judgment store.
They get their own repo, and only **compact derived outputs** sync back.

```
personal-data-store/        ← THIS repo. Synced everywhere. Judgment + query layer.
  trading/                     watchlist, theses, skills — role UNCHANGED.
                               Skills gain read-only access to ../trading-engine/data/.

trading-engine/             ← NEW repo. Sibling clone next to this store on every machine.
  engine/                   ← committed, small. Runs ONLY on the devbox.
    collect.py                 Stooq bulk EOD → DuckDB
    screen.py                  Minervini template + RS rank over the universe
    sync.py                    write compact outputs, git commit + push
    universe.py                build/refresh the ticker universe
    lib/                       shared: db, indicators, stooq client
    run_daily.sh               orchestrator (pull → collect → screen → sync)
    requirements.txt / pyproject
  data/                     ← committed, small, readable from ANY machine
    screens/2026-07-15.md      ranked candidates (human)
    screens/2026-07-15.csv     same (machine)
    screens/latest.md → symlink/copy of newest
    eod/<TICKER>.csv           last ~250 bars for watchlist names only
    universe.csv               current screened universe + index membership
    _meta.json                 last run timestamp, row counts, source health
  store/                    ← GITIGNORED. Devbox-only.
    market.duckdb              full universe OHLCV history (big; re-screen/backtest)
  logs/                     ← GITIGNORED. run logs.
  .gitignore                   store/, logs/, .venv/, __pycache__/
```

**Daily data flow:**

1. **Devbox**, post-US-close (cron): `run_daily.sh` → `collect.py` (Stooq → DuckDB)
   → `screen.py` (rank) → `sync.py` (write `data/` outputs, `git commit && git push`).
2. **Any laptop:** `git pull` in `trading-engine` → today's screen is a **local file**.
   A skill in this repo reads `../trading-engine/data/screens/latest.md` and surfaces new names.

**The invariant:** the multi-GB `market.duckdb` never leaves the devbox (gitignored). Only
the ranked list + small EOD windows for names actually being watched sync. The payload stays
git-friendly, and this store's rule holds — *regenerable machine data = gitignored; the
engine scripts = committed.*

---

## 3 · Data sources

Primary is **Stooq** (keyless, reliable bulk EOD) — a real upgrade over per-ticker Yahoo scraping.

| Purpose | Source | Notes |
|---|---|---|
| **EOD OHLCV** (history + daily) | Stooq per-symbol CSV: `https://stooq.com/q/d/l/?s={ticker}.us&i=d` | Full history first run; incremental after. Polite loop (~550 names). Bulk DB download is the upgrade path. |
| **Universe list** | **Nasdaq Trader symbol directory** (`nasdaqtraded.txt`, keyless — all US-listed stocks/ETFs), + Wikipedia S&P 500 / Nasdaq 100 tables for index-membership *tags* | Directory daily, index tags weekly; cached in `data/universe.csv`, membership snapshots append-only (§11). |
| Fundamentals / earnings date | Existing free scrape (stockanalysis.com) — **unchanged**, run inside `/analyze-stock` | Engine is price/technicals only for v1; fundamentals stay in the interactive skill. |
| Filings | SEC EDGAR — **unchanged** | Interactive skill only. |

**Universe:** full US market with a liquidity floor, ~4,000–6,000 names (§12.1 — supersedes
the original "S&P 500 ∪ NDX ≈ 550" v1 default). Reports lead with the liquid-large slice so
output stays high-signal.

**Failure handling:** if Stooq fails for a ticker, keep the last good bar, mark it stale in
`_meta.json`, and **never fabricate a bar** — the screener skips names whose data is stale
past a threshold. This is the workspace's "never invent a price" rule, enforced in code.

**Stooq contingency (2026-07-15):** Stooq was found **blocked from at least one network**
(returns an HTML block page instead of CSV). Verify it works from the devbox before Phase 1;
`collect.py` ships with a **yfinance fallback** either way (yfinance verified working with
21y of daily history).

---

## 4 · Data model (DuckDB)

Single embedded file `store/market.duckdb`. Columnar SQL, reads/writes Parquet, no server.

```sql
-- Core EOD history. The source of truth the screener reads.
CREATE TABLE prices (
  ticker     VARCHAR NOT NULL,
  date       DATE    NOT NULL,
  open       DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume     BIGINT,
  source     VARCHAR DEFAULT 'stooq',
  fetched_at TIMESTAMP,
  PRIMARY KEY (ticker, date)
);

-- What we screen, and where each name comes from.
CREATE TABLE universe (
  ticker  VARCHAR PRIMARY KEY,
  name    VARCHAR,
  member  VARCHAR,          -- 'SPX' | 'NDX' | 'SPX,NDX'
  added   DATE,
  active  BOOLEAN DEFAULT TRUE
);

-- One row per ticker per screen run — the screener's output, also mirrored to CSV/MD.
CREATE TABLE screen_results (
  run_date        DATE, ticker VARCHAR,
  close           DOUBLE,
  rs_rank         INTEGER,     -- 1..99 percentile across universe
  template_score  INTEGER,     -- 0..8 Minervini checks passed
  passes_template BOOLEAN,     -- template_score = 8 AND rs_rank >= 70
  dist_50d        DOUBLE, dist_200d DOUBLE,   -- % from MA
  off_52w_low     DOUBLE, off_52w_high DOUBLE,-- % above low / below high
  base_tight      BOOLEAN,     -- range contraction flag
  vol_dryup       BOOLEAN,     -- volume drying into the base
  new_today       BOOLEAN,     -- entered the passing set vs prior run
  PRIMARY KEY (run_date, ticker)
);
```

History accumulates forever on the devbox, so real backtests and exact "since last scan"
deltas become possible for free.

**Point-in-time discipline (2026-07-15):** `screen_results` and daily `universe` membership
snapshots are **append-only — never overwritten or pruned**. This is what makes Phase 5
backtests survivorship-free; the research run's Minervini backtest failed verification for
exactly this lack (a survivor universe inflated CAGR by ~7pp/yr).

---

## 5 · Screener logic (`screen.py`)

Computed in SQL/pandas over the DuckDB history. Two ingredients: **RS rank** and the
**Minervini trend template** (already the standard in `templates/trade-idea.md`).

### 5.1 RS rank (IBD/Minervini style)

Blended trailing return, percentile-ranked across the universe:

```
raw = 2·ret(63d) + 1·ret(126d) + 1·ret(189d) + 1·ret(252d)     # 63d ≈ 1 quarter
rs_rank = percentile of raw across all active names, scaled 1..99
```

### 5.2 Minervini Trend Template — all 8 checks

Each check is recorded pass/fail; the count is `template_score` (0–8):

1. Close > 150d SMA and > 200d SMA
2. 150d SMA > 200d SMA
3. 200d SMA rising for ≥ 1 month (~21 trading days)
4. 50d SMA > 150d SMA > 200d SMA
5. Close > 50d SMA
6. Close ≥ 30% above 52-week low
7. Close within 25% of 52-week high
8. RS rank ≥ 70

`passes_template = all 8`. Keeping the score (not just the boolean) lets near-misses surface.

### 5.3 Setup-quality flags (informational, not part of the template)

- `base_tight` — recent N-day high/low range contracting vs the prior window (tightening base).
- `vol_dryup` — recent avg volume below its own 50d average (supply drying up).

### 5.4 Ranking & diffing

Passing names sort by `rs_rank` descending. Near-misses (`template_score ≥ 6`) are listed
separately as "watch — one/two checks away." `new_today` diffs the passing set against the
previous run, so "what's new" is exact, not remembered.

### 5.5 Regime gate (added 2026-07-15)

Every run computes `regime`: **SPY close vs its 200d SMA** (`risk-on` / `risk-off`), written
to `_meta.json` and printed in the screen header. Below the 200d: no new swing entries,
reduced size — the single most robust verified finding from the research (SPY max DD
−55% → −21%). Judged on drawdown reduction, never CAGR (it *will* lag buy-and-hold most years).

---

## 6 · Output artifacts (what syncs)

| Artifact | Format | Purpose |
|---|---|---|
| `data/screens/<date>.md` | Markdown tables (see below) | Human-readable daily screen |
| `data/screens/<date>.csv` | Every `screen_results` column | Programmatic use |
| `data/screens/latest.md` | Copy of newest | Stable path skills read |
| `data/eod/<TICKER>.csv` | Last ~250 bars, **watchlist names only** (parsed from `trading/watchlist.md`) | Offline charting/level math on any laptop |
| `data/universe.csv` | Ticker · name · index membership | Current screened universe |
| `data/_meta.json` | `{last_run, universe_size, passing_count, stale_tickers[], stooq_ok, regime}` | One-read freshness/health check for querying machines |

**`data/screens/<date>.md`** exact shape:

```markdown
# Screen — 2026-07-15  (universe: 548 · passing: 22 · new today: 3 · regime: risk-on)

## ✅ Passing (template 8/8, RS ≥ 70) — RS-ranked
| Ticker | Close | RS | 50d | 200d | off low | off high | base | vol | new |
|--------|------:|---:|----:|-----:|--------:|---------:|------|-----|-----|
| TICKR  | 123   | 96 | +4% | +3%  | +71%    | −8%      | tight| dry | ·   |
| ...

## 👀 Near-miss (6–7/8) — one/two checks from passing
| Ticker | Score | Failing checks | RS |
| ...
```

---

## 7 · Sync & git strategy (`sync.py`)

- **Only the devbox writes `data/`.** Laptops read. → no merge conflicts on outputs.
- Laptops may edit `engine/` code and push; `run_daily.sh` runs `git pull --rebase` first.
- gitignore: `store/`, `logs/`, `.venv/`, `__pycache__/`.
- Commit message: `screen: 2026-07-15 (22 passing, 3 new)`. One commit per run.
- Retention: keep daily `screens/` files forever (small markdown/CSV; history is cheap and useful).
- Freshness signal: latest commit time + `_meta.json.last_run`. Skills warn if stale > 2 days.

---

## 8 · Devbox deploy plan

- **Python env:** **`uv`-managed Python 3.12** — Debian 10 ships Python 3.7, too old for
  current DuckDB/pandas, so the system interpreter is never used. Deps from
  `engine/requirements.txt` (`duckdb`, `pandas`, `requests`, `pandas_market_calendars`).
  Corp egress **TLS-intercepts pip** (observed) — trust the corp CA / configure the index
  on first `uv` run; treat that as an M0 task, not a surprise.
- **Schedule:** cron or systemd timer, **~6:30pm ET on US trading days** (after Stooq posts
  EOD). `pandas_market_calendars` gates runs to real sessions (skip weekends/holidays).
- **Bootstrap (first run):** `collect.py --full` backfills ~2y history for the universe
  (one-time, slower); daily runs thereafter are incremental (append latest bar only).
- **Orchestrator** `run_daily.sh`: `git pull --rebase` → `collect.py` → `screen.py` →
  `sync.py` → log to `logs/`. On nonzero exit: leave a `TODO:` breadcrumb, don't push garbage.
- **Build on the devbox directly** (decided 2026-07-16) — the real risks are environmental
  (corp egress blocking Stooq, pip MITM, cron, disk), so the code is written and tested where
  it runs. **M0's literal first task: verify each data source from the devbox network.**
  Laptops only `git pull` outputs. This store never runs the engine.

---

## 9 · How this store queries the engine

- **Path convention:** engine at `../trading-engine/` relative to this repo (sibling clones
  on every machine). A one-line config note records the path; skills degrade gracefully
  (fall back to current live-scrape behavior) if the sibling repo is absent.
- **`/watchlist-scan` gains a step:** read `../trading-engine/data/screens/latest.md`;
  report *"N new names entered the screen"* and cross-check them against watchlist tiers.
- **`/analyze-stock` gains a fast path:** if `../trading-engine/data/eod/<TICKER>.csv`
  exists and is fresh, use it for OHLCV/MA math instead of scraping Yahoo
  (rate-limit-proof, and it has real history).
- **New optional skill `/screen-review`** (later): triage today's screen → propose radar adds.
- `DATA-SOURCES.md` grows a "Local engine (preferred when present)" section at the top.
- **Guardrails preserved:** every synced row carries `fetched_at`; stale/missing data is
  reported as a gap, never invented. The engine *proposes* candidates; the owner still
  decides tiers and sizing.

---

## 10 · Phased roadmap

| Phase | Deliverable | Runs on |
|---|---|---|
| **1 — Screener** (this spec's target) | `trading-engine` repo, collect + screen + sync, daily ranked candidates syncing back | devbox cron |
| 2 — Local-first skills | `/watchlist-scan` + `/analyze-stock` read the engine's cache | any machine |
| 3 — Trigger watcher | always-on Python daemon: checks written triggers/stops vs live quotes every ~10 min RTH → push alert + inbox line. **No LLM.** | devbox systemd |
| 4 — Autonomous weekly run | devbox cron → `claude -p "run /watchlist-scan then /trading-review"`, commits back. `/trading-review` gains rolling live expectancy per setup vs a *decayed* expectation, with pre-registered kill criteria | devbox cron |
| 5 — Universe expansion / backtest | screen thousands of names; backtest on stored history (where the spare cores finally matter). **First two jobs (2026-07-15):** (a) re-run the trend template on the engine's own point-in-time universe with next-open fills — the honest test; (b) validate the regime gate + any mean-reversion sleeve before either touches sizing | devbox |

---

## 11 · Formerly-open questions — all settled 2026-07-16

| # | Question | Decision |
|---|---|---|
| 1 | Backfill depth | **Max available history** (settled 5y on 2026-07-15, superseded by §12.1 the next day) — backtesting headroom is a first-class goal and storage is trivial |
| 2 | Universe source of truth | **Nasdaq Trader symbol directory** (`nasdaqtraded.txt` — keyless, official, covers all US-listed stocks/ETFs), filtered by the §12.1 liquidity floor computed from our own price history. S&P 500 / NDX membership (Wikipedia, refreshed weekly) becomes a *tag* on rows, per §12.1. **Daily membership snapshot archived, append-only** (settled 2026-07-15) |
| 3 | `eod/` cache scope | **Watchlist names + the current passing set** — still bounded (typically well under 100 small CSVs), and laptops can chart any live candidate offline. Anything else is queried on the devbox |
| 4 | Run time | **6:30pm ET on US trading days** (market-calendar gated), plus a **9:30pm ET catch-up pass** that re-fetches only names still stale from the first run — no second full run, no pre-market pull |
| 5 | Push cadence | **One commit per run**: the 6:30pm screen commit; the catch-up pass commits only if it actually changed data. No intraday commits |

---

## 12 · Mock-bot & research-engine scope (2026-07-16) — what we are actually building

**Decision:** the devbox build is a **self-contained mock trading system + research engine.**
No broker API, no Telegram, no credentials of any kind on the machine — its only external
traffic is public market data in and public derived data out (git). Real-money execution is a
**deferred future phase** on personal hardware ([execution design](trading-execution-design.md)
keeps the verified moomoo integration plan for that day). This removes the corp-policy concern
and turns the constraint into the goal: **use the box's idle capacity (32 cores / 62 GB) to
generate evidence — behind the hard caps in §12.7, so the engine can never overrun the machine.**

Where this section conflicts with §2–§10 above, this section wins.

### 12.1 Universe — full US market, not 550 names

All US-listed common stocks + ETFs passing a liquidity floor (price ≥ $3, ~$5M+ median dollar
volume): **~4,000–6,000 names.** Listing source: **Nasdaq Trader symbol directory** (§11.2).
S&P 500 ∪ NDX remains a tag on rows, not the boundary. The screener ranks the whole market;
reports lead with the liquid-large slice so signal density stays high. Backfill: **maximum
available history** (supersedes "5y" — full-history EOD for 5k names ≈ a few GB in DuckDB;
the growth item is the intraday archive, governed by the §12.7 disk watchdog on the 119 GB disk).

### 12.2 Data mining — capture what's free before it expires, append-only, always `as_of`-stamped

| Job | Cadence | Why |
|---|---|---|
| EOD OHLCV, full universe | nightly | The base layer (§3 sources; Stooq bulk or yfinance batched) |
| **Intraday 1m/5m bars** for top ~500 by dollar volume + watchlist | daily pull of the trailing free window | Free sources only expose ~7–60 days back; pulling daily and **archiving forever** compounds into a proprietary intraday dataset nobody can buy cheaply later |
| Universe membership + index constituents snapshot | daily | The point-in-time discipline that makes backtests honest |
| Screen results, ranks, template scores | daily | Same — the engine's own forward record |
| Fundamentals snapshot (mkt cap, PE, EV/EBIT-ish, sector) via free scrape | weekly | Builds point-in-time fundamentals → enables honest **value** strategies in ~6–12 months |
| Earnings calendar | daily | Feeds the earnings risk gate + event studies |

Politeness rules: rate-limited pulls, off-peak scheduling, honest `_meta.json` health reporting;
a source that blocks is recorded as a gap, never hammered.

### 12.3 Backtest farm — idle cores run experiments, under an anti-overfitting protocol

The §12.7 job queue + capped worker pool (**≤ 24 workers**, `nice 19`), fed by:
nightly **walk-forward re-validation** of every active rule; weekend **deep sweeps** (parameter
grids, bootstrap robustness, subperiod/regime splits, cost-sensitivity). The whole-universe
price matrix fits in RAM (~5k × 6k days ≈ hundreds of MB per field), so backtests vectorize
in-memory well within the §12.7 RAM budget.

**Protocol (non-negotiable, from the research):** experiments are **pre-registered** as config
files (hypothesis, parameters, expected effect) before running; the most recent N months are a
**locked holdout** touched only at publication; results report deflated/decay-haircut Sharpe and
the number of variants tried (multiple-testing honesty); every result — negative ones included —
lands in a `results` table + a markdown report in `data/reports/`. The farm exists to **kill bad
ideas cheaply**, not to find a lucky parameter.

**Experiment backlog (2026-07-16, updated same day after the 0DTE research run — see
[research](../../research/trading-engine/0dte-casino-and-earnings-vol.md)):**
- **E1 (approved, pre-registered): SPY Monday-intraday** — buy Monday open, sell Monday close,
  SPY only, mock-bot only. Decayed expectation ≈ +10%/yr gross vs ~1.2–1.5%/yr costs. **Kill:
  after 40 out-of-sample Mondays, mean ≤ 0 or t < 0.5 — no re-optimization.** Forward window
  starts with the league.
- Closed (tested null on daily data): overnight-vs-intraday shift as a strategy, Friday/expiry
  effects, daily mean-reversion. Deferred: gamma-pinning / EOD-drift (needs the intraday archive
  §12.2 to mature + OI snapshots; revisit only with a ≤US$30/mo data path).

### 12.4 Paper league — parallel mock portfolios generate forward out-of-sample evidence

Compute is free, so instead of one mock bot, run **N competing portfolios** (each at the S$50k
reference notional) auto-trading daily against an **internal fill simulator** (next-open fills,
configurable slippage + cost model — no broker needed):

template-top5 · template-top10-with-banding · dual-momentum · MR-overlay (RSI-2/3-down) ·
regime-gated variants of each · equal-weight benchmark · SPY benchmark · **owner's discretionary
paper portfolio** (via the ticket UI — the only human-traded one).

Daily league table in `data/reports/league.md` (equity curves, rolling expectancy vs each
sleeve's pre-registered decayed bar, drawdowns, kill-criterion status). **After 6–12 months this
is real forward evidence about which strategy deserves real money — the exact evidence the
research said cannot be bought.**

### 12.5 What syncs vs what stays

Unchanged invariant, bigger store: `store/market.duckdb` (now including intraday + fundamentals
+ results) stays devbox-only and gitignored; `data/` (screens, league, reports, small EOD
windows) commits and syncs. The mock system's trades live in the engine repo, **not** in this
store's `trades/` (that folder remains reserved for the owner's real/graded trades).

### 12.6 Revised phase cut

| Phase | Deliverable |
|---|---|
| **M0** | Repo scaffold + full-universe collect (EOD backfill, max history) + nightly cron |
| **M1** | Screener over full universe + regime gate + point-in-time snapshots + first synced screen |
| **M2** | Fill simulator + paper league (auto portfolios) + daily league report |
| **M3** | Local UI (FastAPI + Next.js, intranet/localhost — no real money, so no Tailscale/auth complexity): dashboard, ticket flow for the discretionary paper portfolio, league views |
| **M4** | Backtest farm + intraday/fundamentals mining + weekly review integration (§11 loop in the execution doc) |
| **M5 (deferred, gated)** | Real execution via moomoo on personal hardware — only if the league produces a sleeve that clears its bar for ~6+ months |

### 12.7 Resource governance (2026-07-16) — capped by construction

The engine must never contend with the box's day job or with itself. Every heavy job —
backfill, sweep, walk-forward, intraday archiving — goes through **one job queue** (a DuckDB
`jobs` table); nothing spawns ad-hoc worker pools. The queue runner enforces the caps:

| Guard | Cap | Behavior at the cap |
|---|---|---|
| Workers | **≤ 24 of 32 cores**, `nice 19` + `ionice -c3` | Excess jobs wait in queue |
| Load | 5-min load average > ~28, or free RAM < 8 GB | Runner pauses dequeuing; jobs are resumable, so pausing is always safe |
| RAM | Engine processes ≤ **48 GB combined**; each job config declares its memory need | Runner won't start a job that would exceed the budget |
| Disk (`store/`) | Soft cap **60 GB** → warn in `_meta.json`; hard cap **80 GB** | Intraday archiving pauses first; EOD collection is the last thing to stop (119 GB root disk is the real constraint — checked every run) |
| Priority | Nightly loop (collect → screen → league → sync) preempts the farm | Farm drains/pauses during the nightly window |

---

*Next step: scaffold `trading-engine/` on the devbox and build M0–M1 — full-universe collect +
screen end-to-end, first ranked output synced back. M0 opens by verifying each data source
from the devbox network (§8).*
