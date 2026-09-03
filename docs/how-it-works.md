# How the trading engine works

One box, one DuckDB file, one nightly cron. The engine collects real market data, screens
it, runs a paper-trading league of pre-registered strategies against a conservative fill
simulator, mines supporting datasets, and backtests itself — all locally, with nothing
leaving the machine except public-data git pushes. There is **no broker connection and no
real money** (that is M5, deferred, personal-hardware-only by design).

Specs: [`design/trading-engine-design.md`](design/trading-engine-design.md) (§12 wins on
conflict) and [`design/trading-execution-design.md`](design/trading-execution-design.md).
Build history + every decision: [`BUILDLOG.md`](../BUILDLOG.md). This doc is the map, not the law — when it disagrees with
the specs or BUILDLOG, they win.

## The honesty rules (why the design looks like this)

1. **Never invent a price** — a failed fetch is recorded as missing, never filled in.
2. **Point-in-time, append-only** — anything stamped `as_of`/`run_date`/`fetch_as_of`
   (screens, fundamentals, earnings, universe snapshots, corporate actions, macro signals,
   experiment results) is never updated, only appended. Backtests can therefore only see
   what was knowable at the time.
3. **Pre-registration** — every strategy and experiment freezes its hypothesis, expectation,
   and kill criterion in code *before* evidence accrues (`sim/strategies/configs.py`,
   `farm/experiments/*.yaml`). No peeking, no threshold tuning after the fact.
4. **Conservative fills** — orders fill at the *next* session's open with size-dependent
   slippage and a liquidity cap; never same-bar, never at prices we didn't store.
5. **Prove by running** — nothing is "done" from code inspection; every feature ships with
   an end-to-end proof on a DB copy, logged in BUILDLOG.

## Components

```
engine/               data layer + nightly driver
  collect.py            yfinance EOD -> prices (~4.1k liquid names, 19.8M rows, history to 1962)
  universe.py           nasdaqtraded.txt -> universe + append-only daily snapshot (~12.2k names)
  screen.py             Minervini trend-template screen -> screen_results + data/screens/<date>.md
  actions.py            corporate actions: splits/dividends fetch + the reconciler (see below)
  signals.py            macro/flow/sentiment collector -> macro_signals   [branch, merging soon]
  intraday.py           1m/7d + 5m/60d archive for ~1.1k names (raw archive, not a signal source)
  fundamentals.py       weekly point-in-time fundamentals   earnings.py  daily earnings dates
  queue_runner.py       THE job queue (§12.7): sequential drain behind nice/load/RAM/disk guards,
                        resumable jobs, stale-job reclaim, 4h drain budget
  run_daily.sh          the nightly driver (see pipeline below)
sim/                  the paper league
  strategies/           one file per strategy + configs.py (the frozen pre-registrations)
  league.py             creates books, steps one session/day: orders -> fills -> dividends -> MTM
  fills.py              next-open fill model, slippage by median dollar volume, liquidity cap
  portfolio.py          cash/position accounting; state = pure function of (fills, dividends)
  calendar.py           NYSE session calendar helpers
server/               FastAPI backend (localhost:8000) — read endpoints + discretionary tickets
ui/                   Next.js dashboard (localhost:3000), /api/* proxied to :8000
farm/                 research workloads through the queue
  experiment.py         pre-registered experiments (SHA-256 config immutability, locked holdout)
  experiment_runner.py  E1 forward runner — one append-only row per settled out-of-sample Monday
  backtest/             historical replays of the league books (vectorized screen, real day-step)
  execution_drag.py     measures next-open-vs-signal-close cost from our own fills
store/market.duckdb   everything above in one DuckDB (single-writer!)
data/                 committed outputs: screens, league.md, reports, _meta.json health snapshot
logs/                 cron.log + per-run logs (gitignored)
```

**Key tables:** `prices` (a *cache of Yahoo's split-adjusted view* — see reconciler),
`universe` / `universe_snapshot`, `screen_results`, `jobs`, league state in `portfolios` +
`sim_orders/sim_fills/sim_positions/sim_equity/sim_dividends`, discretionary flow in
`disc_tickets` + `audit_log` + `review_markers`, mining in `fundamentals` /
`earnings_calendar` / `intraday_prices`, actions in `corporate_actions` /
`split_adjustments` / `actions_fetch_log`, research in `experiment_results`, signals in
`macro_signals` (post-merge).

## The nightly pipeline (cron, 22:30 UTC weekdays)

`run_daily.sh`, under `set -euo pipefail`, with an `flock` overlap guard and bounded
DB-lock retries. Stage order and failure semantics matter:

| # | Stage | On failure |
|---|---|---|
| 1 | collect (incremental EOD, calendar-gated) | **fatal** |
| 2 | universe refresh | WARN, continue (transient Nasdaq hiccup must not kill the night) |
| 3 | screen (`--skip-if-done`) | **fatal** |
| 4 | actions fetch (incremental: held ∪ pending ∪ core ETFs ∪ screen-top-50) | WARN, continue |
| 5 | actions **reconcile** | **fatal — deliberately.** If we can't verify the price scale, trading on it is worse than skipping a night |
| 6 | league step (one transaction per day — no half-done sessions) | **fatal** |
| 7 | E1 forward experiment row | WARN, continue |
| 8 | sync (commit + push `data/`) | WARN, continue |
| 9 | farm subshell: enqueue intraday (100) → signals (105, post-merge) → earnings (110) → fundamentals (Fridays, 120) → drain the queue | pinned exit 0 — farm failures never fail the nightly |

A failure breadcrumb names the failing stage (`logs/.last_stage`). Queue jobs are resumable;
a killed drain leaves a stale `running` job that the next drain reclaims automatically.

## The corporate-actions reconciler (the subtle one)

Yahoo restates raw OHLC at fetch time, but incremental collection only re-fetches ~5 days —
so the first split in any stored name would leave a permanent scale break in history.
The reconciler (nightly, fatal) adjudicates every known split against what the **stored
series actually shows**: it locates the break by scanning close ratios (never assumes the
ex-date), restates exactly once (watermarked in `split_adjustments`, audited in
`audit_log`), adjusts held positions (qty×ratio, cost÷ratio), and **never guesses** —
ambiguous or contradictory readings are skipped with a TODO for a human. Dividends are
credited to the books as cash (`sim_dividends`), which is what makes `total_return` real
(the BIL hurdle in dual_momentum was inert until this existed). An independent tripwire
flags any held name with a >40% one-session move and no corporate-actions row.

## The league

18 pre-registered books (17 live + `macro_composite` pending merge), all long-only,
$39,000 reference notional, stepped nightly: benchmarks (SPY buy-and-hold, equal-weight,
BIL-hurdled dual momentum), the Minervini template family (top-5 / top-10-banded, each
gated and ungated), mean-reversion overlays, turtle breakout, stop-managed momentum,
sector rotation, low-vol, 52-week-high, PEAD, a human `discretionary` book fed by the UI,
and (soon) the macro-composite allocator driven by non-price signals. Every book's config
carries an expectation and a **kill criterion**; the weekly review judges process, not
outcome. Current standings: `data/reports/league.md`. Historical replays of every book
over 6mo→15y windows: `data/reports/backtests/`.

**Weekly walk-forward re-validation** (`farm/walkforward/`, job kind `walkforward`) is the
input to that review: every active book is re-run over rolling train→validate folds
(24 months train, 12 months validate, stepped 12 months, 6 folds, anchored on the latest
session), one independent replay per fold through the same league day-step. Reports —
including a mechanical PASS / WATCH / REVIEW flag against `ew_benchmark` on the same folds
— land in `data/reports/walkforward/`. It is NOT part of the weekday nightly: run
`engine/run_weekly_walkforward.sh` (intended cadence: Sunday).

## The discretionary path (the UI's reason to exist)

`ui/` (Next, :3000) → `/api` proxy → FastAPI (:8000, localhost-only) → 8 risk gates from
`rules.md` (stop present, R:R ≥ 2, 1%-risk sizing, 4R heat cap incl. pending tickets,
earnings-window ack, playbook named, …). A passing ticket becomes a **pending** `sim_orders`
row in the discretionary book — it fills at the next session's open through the same fill
model as every other book. The server never fills or steps anything. While a queue job
holds the single DuckDB writer lock, the UI degrades honestly (503 / "database busy").

## Viewing the UI from your Mac

The servers bind to localhost only (by design — nothing is exposed on the network).
From your Mac, tunnel both ports over SSH:

```bash
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 <you>@<devbox>
```

then open **http://localhost:3000**. Port 3000 alone is enough for the UI (the `/api`
proxy runs server-side on the devbox); forward 8000 too if you want to curl the API
directly. If you use VS Code Remote-SSH, its Ports panel auto-forwards — click the
forwarded 3000 and it opens in your browser. If the pages 503, a queue job is holding the
DB writer lock — wait for the drain or check `SELECT * FROM jobs WHERE status='running'`.

Restart if needed (both log to `logs/`):

```bash
cd trading-engine
nohup server/run_server.sh >> logs/server.log 2>&1 &                  # FastAPI :8000
(cd ui && nohup ./run_ui.sh >> ../logs/ui.log 2>&1 &)                 # Next.js :3000
```

## Ops runbook — checking on it

```bash
tail -50 logs/cron.log                     # did last night run? look for "=== done"
cat data/_meta.json                        # health snapshot: counts, failures, per-miner blocks
cat data/reports/league.md                 # standings
grep "TODO" logs/cron.log | tail           # reconciler items awaiting a human
.venv/bin/python - <<'EOF'                 # queue state
import duckdb; print(from engine.lib import db; db.connect(, read_only=True)
  .execute("SELECT id,kind,status,created_at FROM jobs ORDER BY id DESC LIMIT 10").fetchall())
EOF
```

Known operational lessons (all learned the hard way, details in BUILDLOG): long background
jobs need `nohup` or a harness-tracked shell — a bare `&` dies with the SSH session; the
DB is single-writer — never run two writers at once (everything goes through the queue or
the nightly's lock-retry); `git checkout` state matters — **cron runs the working tree**,
so it must be left on master; copies for testing must include runtime-created rows (the
07-24 incident: a UI-created book crashed the league because test copies lacked it).

## Resource caps (§12.7, non-negotiable)

Nice-19/ionice for all heavy work; sequential queue drain with load/RAM checks; disk
watchdog at 60/80 GB (store is ~2.2 GiB); 4h drain budget (stops starting jobs, never
kills in-flight); polite fetch pacing per host. The box: 32 cores / 62 GiB, `/data00`
~400 GB free.
