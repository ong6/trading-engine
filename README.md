# trading-engine

A fully local mock trading bot + research engine on one devbox: real market data in DuckDB,
a nightly Minervini screen, **21 active paper portfolios** (18 historically replayable
rules) against a conservative next-open fill simulator, a gated discretionary
paper-trading UI, and a backtest/experiment farm that works the box overnight. No broker,
no real money, and no credentials. Generated public data may be pushed only when the current
branch has a configured upstream. The `source_control` object in `GET /meta` is authoritative for
the current tracking state; `local-only` means Git is not an off-machine backup.

**Agents start at [`AGENTS.md`](AGENTS.md)** — the operating contract (maintain mode,
admission test, budgets). Humans: **[`docs/README.md`](docs/README.md)** — the documentation index and current
strategy/evidence status. The operating guide is
[`docs/how-it-works.md`](docs/how-it-works.md).

- Design specs (the law): [`docs/design/`](docs/design/) — engine design (§12 wins on
  conflict) + execution design (§7 exit criteria).
- Live-readiness handoff: [`docs/live-readiness-goal.md`](docs/live-readiness-goal.md) —
  data quality, algorithm-only/agent-only/hybrid paper evidence, recoverability,
  broker-paper, independent-risk, and recovery gates. It permits only gated paper-agent
  automation and does not authorize live trading.
- Current decision ledger: [`docs/strategy-research-backlog.md`](docs/strategy-research-backlog.md),
  including the ordered
  [next admissible actions](docs/strategy-research-backlog.md#next-admissible-actions).
  Current runtime evidence comes from `GET /meta`, the Dashboard prospective-evidence cards,
  and generated forward reports. [`docs/review-2026-09-06.md`](docs/review-2026-09-06.md) is a
  detailed dated historical snapshot, as are the 2026-09-02 evaluation and architecture review.
- Build state + every decision and incident: [`BUILDLOG.md`](BUILDLOG.md).
- Latest completed nightly league standings: [`data/reports/league.md`](data/reports/league.md).
- Historical replays of every book: [`data/reports/backtests/`](data/reports/backtests/).
- Deterministic Sunday walk-forward re-validation:
  [`data/reports/walkforward/`](data/reports/walkforward/) — run by
  `engine/run_weekly_walkforward.sh`, not by the weekday nightly. The former autonomous model
  review is retired; these historical reports inform only an explicit human review and cannot
  change a book or authorize trading.
- Frozen prospective paper reviews:
  [`sector_momentum`](data/reports/forward/sector_momentum.md) and
  [`xs_momentum_12_1`](data/reports/forward/xs_momentum_12_1.md). These accumulate new
  evidence only; neither can promote a strategy or authorize live trading.
- Faster prospective experiment:
  [`e1-spy-monday`](data/reports/experiments/e1-spy-monday-forward.md) records exactly 40
  settled Monday open-to-close observations, then applies its frozen kill gate. It is
  evidence-only and cannot promote a strategy or place an order.

## Daily rhythm

Cron fires `engine/run_daily.sh` at 22:30 UTC weekdays: universe refresh → collect → resolve
the breadth-qualified operational date → screen → corporate-actions fetch/reconcile → league
step → two frozen forward reviews → E1
forward experiment → sync → farm (intraday/signals/earnings and Friday fundamentals
through the resource-capped job queue). Health snapshot lands in `data/_meta.json`; the
run log in `logs/cron.log`. Full walk-forward revalidation is a separate Sunday job.
The primary EOD collector and the queued network collectors release DuckDB during HTTP/retry
waits and between bounded writes, so API/UI reads are not locked out for an entire multi-minute
or multi-hour pull. EOD price batches commit independently; backfill batches checkpoint their
price rows, completion flags, and job progress in one transaction.

The former agentic layer (AI-gated/tuned books + news analyst) was **retired 2026-08-18** and moved to
[`archive/agentic-2026-08/`](archive/agentic-2026-08/README.md) — its books are `active = FALSE`;
that README covers what it was and why it was retired. Any replacement follows the current
goal's new structured, separately attributed paper-agent path; it does not reactivate or reuse
the retired implementation or its evidence.

## Running it yourself

```bash
uv venv --python 3.12 .venv
uv sync --extra dev --frozen
.venv/bin/python -m pytest -q -W error             # full suite, warnings are failures
.venv/bin/ruff check .                             # active Python; archive is immutable history
.venv/bin/python -m engine.universe                # build the ticker universe
.venv/bin/python -m engine.collect --bootstrap-floor   # first backfill (hours; see how-it-works)
engine/run_daily.sh                                  # one nightly, end to end
```

The repo ships no market data and no credentials. `store/` (the DuckDB) and `data/eod/`
are regenerated locally; `data/screens/` and `data/reports/` are the committed outputs.
Paper trading only — see the notice in `LICENSE`.

## Quick checks

```bash
tail -50 logs/cron.log            # did last night finish? ("=== done ...")
cat data/reports/league.md        # standings
cat data/_meta.json               # collection/mining health
systemctl --user status trading-engine-api.service trading-engine-ui.service \
  trading-engine-agent-data-capture.timer trading-engine-agent-shadow.timer --no-pager
curl -fsS http://127.0.0.1:8000/research/readiness  # research-data admission only
curl -fsS http://127.0.0.1:8000/meta                 # scheduler: production 5/5 + postflight 1/1
curl -fsS http://127.0.0.1:8000/agent/data/corporate-actions
curl -fsS http://127.0.0.1:8000/agent/data/provider-responses
curl -fsS http://127.0.0.1:8000/agent/data/independent-price-evidence
.venv/bin/python -m tools.adjudicate_agent_data_discrepancy status
.venv/bin/python -m tools.review_agent_data_discrepancy list
curl -fsS http://127.0.0.1:8000/agent/fault-drills
curl -fsS http://127.0.0.1:8000/agent/shadow/control # operator-controlled shadow schedule
curl -fsS http://127.0.0.1:8000/daily-opportunities/status # P8 decisions, alerts, and paper state
.venv/bin/python -m tools.verify_friday_postflight  # inspect Friday; publishing is opt-in
```

The API, production UI, agent-data-capture timer, and agent-shadow timer are enabled user units
bound to local operation. The data timer retains normalized price and corporate-action
observations, exact bounded future Yahoo and independent Nasdaq response bodies, and source
observations derived from those exact bytes without a model;
the shadow timer invokes a static worker through the local Trae proxy and remains gated by an explicit
operator control that installation leaves disabled; it has no order authority. User lingering is
enabled, so these
units survive terminal disconnection and restart after reboot. See the operating
guide for installation, restart, logs, SSH-tunnel commands, and the weekend verifier, liquidity,
sweep, and walk-forward schedules.
An auxiliary Saturday postflight records whether Friday's completed nightly published all four
canonical miner receipts. It is read-only with respect to producer, research, and paper-trading
state; its only writes are its own atomic receipt and redirected log. It does not invoke a model
or repair or recreate missing evidence. The receipt is projected by `GET /meta` and becomes a
persistent-header alert only after the first scheduled observation window or a later missed or
failed check.
The installed scheduled command uses `--publish`; manual invocation is non-publishing by default,
so an operator cannot replace the scheduled receipt merely by inspecting current evidence.

Research readiness requires both time and breadth, not merely row counts: stock and
fundamentals dates qualify at 1,000 distinct names, and each 1m/5m intraday session qualifies
at 500 tickers. The dashboard and endpoint count only qualifying dates toward their minimums;
clearing a gate permits drafting a charter, not activating a strategy or claiming profit.
The `walkforward_evidence` object in `GET /meta` independently validates every active
walk-forward result's live config identity and complete source, protocol-window, fill, universe,
capital, execution, data-snapshot, and comparison cohort. A completed weekly driver does not by
itself make older research artifacts current.

## Guardrails (short form)

Never fabricate a price. Point-in-time tables are append-only. Every strategy/experiment is
pre-registered with a kill criterion before evidence accrues. Orders fill next-open, never
same-bar. One DuckDB writer at a time — heavy work goes through the job queue. Prove by
running, never by code inspection. Full rules: [`docs/how-it-works.md`](docs/how-it-works.md).
