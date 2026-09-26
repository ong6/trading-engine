# Generated research and paper evidence

This directory mixes current paper observations with historical research artifacts. Start with
the current decision ledger in
[`../../docs/strategy-research-backlog.md`](../../docs/strategy-research-backlog.md), then use
`GET /meta` for live producer validity, freshness, and monitor status. A favorable number in any
generated report is not by itself evidence of a profitable strategy and does not authorize a
paper promotion, broker connection, or live capital.

## Prospective paper evidence

- [`forward/`](forward/) contains the generated sector and cross-sectional momentum forward
  reviews. Its family guide separates their maturity boundaries; the reports own the detailed
  frozen observations and verdicts, while `GET /meta` owns their current validity and status.
- [`experiments/`](experiments/) contains the accumulating, prospectively frozen E1 record as
  well as completed historical studies. Its guide separates those evidence lifecycles.
- [`league.md`](league.md) is the latest completed nightly standings snapshot for active paper
  portfolios. It is an operational snapshot, not proof of an edge.
- [`league.csv`](league.csv) is the complete historical paper-equity export, including retired
  portfolios. It is intentionally broader than the active-only Markdown standings.
- [`agent-evaluation.json`](agent-evaluation.json) is the nightly, deterministic P11/P12 scorecard
  for canonical agent traces, mature labels, compatible policy pairs, execution quality, and
  contamination-probe status. Empty or immature cohorts remain explicit and never imply promotion.
- [`agent-eval/`](agent-eval/) contains the human-readable P15 gate report generated from the same
  validated projection as the JSON scorecard.

## Historical and implementation evidence

- [`walkforward/GUIDE.md`](walkforward/GUIDE.md) maps the latest published historical
  walk-forward cohort and its retained archives. It is historical validation, not independent
  prospective evidence; `GET /meta` field
  `walkforward_evidence` determines whether the cohort is current for the deployed source and
  registered configurations.
- [`backtests/GUIDE.md`](backtests/GUIDE.md) maps the in-sample historical reports, whose generated
  index documents survivor and point-in-time limitations. Absolute returns are not edge evidence.
- [`sweeps/`](sweeps/) is the retained archive of closed parameter grids. It is not a promotion
  queue and does not authorize nearby reruns.
- [`capital-sensitivity/`](capital-sensitivity/) records sampled capacity and execution-cost
  tolerance. Those implementation bounds do not establish profitability.
- [`metrics/`](metrics/) is the drift-metrics table published at the end of every agent
  session by `tools.metrics_snapshot` (code size per layer, commit shape, BUILDLOG hygiene,
  research counters, budget status). Definitions live in `docs/metrics.md`. It measures the
  repository, not the market, and is not by itself evidence of anything about a strategy.
- [`execution-drag.md`](execution-drag.md) is a dated execution-timing diagnostic over the paper
  fills then on record, including fills from books that are now retired. It is not a current
  strategy ranking.
