# History

Dated snapshots kept for provenance. Each one records what was known on its date; its counts,
process state, and recommendations are **not** current. Current truth lives in
[`../scope.md`](../scope.md), [`../plans/README.md`](../plans/README.md), `GET /meta`, and the
generated reports under [`../../data/reports/`](../../data/reports/README.md).

| Date | Document | What it is | Why it is kept |
|---|---|---|---|
| 2026-08-20 | [`data-sources-audit-2026-08-20.md`](data-sources-audit-2026-08-20.md) | Robustness audit of every market-data source | Why the verifier and fallbacks look the way they do |
| 2026-08-20 | [`evidence-ceiling-2026-08-20.md`](evidence-ceiling-2026-08-20.md) | Why the walk-forward fold count cannot be increased | Why more history cannot manufacture more independent evidence |
| 2026-08-20 | [`fill-model-audit-2026-08-20.md`](fill-model-audit-2026-08-20.md) | Read-only fill-model diagnosis (repro: `docs/repro_fill_integer_clamp.py`) | Diagnosis behind the later fill-model fixes |
| 2026-08-20 | [`leveraged-etf-audit-2026-08-20.md`](leveraged-etf-audit-2026-08-20.md) | Leveraged/inverse ETFs in the universe: classifier and off-by-default exclusion flag | Measurements behind leaving the flag off |
| 2026-08-20 | [`synthesis-price-adjustment-and-fills-2026-08-20.md`](synthesis-price-adjustment-and-fills-2026-08-20.md) | Reverse splits, stranded cash, fill-model synthesis | Explains the fill-model fix over a universe change |
| 2026-09-02 | [`architecture-review-2026-09-02.md`](architecture-review-2026-09-02.md) | Architecture and open-source readiness review, with 2026-09-11 addendum | Source of the package layout and centralized DB opens |
| 2026-09-02 | [`evaluation-2026-09-02.md`](evaluation-2026-09-02.md) | League, research farm and data evaluation | Cited by the XS momentum and multi-asset charters |
| 2026-09-03 | [`split-restatements-reaudit-2026-09-03.md`](split-restatements-reaudit-2026-09-03.md) | Split-restatement re-audit | Evidence for the corporate-actions reconciler |
| 2026-09-06 | [`review-2026-09-06.md`](review-2026-09-06.md) | Full review, extended with the 2026-09-07 v4 cohort | Last complete narrative review before maintain mode |
| 2026-09-06 | [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md) | Fill-model v4, capital and cost sensitivity | Narrative for `data/reports/capital-sensitivity/` |
| 2026-09-11 | [`recoverability-audit-2026-09-11.md`](recoverability-audit-2026-09-11.md) | Workstream A recoverability inventory | Closure sequence for backup and install automation |
| 2026-09-11 | [`worktree-review-2026-09-11.md`](worktree-review-2026-09-11.md) | Working-tree ownership review | Commit sequence that made the local work releasable |
| 2026-09-17 | [`live-readiness-goal.md`](live-readiness-goal.md) | Former handoff objective (workstreams A–E) | Gates a future execution-layer plan would inherit |
| 2026-09-22 | [`agent-trading-review-2026-09-22.md`](agent-trading-review-2026-09-22.md) | Agent, cadence, simulator-tool and 2022 replay assessment | Rationale for P8, P9 and P10 |
| 2026-09-23 | [`agent-backtesting-roadmap-2026-09-23.md`](agent-backtesting-roadmap-2026-09-23.md) | Point-in-time data, execution and LLM-contamination roadmap | Research behind P11 and P12 |
| 2026-09-23 | [`agent-research-product-completion-audit-2026-09-23.md`](agent-research-product-completion-audit-2026-09-23.md) | Requirement-to-artifact audit for P12 | Proof of P12 completion and its external gates |
