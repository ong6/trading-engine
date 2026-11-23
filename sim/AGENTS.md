# sim/ — agent notes

The fill simulator, the paper league and the account ledger. Fills are next-open and honest by
design: no same-bar fills, no invented prices.

- **Fills and costs**: `fills.py` (the fill model), `execution.py` (named execution profiles),
  `costs/` (versioned commission profiles: `baseline_v1`, `ibkr_pro_tiered_v1`), `p15_fills.py`.
- **League**: `league.py` (one idempotent day-step), `portfolio.py`, `schema.py`, `book_breaks.py`.
- **Account engine**: `ledger.py` (side-aware cash, lots, fees, replay), `order_types.py`,
  `margin.py`, `shorts.py`, `valuation.py`, `bar_sources.py`, `money_inputs.py`.
- **Strategies**: `strategies/` holds the registry (`__init__.py`), the interface (`base.py`) and
  the pre-registered configs (`configs.py`); research charters are in `docs/charters/`.
- **Settlement**: `settle.py` books dead positions at sourced terms or closes out a delisting
  ([`../docs/settlement-runbook.md`](../docs/settlement-runbook.md)).
- **Calendars**: `nyse.py`, `calendar.py`.

Local rules: a strategy is pre-registered with a kill criterion before it trades; new strategies
belong in the private alpha repo, so add only generic mechanics here. Accounting is one fold from
inception ([`../docs/architecture/paper-account-contract.md`](../docs/architecture/paper-account-contract.md)).
Changing a pinned file needs a registration revision. Proofs: `sim/backtest_shakedown.py` and
`sim/corp_actions_shakedown.py` are plumbing tests, not evidence.
