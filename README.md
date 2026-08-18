# trading-engine

A fully local mock trading bot + research engine on one devbox: real market data in DuckDB,
a nightly Minervini screen, a paper-trading **league** of 17+ pre-registered strategies
against a conservative next-open fill simulator, a gated discretionary paper-trading UI,
and a backtest/experiment farm that works the box overnight. No broker, no real money, no
credentials; nothing leaves the machine except public-data git pushes.

**Start here: [`docs/how-it-works.md`](docs/how-it-works.md)** — architecture, the nightly
pipeline, the honesty rules, the ops runbook, and how to view the UI over SSH.

- Design specs (the law): [`../personal-data-store/trading/`](../personal-data-store/trading/)
  — engine design (§12 wins on conflict) + execution design (§7 exit criteria).
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

The agentic layer (`agents/`, `engine/news_analyst.sh`) was **retired 2026-08-18** — its crons
are removed and the five AI books plus their two frozen twins are `active = FALSE`. The scripts
and charters remain on disk; re-enabling is a crontab edit. See BUILDLOG 2026-08-18.

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
