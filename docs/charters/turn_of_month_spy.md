# Turn-of-month SPY — completed research charter

Status: **completed 2026-09-07; `REJECT-V1`; not a paper book**  
Charter ID: `TURN-OF-MONTH-SPY-2026-09-07-v1`  
Registered: 2026-09-07 UTC

## Question and mechanism

Does concentrating SPY exposure around month-end produce positive net return
above an otherwise identical low-beta allocation?

The candidate holds SPY for exactly four exchange sessions per monthly turn: the
final NYSE session of a month and the first three NYSE sessions of the following
month. It holds BIL otherwise. A signal at the preceding session's close enters
SPY at the final session's open; a signal after the third session's close exits
to BIL at the fourth session's open. Exchange dates are public calendar facts,
and no same-session price determines whether a trade occurs.

The proposed mechanism is institutional month-end cash flow, pension rebalancing,
payroll contributions, and benchmark-related demand. The honest negative case is
that this well-known anomaly has decayed, is concentrated in an older era, or is
too small to survive four round trips per month under conservative costs.

## Frozen design before code or return results

| Item | Declaration |
|---|---|
| Candidate ID | `turn_of_month_spy` |
| Control ID | `turn_of_month_static_1911` |
| Candidate | 100% SPY during the four-session turn-of-month window; otherwise 100% BIL |
| Control | Fixed 19.1122888374% SPY / 80.8877111626% BIL, rebalanced at inception and on the candidate's entry/exit signal dates |
| Why that weight | Exactly 577 of the 3,019 SPY sessions in the frozen 2014-09-04 through 2026-09-04 protocol span are in the declared window. The value uses calendar membership only, never returns. |
| Signal timing | The previous close signals entry for the next session; the third session's close signals exit for the fourth session's open |
| Instruments | Exactly SPY and BIL; no substitution |
| Capital | $39,000 at every independent fold start |
| Costs | `baseline_v1`, plus the frozen `cost_2x_v1` stress |
| Historical protocol | Anchor 2026-09-04; 24-month train → 12-month validate; 12-month step; 10 non-overlapping validation folds |
| Trial count | One four-session window, one candidate, one exposure-matched control; no calendar-window grid |
| Primary statistic | Mean paired monthly net excess, candidate minus control, over validation months |
| Confidence method | 90% stationary block-bootstrap interval on the mean, geometric blocks averaging four months, 10,000 draws, seed `20260907` |

The static control shares the candidate's entry and exit signal dates, so each
book has the same opportunities to trade. It always restores the same fixed
weights and makes no calendar-direction decision. Comparison with full-time SPY
would confuse timing with beta reduction; comparison with an untouched buy-and-
hold mix would confound timing with rebalance opportunities.

This is one newly specified experiment, but the broader calendar-anomaly family
has prior exploration: E1 tests Monday intraday, while Friday/expiry effects were
previously closed as null. Therefore even a historical pass is hypothesis support,
not independent confirmation.

## Data and completeness boundary

SPY and BIL are fixed, currently surviving ETFs. Their adjusted daily histories
are complete for all 3,019 required sessions in the declared span; the evidence
class is `fixed_etf_history`. The experiment records the common data snapshot and
a deterministic hash of the exact session calendar and two-instrument price-date
coverage. Missing or nonpositive signal-date prices fail the completeness gate.

Both strategies remain outside production `CONFIGS` and `REGISTRY`; an isolated
experiment process may install them only for its four replays. Production books,
ledgers, schedules, and canonical walk-forward reports must not change.

A pending intent emitted on the final replay session has no in-window next open.
It is an allowed truncation only when its signal date equals that fold's final
session and candidate/control pending counts match for that fold. Every other
pending order is an execution failure.

## Historical decision rule

The result is `PASS-HISTORICAL` only if every gate passes:

1. baseline cumulative paired validation excess is positive;
2. the baseline 90% interval on mean paired monthly excess lies wholly above zero;
3. cumulative paired excess remains positive under `cost_2x_v1`;
4. candidate maximum drawdown is no more than 5 percentage points worse than the
   control in every shared validation fold;
5. all 10 folds complete under both profiles with no rejected or capacity-
   rejected orders, no nonterminal or asymmetric pending orders, no missing
   paired months/prices, and exact ledger rebuilds.

Any failed gate gives `REJECT-V1`. No extra entry/exit day, holiday adjustment,
month subset, trend filter, alternate static weight, or parameter grid is allowed
after seeing the result. An inconclusive interval is a failure, not a reason to tune.

## Result — 2026-09-07

**`REJECT-V1`.** All four frozen replays completed across 10 folds and 120 paired
validation months with matching source, data, fill-model, protocol, capital, and
profile cohorts. Under `baseline_v1`, the candidate compounded **+12.98%** across
the paired validation sequence versus **+61.30%** for the exposure-matched static
control. Mean monthly timing excess was **-0.28%**, and its predeclared 90%
stationary-bootstrap interval was wholly negative at **[-0.54%, -0.02%]**.

At doubled costs, candidate growth fell to **-28.70%** while the control retained
**+61.02%**; cumulative excess was **-89.72%**, and mean monthly excess was
**-0.66%** with a 90% interval of **[-0.92%, -0.39%]**. The candidate's worst
fold-level drawdown disadvantage was 9.35 percentage points at baseline and 12.22
points at doubled costs, also exceeding the frozen five-point limit.

The input was complete for all 3,019 required SPY/BIL sessions and every ledger
rebuild matched, with no rejected or capacity-rejected orders. The terminal-order
symmetry gate nevertheless failed: the candidate had two final-session exit intents
in folds 5 and 9, while the control had zero and one respectively. Those intents
could not fill inside the fold. This is a disclosed execution-boundary mismatch, not
a reason to reinterpret the already negative economic evidence; every economic gate
failed independently.

The generated [result report](../../data/reports/experiments/turn-of-month-spy-v1/README.md)
is the authoritative summary. This calendar window is closed without changing its
dates, selecting month subsets, adding a filter, opening a parameter grid, registering
a paper book, or taking live action.

## Forward boundary

A historical pass permits only registration of candidate and control as isolated
shadow-paper books with hashes frozen before their first signal. It does not
permit broker connectivity or live capital. Forward maturity requires at least
five calendar years and 60 completed monthly turns, positive cumulative and mean
monthly excess, and a 90% block-bootstrap interval wholly above zero. Accounting
inconsistency or candidate drawdown more than 10 points worse than control triggers
human review. No model may alter positions, calendar rules, or the verdict.
