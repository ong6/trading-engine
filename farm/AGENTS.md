# farm/ — agent notes

Research execution: pre-registered experiments, walk-forward revalidation, the shared backtest
core and the P15/P16 evaluation science. Nothing here places a paper order.

- **Shared backtest core** (`study/`): point-in-time panels, named costs, benchmarks, statistics,
  sealed holdouts, reports, the data-coverage auditor (`audit.py`) and runnable `examples/`.
  Standard: [`../docs/change/backtest-standard.md`](../docs/change/backtest-standard.md).
- **Research control plane** (`research/`): StudySpec runner, sandboxed workers, immutable cache.
- **Walk-forward** (`walkforward/`): the Sunday revalidation of every active league rule.
- **Experiments**: `experiment.py`, `experiment_runner.py`, `experiments/` (frozen registrations),
  and the closed historical studies (`*_experiment.py`).
- **Replay and text labs**: `replay/` (point-in-time historical replay), `textlab/`.
- **Statistics and evaluation**: `stats/`, `p16_*` (evaluation v2, sequential tests, trials,
  optimizer, fill calibration, operator digest), `p15_event_runner.py`,
  `agent_evaluation_analysis.py`.
- **Sweeps** (`sweep/`): explicit parameter sweeps over existing strategies; recurring grids are
  empty by design.

Local rules: every study declares its control, costs, sample rule, trial count and kill criterion
before running; never tune a frozen rule after seeing results; historical output stays isolated
from canonical evidence until its cohort identity validates. Strategy-specific studies belong in
the private alpha repo. Speed changes must prove identical outputs.
