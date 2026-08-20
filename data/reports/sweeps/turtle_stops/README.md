# Sweep — `turtle_stops`

_9 candidate(s) · **9 trials** · 10-fold protocol · generated 2026-08-20 10:24 UTC._

## Read this before the table

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+14.61%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `stop_mult-2.5__trail_mult-4.0` | 10 | **-3.38%** | -14.88% | 50% | -36.76% |
| `stop_mult-2.0__trail_mult-4.0` | 10 | **-5.92%** | -9.76% | 40% | -41.02% |
| `stop_mult-3.0__trail_mult-4.0` | 10 | **-7.11%** | -16.38% | 30% | -33.35% |
| `stop_mult-2.5__trail_mult-2.5` | 10 | **-8.83%** | -14.29% | 30% | -31.69% |
| `stop_mult-3.0__trail_mult-2.5` | 10 | **-10.20%** | -16.09% | 30% | -27.07% |
| `stop_mult-2.0__trail_mult-2.5` | 10 | **-11.47%** | -14.02% | 30% | -38.08% |
| `stop_mult-2.5__trail_mult-3.0` | 10 | **-14.67%** | -19.48% | 20% | -31.00% |
| `stop_mult-3.0__trail_mult-3.0` | 10 | **-15.84%** | -19.83% | 20% | -26.57% |
| `stop_mult-2.0__trail_mult-3.0` | 10 | **-18.31%** | -19.82% | 20% | -35.55% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

