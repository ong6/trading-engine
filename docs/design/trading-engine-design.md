
# 🏗️ Trading Engine — Specification

**Status: original specification finalized 2026-07-16; implementation is now active.**
This document preserves the governing design decisions and historical build plan for the
implemented `trading-engine`. Statements below about future scaffolding or milestones describe
the document's 2026-07-16 planning state; use [`../how-it-works.md`](../how-it-works.md) for
current operations and [`../README.md`](../README.md) for current evidence status.

> **Related research (2026-07-15):** _Retail algo trading — viability & direction_
> (`personal-data-store/research/trading-engine/retail-algo-trading-direction.md`, retained
> in the private sibling store rather than this repository) — multi-agent evidence review +
> verified backtests. Its Part 7 proposes amendments to this spec
> (regime field, daily point-in-time snapshots, 5y backfill, Stooq-blocked contingency).

## 0 · Settled decisions

These are final and baked into everything below — not up for re-litigation in review:

| Decision | Value |
|---|---|
| Repo | **`trading-engine`**, cloned as a **sibling of this store** on every machine (skills here read `../trading-engine/data/`; on Windows/WSL that's `~/coding/trading-engine`, on the devbox it sits next to wherever the store is cloned) |
| Primary data source | **yfinance** batched EOD OHLCV; Nasdaq historical API is verification-only. Stooq is blocked from this network and is not a runtime fallback. |
| Split | Multi-GB DuckDB (`store/market.duckdb`) is **devbox-only and gitignored**; only compact derived outputs commit and sync |
| Runtime | **Devbox** (32 cores / 62 GB RAM / 119 GB root disk, Debian 10, always on — inventory retained privately at `personal-data-store/life/tech/devices.md`) runs the engine; every other machine only pulls outputs |
| Phase 1 target | **Daily screener**: yfinance → DuckDB → breadth-qualified market date → Minervini trend template (all 8 checks) + IBD-style RS-rank → ranked candidate list syncing back |
| Positioning (2026-07-15, per the private research note cited above) | **Decision-support + risk-management engine** feeding the discretionary playbook process — not an autonomous alpha bot. Screener = candidate *filter* (proxies documented factors); expectations anchored to the factor literature, and past performance does not model future results |
| Capital base (2026-07-15) | **≈ S$50k (~US$39k)** reference notional, US market from Singapore. Strategy families: momentum + mean reversion, value via ETF sleeve |
| **Scope revision (2026-07-16)** | **The devbox build is a fully local MOCK trading bot + research engine — no broker connection, no credentials, and no Telegram. Only public derived data may leave through Git, and only when a usable upstream is configured.** Real-money execution (moomoo) is a deferred future phase on personal hardware — see [trading-execution-design.md](trading-execution-design.md). Full scope in **§12** |
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
    collect.py                 batched yfinance EOD → DuckDB
    market_date.py             fail-closed breadth gate for nightly state
    screen.py                  Minervini template + RS rank over the universe
    sync.py                    write compact outputs, git commit + push
    universe.py                build/refresh the ticker universe
    lib/                       shared: DB, indicators, logging, resources, settings
    run_daily.sh               orchestrator (pull → collect → qualify date → screen/league → sync/farm)
    requirements.txt / pyproject
  data/                     ← committed, small, readable from ANY machine
    screens/2026-07-15.md      ranked candidates (human)
    screens/2026-07-15.csv     same (machine)
    screens/latest.md → symlink/copy of newest
    eod/<TICKER>.csv           last ~250 bars for watchlist + top-100 passing names
    universe.csv               current screened universe + index membership
    _meta.json                 last run timestamp, row counts, source health
  store/                    ← GITIGNORED. Devbox-only.
    market.duckdb              full universe OHLCV history (big; re-screen/backtest)
  logs/                     ← GITIGNORED. run logs.
  .gitignore                   store/, logs/, .venv/, __pycache__/
```

**Daily data flow:**

1. **Devbox**, post-US-close (cron): `run_daily.sh` → `collect.py` (yfinance → DuckDB)
   → `market_date.py` (breadth gate) → `screen.py` and `league.py` on that exact date
   → monitors/verification/farm → `sync.py` (path-limited `data/` commit and conditional push).
2. **Any laptop:** `git pull` in `trading-engine` → today's screen is a **local file**.
   A skill in this repo reads `../trading-engine/data/screens/latest.md` and surfaces new names.

**The invariant:** the multi-GB `market.duckdb` never leaves the devbox (gitignored). Only
the ranked list + small EOD windows for names actually being watched sync. The payload stays
git-friendly, and this store's rule holds — *regenerable machine data = gitignored; the
engine scripts = committed.*

---

## 3 · Data sources

Primary EOD storage is **yfinance**, downloaded in polite batches. The Nasdaq historical API
is an independent comparison source and never writes prices. Stooq remains recorded as blocked;
it is not called by the active collector.

| Purpose | Source | Notes |
|---|---|---|
| **EOD OHLCV** (history + daily) | yfinance | Maximum-history bootstrap/backfill, then batched incremental pulls for active liquid names. |
| **Independent EOD check** | Nasdaq historical API | Read-only comparison; never corrects or inserts a primary price. |
| **Universe list** | Nasdaq Trader symbol directory (`nasdaqtraded.txt`) | Daily active-symbol refresh; index membership is metadata and snapshots are append-only. |
| Fundamentals / earnings dates | yfinance | Weekly/daily point-in-time snapshots; not joined backward into history. |
| Intraday archive | yfinance | Append-only 1m/5m captures; not yet admitted as strategy evidence. |

**Universe:** full US market with a liquidity floor, ~4,000–6,000 names (§12.1 — supersedes
the original "S&P 500 ∪ NDX ≈ 550" v1 default). Reports lead with the liquid-large slice so
output stays high-signal.

**Failure handling:** if yfinance fails for a ticker, keep the last good bar, record the gap in
`_meta.json`, and **never fabricate a bar**. Dead zero-volume flat OHLC rows remain archived but
do not count as real bars. The breadth-qualified gate prevents a partial batch from advancing
nightly state.

**Operational market date:** the unattended nightly must not use raw `MAX(prices.date)`.
After collection, `engine.market_date` selects the latest date with real bars for at least
90% of active liquid names and at least 1,000 names, with the absolute floor capped at the
universe size for a small initialized store. A real bar has positive volume and is not a flat
OHLC dead quote. The resolved ISO date is passed explicitly to both `engine.screen` and
`sim.league`; a partial later batch remains in the append-only archive but cannot advance
screening, orders, fills, or mark-to-market state. A missing liquid universe or the absence of
any qualifying date is fatal for the nightly. Any newer real-bar date that does not itself qualify
is also fatal, including a row for an inactive, non-liquid, or orphaned ticker: frozen downstream
components still inspect the store-wide maximum date. The driver stops before corporate-action
reconciliation and league processing so those components never observe a rejected tail.
All active paper books must also share one latest equity checkpoint, and the qualified date may
be only that same date or the next scheduled NYSE session. A gap is fatal before screening:
automatic reconstruction would otherwise apply a later universe or later-known corporate action
to an earlier decision point.

**Source decision (verified again 2026-08-20):** Stooq returns a proof-of-work HTML page from
this network rather than CSV. The active collector therefore has one primary source, yfinance;
Nasdaq is deliberately verification-only. A source outage creates a visible gap rather than a
silent fallback with different adjustment semantics.

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
  source     VARCHAR DEFAULT 'yfinance',
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
**Minervini trend template** (already the standard in the private sibling store's
`templates/trade-idea.md`; that path is not part of this repository).

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
| `data/eod/<TICKER>.csv` | Last ~250 bars for the private sibling `trading/watchlist.md` names plus the top 100 passing names; if that optional watchlist is absent, passing names still export | Offline charting/level math on any laptop |
| `data/universe.csv` | Ticker · name · index membership | Current screened universe |
| `data/_meta.json` | Collection, source, screen, actions, verifier, mining, and disk-health snapshot | Generated diagnostics; API also computes live DB/queue/forward status independently |

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
- `run_daily.sh` pulls only when the current branch has a resolvable configured upstream; pull
  failure is visible but does not discard the validated local working state.
- `engine.sync` refuses a pre-existing staged index, stages/commits only `data/`, restores only
  its own path after dry-run/failure, and pushes only to the explicitly configured upstream.
- gitignore: `store/`, `logs/`, `.venv/`, `__pycache__/`.
- Commit message: `screen: 2026-07-15 (22 passing, 3 new)`. One commit per run.
- Retention: keep daily `screens/` files forever (small markdown/CSV; history is cheap and useful).
- Freshness signal: the `market_freshness` object in `GET /meta`. Consumers warn only when its status is
  `stale`, meaning at least one scheduled NYSE session strictly before today is absent after the
  breadth-qualified operational date (90% of active liquid names and at least 1,000 real bars).
  Calendar age and `_meta.json.last_run` remain diagnostic context but must not turn weekends or
  exchange holidays into false alarms; a partial later batch must not make the archive look fresh.

---

## 8 · Devbox deploy plan

- **Python env:** **`uv`-managed Python 3.12** — Debian 10 ships Python 3.7, too old for
  current DuckDB/pandas, so the system interpreter is never used. Direct runtime requirements
  live in `engine/requirements.txt`; `pyproject.toml` declares packaging and the dev extra, and
  `uv.lock` must be reviewed and committed as the reproducible environment contract. The current
  worktree review records that this lockfile is still untracked, so `HEAD` is not yet reproducible.
  Corp egress **TLS-intercepts pip** (observed) — trust the corp CA / configure the index
  on first `uv` run; treat that as an M0 task, not a surprise.
- **Schedule:** cron runs `engine/run_daily.sh` at **22:30 UTC on weekdays**. The collector's
  NYSE calendar gate makes weekends/holidays clean no-ops; the qualified-date stage prevents
  the current session or a partial batch from advancing state.
- **Bootstrap (first run):** `collect.py --bootstrap-floor` pulls roughly 90 calendar days to
  establish liquidity, then `collect.py --backfill` fetches maximum available history for the
  liquid universe. Daily runs thereafter are incremental.
- **Orchestrator** `run_daily.sh`: universe → collect → breadth-qualified market-date resolver
  → screen (explicit date) → actions/reconcile → league (same explicit date) → forward monitors
  → sync/verification/farm → log to `logs/`. Fatal failures leave a stage-named `TODO:`
  breadcrumb; partial market data never silently advances paper state.
- **Build on the devbox directly** (decided 2026-07-16) — the real risks are environmental
  (corp egress blocking Stooq, pip MITM, cron, disk), so the code is written and tested where
  it runs. **M0's literal first task: verify each data source from the devbox network.**
  Laptops only `git pull` outputs. This store never runs the engine.

---

## 9 · Historical sibling-store integration plan

This section records the 2026-07-16 plan for the private `personal-data-store`; it is not a
current operating procedure for this repository. The watchlist and template paths below belong
to that sibling store. The proposed skills and `DATA-SOURCES.md` edit were not implemented there,
so their future-tense bullets are provenance, not promises about files that exist here.

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
| 4 — Autonomous weekly run (**retired 2026-08-18**) | The former `claude -p` review loop was removed with the agentic layer after repeated authentication failures and no decision value. Current cron is deterministic; any future model review is separate, paper/report-only, and cannot promote or trade. | retired |
| 5 — Universe expansion / backtest | screen thousands of names; backtest on stored history (where the spare cores finally matter). **First two jobs (2026-07-15):** (a) re-run the trend template on the engine's own point-in-time universe with next-open fills — the honest test; (b) validate the regime gate + any mean-reversion sleeve before either touches sizing | devbox |

---

## 11 · Formerly-open questions — all settled 2026-07-16

| # | Question | Decision |
|---|---|---|
| 1 | Backfill depth | **Max available history** (settled 5y on 2026-07-15, superseded by §12.1 the next day) — backtesting headroom is a first-class goal and storage is trivial |
| 2 | Universe source of truth | **Nasdaq Trader symbol directory** (`nasdaqtraded.txt` — keyless, official, covers all US-listed stocks/ETFs), filtered by the §12.1 liquidity floor computed from our own price history. S&P 500 / NDX membership (Wikipedia, refreshed weekly) becomes a *tag* on rows, per §12.1. **Daily membership snapshot archived, append-only** (settled 2026-07-15) |
| 3 | `eod/` cache scope | **Watchlist names + the current passing set** — still bounded (typically well under 100 small CSVs), and laptops can chart any live candidate offline. Anything else is queried on the devbox |
| 4 | Run time | **22:30 UTC weekdays**, market-calendar gated. There is no second catch-up run; incomplete data fails at the breadth-qualified date gate. A later run may retry the same session, but cannot skip it and reconstruct history using later-known state. |
| 5 | Push cadence | **At most one path-limited `data/` commit per driver run**, only when generated outputs changed; push occurs only when a usable upstream is configured. |

---

## 12 · Mock-bot & research-engine scope (2026-07-16) — what we are actually building

**Decision:** the devbox build is a **self-contained mock trading system + research engine.**
No broker API, no Telegram, no credentials of any kind on the machine — its only external
traffic is public market data in and, only when a usable upstream is configured, public derived
data out through Git. Real-money execution is a
**deferred future phase** on personal hardware ([execution design](trading-execution-design.md)
keeps the verified moomoo integration plan for that day). This removes the corp-policy concern
and turns the constraint into the goal: **use the box's idle capacity (32 cores / 62 GB) to
generate evidence — behind the hard caps in §12.7, so the engine can never overrun the machine.**

Where this section conflicts with §2–§10 above, this section wins.

### 12.1 Universe — full US market, not 550 names

All US-listed common stocks + ETFs passing a liquidity floor (price ≥ $3, ~$5M+ median dollar
volume): **~4,000–6,000 names.** Listing source: **Nasdaq Trader symbol directory** (§11.2).
Nasdaq's authoritative ETF flag takes precedence; rights, warrants, explicit preferred classes,
and dedicated `.U`/terminal-`U` security units are excluded, while ordinary common partnership
units remain eligible. S&P 500 ∪ NDX remains a tag on rows, not the boundary. The screener ranks the whole market;
reports lead with the liquid-large slice so signal density stays high. Backfill: **maximum
available history** (supersedes "5y" — full-history EOD for 5k names ≈ a few GB in DuckDB;
the growth item is the intraday archive, governed by the §12.7 disk watchdog on the 119 GB disk).

### 12.2 Data mining — capture what's free before it expires, append-only, always `as_of`-stamped

| Job | Cadence | Why |
|---|---|---|
| EOD OHLCV, full universe | weekday nightly | The base layer (§3; batched yfinance, with Nasdaq verification-only) |
| **Intraday 1m/5m bars** for top ~500 by dollar volume + watchlist | daily pull of the trailing free window | Free sources only expose ~7–60 days back; pulling daily and **archiving forever** compounds into a proprietary intraday dataset nobody can buy cheaply later |
| Universe membership + index constituents snapshot | daily | The point-in-time discipline that makes backtests honest |
| Screen results, ranks, template scores | daily | Same — the engine's own forward record |
| Fundamentals snapshot (mkt cap, PE, EV/EBIT-ish, sector) via free scrape | weekly | Builds point-in-time fundamentals → enables honest **value** strategies after the readiness gate; `fundamentals_fetch_log` preserves successful and failed attempt history |
| Earnings calendar | daily | Feeds the earnings risk gate + event studies; `earnings_calendar` stores dated observations and append-only `earnings_fetch_log` distinguishes successful empty responses from retryable failures |

Politeness rules: rate-limited pulls, off-peak scheduling, honest `_meta.json` health reporting;
a source that blocks is recorded as a gap, never hammered.
The intraday, signals, action-backfill, earnings, and fundamentals queue jobs remain sequential
and polite, but their supervised children do not pin DuckDB during HTTP waits. They lease the
writer for setup and bounded checkpoints, so API/UI reads can proceed between writes. Intraday
appends each parsed download batch through the idempotent archive insert. Signals uses a read-only
lease for its internal breadth calculation and one short writer lease per source insert. For
actions, earnings, and fundamentals, data rows and append-only fetch outcomes commit
transactionally so they cannot diverge after a crash. Completed action/earnings pulls resume as
complete; failed attempts remain auditable and retryable. Fundamentals requires the snapshot row
itself as completion evidence. The attempt ledgers are `actions_fetch_log`, `earnings_fetch_log`,
and `fundamentals_fetch_log`.
The separate full-universe price verifier similarly materializes its bounded store snapshot and
closes its read-only connection before contacting Nasdaq, so the three-hour verification budget
cannot hold off a scheduled or discretionary writer.

### 12.3 Backtest farm — idle cores run experiments, under an anti-overfitting protocol

The §12.7 job queue + capped worker pool (**≤ 8 parallel-safe workers**, `nice 19`), fed by:
Sunday **walk-forward re-validation** of every historically replayable active rule; Saturday
recurring sweeps only when a versioned charter is explicitly allowlisted (the allowlist is
currently empty). The whole-universe
price matrix fits in RAM (~5k × 6k days ≈ hundreds of MB per field), so backtests vectorize
in-memory well within the §12.7 RAM budget.

**Protocol (non-negotiable, from the research):** experiments are **pre-registered** as config
files (hypothesis, parameters, expected effect) before running; the most recent N months are a
**locked holdout** touched only at publication; results report deflated/decay-haircut Sharpe and
the number of variants tried (multiple-testing honesty); every result — negative ones included —
lands in a `results` table + a markdown report in `data/reports/`. The farm exists to **kill bad
ideas cheaply**, not to find a lucky parameter.

**Experiment backlog (2026-07-16, updated same day after the 0DTE research run documented
privately in `personal-data-store/research/trading-engine/0dte-casino-and-earnings-vol.md`):**
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
sleeve's pre-registered decayed bar, drawdowns, kill-criterion status). Forward evidence is
interpreted only at each strategy's frozen maturity boundary; elapsed time alone neither proves
an edge nor authorizes real money. The current sector monitor requires 12 calendar months and
200 shared sessions, while fundamentals research admission requires 156 breadth-qualified
snapshots spanning at least 1,095 days (and stock selection has its own 756-date/1,095-day gate).

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
| **M3** | Local UI (FastAPI + Next.js, loopback-only via SSH tunnel): dashboard, ticket flow for the discretionary paper portfolio, league views |
| **M4** | Backtest farm + intraday/fundamentals mining + weekly review integration (§11 loop in the execution doc) |
| **M5 (deferred, gated)** | Real execution on personal hardware only after every strategy-evidence, recoverability, broker-paper, independent-risk, reconciliation, and recovery gate in [`../live-readiness-goal.md`](../live-readiness-goal.md) passes |

### 12.7 Resource governance (2026-07-16) — capped by construction

The engine must never contend with the box's day job or with itself. Every heavy job —
backfill, sweep, walk-forward, intraday archiving — goes through **one job queue** (a DuckDB
`jobs` table); nothing spawns ad-hoc worker pools. The queue runner enforces the caps:

| Guard | Cap | Behavior at the cap |
|---|---|---|
| Workers | **≤ 8 parallel-safe jobs**, `nice 19` + `ionice -c3`; all other kinds remain single-worker | Excess jobs wait in queue |
| Load | 5-min load average > ~28, or free RAM < 8 GB | Runner pauses dequeuing; jobs are resumable, so pausing is always safe |
| RAM | Engine processes ≤ **48 GB combined**; each job config declares its memory need | Runner won't start a job that would exceed the budget |
| Disk (`store/`) | Soft cap **60 GB** → warn in `_meta.json`; hard cap **80 GB** | Intraday archiving pauses first; EOD collection is the last thing to stop (119 GB root disk is the real constraint — checked every run) |
| Priority | Nightly loop (collect → screen → league → sync) preempts the farm | Farm drains/pauses during the nightly window |

---

*Current state (2026-09-07): M0–M4 are implemented and remain paper-only. No strategy has
established positive prospective excess return. The active work is to accumulate the frozen
sector, XS, and E1 records, keep the point-in-time archives growing, and admit new research only
through the documented readiness and pre-registration gates. M5 remains deferred; elapsed time
alone does not authorize live execution.*
