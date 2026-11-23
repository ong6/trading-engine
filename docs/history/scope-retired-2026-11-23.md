# Scope ledger: retired entries (2026-11-23)

Resolved or superseded "Proposed, not approved" lines and completion notes removed from
`docs/scope.md` during the P25 docs cleanup. Background only.

- 2026-11-03 · **Unblock revision 21 for schema-1 readers without a store copy:** a generation's hot database still holds `prices` (only `intraday_prices`, `bitemporal_facts` and `source_response_receipts` are cold), and trial 375's runner reads `market-latest.duckdb`, its sibling `.json` (`schema_version` 1, `snapshot`, `sha256`, `as_of`) and `prices`. Cheapest path: let the schema-2 manifest also carry `schema_version: 1` and `sha256` (the hot file's recorded hash), with the r21 validator accepting those two keys (pinned `engine/lib/snapshots.py`, so one re-pin and a re-review), then rehearse trial 375's dry-run signal on a generation; separately switch the private `confirm_287.py` to `pin_latest_generation` before its 12-03 epoch.

- 2026-10-20 · **Snapshot-invariant defects with no fix branch** (shadow monitor, first run):
  same-night bars whose next-night re-fetch was skipped stay provisional with impossible opens
  (DDS and SUNC 2026-10-12, CIB 2026-10-16); WLFC's 2026-07-15 bar sits on a third price basis
  after the 3:1 restatement (close 23.00 between 72.33 and 65.33: stored already restated, then
  divided again); the walk-forward runner writes NaN Sharpe and worst-month for zero-volatility
  folds (sector_momentum's first train window, every earnings_context_pead fold), which strict JSON
  readers reject. The 18 unrecorded split-sized breaks and the CRWU and ETHA mixed bases are
  `fix/corporate-actions-split-integrity`'s.
  **Resolved by P24** (`p24/integrity`, merged at `11a9a1f2`, registration revision 16): stale
  provisional bars are re-asked and then retired (`settle_stale_provisional`); a restatement leaves
  bars already on the new scale alone; `engine.repair_integrity` fixed the stored split, WLFC and
  same-night defects and was applied to the live store on 2026-10-22 (18,798 rows); walk-forward
  artifacts store an undefined statistic as null (`1ea61488`).

- 2026-10-10 · **Registered-file observability defects (next registration revision)**: since
  `9a37ac0` `engine/verify_prices.py` prints its full evidence JSON (base64 bodies) to stdout,
  ~13k lines a night and 18 MB a weekly verify; fail-soft stages and units exit 0 when they
  skipped work (TradingView archive under the nightly lock). Outside the revision-14 fix set
  (a–k); its third item, the withheld P15 price-fetch record, was fix (e).
  **Verifier output resolved by P24**: it prints one summary line and keeps its evidence in the
  receipt (`46e993c3`, merged at `11a9a1f2`, registration revision 16). The fail-soft exit-0 item
  is still open.

- 2026-10-02 · **Activation of separately held research strategies**: P21 implements the generic
## Completed issue closure

[P21](plans/p21-operational-issues-and-account-isolation.md) completed the owner-requested
operational fixes, complete independent-source evidence, queue-resolution audit, capture
reliability, separate-account proof and behavior-preserving advisory-complexity work. The
complete metadata snapshot is supported by P15 revision 12's narrow recovery-bundle limit
correction, retained by revisions 13 and 14. Registered source identity changes require a properly rehearsed new revision
before deployment; policies and the research runtime remain unchanged.

## Completed review

The two 2026-10-03 shared-study findings (duplicate bars and terminal-zero cross-checks) were
reproduced and corrected under [P20](plans/p20-engine-and-board-review.md).
The review also covered existing dashboard reliability and setup documentation, with read-only
host inspection and independent acceptance. Frozen strategy and execution rules remain in force.

## Completed from this ledger

- 2026-09-28 · Retired the prose-pinning `tests/test_docs*.py` suite and split
  `docs/operate/how-it-works.md` into the operations runbook plus `docs/architecture/architecture-reference.md` under
  P16 W9.
- 2026-09-18 · Move dated audits under `docs/history/`. Done 2026-09-24 on owner request
  (`feedback.md`); doc tests' path constants followed the move.

<!-- sources: docs/plans/README.md, docs/plans/p15-profitability-evidence-loop.md, docs/plans/p16-challenger-lab-and-text-edge.md, server/trading-engine-p15-events.timer, server/trading-engine-tradingview-history.timer -->
