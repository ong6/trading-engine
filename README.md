# trading-engine

A public, paper-only trading engine. It collects daily and intraday market data into a
point-in-time DuckDB store, screens the market nightly, runs paper books through a conservative
next-open fill simulator with commissions, and evaluates strategies and AI policies against frozen,
pre-registered controls. AI models can make paper decisions, but deterministic code owns data
admission, sizing, risk, execution, accounting and halts.

**Paper only.** There is no broker connection, no broker credential and no real money anywhere in
this repository. No strategy here has a proven edge; see the notice in `LICENSE`.

**Public engine, private strategies.** This repo is the reusable infrastructure: data pipeline,
simulator, fill and cost models, evaluation statistics, replay and text labs, the shared backtest
core, paper accounts and a few example strategies. Strategy research, prompts and results are kept
in a separate private repository and reach the engine only through its paper accounts and
backtest core.

## Ground rules

Never fabricate a price. Point-in-time data is append-only. Orders fill at the next open, never on
the bar that produced the signal. One DuckDB writer at a time. Every strategy or experiment is
pre-registered with a kill criterion before its evidence accrues.

## Quick start

Linux and Python 3.12:

```bash
uv venv --python 3.12 .venv
uv sync --extra dev --frozen
.venv/bin/python -m pytest -q -W error -n 8        # full suite; warnings are failures
.venv/bin/python -m engine.universe                # build the ticker universe
.venv/bin/python -m engine.collect --bootstrap-floor   # first backfill (takes hours)
engine/run_daily.sh                                # one nightly run, end to end
```

The repo ships no market store and no credentials: `store/` is rebuilt locally, while
`data/screens/` and `data/reports/` hold the committed outputs. The local API
(`server/run_server.sh`) and dashboard ([`ui/README.md`](ui/README.md)) bind to loopback only and
have no authentication.

## Where to read next

- [`docs/site/index.md`](docs/site/index.md): plain-language guide to how the engine works.
- [`docs/README.md`](docs/README.md): the documentation index (operations, architecture, data,
  testing, deploy).
- [`docs/product.md`](docs/product.md): the goal, what "makes money" means and the current focus.
- [`data/reports/README.md`](data/reports/README.md): the generated evidence and paper standings.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): how to contribute.

AI agents working in this repository start at [`AGENTS.md`](AGENTS.md).
