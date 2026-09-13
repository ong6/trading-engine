# Sell-in-May SPY — completed research charter

Status: **completed 2026-09-07; `REJECT-V1`; not a paper book**  
Charter ID: `SELL-IN-MAY-SPY-2026-09-07-v1`  
Registered: 2026-09-07 UTC

## Question and mechanism

Does holding SPY only during the historically stronger November-through-April
half-year produce positive net return above an otherwise identical low-beta
allocation?

The candidate holds SPY during every NYSE session whose calendar month is
November, December, January, February, March, or April, and BIL during May
through October. The final April close signals a move to BIL at the first May
session's open; the final October close signals a move to SPY at the first
November session's open. Month membership is known before the signal, and no
same-session price determines the state.

The proposed mechanism is a persistent seasonal concentration of risk appetite,
fund flows, and earnings-related returns in the November-April interval. The
honest negative case is that the well-known effect is data-mined, has decayed,
or is simply compensation for less equity exposure and occasional crash
avoidance.

## Frozen design before code or return results

| Item | Declaration |
|---|---|
| Candidate ID | `sell_in_may_spy` |
| Control ID | `sell_in_may_static_4902` |
| Candidate | 100% SPY in November-April; 100% BIL in May-October |
| Control | Fixed 49.0228552501% SPY / 50.9771447499% BIL, rebalanced at inception and on the candidate's May/November transition signal dates |
| Why that weight | Exactly 1,480 of the 3,019 SPY sessions in the frozen 2014-09-04 through 2026-09-04 protocol span are in November-April. The value uses calendar membership only, never returns. |
| Signal timing | The final April or October close signals the state for the next NYSE session's open |
| Instruments | Exactly SPY and BIL; no substitution |
| Capital | $39,000 at every independent fold start |
| Costs | `baseline_v1`, plus the frozen `cost_2x_v1` stress |
| Historical protocol | Anchor 2026-09-04; 24-month train → 12-month validate; 12-month step; 10 non-overlapping validation folds |
| Trial count | One conventional November-April interval, one candidate, one exposure-matched control; no month-boundary grid |
| Primary statistic | Mean paired monthly net excess, candidate minus control, over validation months |
| Confidence method | 90% stationary block-bootstrap interval on the mean, geometric blocks averaging 12 months, 10,000 draws, seed `20260907` |

The static control shares the candidate's two annual transition dates, so both
books have the same rebalance opportunities. It always restores the same fixed
weights and makes no seasonal direction decision. Full-time SPY would confound
timing with beta reduction, while an untouched buy-and-hold mix would confound
timing with rebalance opportunities.

This is one new specification inside the broader calendar-anomaly family. E1
already tests Monday intraday behavior and the four-session turn-of-month rule
was rejected before this charter was registered. A historical pass would
therefore be related-family support, not independent confirmation.

## Data, isolation, and completeness boundary

SPY and BIL are fixed, currently surviving ETFs. Their adjusted daily histories
are complete for all 3,019 required sessions in the declared span; the evidence
class is `fixed_etf_history`. The experiment records the common data snapshot
and hashes the exact SPY/BIL OHLCV/source rows. Missing or nonpositive open or
close prices on a required session fail the completeness gate.

Both strategies remain outside production `CONFIGS` and `REGISTRY`; an isolated
experiment process may install them only for its four replays. Production books,
ledgers, schedules, canonical walk-forward reports, and forward monitors must
not change.

A pending intent is allowed only if emitted on a fold's final replay session and
the candidate and control have equal pending counts for that fold. Every other
pending order, malformed fold set, or count/detail mismatch is an execution
failure.

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

Any failed gate gives `REJECT-V1`. No shifted month boundary, month subset,
trend filter, alternate static weight, asset substitution, or parameter grid is
allowed after seeing the result. An inconclusive interval is a failure, not a
reason to tune.

## Result — 2026-09-07

**`REJECT-V1`.** All four frozen replays completed across 10 folds and 120 paired
validation months with matching source, data, fill-model, protocol, capital, and
profile cohorts. Under `baseline_v1`, the November-April candidate compounded
**+99.38%** across the paired validation sequence versus **+139.83%** for the
exposure-matched static control. Cumulative excess was **-40.45%**. Mean monthly
timing excess was **-0.12%**, with its predeclared 90% stationary-bootstrap
interval spanning zero at **[-0.35%, +0.11%]**.

At doubled costs, candidate growth fell to **+91.33%** while the control retained
**+139.62%**; cumulative excess was **-48.29%**. Mean monthly excess was
**-0.15%**, with a 90% interval of **[-0.38%, +0.07%]**. The candidate's worst
fold-level drawdown disadvantage was 16.30 percentage points under both cost
profiles, exceeding the frozen five-point limit.

The execution, data, and accounting gate passed: all folds completed, all 120
months paired, all 3,019 SPY/BIL sessions were complete, no orders were pending,
rejected, or capacity-rejected, and every ledger rebuild matched. The rejection
therefore comes from the economic evidence, not an incomplete run.

The generated [result report](../../data/reports/experiments/sell-in-may-spy-v1/README.md)
is the authoritative summary. This direction is closed without shifting month
boundaries, selecting months, adding a filter, opening a parameter grid,
registering a paper book, or taking live action.

## Forward boundary

A historical pass permits only a new, separately frozen shadow-paper comparison.
It does not permit broker connectivity or live capital. Forward maturity requires
at least five calendar years and five complete November-April intervals, positive
cumulative and mean monthly excess, and a 90% block-bootstrap interval wholly
above zero. Accounting inconsistency or candidate drawdown more than 10 points
worse than control triggers human review. No model may alter positions, calendar
rules, or the verdict.
