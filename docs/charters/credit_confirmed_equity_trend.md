# Credit-confirmed equity trend — pre-registered research charter

Status: **registered, not yet run**  
Charter ID: `CREDIT-CONFIRMED-SPY-2026-09-18-v1`  
Registered: 2026-09-18 UTC

## Question and mechanism

Does requiring liquid high-yield credit to confirm an existing slow equity trend improve the
timing component of a long-only SPY/BIL allocation after costs? Equity and speculative-grade
credit are claims on the same corporate cash flows, but credit investors are structurally more
sensitive to default and refinancing risk. A weakening HYG-versus-LQD total-return spread may
therefore identify equity uptrends whose risk appetite is already deteriorating. The mechanism can
fail because credit lags equities, because rate-duration differences dominate the spread, or because
monthly switching costs consume the avoided losses.

## Frozen design before code or results

| Item | Declaration |
|---|---|
| Candidate ID | `credit_confirmed_spy_v1` |
| Instruments | Exactly `SPY`, `BIL`, `HYG`, `LQD`; fixed liquid ETFs, no substitutions |
| Decision cadence | Final NYSE session of each calendar month |
| Equity trend | SPY 252-session total return strictly exceeds BIL 252-session total return |
| Credit confirmation | HYG 63-session total return strictly exceeds LQD 63-session total return |
| Candidate target | 100% SPY only when both conditions pass; otherwise 100% BIL |
| Availability | A signal requires complete prior-window closes and cash dividends for all four ETFs; missing input means BIL, never a shorter window |
| Execution | Signal at the monthly close; target fills at next session open |
| Control | Per validation fold, a fixed SPY/BIL mix whose SPY weight equals the candidate's mean binary SPY target in that fold; it rebalances monthly on the same dates |
| Capital | $39,000 at every independent fold start |
| Base and stresses | `baseline_v1`, `cost_2x_v1`, and one additional full-session execution delay |
| Historical protocol | Anchor `2026-09-17`; 24-month train, 12-month validate, 12-month step; every complete non-overlapping fold available after common HYG/LQD history begins |
| Trial count | One candidate and one matched control; no grid or alternate threshold |
| Primary statistic | Mean paired monthly net excess over validation months |
| Confidence method | 90% two-sided stationary-block-bootstrap percentile interval; geometric blocks averaging four months; 10,000 draws; seed `20260918` |
| Minimum effect | Mean paired monthly net excess at least 0.10 percentage point |

The control weight is measured from the candidate's frozen binary targets, not selected for return.
It may know the fold's average exposure because it is a diagnostic exposure-matched comparator,
not a deployable strategy. Both paths use identical instruments, rebalance dates, capital, fill
rules, costs, and data snapshot.

## Decision rule

The v1 hypothesis passes historical review only if all of these hold under `baseline_v1`:

1. cumulative paired validation excess is positive;
2. mean paired monthly net excess is at least 0.10 percentage point;
3. its frozen 90% bootstrap interval lies wholly above zero;
4. cumulative excess remains positive with doubled costs and with one-session extra delay;
5. no fold has a candidate drawdown more than 5 percentage points worse than its control; and
6. every fold has exact source, data, execution, calendar, and matched-month identity with no
   capacity rejection or unexplained missing fill.

Failure of any item is `REJECT-V1`. Passing permits only a separately registered prospective
paper experiment; it does not add a league book, alter an existing strategy, or authorize capital.
No parameter, instrument, cadence, control, or statistic may rescue a failed result.

## Bias and interpretation

The hypothesis uses fixed ETFs and does not depend on today's stock constituents. HYG begins in
2007, limiting the sample to the post-launch ETF era and a few major credit cycles. The 63-session
credit window is a conventional quarter selected as one declared horizon, not as the winner of a
scan. This is historically informed research; even a pass needs new prospective evidence. Positive
standalone return or lower drawdown without positive matched-control excess is a rejection.
