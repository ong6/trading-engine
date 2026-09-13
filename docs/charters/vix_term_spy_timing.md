# VIX-term SPY timing — completed research charter

Status: **completed 2026-09-07; `REJECT-V1`; not a paper book**  
Charter ID: `VIX-TERM-SPY-2026-09-07-v1`  
Registered: 2026-09-07 UTC

## Question and mechanism

Does the public VIX term structure identify periods when owning SPY is rewarded,
after separating timing from the simpler effect of holding less equity?

The candidate reads the latest same-date VIX and VIX3M closes available at a
session close. It holds SPY when `VIX / VIX3M < 0.95` (clear contango) and BIL
otherwise. Orders use the normal next-session-open fill path. The 0.95 threshold
is the already frozen calm-state threshold in `macro_composite`; it was not fitted
for this experiment. There is no smoothing, persistence rule, leverage, short-vol
ETF, stop, or alternate threshold.

The mechanism is the volatility risk premium and state-dependent equity risk:
contango normally accompanies calm, risk-bearing markets, while a flat or inverted
curve indicates demand for near-term protection. The honest negative case is that
the curve reacts with the market, exits after losses, re-enters after rebounds, and
adds turnover without forecasting future SPY returns.

## Frozen design before code or return results

| Item | Declaration |
|---|---|
| Candidate ID | `vix_term_spy_timing` |
| Control ID | `vix_term_static_8068` |
| Candidate | 100% SPY while the ratio is below 0.95; otherwise 100% BIL |
| Control | Fixed 80.6844819503% SPY / 19.3155180497% BIL, rebalanced only at inception and on the exact sessions when the candidate's binary state changes |
| Why that weight | The signal was in contango on 3,442 of the 4,266 joined observations available at registration (80.6844819503%). This matches average gross equity exposure without selecting on returns. It is a disclosed full-history design input, so historical evidence remains exploratory. |
| Signal timing | Same-date official index closes are used only after that close; resulting trades fill no earlier than the next session open |
| Instruments | Exactly SPY and BIL; no substitution |
| Capital | $39,000 at every independent fold start |
| Costs | `baseline_v1`, plus the frozen `cost_2x_v1` stress |
| Historical protocol | Anchor 2026-09-03, the latest complete joined VIX/VIX3M session at registration; 24-month train → 12-month validate; 12-month step; 10 non-overlapping validation folds |
| Trial count | One threshold, one candidate, one matched-exposure control; no grid |
| Primary statistic | Mean paired monthly net excess, candidate minus control, over validation months |
| Confidence method | 90% stationary block-bootstrap interval on the mean, geometric blocks averaging four months, 10,000 draws, seed `20260907` |

The control deliberately shares the candidate's transition dates. This gives both
books the same opportunities to trade while denying the control any directional
timing decision. Comparing with 100% SPY would credit ordinary beta reduction to
the signal; comparing with an untouched 80/20 buy-and-hold would confound timing
with different rebalance dates.

## Data-quality boundary

VIX and VIX3M are official end-of-day index histories, joined only on identical
observation dates. The local store contains 4,266 joined dates from 2009-09-18
through 2026-09-03. Most old rows were fetched retrospectively in August 2026, so
their production `fetch_as_of` correctly makes them invisible to historical live
replay. This experiment creates an isolated scratch reconstruction with
`fetch_as_of = obs_date` for these two series only. That models public close-time
availability; it does not claim the local database observed the values then.

The report must label the evidence class
`reconstructed_public_eod_macro_history`, record a deterministic hash/count/date
range of the exact joined macro input, and keep this result outside canonical
league reports. Production `macro_signals`, strategies, ledgers, and schedules
must not be modified. Missing or nonpositive paired values cause no signal and
must fail the execution/data-completeness gate if they affect a required session.

## Historical decision rule

The result is `PASS-HISTORICAL` only if every gate passes:

1. baseline cumulative paired validation excess is positive;
2. the baseline 90% interval on mean paired monthly excess lies wholly above zero;
3. cumulative paired excess remains positive under `cost_2x_v1`;
4. candidate maximum drawdown is no more than 5 percentage points worse than the
   control in every shared validation fold;
5. all 10 folds complete under both profiles with no pending, rejected, or
   capacity-rejected orders, no missing paired months, complete macro input, and
   exact ledger rebuilds.

Any failed gate gives `REJECT-V1`. No threshold adjustment, state persistence,
alternate static weight, asset substitution, or parameter grid is allowed after
seeing the result. An inconclusive confidence interval is a failure, not a reason
to tune.

## Result — 2026-09-07

**`REJECT-V1`.** All four frozen replays completed across 10 folds and 120 paired
validation months. Under `baseline_v1`, the candidate compounded **+117.74%**
across the paired validation sequence versus **+261.17%** for the static control.
Mean monthly timing excess was **-0.42%**, with its predeclared 90% stationary-
bootstrap interval entirely negative at **[-0.67%, -0.17%]**. Candidate mean
validate return was **+8.49%** per fold versus **+13.26%** for the control, and
one candidate fold's maximum drawdown was 8.47 percentage points worse.

At doubled costs, candidate paired growth fell to **+47.05%** while the control
retained **+260.76%**; mean monthly excess was **-0.74%**, with a 90% interval
of **[-1.03%, -0.46%]**. The macro input was complete for all 3,019 required
sessions and ledger rebuilds matched. Each replay retained two symmetric orders
signalled on fold 8's final session, which had no next session on which to fill;
the charter's literal no-pending gate therefore also failed. The economic gates
already reject the rule independently.

The generated [result report](../../data/reports/experiments/vix-term-spy-v1/README.md)
is the authoritative summary. This direction is closed without threshold tuning,
a parameter sweep, shadow-paper activation, or live action.

## Forward boundary

A historical pass permits only registration of candidate and control as isolated
shadow-paper books with code/config/profile hashes frozen before their first
signal. It does not permit broker connectivity or live capital. Forward maturity
requires at least five calendar years and 20 completed risk-off transitions, with
positive cumulative and mean monthly excess and a 90% block-bootstrap interval
wholly above zero. Accounting inconsistency or candidate drawdown more than 10
points worse than control triggers human review. No model may alter positions,
thresholds, or the verdict.
