# trading-engine

A fully local mock trading bot + research engine on one devbox: real market data in DuckDB,
a nightly Minervini screen, a paper-trading **league** of 17+ pre-registered strategies
against a conservative next-open fill simulator, a gated discretionary paper-trading UI,
and a backtest/experiment farm that works the box overnight. No broker, no real money, no
credentials; nothing leaves the machine except public-data git pushes.

**Start here: [`docs/how-it-works.md`](docs/how-it-works.md)** — architecture, the nightly
pipeline, the honesty rules, the ops runbook, and how to view the UI over SSH.

- Design specs (the law): [`docs/design/`](docs/design/) — engine design (§12 wins on
  conflict) + execution design (§7 exit criteria).
- Where things stand: [`docs/evaluation-2026-09-02.md`](docs/evaluation-2026-09-02.md)
  (every book KEEP/WATCH/RETIRE with the deciding fact) and
  [`docs/architecture-review-2026-09-02.md`](docs/architecture-review-2026-09-02.md).
- Build state + every decision and incident: [`BUILDLOG.md`](BUILDLOG.md).
- Current league standings: [`data/reports/league.md`](data/reports/league.md).
- Historical replays of every book: [`data/reports/backtests/`](data/reports/backtests/).
- Weekly walk-forward re-validation (feeds the Sunday review):
  [`data/reports/walkforward/`](data/reports/walkforward/) — run by
  `engine/run_weekly_walkforward.sh`, not by the weekday nightly.

## Daily rhythm

Cron fires `engine/run_daily.sh` at 22:30 UTC weekdays: collect → screen → corporate-actions
reconcile → league step → sync → farm (intraday/earnings/fundamentals/backtests through the
resource-capped job queue). Health snapshot lands in `data/_meta.json`; the run log in
`logs/cron.log`.

The agentic layer (AI-gated/tuned books + news analyst) was **retired 2026-08-18** and moved to
[`archive/agentic-2026-08/`](archive/agentic-2026-08/README.md) — its books are `active = FALSE`;
that README covers what it was, why it went, and how to re-enable it.

## Running it yourself

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt
.venv/bin/python -m pytest -q                      # 190+ tests, in-memory DuckDB, no network
.venv/bin/python -m engine.universe              # build the ticker universe
.venv/bin/python -m engine.collect --bootstrap-floor   # first backfill (hours; see how-it-works)
engine/run_daily.sh                                # one nightly, end to end
```

The repo ships no market data and no credentials. `store/` (the DuckDB) and `data/eod/`
are regenerated locally; `data/screens/` and `data/reports/` are the committed outputs.
Paper trading only — see the notice in `LICENSE`.

## Quick checks

```bash
tail -50 logs/cron.log            # did last night finish? ("=== done ...")
cat data/reports/league.md        # standings
cat data/_meta.json               # collection/mining health
```

## Guardrails (short form)

Never fabricate a price. Point-in-time tables are append-only. Every strategy/experiment is
pre-registered with a kill criterion before evidence accrues. Orders fill next-open, never
same-bar. One DuckDB writer at a time — heavy work goes through the job queue. Prove by
running, never by code inspection. Full rules: [`docs/how-it-works.md`](docs/how-it-works.md).
