# Strategy research backlog

> **Scope: deterministic strategies only.** AI policies are judged by the daily opportunity agent
> (P8), profitability evidence loop (P15), and challenger lab (P16) gates and ordered by
> [`product.md`](product.md). "No evidence-authorized new strategy run"
> below refers to deterministic strategies.

This is the deterministic research queue, not a promise of profit. A strategy “works” only when
it survives its prospectively declared control, costs, capacity, data-quality, and forward-paper
tests. Positive standalone CAGR is insufficient.

`GET /meta`, `GET /research/readiness` and the generated forward reports are authoritative for
runtime state; numbers below are the frozen results each decision rests on.

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
cohort had one signature, one source and data snapshot, fill model v4, `baseline_v1`, $39,000 initial capital, and the frozen 24/12/12-month protocol anchored on
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
