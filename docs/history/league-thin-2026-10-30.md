# Paper league thinning — 2026-10-30

Recommend retiring **dual_momentum_gated** and **template_top5_gated** as exact copies,
keeping their parents and every other active book. This is a recommendation and dry run:
17 remain active; applying the two retirements would leave 15. No real store was written.

## Evidence boundary

The sole market/ledger input was the published snapshot
`store/snapshots/market-20261030T025723842464Z.duckdb`, opened through
`engine.lib.db.connect(..., read_only=True)`. Latest equity: 2026-10-29.
The read-only `/meta` response reported `nightly_evidence.status=current`, 17 active
portfolios and 17 with equity. Inception comparisons cover every retained row, not a
recent window. Orders/fills are compared after removing portfolio and sequence IDs;
all economic fields, dates, statuses and rejection reasons remain. A second fill comparison
joins each fill to its order economics to verify the associations. Positions include zero
quantity rows; daily equity comparisons include equity, cash and position counts.

## Twins since inception

| Gated book | Twin | Orders each | Fills each | Position rows each (nonzero) | Equity rows each | First difference |
|---|---|---:|---:|---:|---:|---|
| dual_momentum_gated | dual_momentum | 4 | 4 | 2 (1) | 74 | None; exact |
| template_top5_gated | template_top5 | 98 | 98 | 24 (5) | 74 | None; exact |

Both pairs were created 2026-07-17 and have daily marks 2026-07-17–2026-10-29.
Current cash and initial cash are also identical within each pair. The implemented
`regime_risk_off` predicate (SPY close below its latest 200-session mean) returns false
on all 74 SPY sessions in that interval, using the snapshot. This supports the review's
"gate never fired" explanation. It does not establish the gates' value in a future bear
market. Removing a duplicate book ends that paired live test; it does not tune either rule
or disturb the E1, sector or XS frozen forward records.

## Returns and minimum detectable effect

Returns use paired consecutive common equity marks: `equity[t]/equity[t-1]-1`,
then book return minus benchmark return. Equity already includes the costs charged at the
time; no price reconstruction or extra fee subtraction is used. Daily SD is the sample
SD of that excess, with `ddof=1`; annualised excess is arithmetic `252 * mean(excess)`
in percentage points per year, not CAGR. These large annualisations of short windows
are descriptive and are not forecasts.

Comparators follow `farm.walkforward.controls`: allocation books vs `spy_benchmark`,
screen-driven books vs `ew_benchmark`. P15 AI books use their paired `p15_rule_control`.
EW and the discretionary book use SPY for context; SPY and P15's rule control compare to
self. For `momo_stopped`, EW is the surviving report comparator: its original stop A/B
comparator, `template_top10_banded`, stopped marking on 2026-10-20, so it cannot support
an up-to-date post-break series. Reference self-comparisons have mechanically zero SD
and MDE; that says nothing about detectability of an independent strategy.

Multiplicity uses **16**, the league's published `n_trials` in
`data/reports/walkforward/monthly-2026-10-05.json` (all evaluated non-reference books;
`farm.walkforward.monthly.build` counts them). The roughly 13 active alternatives do not
erase prior trials. The league reports DSR as multiplicity context; it has no registered
daily Bonferroni promotion gate. For this requested power diagnostic, carry that same
family size into a one-sided 5% familywise Bonferroni calculation:

`MDE(n) = 252 * SD_daily * (Phi^-1(1 - 0.05/16) + Phi^-1(0.80)) / sqrt(n)`.

The normal quantile sum is **3.5759900201**. Columns at +1/+2 years replace `n` with
`n+252`/`n+504`, holding SD and the family size fixed. This is the usual normal-approximation
80%-power planning MDE, assuming independent stationary daily excess and known population
SD approximated by the observed sample SD. Nine returns give a particularly unstable SD;
serial dependence, regime change, and estimating variance can make actual power lower.
There is no registered daily power rule to revise here. The MDE alone cannot prove that a
book could never earn an effect that large. No non-copy retirement is recommended on that basis.

### Current cost regime (decision-relevant)

Each active book and comparator has a `sim_book_breaks` cost boundary of 2026-10-19.
Use the last common pre-break mark (2026-10-16) as the base, including the return ending
on D0. All books have **9** current-cost return observations, 2026-10-19–2026-10-29.
The longer pre-break records below remain diagnostic, as required by the restarted clock.

| Active book | Benchmark | n | Excess pp/yr | Daily SD % | Daily t | MDE now pp/yr | +1 year | +2 years |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| discretionary | spy_benchmark | 9 | -6.86 | 0.39345 | -0.21 | 118.19 | 21.95 | 15.65 |
| dual_momentum | spy_benchmark | 9 | +0.12 | 0.00336 | 0.44 | 1.01 | 0.19 | 0.13 |
| dual_momentum_gated | spy_benchmark | 9 | +0.12 | 0.00336 | 0.44 | 1.01 | 0.19 | 0.13 |
| ew_benchmark | spy_benchmark | 9 | +233.63 | 2.63781 | 1.05 | 792.35 | 147.14 | 104.95 |
| ew_voltarget | ew_benchmark | 9 | -20.55 | 0.47031 | -0.52 | 141.27 | 26.23 | 18.71 |
| high_52wk | ew_benchmark | 9 | -173.82 | 3.00356 | -0.69 | 902.22 | 167.54 | 119.50 |
| macro_composite | spy_benchmark | 9 | -11.45 | 0.31637 | -0.43 | 95.03 | 17.65 | 12.59 |
| momo_stopped | ew_benchmark | 9 | -178.14 | 1.84794 | -1.15 | 555.09 | 103.08 | 73.52 |
| p15_ai_ranked | p15_rule_control | 9 | -79.55 | 1.30762 | -0.72 | 392.79 | 72.94 | 52.03 |
| p15_hybrid_veto | p15_rule_control | 9 | -32.41 | 0.26635 | -1.45 | 80.01 | 14.86 | 10.60 |
| p15_rule_control | p15_rule_control | 9 | +0.00 | 0.00000 | identity | 0.00 | 0.00 | 0.00 |
| pead_ear | ew_benchmark | 9 | -212.13 | 3.27717 | -0.77 | 984.41 | 182.80 | 130.39 |
| sector_momentum | spy_benchmark | 9 | +47.50 | 0.63473 | 0.89 | 190.66 | 35.40 | 25.25 |
| spy_benchmark | spy_benchmark | 9 | +0.00 | 0.00000 | identity | 0.00 | 0.00 | 0.00 |
| template_top5 | ew_benchmark | 9 | +26.42 | 2.42517 | 0.13 | 728.48 | 135.28 | 96.49 |
| template_top5_gated | ew_benchmark | 9 | +26.42 | 2.42517 | 0.13 | 728.48 | 135.28 | 96.49 |
| xs_momentum_12_1 | ew_benchmark | 9 | +44.27 | 1.65163 | 0.32 | 496.12 | 92.13 | 65.71 |

Dual momentum's tiny current SD reflects its near-SPY holdings in this short window.
It must not be projected as a stable low tracking error across a future cash-switch regime.

### Paired inception record (mixed cost regimes; diagnostic)

The initial equity mark is the base, so there is one fewer return than common equity rows.
The two July-17 twins have 73 returns; P15 has 23 returns from its September-28 base.
The discretionary book starts July 20; XS starts September 2. Last mark is October 29 for all.

| Active book | Benchmark | n | Excess pp/yr | Daily SD % | Daily t | MDE now pp/yr | +1 year | +2 years |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| discretionary | spy_benchmark | 72 | -6.09 | 0.57042 | -0.36 | 60.58 | 28.56 | 21.42 |
| dual_momentum | spy_benchmark | 73 | -17.25 | 0.49497 | -1.18 | 52.21 | 24.74 | 18.57 |
| dual_momentum_gated | spy_benchmark | 73 | -17.25 | 0.49497 | -1.18 | 52.21 | 24.74 | 18.57 |
| ew_benchmark | spy_benchmark | 73 | -9.59 | 1.60649 | -0.20 | 169.44 | 80.30 | 60.27 |
| ew_voltarget | ew_benchmark | 51 | +3.89 | 0.69153 | 0.16 | 87.26 | 35.80 | 26.45 |
| high_52wk | ew_benchmark | 66 | +0.18 | 1.86031 | 0.00 | 206.35 | 94.01 | 70.22 |
| macro_composite | spy_benchmark | 61 | -0.85 | 0.30614 | -0.09 | 35.32 | 15.59 | 11.61 |
| momo_stopped | ew_benchmark | 66 | +15.51 | 1.52269 | 0.33 | 168.90 | 76.95 | 57.47 |
| p15_ai_ranked | p15_rule_control | 23 | +11.72 | 1.29083 | 0.17 | 242.55 | 70.15 | 50.67 |
| p15_hybrid_veto | p15_rule_control | 23 | -0.35 | 0.28161 | -0.02 | 52.91 | 15.30 | 11.05 |
| p15_rule_control | p15_rule_control | 23 | +0.00 | 0.00000 | identity | 0.00 | 0.00 | 0.00 |
| pead_ear | ew_benchmark | 66 | +5.51 | 1.75906 | 0.10 | 195.12 | 88.89 | 66.40 |
| sector_momentum | spy_benchmark | 66 | +31.79 | 0.65476 | 1.57 | 72.63 | 33.09 | 24.71 |
| spy_benchmark | spy_benchmark | 73 | +0.00 | 0.00000 | identity | 0.00 | 0.00 | 0.00 |
| template_top5 | ew_benchmark | 73 | +29.69 | 3.02842 | 0.33 | 319.41 | 151.38 | 113.61 |
| template_top5_gated | ew_benchmark | 73 | +29.69 | 3.02842 | 0.33 | 319.41 | 151.38 | 113.61 |
| xs_momentum_12_1 | ew_benchmark | 40 | -20.69 | 1.22745 | -0.42 | 174.89 | 64.73 | 47.42 |

Sector momentum's inception paired daily t is **1.565**, versus the review's 1.40 on its
previous input. Its current-cost t is **0.891**. Neither reaches the diagnostic critical
normal value **2.734** at one-sided `0.05/16`. No active non-reference book establishes
an edge from these comparisons. P15's candidate-level registered IC test remains its primary
experiment; daily book power is only a monetisation diagnostic.

## Protected books and recommendations

Protection was checked read-only against public `server/*registration*.json`, private
`live/*.json` (also nested live JSON), `registrations/**`, and `trials/**`.
Exact book-ID matches count even in historical registration references; related-family
prose is not evidence that the specific gated ID is a registered live dependency.
The two proposed gated IDs have no exact references in those inputs.

Private registration references protect `discretionary`, `dual_momentum`, `high_52wk`,
`p15_ai_ranked`, `sector_momentum` and `xs_momentum_12_1` among the active books.
Public registrations and the explicit AI/control list additionally protect all three P15
books, `momo_stopped`, `pead_ear`, `spy_benchmark` and `ew_benchmark`.
The tool checks these inputs again on every invocation, before any mutation.
Missing private input directories or unreadable files refuse the operation.
No private strategy parameters or research results are reproduced here.

| Active book | Recommendation | Reason |
|---|---|---|
| discretionary | KEEP | Owner book, not an alpha test; private registration reference. |
| dual_momentum | KEEP | Protected AI algorithm control and private registration reference; retain the original. |
| dual_momentum_gated | RETIRE | Exact copy of dual_momentum in all four ledgers; no separate protected reference. |
| ew_benchmark | KEEP | Screen-basket reference and comparator; excess vs SPY is context. |
| ew_voltarget | KEEP | Open drawdown/volatility question across a risk-off episode; nine current-cost returns cannot answer it. |
| high_52wk | KEEP | Private registration reference; retain regardless of weak power. |
| macro_composite | KEEP | Open risk-off drawdown question with a two-year charter; low excess alone cannot answer it. |
| momo_stopped | KEEP | Protected historical AI control and private registration reference. |
| p15_ai_ranked | KEEP | Registered P15 AI book; its registered IC looks govern the verdict. |
| p15_hybrid_veto | KEEP | Registered P15 AI book; retain the paired experiment. |
| p15_rule_control | KEEP | Registered P15 control; zero self-excess is an identity. |
| pead_ear | KEEP | Protected historical AI control; open event-sleeve expectancy question. |
| sector_momentum | KEEP | Private registration reference and frozen forward record; open drawdown question. |
| spy_benchmark | KEEP | Protected market/AI control; zero self-excess is an identity. |
| template_top5 | KEEP | Retain one original concentrated-momentum record; the six-month/risk-off charter question remains open. |
| template_top5_gated | RETIRE | Exact copy of template_top5 in all four ledgers; no separate protected reference. |
| xs_momentum_12_1 | KEEP | Private registration reference and frozen forward control; open screen-versus-momentum question. |

## Retirement operation

`tools.retire_books` defaults to a read-only published-snapshot preview. Repeated book,
reason and evidence arguments pair by order. `--apply` uses the normal writer connection
and wait policy, validates the whole batch in one transaction, then changes only `active`
and appends one audit row per book. A failed validation or write rolls the batch back.
Already retired books refuse a rerun without adding another audit row. Open orders refuse;
the tool cancels none. Equity, fills, orders, cash and position rows stay retained.

The audit payload retains the 2026-10-21 fields `portfolio_id`, `reason`, `positions_kept`,
`pending_cancelled`, `precedent`; it adds the supplied `evidence` path. Nonzero holdings
are counted in `positions_kept`, as in the earlier batch. `pending_cancelled` is always 0;
`precedent` stays `2026-08-18`. Actor: `operator.retire_books`. The audit's naive timestamp
stores actual UTC. The preview includes the exact prospective audit timestamp at its run;
an apply obtains its own current timestamp.

The tool refuses retirement before the latest marked session's 16:00 America/New_York close.
An after-close retirement therefore remains valid in that session's published report through
`server.nightly_reports._retired_after_session`. The next report drops the retired book,
while the complete equity CSV still retains it. Temporary-store tests exercise that validator,
including a retained stale holding, and a second-book audit-write failure rolls back the first.

Exact recommended preview command (no apply):

```sh
.venv/bin/python -m tools.retire_books \
  --book dual_momentum_gated \
  --reason "Exact copy of dual_momentum since inception; gate never fired through 2026-10-29." \
  --evidence docs/history/league-thin-2026-10-30.md \
  --book template_top5_gated \
  --reason "Exact copy of template_top5 since inception; gate never fired through 2026-10-29." \
  --evidence docs/history/league-thin-2026-10-30.md
```

The captured output is retained in the lane STATUS and reproduced below. No apply was run
against any real store. The product's active count remains 17 until the orchestrator applies
and publishes the retirement; a recommendation does not change that count.

```json
{
  "changes": [
    {
      "active": {
        "from": true,
        "to": false
      },
      "audit_row": {
        "action": "portfolio_retired",
        "actor": "operator.retire_books",
        "payload": {
          "evidence": "docs/history/league-thin-2026-10-30.md",
          "pending_cancelled": 0,
          "portfolio_id": "dual_momentum_gated",
          "positions_kept": 1,
          "precedent": "2026-08-18",
          "reason": "Exact copy of dual_momentum since inception; gate never fired through 2026-10-29."
        },
        "ts": "2026-10-30T13:38:46.544106+00:00"
      },
      "book": "dual_momentum_gated"
    },
    {
      "active": {
        "from": true,
        "to": false
      },
      "audit_row": {
        "action": "portfolio_retired",
        "actor": "operator.retire_books",
        "payload": {
          "evidence": "docs/history/league-thin-2026-10-30.md",
          "pending_cancelled": 0,
          "portfolio_id": "template_top5_gated",
          "positions_kept": 5,
          "precedent": "2026-08-18",
          "reason": "Exact copy of template_top5 since inception; gate never fired through 2026-10-29."
        },
        "ts": "2026-10-30T13:38:46.544106+00:00"
      },
      "book": "template_top5_gated"
    }
  ],
  "mode": "dry-run"
}
```
