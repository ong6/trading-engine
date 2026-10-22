# History

Dated snapshots kept for provenance. Each one records what was known on its date; its counts,
process state, and recommendations are **not** current. Current truth lives in
[`../scope.md`](../scope.md), [`../plans/README.md`](../plans/README.md), `GET /meta`, and the
generated reports under [`../../data/reports/`](../../data/reports/README.md).

| Date | Document | What it is | Why it is kept |
|---|---|---|---|
| 2026-07-15 → 09-17 | [`buildlog-2026-07-15-to-2026-09-17.md`](buildlog-2026-07-15-to-2026-09-17.md) | Legacy BUILDLOG (pre-v2 format), verbatim | Decisions, incidents and proofs behind every early design choice |
| 2026-08-20 | [`data-sources-audit-2026-08-20.md`](data-sources-audit-2026-08-20.md) | Robustness audit of every market-data source | Why the verifier and fallbacks look the way they do |
| 2026-08-20 | [`evidence-ceiling-2026-08-20.md`](evidence-ceiling-2026-08-20.md) | Why the walk-forward fold count cannot be increased | Why more history cannot manufacture more independent evidence |
| 2026-08-20 | [`fill-model-audit-2026-08-20.md`](fill-model-audit-2026-08-20.md) | Read-only fill-model diagnosis (repro: `docs/repro_fill_integer_clamp.py`) | Diagnosis behind the later fill-model fixes |
| 2026-08-20 | [`leveraged-etf-audit-2026-08-20.md`](leveraged-etf-audit-2026-08-20.md) | Leveraged/inverse ETFs in the universe: classifier and off-by-default exclusion flag | Measurements behind leaving the flag off |
| 2026-08-20 | [`synthesis-price-adjustment-and-fills-2026-08-20.md`](synthesis-price-adjustment-and-fills-2026-08-20.md) | Reverse splits, stranded cash, fill-model synthesis | Explains the fill-model fix over a universe change |
| 2026-09-02 | [`architecture-review-2026-09-02.md`](architecture-review-2026-09-02.md) | Architecture and open-source readiness review, with 2026-09-11 addendum | Source of the package layout and centralized DB opens |
| 2026-09-02 | [`evaluation-2026-09-02.md`](evaluation-2026-09-02.md) | League, research farm and data evaluation | Cited by the XS momentum and multi-asset charters |
| 2026-09-02 | [`incident-tools-2026-09-02/`](incident-tools-2026-09-02/) | Verbatim missed-dividend and false-restatement repair tools | Replays the completed incidents without exposing one-off commands in `engine.*` |
| 2026-09-03 | [`split-restatements-reaudit-2026-09-03.md`](split-restatements-reaudit-2026-09-03.md) | Split-restatement re-audit | Evidence for the corporate-actions reconciler |
| 2026-09-06 | [`review-2026-09-06.md`](review-2026-09-06.md) | Full review, extended with the 2026-09-07 v4 cohort | Last complete narrative review before maintain mode |
| 2026-09-06 | [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md) | Fill-model v4, capital and cost sensitivity | Narrative for `data/reports/capital-sensitivity/` |
| 2026-09-11 | [`recoverability-audit-2026-09-11.md`](recoverability-audit-2026-09-11.md) | Workstream A recoverability inventory | Closure sequence for backup and install automation |
| 2026-09-11 | [`worktree-review-2026-09-11.md`](worktree-review-2026-09-11.md) | Working-tree ownership review | Commit sequence that made the local work releasable |
| 2026-09-17 | [`live-readiness-goal.md`](live-readiness-goal.md) | Former handoff objective (workstreams A–E) | Gates a future execution-layer plan would inherit |
| 2026-09-19 | [`buildlog-2026-09-19-c90-complexity-series.md`](buildlog-2026-09-19-c90-complexity-series.md) | The 42 v2 BUILDLOG entries of the C90 complexity refactor series, verbatim | Per-function evidence behind the one summary entry left in `BUILDLOG.md` |
| 2026-09-22 | [`agent-trading-review-2026-09-22.md`](agent-trading-review-2026-09-22.md) | Agent, cadence, simulator-tool and 2022 replay assessment | Rationale for the daily opportunity agent (P8), multi-cadence tools (P9), and 2022 replay (P10) |
| 2026-09-23 | [`agent-backtesting-roadmap-2026-09-23.md`](agent-backtesting-roadmap-2026-09-23.md) | Point-in-time data, execution and LLM-contamination roadmap | Research behind forward agent evaluation (P11) and the agent research product (P12) |
| 2026-09-23 | [`agent-research-product-completion-audit-2026-09-23.md`](agent-research-product-completion-audit-2026-09-23.md) | Requirement-to-artifact audit for P12 | Proof of P12 completion and its external gates |
| 2026-10-05 | [`p21-source-amendments-2026-10-05.md`](p21-source-amendments-2026-10-05.md) | P21 registered source amendments | Shows which operational corrections changed registered sources and which evidence and activation boundaries stayed fixed |
| 2026-10-08 | [`p22-round4-rehearsals.md`](p22-round4-rehearsals.md) | P22 round-4 disposable-store rehearsal transcripts | Legacy-D0 processing and revision-13 rollback proof behind the engine v2 deployment |
| 2026-10-10 | [`p22-lifecycle-brief-2026-10-10.md`](p22-lifecycle-brief-2026-10-10.md) | The P22 lifecycle writer brief (round-6 rulings), formerly `P22-BRIEF.md` at the root | Superseded by `feedback.md` and the P22 plan; kept so older links resolve |
| 2026-10-18 | [`retired-pit-restore-2026-10-18.md`](retired-pit-restore-2026-10-18.md) | Portable identity and restore procedure for retired PIT inputs | Prevents absent retired databases from being silently recreated empty |
| 2026-10-20 | `commit-map-2026-10-20.txt` (kept privately, not in this tree) | Old-to-new commit IDs from the 2026-10-20 history rewrite | Resolves commit IDs cited in registrations, reports and docs written before the rewrite |
