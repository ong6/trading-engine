# Fill-model audit — 2026-08-20

> **Historical snapshot.** This predates fill model v4. See
> [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md)
> for current execution assumptions.

Diagnosis only. Nothing in `sim/` was changed; no job was enqueued or killed; every DB access
was `duckdb.connect(..., read_only=True)`. Repro script: `docs/repro_fill_integer_clamp.py`
(in-memory DuckDB, never opens the store).

Throughout: **[M]** = measured by a query/parse I ran. **[D]** = derived from those measurements
by an arithmetic model whose assumptions are stated. **[C]** = read off the code.

---

## 1 · How sizing, cash and the clamp actually work  [C]

**Sizing is against EQUITY, not cash.** Every strategy path:

- `sim/strategies/base.py:386` — `target_qty = target_weights.get(tk, 0.0) * pf.equity / price`
- `sim/strategies/turtle_breakout.py:70` — `qty = risk_frac * pf.equity / (stop_mult * atr)`
- `sim/strategies/pead_ear.py:104` — `qty = weight * pf.equity / price`

`pf.equity` is the day-`d` `sim_equity` mark (`sim/league.py:generate_all`). Orders are pure
intents; nothing checks cash at generation time. Dust below `MIN_ORDER_USD = 50` is dropped.

**Sells DO settle before buys in the same session.**
`sim/league.py:fill_pending` — `ORDER BY CASE side WHEN 'sell' THEN 0 ELSE 1 END, id`.
`sim/portfolio.py:rebuild_state` replays in the same order, so `--rerun` is exact. The
sell-before-buy ordering is correct and is not the source of the rejections.

**The clamp** lives in one place, `sim/portfolio.py:126-135`:

```python
if px > 0 and qty * px > cash:
    affordable = math.floor(cash / px) if cash > 0 else 0
    if affordable <= 0:
        ... return 0.0            # order rejected: insufficient_cash
    qty = float(affordable)       # order clamped
```

Two things happen here. Bounding a buy by available cash is **correct** — without it a
signal-close → next-open gap-up would create phantom leverage. Rounding the affordable quantity
to a **whole share** is not: every other sizing path in the engine is fractional, and no design
document asks for integer lots.

**Whole-share trading is NOT a documented design choice.** `trading-execution-design.md §2`
specifies next-open fills, the slippage tiers and the 1%-of-median-$vol liquidity guard, and says
nothing about lot size. `BUILDLOG.md:284` records the clamp's introduction on 2026-07-18 as a
negative-cash safety fix ("sells clamp to held qty, buys clamp to cash (floor-to-0 → rejected
insufficient_cash)"); `BUILDLOG.md:698` later refers to it in passing as "`apply_fill`'s integer
cash clamp" without justifying the integer part. `grep -rn "floor|fractional|whole.share|round("
sim/` returns the clamp and nothing else. **The `floor()` is incidental to the safety fix, not a
market-structure model.**

---

## 2 · Volume of the leak

### `logs/run-2026-08-19.log` (one nightly sweep run: banding × 9, momo_stop × 9, ew_benchmark × 2, 10 folds each)  [M]

| | count | Σ cash involved |
|---|---|---|
| `cash-clamp` (partial buy, qty floored) | **17,129** | floor residual **$536,633** |
| `insufficient_cash` (buy killed outright) | **2,634** | stranded **$1,002,268** |
| `sell-clamp` | 0 | — |

Per-event decomposition of each `cash-clamp`, on a $39,000 reference book:

| component | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|
| genuinely unaffordable (correct constraint) | $228.37 | $99.24 | $506.23 | $2,140.82 | $10,330.47 |
| stranded purely by `floor()` (the defect) | $31.33 | $13.02 | $65.04 | $315.51 | $1,649.30 |

**Only 12.1% of the clamp gap is the integer floor.** The other 87.9% is real: the book asked for
more than it had, because buys pay `open × (1 + slip)` while the sells that funded them received
`open × (1 − slip)`, and the whole batch was sized off the previous close. That part is the fill
model behaving as designed.

Worst books in that log, by floor-stranded + reject-stranded dollars:

| book | clamps | rejects | floor $ | reject-stranded $ |
|---|---|---|---|---|
| `sweep__momo_stop__n-5__stop_frac-0.9` | 924 | 70 | 27,999.76 | 119,985.46 |
| `sweep__banding__band_rank-15__n-5` | 916 | 67 | 34,360.63 | 98,035.22 |
| `sweep__momo_stop__n-5__stop_frac-0.85` | 896 | 66 | 27,371.31 | 96,081.71 |
| `sweep__momo_stop__n-5__stop_frac-0.8` | 907 | 75 | 27,230.12 | 95,926.75 |
| `ew_benchmark` (×2 families) | 550 | 112 | 15,840.18 | 19,680.22 |

Concentration is by **n=5** — the fewer names a book holds, the bigger each slot, the more of the
book a single killed buy strands.

### Stored fold JSONs — `data/reports/sweeps/*/results/` + `data/reports/walkforward/results/` (65 files)  [M]

Aggregating `folds[].n_fills` / `folds[].n_rejected`:

**1,013,340 fills · 5,670 rejected · 0.56% reject rate.**

Worst by reject rate: `dual_momentum` 50.0% (85/170) and `dual_momentum_gated` 44.2% —
a 1-position monthly book, so a killed buy is the *entire* book;
`sweep__turtle_stops__stop_mult-2.0__trail_mult-4.0` 9.6%; `high_52wk` 4.1%; `low_vol` 3.0%.
Zero rejects: every `mr_overlay` / `adaptive_mr` / `meanrev` variant (they target ≤50% deployed,
so they never run out of cash).

**`n_rejected` in the fold JSONs is, to within one order, entirely `insufficient_cash`**  [M].
Cross-checked by matching the 08-19 log's per-book `insufficient_cash` counts against the same
books' stored `Σ n_rejected` — exact ties on
`momo_stop n-20 stop_frac-0.85` (221=221), `n-20 stop_frac-0.8` (197=197),
`n-10 stop_frac-0.85` (135=135), `banding band_rank-15 n-10` (141=141),
`band_rank-30 n-5` (101=101), `band_rank-20 n-5` (80=80),
`band_rank-15 n-20` and `band_rank-20 n-20` (184=184 each), `ew_benchmark` (112 = 2×56).
So `illiquid` and `no_bar` rejects are ≈0, and the reject column in every stored backtest is a
cash-model artefact, not a liquidity result.

### Live league store (read-only SQL on `store/market.duckdb`)  [M]

```sql
SELECT f.portfolio_id, COUNT(*) n_buys,
       SUM(CASE WHEN f.qty < o.qty - 1e-9 THEN 1 ELSE 0 END) n_clamped,
       SUM((o.qty - f.qty) * f.fill_px) unfilled_notional
FROM sim_fills f JOIN sim_orders o ON o.id = f.order_id
WHERE f.side='buy' GROUP BY 1;
```

378 buy fills (2026-07-17 → 2026-08-19), **20 clamped (5.3%)**, $4,579.23 of buy notional never
executed. Every clamped fill has an integer quantity. **Zero rejected orders of any reason**
(`SELECT COUNT(*) FROM sim_orders WHERE status='rejected'` → 0, over 610 orders).
The live league has the clamp but has not yet hit a reject.

---

## 3 · Bug or correct constraint?

**Both, cleanly separable.**

*Correct:* bounding a buy by available cash, and settling sells before buys. 87.9% of the clamp
gap is a genuine shortfall from slippage + the overnight gap on a book sized to 100% of equity.
The residual on an ordinary name is rounding: excluding the leveraged/inverse ETF cluster, the
mean `insufficient_cash` reject strands **$42** — 11 bp of a $39,000 book  [M].

*Bug:* `math.floor`. Two failure modes, both reproduced in `docs/repro_fill_integer_clamp.py`:

1. **Rounding down the affordable quantity.** `ew_benchmark ZG buy 17.4366 → 11 @ $45.4430
   (cash $530.36)`. The book could afford 11.6709 shares; it bought 11 and left $30.49 idle.
2. **Killing the order when one share costs more than the balance.** The extreme case, straight
   from the log: `sweep__momo_stop__n-5__stop_frac-0.9 DRIP buy 0.7027334 @ $47,988.5430
   (notional $33,723.15 > cash $29,569.57) — fill rejected`. The strategy asked for **0.70 of a
   share**; the engine bought nothing and left **76% of the book in cash** for a week.

`DRIP` at $47,988 is a split-restated leveraged ETF (repeated reverse splits push the historical
price into five figures). This is where the money is:

**436 of 2,634 rejects (16.6%) are leveraged/inverse ETFs — and they account for $910,447 of the
$1,002,268 stranded (90.8%).**  [M]

Rejections do NOT cluster because of sell/buy ordering — that ordering is already correct, and
the live store has zero rejects across 22 book-days with both sells and buys on the same signal
date. They cluster on **high nominal share prices in concentrated (n=5, or single-position
`dual_momentum`) books.**

---

## 4 · Size of the bias

The right metric is time-weighted uninvested cash, not the sum of clamp events — the same dollar
is re-clamped every week and summing events triple-counts it.

### Direct measurement, live books  [M]

```sql
WITH r AS (SELECT portfolio_id, date, cash, equity,
                  ROW_NUMBER() OVER (PARTITION BY portfolio_id ORDER BY date) rn
           FROM sim_equity)
SELECT portfolio_id, COUNT(*) n, AVG(cash/equity)*1e4 mean_bp, MEDIAN(cash/equity)*1e4 med_bp
FROM r WHERE rn > 3 GROUP BY 1 HAVING COUNT(*) >= 8 ORDER BY 3;
```

(`rn > 3` drops each book's inception ramp, when it is 100% cash by construction and the mean is
meaningless.) Steady-state **median** cash for the books that target ~full deployment:

| book | median cash |
|---|---|
| `template_top5` / `_gated` | 5.3 bp |
| `high_52wk` | 8.0 bp |
| `template_top10_banded` / `_gated` | 10.0 bp |
| `dual_momentum` / `_gated` | 14.2 bp |
| `low_vol` | 26.3 bp |
| `spy_benchmark` | 28.5 bp |
| `sector_momentum` | 39.8 bp |
| `ew_benchmark` | 46.8 bp |
| `momo_stopped` | 47.4 bp |

`mr_overlay` (5,955 bp), `pead_ear` (6,064 bp), `macro_composite` (5,002 bp), `turtle_breakout`
(3,040 bp) and `discretionary` (8,993 bp) sit in cash **by design** — those strategies target
partial deployment. Their cash level is not a fill-model artefact.

`spy_benchmark` is the clean single-name proof: it holds 52 SPY bought at $747.807 against
$39,000 of cash. `39000/747.807 = 52.153` shares. The floor cost it 0.153 shares = **$114** left
permanently idle = exactly the 28.5 bp median measured above. **100% of that book's uninvested
cash is the integer floor.**  [M]

### Derived drag for the sweep books  [D]

Assumptions, stated: each stranding persists one weekly rebalance interval (5 sessions = 5/252
yr); book equity ≈ the $39,000 reference notional (actual equity drifts across folds); 20
book-runs × 10 folds × 3 years (24mo train + 12mo validate) = 600 book-years in the 08-19 log.

```
excess cash fraction = ($536,633 + $1,002,268) / $39,000 × (5/252) / 600 = 13.05 bp of equity
```

| gross return | annualised drag |
|---|---|
| 10%/yr | **1.30 bp/yr** |
| 17.7%/yr (`banding` mean train CAGR) | 2.31 bp/yr |
| 25.9%/yr (`banding` mean validate CAGR) | 3.38 bp/yr |

Split: integer-floor clamps 4.55 bp of cash → 0.46 bp/yr at 10%; `insufficient_cash` rejects
8.50 bp of cash → 0.85 bp/yr.

The live-store measurement is the independent cross-check and agrees: a permanent 28.5 bp cash
holding on a 10%/yr book is a 2.9 bp/yr drag.

**So: single-digit basis points per year. The premise that this biases every backtest materially
downward is not supported.**

### The caveat that IS worth acting on  [M]

The mean is tiny but the tail is not. **50 of 2,634 rejects strand more than 10% of a book's
equity; 293 strand more than 1%.** Over ~200 fold-runs in that log, a >10%-of-book stranding
event is available to roughly a quarter of folds. That is fold-level *variance*, not systematic
bias — but sweep rankings are compared on `mean_validate_cagr` across 10 folds, so a single
DRIP-class event landing in a strong week can move one fold's number by more than the parameter
effect being measured. Concentrated books (`n=5`) and single-position books (`dual_momentum`,
50% reject rate) are the exposed ones.

---

## 5 · Proposed fix — NOT applied

One line, `sim/portfolio.py:128`:

```python
affordable = cash / px if cash > 0 else 0.0        # was: math.floor(cash / px)
```

and lower the reject test to a dust floor rather than zero, so a rounding sliver still can't
create a $0.01 position:

```python
if affordable * px < MIN_FILL_USD:   # e.g. 1.0
    ... reject insufficient_cash
```

This makes the clamp consistent with the rest of the engine (fractional everywhere) and removes
the pathological case where a sub-1-share order is killed. It keeps the safety property that
motivated the clamp — cash can still never go negative.

**What it invalidates.** Everything. `sim_positions`, `portfolios.cash` and `sim_equity` are a
pure function of `sim_fills` via `rebuild_state`, and the change alters fill quantities, so:

- every stored fold JSON under `data/reports/sweeps/` and `data/reports/walkforward/` (65 files,
  1,013,340 fills) becomes non-comparable with anything produced after the change;
- the live league's equity curves since 2026-07-17 would need a `--rerun` over the whole span to
  be internally consistent, and the pre-registered forward record restarts;
- `docs/execution-drag.md` and any A/B whose two arms straddle the change are void.

Given a measured drag of 1–3 bp/yr, **the fix is not worth invalidating the forward record on its
own.** The sequencing that costs nothing: land it at a scheduled sweep regeneration, tagged in
`BUILDLOG.md` as a fill-model version bump, with the old results kept and labelled `fillmodel=v1`.

If only one thing changes, make it the reject branch (case 2). It is the pathological half, it is
90.8% of the stranded dollars, it is confined to a handful of high-priced ETFs, and clamping
`affordable` to a fraction only where `floor()` would return 0 leaves every other stored fill
byte-identical.

---

## Appendix · what was NOT measured

- Per-fold cash series for the sweep books. The walk-forward scratch stores
  (`scratch/wf__*/replay.duckdb`) are deleted at job end and the surviving ones belong to the
  running sweep, so they were left alone; `write_reports` exports `equity` but not `cash`, and
  the fold JSONs carry no cash series. The 13.05 bp figure above is therefore **derived**, with
  its holding-period assumption stated, not measured.
- Whether `n_rejected` is 100% `insufficient_cash` for the sweep families NOT covered by the
  08-19 log (`concentration`, `voltarget`, `meanrev`, `turtle_stops`, and the walk-forward set).
  The identity was verified only for `banding`, `momo_stop` and `ew_benchmark`.
