# Experiment e1-spy-monday — SPY Monday intraday

*Pre-registered 2026-07-18 · report generated 2026-07-18 05:18 UTC · config hash `5dc40ff465de67a9`*

> **Pre-registered, frozen config.** This report was produced by `farm/experiment.py` from `farm/experiments/e1-spy-monday.yaml`. The config is immutable once this result exists (hash stored in every `experiment_results` row); a changed config is refused under this id.

## Hypothesis
> SPY shows a positive Monday intraday drift: buying the Monday open and selling the same Monday's close earns a small positive average per-trade return. The classic "weekend/Monday effect" was strongly positive intraday in early data and is expected to have decayed. Null hypothesis: mean Monday open->close return <= 0 net of costs.

- **Instrument:** SPY (single) · **entry:** weekday_open / monday · **exit:** same_day_close (same-bar open→close)
- **Registered expectation:** positive, ~10%/yr GROSS (decayed prior — not fitted). Source: trading-engine-design.md §12.3 experiment backlog (E1, approved/pre-registered) and the 0dte-casino-and-earnings-vol.md research run. The +10%/yr gross figure is the decayed prior, NOT a fitted value.
- **Cost (registered):** 3.0bp round-trip (~1.42%/yr at 47.3 trades/yr).
- **Kill criterion (forward):** FORWARD phase (starts with the paper league): after 40 out-of-sample Mondays, if mean <= 0 OR t-stat < 0.5, the strategy is killed. No re-optimization, no parameter search to rescue it.
- **Variants tried (multiple-testing N):** 5 — used for the Deflated-Sharpe haircut (see Methods).

## Data & partition accounting
- SPY daily bars from the store: **1993-02-01 → 2026-07-13** (real data, read-only).
- **Holdout = most recent 12 months of Mondays**, locked at cutoff **2025-07-13** (trades on/after are holdout).
- In-sample Mondays: **1534** · Holdout Mondays: **49** · Total: **1583** — 1534 + 49 = 1583 (✓ sums, no overlap).

## Results — in-sample vs LOCKED HOLDOUT (holdout computed once)

| Partition | n | mean/trade | t-stat | gross CAGR | net CAGR | ann. Sharpe | deflated Sharpe | max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| In-sample | 1534 | -0.0069% | -0.28 | +0.88% | -0.55% | -0.05 | 0.070 | -45.24% |
| **Holdout (once)** | 49 | 0.1350% | 1.66 | +8.36% | +6.77% | 1.66 | 0.677 | -1.73% |
| Full (reference) | 1583 | -0.0025% | -0.11 | +1.09% | -0.33% | -0.02 | 0.097 | -45.24% |

- **Registered gross expectation:** 10%/yr. **In-sample gross:** +0.88%/yr (0.09× the registered prior). **In-sample net:** -0.55%/yr.
- **In-sample t-stat** on the per-trade net mean: **-0.28** (mean/trade -0.0069%, sd 0.959%).
- **Deflated Sharpe (in-sample, N=5 trials):** **0.070** (benchmark SR0=0.0304 per-trade; annualized Sharpe -0.05).

## Verdict (in-sample only — holdout never feeds the decision)

> in-sample edge is weak or absent (mean <= 0 or t < 0.5); gross CAGR 0.88%/yr vs registered 10%/yr (0.09x); deflated Sharpe (N=5 trials) = 0.070

## Cost sensitivity (in-sample)
- Registered 3bp r/t → net CAGR **-0.55%/yr**.
- Conservative 20bp r/t (sim fill model, exec-design §2 SPY tier) → net CAGR **-8.23%/yr**, mean/trade -0.1768%, t -7.23.

## Subperiod stability (in-sample, 5-year blocks)

| Block | n | mean/trade | t-stat | gross CAGR | net CAGR | ann. Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| 1990-1994 | 91 | 0.0637% | 1.21 | +4.58% | +3.07% | 0.88 |
| 1995-1999 | 240 | -0.0277% | -0.40 | -0.17% | -1.61% | -0.18 |
| 2000-2004 | 238 | 0.0212% | 0.28 | +2.14% | +0.69% | 0.12 |
| 2005-2009 | 236 | -0.0950% | -1.15 | -3.40% | -4.77% | -0.51 |
| 2010-2014 | 236 | -0.0485% | -1.02 | -1.00% | -2.40% | -0.46 |
| 2015-2019 | 236 | -0.0452% | -1.08 | -0.81% | -2.21% | -0.49 |
| 2020-2024 | 233 | 0.1067% | 2.03 | +6.44% | +4.96% | 0.91 |
| 2025-2029 | 24 | 0.2016% | 0.91 | +11.49% | +9.89% | 1.29 |

_The decay hypothesis predicts the earliest blocks carry the effect and later blocks fade — read the trend, not any single block._

## Regime split (in-sample)

_Regime = SPY prior-day close vs its 200-day SMA, known BEFORE the Monday open (no look-ahead). The store's `screen_results.regime` only covers 2026-07-15→17 (3 days), so it is unusable historically; regime is computed from SPY price history instead — stated honestly._

| Regime | n | mean/trade | t-stat | gross CAGR | net CAGR | ann. Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| risk-on | 1097 | -0.0016% | -0.07 | +0.90% | -0.14% | -0.01 |
| risk-off | 400 | -0.0299% | -0.41 | -0.14% | -0.52% | -0.07 |

_(37 early in-sample Mondays had < 200 prior bars to define a regime and are excluded from this split only.)_

## Methods & honesty notes
- **No look-ahead:** the entry is the Monday open and the exit is the same bar's close — the open is known before the close. No signal or filter uses any data at/after the Monday open. Regime uses only the prior day.
- **Costs** applied multiplicatively: buy at open·(1+h), sell at close·(1−h), h = round-trip_bps/2/1e4.
- **CAGR** is geometric on the compounded per-trade equity curve over the partition's calendar span; the strategy is flat except on Mondays.
- **Annualized Sharpe** = (mean/sd per trade)·√(trades/yr), rf=0.
- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) = PSR(SR0), where PSR(SR*) = Φ[(SR−SR*)·√(n−1) / √(1−γ₃·SR + ((γ₄−1)/4)·SR²)] with γ₃ skew, γ₄ non-excess kurtosis, and the deflation benchmark SR0 = √V·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(Ne))], γ=0.5772 (Euler-Mascheroni), N = variants tried. **V (variance of trial Sharpes) is unknown**, so we use the SR-estimator sampling variance V = (1−γ₃·SR+((γ₄−1)/4)·SR²)/(n−1) as a documented, conservative fallback. DSR is a probability the true SR>0 after the multiple-testing/non-normality haircut.
- **Skew/kurtosis (in-sample per-trade):** skew -0.565, kurtosis 13.76 (Gaussian = 3).
- **Negative results are reported as prominently as positive ones** — the farm exists to kill bad ideas cheaply.
- **Storage:** identical config already has results — append skipped (holdout not re-touched); report refreshed.

## Forward (out-of-sample) plan
- The kill criterion runs FORWARD from league go-live: FORWARD phase (starts with the paper league): after 40 out-of-sample Mondays, if mean <= 0 OR t-stat < 0.5, the strategy is killed. No re-optimization, no parameter search to rescue it.
- The holdout above was touched exactly once, at this publication, and is not the forward test — the forward test is new Mondays after go-live.
- **The forward record is live and published separately: [`e1-spy-monday-forward.md`](./e1-spy-monday-forward.md)** — one row per out-of-sample Monday from 2026-07-20, written nightly by `farm/experiment_runner.py`, accumulating toward the 40-Monday kill evaluation.

