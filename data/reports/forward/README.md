# Frozen prospective paper evidence

This directory contains generated observations for already-registered paper comparisons. The
Markdown files are human-readable projections; their sibling JSON files are the machine-readable
checkpoints validated by `GET /meta`. The live endpoint is authoritative for current validity and
status, while each generated pair owns the full frozen boundary and accumulated evidence.

Neither monitor optimizes parameters, promotes a strategy, places an order, connects to a broker,
or authorizes live capital. `ACCUMULATING` and `WAITING` are incomplete evidence. Even a future
`CONTINUE` verdict would mean only that a predeclared downside rule did not fire—not that the
candidate has established a profitable edge.

## Registered monitors

- [`sector_momentum.md`](sector_momentum.md) and
  [`sector_momentum.json`](sector_momentum.json) compare the sector-rotation candidate with its
  frozen SPY control from the 2026-09-04 baseline. The test needs a full 12-month window and at
  least 200 shared sessions before applying its kill criterion.
- [`xs_momentum_12_1.md`](xs_momentum_12_1.md) and
  [`xs_momentum_12_1.json`](xs_momentum_12_1.json) compare unscreened 12-1 momentum with the
  equal-weight screened control. The monitor remains `WAITING` until its frozen 2026-09-30 signal
  and next-open transition can establish the 2026-10-01 baseline; maturity then requires the
  declared five-year window and at least 48 paired complete months.

See the current decision ledger in
[`../../../docs/strategy-research-backlog.md`](../../../docs/strategy-research-backlog.md) before
interpreting either record.
