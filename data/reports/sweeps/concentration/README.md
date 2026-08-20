# Sweep — `concentration`

_6 candidate(s) · **6 trials** · 10-fold protocol · generated 2026-08-20 06:52 UTC._

## Read this before the table

**Every row here is one of 6 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+17.21%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `cap-50` — _identical to the benchmark; not a result_ | 10 | **+0.00%** | +0.00% | 0% | -37.53% |
| `cap-10` | 10 | **-0.39%** | +7.55% | 50% | -48.19% |
| `cap-75` | 10 | **-2.04%** | -2.16% | 40% | -36.26% |
| `cap-100` | 10 | **-3.29%** | -5.01% | 30% | -36.10% |
| `cap-30` | 10 | **-3.75%** | +1.54% | 40% | -42.58% |
| `cap-20` | 10 | **-5.49%** | +4.41% | 40% | -46.40% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

