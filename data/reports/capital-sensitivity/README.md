# Capital and execution-cost sensitivity archive

These reports replay selected strategies at several account sizes under the baseline and doubled-
cost execution profiles. They answer bounded implementation questions—how returns change with
explicit costs and where sampled participation limits begin to reject orders—not whether a
strategy has a reliable edge.

## Five-year snapshots

- [`dual_momentum/5y/`](dual_momentum/5y/)
- [`sector_momentum/5y/`](sector_momentum/5y/)
- [`spy_benchmark/5y/`](spy_benchmark/5y/)
- [`xs_momentum_12_1/5y/`](xs_momentum_12_1/5y/)

Every row is a complete historical replay at one sampled capital level. A zero-rejection sample
is only a lower bound on tested capacity; it is not a guarantee between samples or in future
markets. Positive standalone return, cost tolerance, or capacity does not establish positive
excess over a proper control. In particular, the XS report remains explicitly survivor-biased.

These are dated research snapshots. The current decision remains in
[`../../../docs/strategy-research-backlog.md`](../../../docs/strategy-research-backlog.md), and
prospective monitor state comes from `GET /meta` and the generated forward reports. Nothing in
this family authorizes paper promotion, broker connectivity, or live capital.
