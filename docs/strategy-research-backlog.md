# Strategy research backlog

This is the current decision ledger, not a promise of profit. A strategy “works” only when
it survives its prospectively declared control, costs, capacity, data-quality, and forward-paper
tests. Positive standalone CAGR is insufficient.

Last reconciled with the research evidence on 2026-09-13. Dated counts below are explicitly
historical baseline snapshots; `GET /meta`, `GET /research/readiness`, and the generated forward
reports remain authoritative for advancing runtime state.

## Current decision

Do not promote a new book from the completed parameter sweeps. No completed candidate has
a confidence interval establishing positive excess over its proper control. Keep the
engine paper-only and continue the frozen forward records.

The Saturday sweep runner now uses the versioned `OPEN_RECURRING_GRIDS` mapping, which is
intentionally empty. Completed grids remain reproducible by explicit CLI invocation, but
are not rerun every week on substantially the same history. A future grid enters recurring
automation only with a frozen charter version; rerunning after completion requires an
explicit version bump. Recurring outputs are isolated under
`data/reports/sweeps/<grid>/charters/<version>/`, and dispatch rejects a queued charter
after it is removed or superseded in the mapping.

The primary deployable-strategy candidate is **prospective confirmation of the existing
`sector_momentum` rule**, with no parameter changes. It uses a fixed ETF universe, has no
single-stock survivorship problem, and had the strongest clean-data result, but its current
mean validate return of +14.09% trails SPY by 1.17 percentage points and its 90% interval
on excess spans -6.50 to +4.86 points. It is therefore WATCH, not proven.

No historical rerun can resolve that uncertainty without reusing the same market path.
The needed evidence is new forward time spanning a materially different regime. The rule,
benchmark, execution profile, and capital stay frozen while that evidence accrues.
`engine.forward_review` evaluates that paper path nightly and remains `ACCUMULATING` until
a full 12-calendar-month shared record (with at least 200 shared sessions) exists. It can
request a human kill review but cannot alter a portfolio or authorize live trading.

### Live decision checkpoint — 2026-09-12 06:00 UTC

This is a dated observation, not a replacement for the endpoints or generated reports:

- The complete 18-result walk-forward cohort is `current`, with one matching source/data/
  execution signature and no missing, invalid, duplicate, config-mismatched, or
  registration-mismatched artifacts.
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

### Source-transition checkpoint — 2026-09-13 02:17 UTC

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
optimized-Python replay and proof guards advanced the 111-file identity to
`cfcdcb5dc3bb690567173dd87d85adff49e32b76863f4a8e0494f923dcf34592`, including exception-safe
closure for replay, proof, walk-forward, and shakedown scratch database handles, historical screen
and execution-drag CLIs, both queue grids, queue schema initialization, and the legacy dividend
backfill. Daily screen/league ownership, atomic publication, and committed-run artifact recovery
were inside the frozen XS and sector runtime boundaries, so their exact checkpoints were explicitly
migrated through v19 and v8 respectively. The subsequent breadth-reader and historical-screener
cleanup guaranteed removal of temporary SQL relations after a failed calculation. Centralized
interruption-safe transaction cleanup then advanced the exact checkpoints to XS v20, sector v9,
and E1 v6. Every migration changed only contract metadata; no signal or screening formula, stored
observation, strategy rule, execution assumption, or statistical gate changed. The resulting
current 111-file identity is
`2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`.
At this checkpoint the latest published 18-result walk-forward cohort still recorded source
`2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, so
`walkforward_evidence.status = stale-source`. That was an explicit provenance mismatch, not a
failed strategy verdict, and the artifacts were not reconstructed or manually relabelled. The
normal Sunday job subsequently completed at 08:45 UTC with source
`2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`;
`walkforward_evidence.status = current`.
Do not tune a frozen rule, reopen a rejected charter, launch a discretionary sweep, or interpret
the current E1 estimate before its terminal gate.

The canonical observation starts at the shared 2026-09-04 closing marks, when fill model
v4 and its exact `baseline_v1` assumptions were frozen. Earlier July–September league
returns remain operational history but are excluded because they span older fill models.
The opening holdings are inherited and disclosed; no pre-boundary return is credited.
The schema-v2 checkpoint now reconciles those exact inherited positions, cash, position
counts, and frozen closes to both baseline equity rows. It also anchors the complete equity
prefix and post-boundary order/fill/cost/attempt/settlement ledger. Legitimate pending-order
status transitions and late dividend credits remain possible without weakening the immutable
event checkpoint. The next gate is therefore new untouched sessions, not more code or tuning.
Sector runtime-contract v9 SHA-256
`c430b451ee510c858705ba4235f81b68f9d7443745a60b4716035acb32741788` makes explicit DuckDB
transactions interruption-safe and preserves the original failure if rollback also fails; its
exact five-session equity and execution-ledger evidence remain unchanged. V8 SHA-256
`c0788167bf63f734c6c9b3428b425a0054f1cead1754048aa00a6cc48eb5662f` releases temporary
DuckDB DataFrame views after failed statements. V7 SHA-256
`8bc5fae78807daadc9502060659a05df4ca022fb046ecea39b93b4d4ef0926b5` reconstructs both league
reports from committed ledger state on an idempotently skipped step. V6 SHA-256
`43ff467d091a9777703c9a260899fc14c536a552dc28f2d5270034ca63ad2ffe` atomically replaces league
Markdown and CSV output. V5 makes the daily league connection close on every exit, v4 made the existing no-same-bar fill rule
unconditional under optimized Python, and v3
excluded retired portfolio state from current verification and corporate-action work. XS
runtime-contract v20 SHA-256
`8bdfdf2ce028964de6c49d10a95132ac66d66e5a900b4173109355e1945d781e` makes explicit DuckDB
transactions interruption-safe before the first signal. V19 SHA-256
`7f4085fca17872a9ef1125c64ed03f58b2191abe68286e9720441df74f8f06f3` releases temporary
DuckDB DataFrame views after failed statements. V18 SHA-256
`1ddc09660316ab2479855298b73bd5c8481a76b7b93553d4963e3b92ceb13211` keeps the borrowed screen
connection open through the no-eligible return so the outer runtime owns its one close. V17 SHA-256
`4c6bfa198684a82bf05d500856039214a2ad105ab63afa107eb36603bae42906` publishes the dated screen
recovery anchor before committing rows and refuses to recompute committed rows when that
non-derivable anchor is missing. V16 SHA-256
`86942578863d96b1005aab08ae06cd63e789874124f7b9c0da6cfced8b643d21` reconstructs screen CSV/EOD
exports and league reports from committed state on idempotent skips before the first signal. V15
SHA-256 `28a53cfaaa4803d23123c7d7e9f3efbcec3f98b57da08f8f9522cc5926e544eb`
makes universe-cache, screen, league, and monthly walk-forward artifacts atomic. V14 SHA-256
`71ed966bca01af6c5a4b9f9cbf00d67c115ecf17c1c3a607588d9c100dcf6d5a` makes the daily screen and
league connections close on every exit. V13 SHA-256
`345fcea5fd72606b1fc3a0700c1b22c9c977f6ded0cbd5b297cd4c875b6de1d5` makes directory
insert/update/deactivation and daily snapshot publication one transaction and atomically replaces
the derived universe CSV. V12 SHA-256
`158ed6666d4005c9a555f41ea829925503214838199e4887acfc94169b9c32d9` enforces the existing
common-stock/ETF policy for Nasdaq's plural rights, warrants, preferred classes, and dedicated
unit symbols before the first signal. V11 SHA-256
`2dc2b853419cadb448f45c2b895998be0f73c617183cd9c3afc70c53876b8455` adds unconditional retry
of the complete resumable pending liquid-backfill set on every real weekly refresh, including
zero-admission runs. V10 SHA-256
`90f68c2616757a724c390fb65cb9e27a9b7654ba34e2d5aab08183b689be12a9` makes the same guard
unconditional before the first signal. V9 excluded retired portfolio positions from liquidity
protection before the first signal. V8 made malformed shared
metadata fail closed instead of being replaced as an empty snapshot. V7 made an existing screen's
stored rows and report agree before its metadata is restored, with no historical recomputation. V6
made concurrent publishers serialize the complete read/merge/write operation, routed the screener
through the common helper, and froze that dependency. V5 made EOD collection merge its own counters instead of erasing
independently generated miner, verifier, and screen blocks. V4 changed only weekly-liquidity dry-run
reporting: `liquid_after` became the projected post-reconciliation
count while the store remained unchanged. V3 changed only EOD collector connection lifetime:
universe preparation, Yahoo downloads, bounded batch writes, and final metadata no longer shared
one long-lived DuckDB connection, and backfill state was checkpointed transactionally with each
batch. V2's sole change was corporate-action fetch recovery. Each explicit pre-signal migration
verified the exact prior record, unchanged
strategy/execution/statistical rules, no frozen signal boundary, and no signal-date orders or
post-fill observations.

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

The nearer-term falsification test is the already registered **E1 SPY Monday intraday**
experiment. It is not a deployable strategy, and no running result may be treated as a verdict.
The generated E1 report and `GET /meta`'s `e1_forward` object are authoritative for the current
count and running statistics. The append-only record is cryptographically anchored, requires
every eligible NYSE Monday, and stops at exactly 40 observations on the expected final date
2027-05-10. At that boundary it is killed if net mean return is nonpositive or the one-sample
t-statistic is below 0.5; surviving that permissive gate would justify only further research,
not paper-book activation or live trading.
Checkpoint schema v2 also freezes the exact runtime source that selects eligible sessions,
computes costs/returns, appends observations, evaluates the kill rule, and publishes the
checkpoint. Runtime-contract v6 SHA-256
`5a665966f7bad78474dab9367618aab4016ea847fec8bba9a92966e7706e5612` makes explicit DuckDB
transactions interruption-safe and preserves the original failure if rollback also fails. V5
SHA-256 `31ff0e06dad3ee1063dc25210cf049df5dffba1662621bc6a97de30e535420a2`
releases temporary DuckDB DataFrame views after failed statements. V4 SHA-256
`da752d28c1b9bb18e3520139bbce71c885b89b192a47d00d5cd8fbfa0f1399ae` makes the shared
no-same-bar fill rule unconditional under optimized Python. V3 changed only fail-closed
shared-metadata recovery. These migrations preserve
all seven observations through 2026-08-31 with prefix SHA-256
`e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad`. Its original
schema-v1 migration has no invented predecessor hash because schema v1 did not record one.

## Ranked backlog

| Priority | Direction | Existing evidence | Decision / next gate |
|---:|---|---|---|
| 1 | E1 SPY Monday forward experiment | Append-only immutable OOS record; the generated report supplies the current count and running result, neither of which may be judged early | Continue unchanged through exactly 2027-05-10; apply the frozen 40-observation kill gate once, with no automatic action. |
| 2 | `sector_momentum` forward paper vs SPY | Fixed ETFs; scalable through sampled $1m; excess CI crosses zero; boundary and execution ledger now frozen/reconciled | Continue unchanged. Reassess only after materially different forward regime data and the registered 2027-09-04/200-session maturity gate. |
| 3 | `xs_momentum_12_1` prospective paper vs EW | Historical +6.42pp mean excess has a CI crossing zero and is survivor-biased; candidate has not yet traded | Keep both rules frozen. Start measurement only at the post-fill 2026-10-01 boundary; do not backfill or tune while evidence accrues. |
| 4 | Fixed-ETF rebalancing-premium hypothesis | Full chartered run completed cleanly: +2.34% cumulative excess at baseline and +1.88% at 2× costs, but mean monthly excess was effectively zero and its 90% CI crossed zero | `REJECT-V1`; close this direction without tuning, a new sweep, or a paper book. |
| 5 | Sector caps / concentration | `ew_sector_capped` failed its 5pp drawdown-relief gate (best-returning cell: +0.72% median excess, CI crosses zero, and -38.82% worst DD vs EW -37.54%); static sector history also creates look-ahead. Concentration's apparent +9.38pp median came with -48.19% worst drawdown and search bias. | Closed. Do not promote or forward-test; reopening requires point-in-time sectors and a newly frozen hypothesis. |
| 6 | Gross-volatility and drawdown throttles | Drawdown throttle failed its 8pp relief gate. The completed gross-vol matched-static review found no positive timing-edge cell; all mean timing CIs include zero and the inputs are legacy v2 artifacts with incomplete provenance. | Drawdown throttle is rejected. Gross-vol is `INCONCLUSIVE-LEGACY` and closed, not promotable; a new provenance-complete charter/cohort is required to revisit it. |
| 7 | VIX-term SPY/BIL timing | One fixed 0.95 threshold was tested against a static 80.6845% SPY control over 120 paired months. Baseline mean timing excess was -0.42%/month, 90% CI [-0.67%, -0.17%], and doubled costs weakened it further. | `REJECT-V1`; close without tuning the threshold, adding persistence, or opening a grid. |
| 8 | Turn-of-month SPY/BIL timing | One fixed four-session window was tested against a static 19.1123% SPY control over 120 paired months. Baseline candidate growth was +12.98% versus +61.30%; mean excess was -0.28%/month with 90% CI [-0.54%, -0.02%]. At doubled costs the candidate lost 28.70%. | `REJECT-V1`; close without shifting the window, selecting months, adding a filter, or opening a grid. |
| 9 | Sell-in-May SPY/BIL timing | One conventional November-April interval was tested against a static 49.0229% SPY control over 120 paired months. Baseline growth was +99.38% versus +139.83%; mean excess was -0.12%/month with 90% CI [-0.35%, +0.11%], and one fold's drawdown was 16.30pp worse. | `REJECT-V1`; close without shifting month boundaries, selecting months, adding a filter, or opening a grid. |
| 10 | Mean reversal, per-name stops, turtle stops, trend gates, banding | Generally negative or statistically indistinguishable after multiple trials | Closed unless new data or a genuinely different mechanism changes the premise. Do not resweep nearby parameters. |

### Next admissible actions

There is currently no evidence-authorized new strategy run. The queue below names the event that
unlocks each next action; elapsed time by itself does not waive any count, breadth, provenance, or
pre-registration requirement.

| Order | Trigger | Action unlocked | What remains forbidden |
|---:|---|---|---|
| Complete | The 2026-09-13 Sunday walk-forward published a complete cohort whose source hash equals the deployed 111-file identity | Treat the cohort as current historical context; no already-recorded conclusion changed | No parameter selection, promotion, or new paper book; source parity is provenance, not profit evidence |
| 2 | Each newly settled eligible observation for E1 or Sector, and the frozen 2026-09-30 XS signal followed by its 2026-10-01 baseline | Append through the existing monitors and apply only their predeclared terminal gates | No early verdict, backfill, reset, rule change, or evidence-driven tuning |
| 3 | Both intraday resolutions reach 252 qualifying sessions over at least 365 calendar days | Permit drafting one genuinely new, theory-led charter with a fixed event definition, control, cost model, sample size, and total trial count | No exploratory grid on the accumulated archive before registration; earliest possible calendar-span clearance is around 2027-07-08 because the one-minute archive is the limiting series |
| 4 | Stock selection reaches 756 qualifying shared dates over 1,095 days, or fundamentals reaches 156 qualifying snapshots over 1,095 days | Permit a point-in-time charter in the family whose complete gate cleared | No historical join to today's universe or fundamentals and no claim before roughly July 2029 at the earliest under the current archive start dates |
| 5 | An independent point-in-time dataset with documented publication timestamps and membership history is acquired and audited | Recalculate the relevant readiness gate from that source, then consider a separately versioned charter | No silent substitution into existing evidence and no reuse of rejected hypotheses under new labels |

This order makes the shortest honest route to a possible profitable strategy explicit. It does not
guarantee that any candidate will pass. If E1 fails at 40 observations, Sector fails at maturity,
or XS later fails its paired-month gate, record the rejection and move to the next admitted family
instead of relaxing the rule after seeing the outcome.

## Evidence rules for the next candidate

Before any new run, freeze in a charter:

1. the economic mechanism and why it is not a renamed failed hypothesis;
2. the proper control and evidence-quality class;
3. one primary statistic, a kill criterion, and the total trial count;
4. execution profile, starting capital, capacity limit, and data snapshot;
5. what result would trigger forward paper observation—and what would stop work.

Historical output stays isolated from canonical evidence until cohort validation confirms
matching source hash, fill model, protocol, capital, cost profile, and data fingerprint.
No broker connection or live-capital step is authorized by this backlog.

### Candidate-admission data boundary

The following table is the dated **2026-09-08 pre-nightly baseline snapshot**, not current
runtime state. `GET /research/readiness` is authoritative for current coverage and naturally
advances as unattended producers publish new observations. The baseline audit prevents a long
price history from being mistaken for long point-in-time selection history:

| Input family | Coverage at the 2026-09-08 pre-nightly baseline | Admission consequence |
|---|---|---|
| Fixed-instrument daily prices | SPY/BIL and the fixed ETF sets have multi-year complete histories | A genuinely new fixed-instrument mechanism may be chartered, but only as one frozen trial with a proper exposure-matched control. |
| Universe and screen snapshots | 39 universe dates and 38 screen dates; 37 breadth-qualified shared dates, beginning 2026-07-16 | Not enough to validate historical stock selection; older replays use today's survivors and remain explicitly survivor-biased. |
| Fundamentals snapshots | 8 as-of dates, 2026-07-18 through 2026-09-04 | Not enough for a historical value/quality/fundamental strategy; current values must never be joined backward into old prices. |
| Intraday archive | 43 one-minute sessions and 96 five-minute sessions | Not enough for a robust event or microstructure claim; retain the archive and pre-register only after sample-size and event-coverage requirements are defensible. |

A stock-selection, fundamental, or intraday candidate is therefore not admitted merely
because decades of daily prices are present. It must either wait for the append-only
point-in-time archive to mature or bring an independently acquired historical dataset with
documented publication timestamps, membership history, corporate-action treatment, and a
frozen availability rule. This is a research gate, not a reason to lower the confidence
standard or search more fixed-ETF calendar variants.

`GET /research/readiness` derives these coverage counts directly from the read-only store.
At the 2026-09-11 snapshot, all three input schemas were valid but no family was charter-ready:
stock selection had 40 of 756 qualifying shared dates over 56 of 1,095 required calendar days;
fundamentals had 8 of 156 qualifying snapshots over 48 of 1,095 days; intraday had 46 of 252
qualifying one-minute sessions and 99 of 252 five-minute sessions, with spans of 64 and 142 of
365 days respectively. These are progress counters, not strategy results. Their large remaining
gaps confirm that continuing the unattended archive is the evidence-producing action; another
search over the current history would only spend trials without fixing survivorship or
publication-time bias.
Only breadth-qualified observations count: each shared universe/screen date and fundamentals
snapshot needs at least 1,000 distinct names, while each intraday session needs at least 500
distinct tickers with substantial per-ticker coverage. Each ticker needs at least 75% of the bars
expected from the published NYSE schedule for that date and resolution. This retains legitimate
early closes, rejects truncated normal-day downloads, and assigns zero usable breadth to unknown
or closed dates. Stock breadth is the actual same-date ticker intersection between the universe
and screen snapshots, not the smaller of unrelated table counts. Fundamentals breadth counts only
equities with finite positive market cap and at least one finite valuation input (trailing P/E,
price-to-book, or EV/EBITDA); finite negative ratios remain valid, while ETFs, non-finite values,
and valuation-empty rows do not count. It reports `READY_FOR_CHARTER` only after at least 756
qualifying stock dates spanning 1,095 calendar days, 156 qualifying fundamentals snapshots
spanning 1,095 days, or 252 qualifying sessions spanning 365 days in both stored intraday
resolutions. A thin bootstrap date remains visible in observed coverage but neither counts
toward admission nor permanently blocks later qualifying history. These are minimum admission
gates, not evidence of an edge; the endpoint is paper-only, has `automatic_action: none`, and
cannot register or activate a strategy.
Every family separately exposes `input_status` (`ready`, `missing`, or `invalid-schema`) plus any
missing tables/columns or incompatible column types. Only `ready` inputs can reach `READY_FOR_CHARTER`; malformed legacy schemas
remain visible and fail closed instead of producing an endpoint error or a misleading valid zero.

The unattended weekday nightly continues the point-in-time archive after disconnect: it creates
the universe/screen observations and queues both intraday resolutions every weekday, while the
Friday plan also queues fundamentals. At the 2026-09-08 pre-nightly baseline,
`miner_evidence` was 3/4 because the latest completed fundamentals job predated its missing
summary receipt. That historical receipt was not reconstructed: the real scheduled 2026-09-11
Friday producer published a fresh receipt and advanced current evidence to 4/4. `GET /meta`
remains authoritative for current producer evidence, and this operational completion does not
lower any admission threshold or authorize a new charter.

Historical walk-forward comparator choices are versioned inside each newly generated
artifact. Results created before that field existed remain useful absolute context, but the
current renderer withholds a relative verdict rather than inferring a comparator from mutable
report code. The normal 2026-09-13 Sunday refresh completed all 18 active replayable books and
`GET /meta` reported `weekly_walkforward = ok` and `walkforward_evidence.status = current`. The
cohort has one signature
`b304ae92d54e27a8f3a3adaa77dcf5b77175f9be141e71dfa232f29c3b32aec2`, source
`2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`, data snapshot
`039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`, fill model v4,
`baseline_v1`, $39,000 initial capital, and the frozen 24/12/12-month protocol anchored on
2026-09-11. This was scheduled provenance maintenance, not a new strategy search or promotion.

The old/new artifact audit did not claim false exact equivalence. Six books differed only in the
approved provenance and runtime fields. Eleven screen-driven books also changed from 1,107,457 to
1,107,456 historical passing rows, plus non-economic screen timing. XS alone had a full-precision
economic delta: its last validate return moved from 44.9166529% to 44.9167235% and ending equity
from $94,960.2749 to $94,960.3212. The nightly had advanced the stamped data snapshot and refreshed
Yahoo's mutable historical cache between cohorts; the earnings selector is not part of replay
economics. Rounded report values, rankings, and the decision below are unchanged. This was
evidence maintenance, not a new search or a promotion event.
The rankings therefore do not justify promotion or a
new parameter search: the fixed-ETF Sector candidate remains WATCH pending prospective data,
and the stronger-looking single-stock histories remain survivor-biased.

## Model-review boundary

A model may summarize new reports, audit code, or draft a new charter for human review. It
is not an evidence source and cannot turn an inconclusive backtest into a profitable rule.
Any unattended model review remains outside the nightly dependency chain and may write only
review artifacts or proposed code changes. It must not modify paper ledgers, activate or
retire books, add a grid to `OPEN_RECURRING_GRIDS`, select parameters after seeing results,
or authorize broker/live-capital activity.
