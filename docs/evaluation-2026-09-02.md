# Evaluation — league, research farm, data — 2026-09-02

> **Historical snapshot.** This records evidence available on 2026-09-02. Use
> [`review-2026-09-06.md`](review-2026-09-06.md) and the generated walk-forward index for
> current conclusions.

_External review pass. Everything marked **[fact]** was read from a file or a read-only query
against `store/market.duckdb` on 2026-09-02; everything marked **[read]** is the reviewer's
judgment. Nothing here was run through the engine and nothing in `store/` was touched._

## 0. Framing that governs every verdict below

- **The live record is 32 sessions old** (`sim_equity` 2026-07-17 → 2026-09-01; 26 sessions
  for the 07-28 cohort, 11 for the 08-18 pair, 21 for `macro_composite`) **[fact]**. Recomputed
  daily-excess t-stats vs SPY and vs EW: no book is beyond |t| = 1.3 **[fact]**. The league
  table (`data/reports/league.md`) is therefore not evidence for any verdict here; it is only
  used to flag books whose *own kill clock* is already running.
- Verdicts lean on the 10-fold walk-forward with bootstrap CIs
  (`data/reports/walkforward/*.md`, generated 2026-08-30, fill model v2), the nine sweep grids
  (`data/reports/sweeps/*/README.md`), and the in-sample backtests
  (`data/reports/backtests/README.md`, 2026-07-29, fill model v1, unstamped).
- Everything historical sits on a survivor-only universe (11% coverage in 1996, 42% in 2014,
  `docs/evidence-ceiling-2026-08-20.md`) and on a screen whose top-50 basket is today 64%
  healthcare (32 of 50 `ew_benchmark` positions, `fundamentals.sector`) and contains three
  leveraged ETFs (CRWL 2x, DLLL 2x, LABU 3x) **[fact]**. "Beats EW" means beats *that*.

## 1. League — 20 books

Six-week live figures are quoted only where a pre-registered kill criterion is already being
approached. WF = walk-forward 10-fold summary (`data/reports/walkforward/README.md`).

| Book | Verdict | The one fact that decides it |
|---|---|---|
| `spy_benchmark` | KEEP | Reference. |
| `ew_benchmark` | KEEP | Reference — but see §3: it holds a 3x biotech ETF and is a 64% healthcare bet, so every "vs EW" number in the store inherits that. |
| `discretionary` | KEEP | Human book, 1 fill; not a strategy under test. |
| `template_top5` | RETIRE | Breaches its own 40% max-DD kill line in **5 of 10** WF validate folds (−55.9, −41.6, −44.7, −46.9, −65.3%; `walkforward/template_top5.md`). The PASS verdict rests on one fold (+418%, 2020-21); median excess is +3.3% with CI [−15.0%, +79.7%]. |
| `template_top5_gated` | RETIRE | Twin: 0 sessions of live divergence from `template_top5` (`sim_equity` join, 33 dates). WF says the entry gate buys 14pp of DD (−51% vs −65%) at 2pp of mean excess; if the family is kept at all, keep this one, not the parent. |
| `template_top10_banded` | WATCH | INDISTINGUISHABLE (CI [−12.8%, +30.4%]); 15y backtest CAGR 14.1% vs EW 18.3% at −52.9% DD. Kill clock: trailing EW by 16.9pp after 6 weeks against a ">15% over 6 months" criterion. `banding` sweep: all n-10 cells negative median. |
| `template_top10_banded_gated` | RETIRE | Twin, 0 sessions of divergence; WF DD relief 2.2pp (−46.4 vs −48.6) for −0.1pp excess. Redundant slot. |
| `momo_stopped` | RETIRE | The A/B it exists for is answered: WF worst DD −48.0% vs the unstopped parent's −48.6%; `momo_stop` sweep, 9 cells, every median excess negative. The stop buys ~0.6pp of drawdown. |
| `dual_momentum` | WATCH | Distinguishable − vs EW ([−32.5%, −1.9%]) but judged vs SPY by charter; 15y backtest CAGR 7.9% vs SPY 13.1% **with a worse max DD** (−33.7% vs −30.4%), i.e. it did not deliver the one thing GEM promises. Not yet a kill on the 2-year window. |
| `dual_momentum_gated` | RETIRE-AS-TWIN | 0 live divergence. WF: gate halves worst DD (−17.5% vs −33.7%) at −0.3pp mean. Of the pair, this is the better book; run one, not both. |
| `mr_overlay` | RETIRE | Distinguishable − ([−38.0%, −10.5%]); `meanrev` sweep **9/9 cells distinguishable −**, best −10.7%; 15y backtest total −0.01%. The parameter space, not the parameter, fails. |
| `mr_overlay_gated` | RETIRE | Twin, 0 divergence; same family verdict. |
| `turtle_breakout` | RETIRE | Distinguishable − ([−32.6%, −9.1%]); `turtle_stops` sweep 9 cells all negative, 5 distinguishable −; WF worst DD −31.0% breaches its own 25% kill line; latest fold −8.8% vs EW +27.6%. |
| `sector_momentum` | WATCH | INDISTINGUISHABLE vs EW; the only equity book with WF validate Sharpe ≥1.9 in the latest fold at −7.9% DD; vs SPY (its charter benchmark) 5y +4.2pp, 15y-clamped −0.3pp CAGR. Low information but no kill signal. |
| `low_vol` | WATCH | INDISTINGUISHABLE ([−33.9%, +0.5%]); 15y backtest Sharpe 0.95, highest of any equity book, but max DD −35.7% vs SPY −30.4% fails its DD prong; carries a static-2026-market-cap look-ahead. |
| `high_52wk` | RETIRE | Distinguishable − vs EW ([−34.2%, −1.7%]) **and** 15y CAGR 6.9% vs SPY 13.1%: worse than both yardsticks. Also the book with 12.1% of equity frozen in EA/TALK/WBS (§3). |
| `pead_ear` | KEEP | Cannot be walk-forwarded (earnings dates 2026-04→2026-12 only). Forward-only by design, 26 fills, kill at 30 closed trades on expectancy. The only event sleeve; let it accrue. |
| `macro_composite` | KEEP (unvalidatable) | Only non-price-signal book; 2-year pre-registered horizon. WF impossible until a `--pit-lag` reconstruction backfill exists (`walkforward/README.md` exclusions). 21 sessions live. |
| `ew_voltarget` | WATCH | INDISTINGUISHABLE with the tightest CI in the league ([−7.4%, +2.0%]); DD −35.4% vs −37.5%. `voltarget` sweep: 6/6 cells within ±1% median. The rule does approximately nothing; harmless, uninformative. |
| `ew_trend_gated` | RETIRE | Distinguishable − ([−8.0%, −1.6%]) and worst DD −36.46% vs −37.54%: 1pp of relief for −4.3% mean excess. Its own charter's kill #1 ("no max-DD improvement across a full risk-off fold") is met in substance. |

**Duplicate slots [fact]:** all four `*_gated` twins are equal to the cent to their parents on
every one of 33 live sessions (`sim_equity` join, tolerance $0.005). Regime has been risk-on
every session since inception (`BUILDLOG.md` 2026-08-20 Next #3, `data/_meta.json`). Four
rows in every report carry zero information and inflate the comparison count.

**Net [read]:** 20 books → 3 references, 4 KEEP/WATCH on real hypotheses (`sector_momentum`,
`low_vol`, `pead_ear`, `macro_composite`), 3 WATCH on weak hypotheses (`template_top10_banded`,
`dual_momentum` family as one book, `ew_voltarget`), and 9 slots that the evidence has already
answered. A 10-book league would say everything this one says.

## 2. Research farm — what it established, what is noise

### Established (with the caveat that "established" here means "at the 10-fold level")

1. **Negative results are real and useful [fact].** Three parameter spaces are ruled out with
   CIs that exclude zero: mean-reversion on template names (`meanrev`, 9/9 distinguishable −),
   equity-curve drawdown throttles (`dd_throttle`, 5/6 −), and ATR-stopped breakouts
   (`turtle_stops`, 5/9 −, 0 positive). That is the farm's genuine output.
2. **No positive result exists anywhere [fact].** Across nine grids, 63 cells, the best median
   excess is `sector_cap/max_per_sector-15` at +0.50% [−0.66%, +1.46%], DSR 0.20. Top-of-grid
   DSRs run 0.00–0.44 against a ~0.95 bar.
3. **Gross-exposure scaling re-measures de-risking, not timing [fact].** `gross_voltarget`
   9/9 INDISTINGUISHABLE; the amended charter (`docs/charters/ew_gross_voltarget.md`) correctly
   re-bases the comparison on `static_exposure`, which is itself 5/5 INDISTINGUISHABLE and
   monotonically negative in median excess as exposure falls. Nothing here beats holding less.

### Noise being read as signal

- **The momentum family's PASS verdicts [fact→read].** `template_top5` mean excess +25.4% is
  fold 5 (+289.7pp vs EW) with the other nine summing to roughly zero; median +3.3%. The
  mechanical PASS/WATCH/REVIEW rule keys on the *mean*, which the reports themselves say was
  hijacked by 2018-21. The rule is mis-specified for this distribution and the authors know it;
  it should be changed to median or dropped, not annotated around.
- **"The screen is the edge" [read].** Every comparison is vs `ew_benchmark`, which is the
  screen. Nothing in the store tests the screen itself against a plain alternative (equal-weight
  top-50 by 12-1 return on the full liquid universe, no Minervini template). Until that control
  exists, "the screen is the edge" is the untested assumption every other result is relative to.
- **The `Universe` column jumps 3,905 → 12,105 between fold 9 and fold 10** in every WF page
  **[fact]**. Fold 10 counts something different (probably all tickers with any bar rather than
  tickers with the required history). The column exists specifically to show survivorship
  thinning; its last value is wrong and undermines the point.
- **Report header drift [fact].** `walkforward/README.md` line 3 says "6 folds, anchored
  2026-08-14"; every book page says 10 folds anchored 2026-08-28. `execution-drag.md` is dated
  07-29 with 124 fills; the store now has 968 (`sim_fills`). `backtests/README.md` does not say
  it is fill model v1.

### Does the evidence-ceiling argument hold?

- **Survivorship part: yes, and it is under-argued in one direction [read].** The doc argues
  the bias is common to both sides of "vs EW". That is weakest exactly for the books that look
  best: a top-5 RS book concentrates in high-RS small names, the population where delisting is
  most frequent, so it inherits *more* survivor lift than a 50-name basket. Differencing does not
  remove a bias that scales with concentration. This cuts against `template_top5`/`cap-10`
  further, not in their favour.
- **Power part: no, not as stated [read].** "50% power at +7pp/yr" is a property of the chosen
  test — bootstrap over n=10 fold-level returns — not of the data. Validate windows are
  non-overlapping, so the same 12 years give ~144 monthly paired excess returns (book − EW). A
  paired t or block bootstrap on monthly excess has an order of magnitude more observations
  and the same survivorship exposure. The fold was chosen as the unit for replay-independence
  reasons (D-WF2), but nothing prevents *reporting* at monthly granularity from the same
  replays. This is the cheapest available power and it has not been tried. The ceiling on
  *reaching further back* is real; the ceiling on *resolution within 2014-2026* is self-imposed.

### Statistical practice — findings

| Issue | Status | Note |
|---|---|---|
| Multiple comparisons | Partly handled | DSR per grid only; cross-grid N (63 cells + 20 books) never aggregated. Disclosed as a lower bound, which is correct. |
| In-sample rule selection | Disclosed, not avoided | All 2026-08 candidates were designed after reading the WF that showed EW's −36% DD; fold 10 (2025-08→2026-08) is the exact data the July 2026 registrations were written against. Fold 10 should be excluded from the CIs, not just marked ◈. |
| Survivorship | Disclosed, untested | The "common to both sides" claim is asserted; a test exists (re-run fold 10 on `universe_snapshot` as of 2026-07-16 vs today's universe, which the backtest README already did informally: 6 names gone in two weeks). |
| Inert-fold handling | Fixed 08-20 | Good: `status: inert` and exclusion tables. The earlier `+0.00%/REVIEW` row was published. |
| Fold-level unit | Wasteful | See power point above. |
| Median bootstrap at n=10 | Coarse, disclosed | Percentile CI on a median of 10 is order-statistic granular; the reports say so. |
| Verdict metric | Mis-specified | PASS on mean while ranking sweeps on median; two rules for the same question. |

## 3. Data quality and what it does to the numbers

| Item | Fact | Effect on trust |
|---|---|---|
| Stale marks | 11 positions carried at a dead close (`league.md`). EA last traded 2026-08-04 (20 sessions), TALK 08-14, WBS 08-19, FBRX 08-26; all four return `symbol_not_found` from the Nasdaq verifier (`data/_meta.json` price_verify). | `high_52wk` has 12.1% of equity frozen (EA+TALK+WBS), `momo_stopped` 9.8% and both `template_top10_banded*` 9.8% in FBRX. Their live returns are unknown to roughly that magnitude. No delisting handler exists in `sim/`. |
| Phantom bars | yfinance emits zero-volume bars at the last price after a name stops trading (EA: 4 bars). Stale detector re-keyed on `volume>0` (BUILDLOG 08-20c). | Live marks now flagged. Historical replays are unaffected only because dead names are absent from `prices` entirely — which is the survivorship problem wearing a different hat. |
| Fill model v1→v2 | v2 (fractional clamp) landed in commit 73f3de3 on 2026-08-20. Walk-forward and all 9 sweep grids regenerated 08-29/30 under v2, stamped in JSON (99 files `fill_model: v2`). Backtests (78 runs, 07-29) are v1 and carry no stamp. The live record is v1 through 08-20 and v2 after. | Historical WF/sweep numbers are internally consistent. The live equity series is spliced across two fill models with no marker in `league.md`. The BUILDLOG has no entry recording that v2 shipped; its last two entries list it under "Next". Measured effect is 1-3 bp/yr average, so the splice is cosmetic except for the stranded-cash tail. |
| Leveraged ETFs in the screen | 812/12,459 names flagged; every stored screen passes 6-25 (BUILDLOG 08-20b). Today `ew_benchmark`, `ew_voltarget`, `ew_trend_gated` hold CRWL (2x), DLLL (2x), LABU (3x); every template book holds DLLL, `template_top5` at 287.9 shares (~a full 20% slot). Policy `ex-leveraged` exists, default off. | The yardstick every book is judged against carries embedded 2-3x leverage. The "run both policies and publish the pair" decision (BUILDLOG Next #2) has not been executed. |
| Sector concentration | 32/50 `ew_benchmark` holdings are Healthcare (query on `sim_positions` × latest `fundamentals`). | "Diversified benchmark" is a sector bet; fine as a fact, but the WF's "vs EW" is then largely "vs healthcare momentum" in the current fold. |
| Price source | Single-sourced yfinance; stooq permanently blocked. Nasdaq verifier: 178 checked, 170 agree, 8 disagree, all on the as-of session O/H/L (settlement lag), 0 close disagreements. | Good. The verifier firing proof (BUILDLOG 08-20b) is the right kind of evidence. |
| Fundamentals | 7 weekly snapshots, 2026-07-18 → 2026-08-28, 28,826 rows. | `low_vol` cap floor and `ew_sector_capped` sector are 2026 values restamped into 2014. Disclosed. Any value/quality book is 2-3 years away from testable. |
| Earnings | `earnings_calendar` 2026-04-22 → 2026-12-01. | PEAD has no history; forward-only. |
| Macro signals | 19 series; VIX 1990→, `vix3m` 2009→, breadth 2012→, `hy_oas` only 2023-08→. `fetch_as_of` = collection date. | `macro_composite` cannot be replayed honestly; the credit block has 3 years of history even if it could. |
| Intraday | 1,645 tickers, 1m/5m, 2026-04-21 → 2026-09-01, 25.1M rows. | 4.5 months. Enough to calibrate the slippage model against real opens; not enough to backtest an intraday strategy. |
| Universe snapshots | 35 dates, 432,804 rows since 2026-07-16. | The only compounding fix for survivorship; usable for a point-in-time universe in ~2028. |

## 4. Highest-value next actions, ranked

1. **Settle EA, TALK, WBS, FBRX to cash and add a delisting handler** — four books' live
   equity is 10-12% frozen; every live number for them is fiction until this is done, and it is
   the only item here that gets worse each session.
2. **Collapse the league to ~10 books** (one of each gated pair, drop `mr_overlay*`,
   `turtle_breakout`, `momo_stopped`, `ew_trend_gated`, `high_52wk`, `template_top5*`) — the
   evidence has answered them; fewer books means fewer comparisons to deflate against and
   frees slots for §5.
3. **Re-report every WF book and sweep cell on monthly paired excess vs EW (n≈144) with a
   block bootstrap**, from the fold JSONs already on disk — an order of magnitude more
   resolution at zero replay cost; this tests whether the "ceiling" is the data or the test.
4. **Publish `ew_benchmark` under `ex-leveraged` beside the default and decide the policy** —
   the benchmark holds a 3x ETF; until this is settled, "vs EW" is partly "vs leverage".
5. **Add the missing control: equal-weight top-50 by plain 12-1 momentum on the full liquid
   universe, no Minervini template** — the only way to test the store's central claim that the
   screen, rather than momentum, is the edge.

Housekeeping that should ride along: stamp fill model into `league.md` and
`backtests/README.md`; fix the `walkforward/README.md` header (6→10 folds, anchor); fix the
fold-10 `Universe` count; regenerate `execution-drag.md` at 968 fills; write the BUILDLOG entry
for v2 landing.

## 5. Gaps in the strategy set

Everything live is long-only, daily-or-slower, price-only, US-equity, and (except three ETF
books) drawn from one Minervini screen. Not represented at all:

| Return source / style | In store today | Feasible with data on hand? |
|---|---|---|
| Plain cross-sectional momentum (12-1), unscreened | No — every momentum book is template-gated | **Yes now** (daily EOD, 4k names). Also the missing control for §2. |
| Short-term reversal (1-month, or 5-day on liquid names) | No — `mr_overlay` is RSI(2) on template passers only | **Yes now**. Cross-sectional, monthly, top/bottom decile on prior-month return. Long-only version: buy the losers. |
| Cross-sectional value (E/P, B/P, EV/EBITDA) | No | **Not yet** — fundamentals are 7 weekly snapshots since 07-18. Accrue; ~2028. |
| Quality / profitability / accruals | No | **Not yet**, same reason. |
| Multi-asset trend / time-series momentum via ETFs (SPY, TLT, IEF, GLD, DBC, UUP, EFA, EEM) | Partially — GEM is SPY/EFA/BIL only | **Yes now**. Long history for most ETFs; long-only via cash proxy. |
| Carry / term structure via ETFs | No | **Yes now**: bond carry (TLT/IEF/SHY vs BIL with `t10y2y` in `macro_signals`); commodity roll via USO/UNG/DBC (in universe); VIX term structure via `vix`/`vix3m` (2009→) driving SVXY/VIXY or plain SPY exposure. |
| Options-free volatility harvesting | Half — `ew_gross_voltarget` candidate scales exposure; nothing harvests the VRP | **Yes now**: SVXY-style short-vol via VIX contango signal with hard cash-out; or vol-scaled SPY. No options data, so this is the only route. |
| Seasonality (turn-of-month, pre-holiday, sell-in-May, earnings-season effects) | Only E1 (SPY Monday), which is on course to be killed at n=40 | **Yes now** on SPY 1993→ and the 4k names; cheap, pre-registerable, low power per effect. |
| Overnight vs intraday return decomposition (close→open vs open→close) | No | **Yes now** from daily OHLC; the overnight-drift long is a documented anomaly and the fill model already trades opens. |
| Corporate-action events (ex-dividend drift, split announcement drift, dividend capture) | No | **Yes now**: `corporate_actions` has 8,706 splits and 401k dividends, point-in-time by fetch. |
| Intraday (opening-range breakout, gap fade, VWAP reversion) | No | **Forward-only**: 1m archive is 4.5 months. First use should be calibrating `sim/fills.py` slippage against realised open prints, not a strategy. |
| Earnings-fundamental PEAD (SUE, not price reaction) | No — `pead_ear` is price/volume reaction only | **Not yet**: needs EPS surprise history; earnings table is 2026-04→. |
| Long-short / market-neutral anything | No — design is long-only | Out of scope by design; note that every "defensive" book is therefore a beta dial, not a hedge. |
| Sector-neutral or industry-relative momentum | No — `sector_cap` candidate caps count, does not neutralise | **Yes now** but with the 2026-sector look-ahead already disclosed for `ew_sector_capped`. |

**Recommended first three from this table [read]:** unscreened 12-1 momentum (control),
1-month cross-sectional reversal (uncorrelated to everything live), multi-asset ETF trend with
BIL (a real drawdown-reducer candidate that does not depend on the survivor universe at all,
since ETFs are the survivors). All three are daily-EOD, long-only, and walk-forwardable today.
