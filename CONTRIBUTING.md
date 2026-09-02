# Contributing

This is one person's research engine, published so the methodology can be read and
reused. Issues and pull requests are welcome; expect slow replies.

- **Read `docs/how-it-works.md` first.** The honesty rules there are not negotiable:
  never invent a price, point-in-time tables are append-only, no same-bar fills,
  every strategy is pre-registered with a kill criterion before evidence accrues.
- **Tests:** `python -m pytest -q` must pass. Tests use in-memory DuckDB only and
  never touch a live store or the network.
- **Prove by running, not by inspection.** A PR that changes the simulator, the
  screen or the fill model should show a before/after replay.
- **Data:** the repo ships no market data. `store/`, `data/eod/`, `data/screens/`
  are regenerated locally by the nightly.
- **No broker code.** Execution against real money is out of scope by design.
