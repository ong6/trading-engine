# Experiment e1-spy-monday — FORWARD (out-of-sample) record

*Forward phase registered 2026-07-29 · report generated 2026-09-15 22:33 UTC · params hash `5dc40ff465de67a9` · forward-config hash `399ce03bee8bab4e`*

> **NO RESULT YET — 8 of 40 out-of-sample Mondays.** This experiment is not evaluated until the pre-registered sample is complete. Anything below is an accumulating record, **not** a verdict: reading a mean or a t-stat at n=8 and calling it a finding is exactly the peeking the §12.3 protocol exists to prevent. **32 Mondays to go.**

## Frozen registration

| Field | Value |
|---|---|
| Hypothesis | SPY shows a positive Monday intraday drift: buying the Monday open and selling the same Monday's close earns a small positive average per-trade return. Null hypothesis: mean Monday open->close return <= 0 net of costs. |
| Instrument / rule | SPY only — enter **monday open**, exit **same-bar close** |
| Expectation | positive, ~10%/yr **gross** vs ~1.2–1.5%/yr costs (decayed prior, not fitted) |
| **Kill criterion** | after 40 out-of-sample Mondays, if mean <= 0 OR t-stat < 0.5 the strategy is KILLED — evaluated on **net (league cost model, 20bp round-trip)**. No re-optimization. |
| Out-of-sample start | **2026-07-17** — first out-of-sample Monday is the first Monday on or after it (2026-07-20) |
| Cost model | `sim/fills.py slippage_bps_for(median_dollar_vol('SPY', monday))` → **20bp round-trip** (10bp/side) |
| Params hash | `5dc40ff465de67a9b887966ba853bf5dfcb310076edd171739c4fd7ebe925d35` |
| Runtime contract | v6 `5a665966f7bad78474dab9367618aab4016ea847fec8bba9a92966e7706e5612` |
| Runtime migration | 2026-09-13 interruption-safe transaction cleanup: every explicit DuckDB transaction now rolls back process-level interruptions, preserves the original failure if cleanup also fails, and leaves borrowed connections reusable; the frozen seven-observation E1 prefix, strategy, execution economics, and verdict rules are unchanged |

Registration source: `farm/experiments/e1-spy-monday.yaml` (pre-registered 2026-07-18, frozen) + `farm/experiments/e1-spy-monday.forward.json` (forward phase, frozen). Design authority: trading-engine-design.md §12.3.

## Out-of-sample record (the only series that counts)

| # | Monday | open | close | gross | net (20bp) | cum gross | cum net |
|--:|---|--:|--:|--:|--:|--:|--:|
| 1 | 2026-07-20 | 747.06 | 742.09 | -0.6653% | -0.8637% | -0.6653% | -0.8637% |
| 2 | 2026-07-27 | 744.91 | 739.09 | -0.7813% | -0.9795% | -1.4414% | -1.8348% |
| 3 | 2026-08-03 | 749.44 | 757.67 | +1.0982% | +0.8962% | -0.3590% | -0.9551% |
| 4 | 2026-08-10 | 772.60 | 773.03 | +0.0557% | -0.1442% | -0.3036% | -1.0980% |
| 5 | 2026-08-17 | 776.18 | 772.67 | -0.4522% | -0.6511% | -0.7544% | -1.7419% |
| 6 | 2026-08-24 | 764.78 | 763.47 | -0.1713% | -0.3708% | -0.9244% | -2.1062% |
| 7 | 2026-08-31 | 767.33 | 767.05 | -0.0365% | -0.2362% | -0.9606% | -2.3375% |
| 8 | 2026-09-14 | 759.00 | 760.88 | +0.2477% | +0.0474% | -0.7153% | -2.2912% |

_Every row is one real stored SPY daily bar; holiday Mondays have no bar and are simply absent (no trade that week). Rows are append-only — a Monday is written once, after its session has settled, and never revised. The published machine-readable checkpoint hashes the complete stored prefix._

## Running statistics (informational until n = 40)

| Series | n | mean/Monday | sd | t-stat | cumulative | win rate |
|---|--:|--:|--:|--:|--:|--:|
| gross | 8 | -0.0881% | 0.5972% | -0.42 | -0.715% | 3/8 |
| **net — 20bp r/t (kill series)** | 8 | -0.2878% | 0.5960% | -1.37 | -2.291% | 2/8 |
| net — 3bp r/t (registered) | 8 | -0.1181% | 0.5970% | -0.56 | -0.953% | 3/8 |

- **Mondays recorded:** 8 / 40 · **Mondays to kill-evaluation:** **32**.
- **Kill test (runs once, at n = 40):** kill if `mean <= 0` **or** `t < 0.5` on the net series. Current standing — mean -0.2878%, t -1.37 — **would KILL** if the criterion were applied today, which it is **not**.
- **Frozen cost sensitivity:** net uses compatibility profile `baseline_v1` (`6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`), 20bp round-trip for SPY's liquidity tier — 6.7× stricter than the 3bp the backtest registered. The registered-cost row is shown so the forward record can also be read against the original pre-registration.

## Backtest context — NOT part of the out-of-sample record

The identical computation over the **2 years of Mondays immediately before the out-of-sample start** (2024-07-22 → 2026-07-13). This is history the rule was registered against; it has **no bearing on the kill decision** and is never written to `experiment_results` as a forward row.

| Series | n | mean/Monday | sd | t-stat | cumulative | win rate |
|---|--:|--:|--:|--:|--:|--:|
| gross | 96 | +0.1655% | 0.7056% | 2.30 | +16.93% | 58/96 |
| net (20bp r/t) | 96 | -0.0347% | 0.7042% | -0.48 | -3.50% | 43/96 |

The full pre-registered backtest (1990→2026, in-sample vs a locked holdout, deflated Sharpe, subperiod and regime splits) lives in the sibling report [`e1-spy-monday.md`](./e1-spy-monday.md). **Neither that backtest nor this context window can rescue or condemn the rule** — only the 40 out-of-sample Mondays above can.

## Method & honesty notes
- **Gross** = close/open − 1 on the stored Monday daily bar. **Net** applies the frozen `baseline_v1` compatibility profile multiplicatively: buy at open·(1+s), sell at close·(1−s), s = per-side cost/1e4. For SPY, the profile's tiered spread plus fixed adverse component is 10.0 bp/side (60-bar median dollar volume ~$36bn, far above the $50M top tier) → **20bp round-trip**.
- **No look-ahead.** The entry is the Monday open and the exit is that same bar's close — the registered mechanics, and the open is known before the close. Nothing else is read at or after the open; even the slippage tier comes from bars strictly *before* the Monday.
- **No fabricated bars.** A Monday without a real stored open+close (market holiday) produces no row at all, rather than a synthetic flat trade.
- **No peeking-driven change.** The config, the cost model, the kill rule and the sample size were all frozen before this evidence existed. If E1 is killed at n=40 it is killed; there is no re-optimization branch.
- **Negative results are published exactly like positive ones** — the farm exists to kill bad ideas cheaply (§12.3).
- **Storage:** no new settled Mondays — nothing appended; the report was regenerated from `experiment_results` (re-running is a no-op by design).

