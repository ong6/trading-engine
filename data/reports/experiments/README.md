# Research experiment evidence

This family contains two different evidence lifecycles. Read the current strategy decision ledger
at [`../../../docs/strategy-research-backlog.md`](../../../docs/strategy-research-backlog.md)
before treating any result as actionable.

## Prospective evidence still accumulating

- [`e1-spy-monday-forward.md`](e1-spy-monday-forward.md) is the generated paper-only E1 report.
  Its sibling JSON is the machine-readable checkpoint projection, and
  [`e1-spy-monday.md`](e1-spy-monday.md) preserves the frozen experiment declaration. The record
  must reach exactly 40 eligible observations before its one-time gate is judged; partial results
  do not authorize an early decision.

## Completed historical studies

- [`fixed-etf-rebalancing-v1/`](fixed-etf-rebalancing-v1/) — `REJECT-V1`.
- [`gross-voltarget-matched-static/`](gross-voltarget-matched-static/) —
  `INCONCLUSIVE-LEGACY`, closed.
- [`sell-in-may-spy-v1/`](sell-in-may-spy-v1/) — `REJECT-V1`.
- [`turn-of-month-spy-v1/`](turn-of-month-spy-v1/) — `REJECT-V1`.
- [`vix-term-spy-v1/`](vix-term-spy-v1/) — `REJECT-V1`.

Each directory contains its own human-readable result and machine-readable decision. These closed
studies do not authorize parameter tuning, a nearby variant, a paper portfolio, broker access, or
live capital. Reopening a mechanism requires a genuinely new hypothesis and a newly frozen
charter, not reinterpretation of the retained result.
