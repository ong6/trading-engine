# Strategy backlog checkpoints, September 2026 (archive)

Dated live-decision and source-transition checkpoints removed from
`docs/strategy-research-backlog.md`. Background only.

## Live decision checkpoint — 2026-09-12 06:00 UTC

This is a dated observation, not a replacement for the endpoints or generated reports:

- The complete 18-result walk-forward cohort is `current`, with one matching source/data/
  execution signature and no missing, invalid, duplicate, config-mismatched, or
  registration-mismatched artifacts. (Later cohorts replaced this one; the current cohort's
  identities are in [`../data/reports/walkforward/GUIDE.md`](../../data/reports/walkforward/GUIDE.md)
  and `GET /meta` `walkforward_evidence`.)
- Sector momentum is `ACCUMULATING` at 5/200 shared sessions and cannot mature before
  2027-09-04. XS momentum is `WAITING` at 0/48 paired complete months; its first frozen signal is
  2026-09-30 and measurement begins at the post-fill 2026-10-01 boundary.
- E1 is `ACCUMULATING` at 7/40 observations. Its running mean net return is negative and its
  t-statistic is negative, but the predeclared rule forbids an early verdict; the only valid gate
  is the frozen 40-observation decision on 2027-05-10.
- `GET /research/readiness` reports no ready family. Stock selection is 41/756 qualifying dates
  over 57/1,095 calendar days, fundamentals is 9/156 over 55/1,095 days, and intraday is 47/252
  one-minute plus 100/252 five-minute sessions over 65/365 and 143/365 days.
- Recurring sweeps are correctly `idle` with no open charter. Miner evidence is current at 4/4:
  the scheduled Friday run published fresh intraday, signals, earnings, and fundamentals receipts
  from completed jobs 476–479.
- The scheduled Saturday full-universe verifier reached its terminal marker at 05:00:04 UTC after
  its explicit three-hour budget. It checked 3,968/4,093 names: 3,963 agreed, five names produced
  49 field disagreements (17 material), 114 names were left transparently unchecked by the time
  budget, and 11 were not checked because of source fetch/symbol failures. There were no parser
  failures or store-missing sessions, but `GET /meta` correctly reports `price_verification` as
  `issues`, not clean. Read-only adjudication found no active position or pending order in the five
  names and a fresh primary-source pull matched the stored bars. Nasdaq's own current quote showed
  VFLO at $53.88 while its history endpoint returned implausible 83,000–87,000 values; the other
  four names differed by 11–62 bp. That supports a secondary-source anomaly, not confirmation that
  the primary store is wrong, so no quarantine or price rewrite was made.
- The scheduled 05:15 UTC Friday postflight published at 05:15:02 UTC and is `current`, reconciling
  market date 2026-09-11, the successful nightly, and miner jobs 476–479.

The scheduled 06:00 UTC sweep runner then exited cleanly at 06:00:01 with no open recurring
charter, no job enqueued, and `sweep_evidence.status = idle`. Therefore no new strategy run is
currently admitted.

## Source-transition checkpoint — 2026-09-13 02:17 UTC

The first independent Sunday liquidity run started at 02:00:01 UTC and completed at 02:05:14
UTC. It evaluated 8,293 active non-liquid candidates, admitted 141, demoted 162, and moved the
liquid universe from 4,118 to 4,097 names. All 138 pending liquid histories backfilled, with zero
backfill failures and zero names left pending. The 69 candidate download failures remain visible as
`liquidity_evidence.status = issues` rather than being treated as a clean run. Reconciliation
against the official cached Nasdaq directory attributes 68 to securities now excluded by the
corrected common-stock/ETF parser and one to `SVA`, an ordinary share for which Yahoo returned no
data. The parser correction has not been applied retroactively to the live universe; the next
normal universe refresh owns that state transition.

The weekly liquidity producer now retries the complete resumable pending-backfill set on every
real run, including a zero-admission run. Its first independent Sunday run then exposed plural
Nasdaq security-class descriptions that the common-stock/ETF parser did not reject. The parser now
excludes rights, warrants, explicit preferred classes, and dedicated unit symbols while preserving
ETFs, issuer names such as Preferred Bank, and ordinary partnership units such as ET, MPLX, and
PAA. Because collection and universe selection are deliberately included in the XS prospective
source boundary, its exact zero-observation, pre-signal checkpoint was explicitly migrated through
runtime-contract v11 through v20. V20 makes explicit DuckDB transactions interruption-safe without
masking the original failure; v19 releases temporary DuckDB DataFrame views after failed
statements; v18 keeps the borrowed screen connection under its outer owner's single close on the
no-eligible exit; v17 publishes the non-derivable dated screen anchor before row
commit and fails closed on legacy committed rows without it; v16 reconstructs screen and league
companion artifacts when an idempotent retry finds an already committed run; v15 makes universe-cache, screen, league, and
monthly walk-forward artifacts atomic; v14 makes the daily screen and league connections close on every exit; v13 makes
the directory reconciliation and daily snapshot one database transaction and atomically replaces
the derived CSV. XS remains `WAITING` at 0/48 with
no signal boundary and no changed strategy or execution economics.

Those operational corrections first advanced the protected runtime identity, and the subsequent
optimized-Python replay and proof guards advanced the 111-file identity again, including
exception-safe closure for replay, proof, walk-forward, and shakedown scratch database handles,
historical screen and execution-drag CLIs, both queue grids, queue schema initialization, and the
legacy dividend backfill. Daily screen/league ownership, atomic publication, and committed-run
artifact recovery were inside the frozen XS and sector runtime boundaries, so their exact
checkpoints were explicitly migrated through v19 and v8 respectively. The subsequent
breadth-reader and historical-screener cleanup guaranteed removal of temporary SQL relations after
a failed calculation. Centralized interruption-safe transaction cleanup then advanced the exact
checkpoints to XS v20, sector v9, and E1 v6. Every migration changed only contract metadata; no
signal or screening formula, stored observation, strategy rule, execution assumption, or
statistical gate changed.
At this checkpoint the latest published 18-result walk-forward cohort still recorded the previous
source, so `walkforward_evidence.status = stale-source`. That was an explicit provenance
mismatch, not a failed strategy verdict, and the artifacts were not reconstructed or manually
relabelled. The normal Sunday job subsequently completed at 08:45 UTC with the new source;
`walkforward_evidence.status = current`.
The next normal Sunday job completed on 2026-09-20 with all 18 active replayable books and one
cohort signature; live evidence remains `current`. This refresh likewise changes no strategy
verdict or admission gate.
Do not tune a frozen rule, reopen a rejected charter, launch a discretionary sweep, or interpret
the current E1 estimate before its terminal gate.

The canonical observation starts at the shared 2026-09-04 closing marks, when fill model v4 and its
exact `baseline_v1` assumptions were frozen. Earlier July–September league returns remain
operational history but are excluded because they span older fill models. The opening holdings are
inherited and disclosed; no pre-boundary return is credited. The schema-v2 checkpoint now
reconciles those exact inherited positions, cash, position counts, and frozen closes to both
baseline equity rows. It also anchors the complete equity prefix and post-boundary
order/fill/cost/attempt/settlement ledger. Legitimate pending-order status transitions and late
dividend credits remain possible without weakening the immutable event checkpoint. The next gate is
therefore new untouched sessions, not more code or tuning. Sector runtime-contract v10 (current,
`8a91b71295afd533c1d508645daad2b62e9dc80deab506f2b422b095b1b8a2ce`) preserves the isolated
agent-paper lifecycle without changing sector strategy or execution economics. V9 makes explicit
DuckDB transactions interruption-safe and preserves the original failure if rollback also fails;
its exact five-session equity and execution-ledger evidence remain unchanged. V8 releases temporary
DuckDB DataFrame views after failed statements. V7 reconstructs both league reports from committed
ledger state on an idempotently skipped step. V6 atomically replaces league Markdown and CSV
output. V5 makes the daily league connection close on every exit, v4 made the existing no-same-bar
fill rule unconditional under optimized Python, and v3 excluded retired portfolio state from
current verification and corporate-action work. XS runtime-contract v21 (current,
`f7a8a048eb79643f244f08a40dbd328e299644452c03ef95907b6cf5db6c7fac`) preserves the isolated
agent-paper lifecycle before the first signal without changing XS strategy or economics. V20 makes
explicit DuckDB transactions interruption-safe before the first signal. V19 releases temporary
DuckDB DataFrame views after failed statements. V18 keeps the borrowed screen connection open
through the no-eligible return so the outer runtime owns its one close. V17 publishes the dated
screen recovery anchor before committing rows and refuses to recompute committed rows when that
non-derivable anchor is missing. V16 reconstructs screen CSV/EOD exports and league reports from
committed state on idempotent skips before the first signal. V15 makes universe-cache, screen,
league, and monthly walk-forward artifacts atomic. V14 makes the daily screen and league
connections close on every exit. V13 makes directory insert/update/deactivation and daily snapshot
publication one transaction and atomically replaces the derived universe CSV. V12 enforces the
existing common-stock/ETF policy for Nasdaq's plural rights, warrants, preferred classes, and
dedicated unit symbols before the first signal. V11 adds unconditional retry of the complete
resumable pending liquid-backfill set on every real weekly refresh, including zero-admission runs.
V10 makes the same guard unconditional before the first signal. V9 excluded retired portfolio
positions from liquidity protection before the first signal. V8 made malformed shared metadata fail
closed instead of being replaced as an empty snapshot. V7 made an existing screen's stored rows and
report agree before its metadata is restored, with no historical recomputation. V6 made concurrent
publishers serialize the complete read/merge/write operation, routed the screener through the
common helper, and froze that dependency. V5 made EOD collection merge its own counters instead of
erasing independently generated miner, verifier, and screen blocks. V4 changed only
weekly-liquidity dry-run reporting: `liquid_after` became the projected post-reconciliation count
while the store remained unchanged. V3 changed only EOD collector connection lifetime: universe
preparation, Yahoo downloads, bounded batch writes, and final metadata no longer shared one
long-lived DuckDB connection, and backfill state was checkpointed transactionally with each batch.
V2's sole change was corporate-action fetch recovery. Each explicit pre-signal migration verified
the exact prior record, unchanged strategy/execution/statistical rules, no frozen signal boundary,
and no signal-date orders or post-fill observations.

The second priority is a prospectively frozen comparison of `xs_momentum_12_1` with
`ew_benchmark`. Historical XS results cannot establish an edge: the stored
`universe_snapshot` history had only 39 dates beginning 2026-07-16 at the 2026-09-08
pre-nightly baseline, while historical single-stock replays select from today's surviving
names. The apparent historical momentum advantage is therefore explicitly survivor-biased.
Current coverage comes from `GET /research/readiness`; another retrospective rerun or nearby
parameter search would not repair that evidence ceiling.

`engine.xs_forward_review` was frozen before the candidate's first monthly trade. It waits
for the 2026-09-30 signals and uses the first shared close after next-open execution,
expected 2026-10-01, as the baseline. It excludes all legacy EW performance and requires
60 calendar months, at least 48 complete paired months, positive candidate and excess
returns, and a 90% stationary-bootstrap interval on mean monthly excess wholly above
zero. A 55% candidate drawdown or dirty post-baseline execution requests human review.
Even `PASS-FORWARD` permits only continued paper review; there is no automatic action.

The nearer-term falsification test is the already registered **E1 SPY Monday intraday** experiment.
It is not a deployable strategy, and no running result may be treated as a verdict. The generated
E1 report and `GET /meta`'s `e1_forward` object are authoritative for the current count and running
statistics. The append-only record is cryptographically anchored, requires every eligible NYSE
Monday, and stops at exactly 40 observations on the expected final date 2027-05-10. At that
boundary it is killed if net mean return is nonpositive or the one-sample t-statistic is below 0.5;
surviving that permissive gate would justify only further research, not paper-book activation or
live trading. Checkpoint schema v2 also freezes the exact runtime source that selects eligible
sessions, computes costs/returns, appends observations, evaluates the kill rule, and publishes the
checkpoint. Runtime-contract v6 (current,
`5a665966f7bad78474dab9367618aab4016ea847fec8bba9a92966e7706e5612`) makes explicit DuckDB
transactions interruption-safe and preserves the original failure if rollback also fails. V5
releases temporary DuckDB DataFrame views after failed statements. V4 makes the shared no-same-bar
fill rule unconditional under optimized Python. V3 changed only fail-closed shared-metadata
recovery. These migrations preserve all seven observations through 2026-08-31 with the same
anchored prefix. Its original schema-v1 migration has no invented predecessor hash because schema
v1 did not record one.

