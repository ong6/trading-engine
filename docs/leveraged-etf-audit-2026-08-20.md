# Leveraged & inverse ETFs in the universe — audit, 2026-08-20

**Status: measured, nothing turned on.** A classifier and an off-by-default
exclusion flag were built. No stored screen, fill or result was mutated. Every
query below ran against `store/market.duckdb` with `read_only=True`.

Throughout: **MEASURED** = the output of a query or a run that is reproduced
here. **READ** = inferred from reading code, not executed. **UNMEASURABLE** =
the data required does not exist on disk; said so rather than estimated.

---

## 1. The classifier

`engine/lib/leverage.py`. Six rules over `universe.name`, with `universe.etf`
used only to promote a bare `>=1.5x` multiplier. Precision was prioritised over
recall throughout, because a false positive silently deletes a legitimate name
from the universe forever while a false negative leaves one fund in a 500-name
screen.

| rule | flagged | of which liquid | anchor |
|---|---|---|---|
| `multiplier` | 387 | 118 | `2X`/`3x`/`-1x`/`1.5X` **plus** a direction word |
| `leveraged_word` | 153 | 30 | `Leverage(d)`, minus `Leveraged Loan` |
| `direxion_bull_bear` | 125 | 64 | `Direxion` + `Bull`/`Bear` |
| `proshares_ultra` | 90 | 28 | `ProShares Ultra*` (incl. `UltraShort`) |
| `inverse` | 20 | 8 | `Inverse` |
| `proshares_short` | 17 | 6 | `^ProShares Short <underlying>` |
| `ultrapro` | 11 | 8 | `UltraPro` |
| **total** | **812** | **265** | of 12,459 universe rows / 4,118 liquid |

### Tokens deliberately REFUSED (this is the whole design)

Every one of these was checked against the live `universe` table before being
rejected:

* **bare `Bear`** — `Build-A-Bear Workshop, Inc.` (BBW) is a real, liquid stock
  that matches. `Ranger Equity Bear Bear ETF` (HDGE) is an actively-managed
  short fund, not a leveraged one.
* **bare `Short`** — 218 universe names contain it; the great majority are
  short-DURATION bond funds (`Vanguard Short-Term Bond ETF`, `JPMorgan
  Ultra-Short Income ETF`).
* **bare `Ultra`** — `Ultra Clean Holdings`, `Ultragenyx`, `Ultrapar`,
  `Ultralife` are operating companies; ~30 more are ultra-short BOND funds.
  Only `ProShares Ultra*` and the `UltraPro` brand are leveraged.
* **bare `Bull`** — `Simplify Bond Bull ETF`, `TrueShares Quarterly Bull Hedge`.
* **bare `\d+X`** — **`10x Genomics, Inc.` (TXG)** is a real, liquid stock. This
  is why the multiplier rule requires a corroborating direction word (or the
  ETP flag with a multiplier >= 1.5, which also excludes `IncomeSTKd 1x Bitcoin
  & 1x Gold Premium ETF`, a 1x income fund).
* **`Leveraged Loan`** — a credit asset class. `State Street SPDR S&P Leveraged
  Loan ETF` (LVLN) is unlevered and is explicitly carved out.

### Validation (MEASURED)

* **Recall:** 94 hand-listed leveraged/inverse tickers (TQQQ, SQQQ, SPXL, SPXS,
  TNA, TZA, SOXL, SOXS, FAS, FAZ, NUGT, DUST, JNUG, JDST, YINN, YANG, TMF, TMV,
  UVXY, SVXY, SVIX, FNGU, FNGD, BULZ, BERZ, NVDL, TSLL, MSTU, CONL, BITX, …).
  All 94 are in the universe. **0 missed.**
* **Precision:** a 33-name control list of legitimate look-alikes (BBW, TXG,
  UCTT, RARE, UGP, ULBI, LVLN, JPST, VUSB, BSV, SCHO, VCSH, MINT, ICSH, FTLS,
  CLSE, HDGE, QBER, QBUL, RFIX, CLIX, DWSH, SHRT, ULTY, UPAR, UAPR, ISBG, ISSB,
  YEAR, NEAR, PULS, GSY, …). **0 flagged.**
* Every one of the 118 flagged names that carries NO explicit
  multiplier/`Inverse`/`Leveraged` token — the riskiest set, where the flag
  rests on a brand rule alone — was printed and read by hand. All 118 are
  genuine leveraged or inverse products (98 `ProShares Ultra*`, 11 `UltraPro`,
  17 `ProShares Short`).

### Names I am NOT sure about (reported, not quietly included)

These are **deliberately left UNFLAGGED**. Each is arguably in scope; none is a
`2x`/`3x` daily-reset fund, so under a precision-first rule they stay in:

| ticker | name | why it is borderline |
|---|---|---|
| `HDGE` | Ranger Equity Bear Bear ETF | actively-managed short book, unlevered |
| `DWSH` | AdvisorShares Dorsey Wright Short ETF | short book, unlevered |
| `SHRT` | Gotham Short Strategies ETF | short book, unlevered |
| `UPAR` | UPAR Ultra Risk Parity ETF | ~1.4x levered risk parity — genuinely levered, but no token says so |
| `TUA` | Simplify Short Term Treasury Futures Strategy ETF | futures notional leverage |

And two that ARE flagged but sit at the edge of the definition:

| ticker | name | note |
|---|---|---|
| `SVXY` | ProShares Short VIX Short Term Futures ETF | -0.5x inverse, not levered long |
| `ELOL` | Leverage Shares 100% TSLA AND 100% SPCX Daily ETF | 200% gross, expressed as two 100% legs |

---

## 2. How often has a flagged name passed the screen? (MEASURED)

All 26 stored `run_date`s in `screen_results` (2026-07-15 → 2026-08-19).
**Every single screen ever stored has passed at least six of them.**

| run_date | passers | flagged | | run_date | passers | flagged |
|---|---|---|---|---|---|---|
| 2026-07-15 | 629 | 19 | | 2026-08-04 | 710 | 22 |
| 2026-07-16 | 651 | 18 | | 2026-08-05 | 678 | 15 |
| 2026-07-17 | 642 | 12 | | 2026-08-06 | 645 | 17 |
| 2026-07-20 | 624 | 10 | | 2026-08-07 | 626 | 21 |
| 2026-07-21 | 675 | 20 | | 2026-08-10 | 631 | 20 |
| 2026-07-22 | 661 | 18 | | 2026-08-11 | 621 | 18 |
| 2026-07-23 | 664 | 15 | | 2026-08-12 | 656 | 24 |
| 2026-07-24 | 666 | 10 | | 2026-08-13 | 653 | 25 |
| 2026-07-27 | 647 | 11 | | 2026-08-14 | 663 | 23 |
| 2026-07-28 | 654 | 13 | | 2026-08-17 | 680 | 25 |
| 2026-07-29 | 630 | 10 | | 2026-08-18 | 603 | 18 |
| 2026-07-30 | 632 | 6 | | 2026-08-19 | 534 | 15 |
| 2026-07-31 | 631 | 9 | | | | |
| 2026-08-03 | 647 | 15 | | **min/median/max** | | **6 / 17 / 25** |

**42 distinct flagged tickers have passed at least once.** The 2026-08-19 count
is **15**, not the 6 named in the brief — the earlier pass missed the entire
`ProShares Ultra`/`UltraPro` family and a 4X ETN.

| ticker | dates passed | name |
|---|---|---|
| DPST | 25 | Direxion Daily Regional Banks Bull 3X ETF |
| UDOW | 25 | ProShares UltraPro Dow30 |
| ERX | 25 | Direxion Energy Bull 2X ETF |
| SVIX | 23 | -1x Short VIX Futures ETF |
| UWM | 22 | ProShares Ultra Russell2000 |
| TNA | 21 | Direxion Small Cap Bull 3X ETF |
| URTY | 21 | ProShares UltraPro Russell2000 |
| GUSH | 20 | Direxion Daily S&P Oil & Gas Exp. & Prod. Bull 2X ETF |
| LABU | 17 | Direxion Daily S&P Biotech Bull 3X ETF |
| SPXL | 16 | Direxion Daily S&P 500 Bull 3X ETF |
| UPRO | 16 | ProShares UltraPro S&P 500 |
| **SPYU** | **15** | **MAX S&P 500 4X Leveraged ETNs due October 30, 2043** |
| DLLL | 15 | GraniteShares 2x Long DELL Daily ETF |
| DDM | 14 | ProShares Ultra Dow30 |
| UCO | 14 | ProShares Ultra Bloomberg Crude Oil |
| LLYX | 11 | Defiance Daily Target 2X Long LLY ETF |
| ROM | 11 | ProShares Ultra Technology |
| DFEN | 10 | Direxion Daily Aerospace & Defense Bull 3X ETF |
| SSO | 10 | ProShares Ultra S&P500 |
| ASMG | 9 | Leverage Shares 2X Long ASML Daily ETF |
| CURE | 8 | Direxion Daily Healthcare Bull 3X ETF |
| QLD | 8 | ProShares Ultra QQQ |
| CRWL | 8 | GraniteShares 2x Long CRWD Daily ETF |
| TQQQ | 6 | ProShares UltraPro QQQ |
| TECL | 6 | Direxion Daily Technology Bull 3X ETF |
| SVXY | 6 | ProShares Short VIX Short Term Futures ETF |
| USD | 5 | ProShares Ultra Semiconductors |
| AMUU | 5 | Direxion Daily AMD Bull 2X ETF |
| HIBL | 4 | Direxion Daily S&P 500 High Beta Bull 3X ETF |
| AMDG | 4 | Leverage Shares 2X Long AMD Daily ETF |
| AMDL | 4 | GraniteShares 2x Long AMD Daily ETF |
| DRN | 4 | Direxion Daily Real Estate Bull 3X ETF |
| MQQQ | 3 | Tradr 2X Long Innovation 100 Monthly ETF |
| BTCZ | 3 | T-Rex 2X **Inverse** Bitcoin Daily Target ETF |
| SBIT | 3 | ProShares **UltraShort** Bitcoin ETF |
| MSFD | 2 | Direxion Daily MSFT **Bear** 1X ETF |
| GOOX | 2 | T-Rex 2X Long Alphabet Daily Target ETF |
| YANG | 2 | Direxion Daily FTSE China **Bear** 3X ETF |
| GEVX | 2 | Tradr 2X Long GEV Daily ETF |
| GGLL | 2 | Direxion Daily GOOGL Bull 2X ETF |
| BITI | 1 | ProShares **Short** Bitcoin ETF |
| EDC | 1 | Direxion Emerging Markets Bull 3X ETF |

Note the six INVERSE names in that list (SVIX, SVXY, BTCZ, SBIT, MSFD, YANG,
BITI). A trend-template screen that requires price above a rising 200-day SMA
passing a 3x SHORT fund is the screen correctly identifying that the fund's
underlying has been falling for a year. It is still a daily-reset short book,
and `template_top5` would buy it long.

---

## 3. Which books have held one?

### Live store (MEASURED)

`sim_fills` holds 599 fills. **12 of them are on flagged names, and every one is
the same ticker — `DLLL`, GraniteShares 2x Long DELL Daily ETF.** Six books
bought it:

| portfolio_id | buys | sells | first | last | still holding |
|---|---|---|---|---|---|
| `momo_stopped` | 1 | 1 | 2026-08-10 | 2026-08-17 | **yes** (120.82 sh) |
| `news_gated_momo` | 1 | 1 | 2026-08-10 | 2026-08-17 | **yes** (117.25 sh) |
| `template_top10_banded` | 2 | 2 | 2026-07-27 | 2026-08-17 | **yes** (102.38 sh) |
| `template_top10_banded_gated` | 2 | 2 | 2026-07-27 | 2026-08-17 | **yes** (102.38 sh) |
| `template_top5` | 2 | 2 | 2026-07-27 | 2026-08-17 | no (0 sh) |
| `template_top5_gated` | 2 | 2 | 2026-07-27 | 2026-08-17 | no (0 sh) |

`sim_positions` (MEASURED): 6 rows on flagged names, 4 with non-zero quantity —
the four books above. **Four live league books are long a 2x ETF right now.**

### Stored fold results — **UNMEASURABLE**

Checked all **65** result JSONs under `data/reports/walkforward/results/` and
`data/reports/sweeps/*/results/`. The fold record is:

```
['dividend_cash','first_session','index','last_session','n_dividend_credits',
 'n_fills','n_rejected','n_validate_fills','runtime_s','sessions','split_date',
 'split_session','status','train','train_start',
 'train_start_clamped_to_data_floor','validate','validate_end']
```

Counts only. **No ticker appears in any of the 65 files** (the two files that
grep on `positions` match the word inside a `description` string). READ from
`farm/backtest/replay.py` and `farm/walkforward/runner.py`: `sim_fills` and
`sim_positions` live only in the per-job scratch DB, which the job `rmtree`s in
its `finally` block. So **which historical books held which leveraged fund is
not recoverable from anything on disk** — it can only be re-derived by re-running
a replay with `keep_scratch`, which this audit did not do.

This is a real gap and it is the same class of defect as the BUILDLOG's
2026-08-20 entry: the number that got published (`n_fills`) is not the number
that would let anyone check it.

---

## 4. Reverse-split price artifacts (MEASURED)

`prices` tickers whose maximum stored close exceeds $2,000:

* **universe-wide: 84**
* **flagged: 35** — 4.51% of the 776 flagged tickers that have price history
* non-flagged: 49 — **0.43%** of 11,329

A flagged name is **10.4x more likely** to carry an implausible back-adjusted
close, and flagged names are **42% of all such tickers** while being 6.4% of the
priced universe. All 35 are `liquid = TRUE`, so all 35 are screen-eligible.

| ticker | min close | max close | name |
|---|---|---|---|
| SPXU | 33.02 | **666,400.00** | ProShares UltraPro Short S&P500 |
| SRTY | 20.49 | 614,160.00 | ProShares UltraPro Short Russell2000 |
| ZSL | 15.39 | 447,840.00 | ProShares UltraShort Silver |
| UVIX | 44.06 | 261,610.00 | 2x Long VIX Futures ETF |
| LABD | 5.93 | 186,160.00 | Direxion Daily S&P Biotech Bear 3X ETF |
| QID | 13.51 | 157,760.00 | ProShares UltraShort QQQ |
| ERY | 9.01 | 132,465.00 | Direxion Daily Energy Bear 2X ETF |
| YANG | 20.53 | 131,300.00 | Direxion Daily FTSE China Bear 3X ETF |
| NUGT | 21.01 | 86,440.00 | Direxion Daily Gold Miners Index Bull 2X ETF |
| DRIP | 35.57 | 83,000.00 | Direxion Daily S&P Oil & Gas Bear 2X ETF |
| SDOW | 21.62 | 81,725.44 | UltraPro Short Dow30 |
| GDXD | 18.38 | 61,380.00 | MicroSectors Gold Miners -3X Inverse Leveraged ETNs |
| TWM | 20.18 | 53,728.00 | ProShares UltraShort Russell2000 |
| SDS | 52.76 | 51,188.00 | ProShares UltraShort S&P500 |
| JNUG | 21.08 | 41,680.00 | Direxion Daily Junior Gold Miners Bull 2X ETF |
| NVDS | 18.37 | 24,142.50 | Tradr 1.5X Short NVDA Daily ETF |
| GUSH | 3.38 | 20,355.00 | Direxion Daily S&P Oil & Gas Bull 2X ETF |
| SCO | 23.32 | 11,838.00 | ProShares UltraShort Bloomberg Crude Oil |
| DXD | 15.98 | 7,936.80 | ProShares UltraShort Dow30 |
| UCO | 3.01 | 6,225.00 | ProShares Ultra Bloomberg Crude Oil |
| LABU | 37.64 | 4,648.00 | Direxion Daily S&P Biotech Bull 3X ETF |
| MUD | 9.32 | 3,254.00 | Direxion Daily MU Bear 1X ETF |
| GLL | 16.01 | 2,106.40 | ProShares UltraShort Gold |
| _+ 12 more between $2,000 and $2,100_ | | | |

**The artifact is NOT confined to leveraged funds and excluding them does not
fix it.** The worst offenders in the store are ordinary equities:

| ticker | max close | name |
|---|---|---|
| TNXP | **19,200,000,000.00** | Tonix Pharmaceuticals Holding Corp. |
| ORKA | 68,720,400.00 | Oruka Therapeutics, Inc. |
| TENX | 19,200,000.00 | Tenax Therapeutics, Inc. |
| ABEO | 5,312,500.00 | Abeona Therapeutics Inc. |
| ACHV | 1,821,600.00 | Achieve Life Sciences, Inc. |
| BRK.A | 809,350.00 | Berkshire Hathaway Inc. (legitimate) |

A $19.2 **billion** synthetic close on a nano-cap biotech is a bigger data
integrity problem than any leveraged fund in the store, and the leveraged-ETF
exclusion would not touch it. **Filed here as a separate, larger bug.**

---

## 5. The flag (built, default OFF)

`engine/lib/leverage.py` defines `POLICY_ALL = "all"` (default) and
`POLICY_EX_LEVERAGED = "ex-leveraged"`, resolved by
`leverage.resolve_policy(cli_value)` with precedence **CLI flag > env
`TRADING_ENGINE_UNIVERSE_POLICY` > `all`**. An unrecognised value raises rather
than falling back to the permissive policy — a typo must not silently mean
"all".

Wired at four call sites:

| file | change |
|---|---|
| `engine/screen.py` | `--universe-policy`; filters the eligible set BEFORE ranking |
| `farm/backtest/hist_screen.py` | `universe_policy=` + `--universe-policy`; SQL anti-join |
| `farm/backtest/replay.py` | resolves once per replay, passes through, records in result JSON |
| `farm/walkforward/runner.py` | same, once per book |

The exclusion is applied **before** `rs_rank` is computed. It has to be:
`rs_rank` is a cross-sectional percentile, so dropping names afterwards would
leave every survivor holding a rank scored against a universe it is no longer
in.

The classification runs in **Python only**. `hist_screen` gets the flagged set
as a materialised TEMP table (`leverage.register_exclusion`) and anti-joins it,
rather than re-expressing the regexes in SQL, so the two paths cannot drift.

### Self-describing output

* `screen_results` gains `universe_policy VARCHAR DEFAULT 'all'` via
  `db.init_screen_policy_schema()` (`ADD COLUMN IF NOT EXISTS`, following the
  `init_queue_schema` precedent). The default is factually true of the 26 stored
  dates: they were all built with no exclusion.
* The report H1 carries it: `# Screen — 2026-08-19 (universe: 3697 · passing:
  515 · … · policy: ex-leveraged)`, plus a one-line subtitle naming the count
  removed.
* `data/_meta.json` gains `universe_policy` and `excluded_leveraged`.
* Replay and walk-forward result JSONs gain `universe_policy`.
* The append-only abort message now names the STORED policy and the requested
  one, so a same-date rerun under a different policy is visible instead of
  looking like a routine collision.

### Proof (RUN, on scratch copies — the live store was never written)

A scratch DB with the full universe and all `prices` from 2024-06-01:

```
=== A: policy all (default) ===
[screen] universe policy = all
[screen] active&liquid → screened=3887 skipped_stale=0 skipped_short=217
[screen] passing=534

=== B: --universe-policy ex-leveraged ===
[screen] universe policy = ex-leveraged
[screen] policy ex-leveraged: excluded 190 leveraged/inverse ETPs (3887 → 3697)
[screen] active&liquid → screened=3697 skipped_stale=0 skipped_short=217
[screen] passing=515
```

**Run A reproduces the live 2026-08-19 screen exactly — 534 passers, and the
passing SET is identical to the 534 rows stored in `screen_results`.** That is
the equivalence proof that the default path is unchanged.

`hist_screen`'s SQL anti-join, same scratch DB, 2026-08-12 → 2026-08-19:
`policy=all → 206 rows (7 leveraged)`, `policy=ex-leveraged → 204 rows (0
leveraged)`.

Also proven: the env var path, the abort message naming both policies, and
`TRADING_ENGINE_UNIVERSE_POLICY=ex-levraged` being rejected outright.

### The cost, measured exactly

534 → 515 is **-19 passers**, of which 15 are the flagged names and **4 are
collateral**: `CHE` (Chemed), `MTB` (M&T Bank), `OFG` (OFG Bancorp), `QCRH`
(QCR Holdings) drop below RS 70 purely because removing 190 names from the
ranking shifts every percentile. **0 names were gained.**

That is the mechanism by which flipping this changes `ew_benchmark`: not just
the 15 removals, but a re-scaling of the RS percentile for all 3,697 survivors.

---

## 6. Recommendation

**Turn it on — for the historical farm first, as a versioned A/B against the
current benchmark, not as a silent default.** It is not turned on here.

### The case FOR

1. **It is not a tail case.** 15 flagged names in the newest screen, 6-25 in
   every one of the 26 stored screens, 42 distinct tickers, including a **4X**
   ETN (SPYU, 15 passes). Four live books are long a 2x ETF today.
2. **A momentum screen selecting 3x funds is measuring the multiplier, not the
   signal.** RS is `2·r63 + r126 + r189 + r252`; a 3x fund's numerator is ~3x
   the underlying's, so it sorts above its own underlying by construction. The
   screen is not discovering anything when SPXL outranks SPY.
3. **The risk is understated in exactly the direction that matters.** Books
   rebalance monthly; these funds reset daily. The path decay never shows up in
   a monthly-sampled equity curve, so the backtest books the leverage without
   the volatility drag.
4. **The reverse-split artifact concentrates here 10x.** 35 of the 84
   implausible-price tickers, all screen-eligible. Excluding them removes 42% of
   the store's worst price data from the replay path for free.
5. **The inverse names are worse than the levered longs.** Seven inverse funds
   have passed. Every book that acts on the screen buys them LONG.

### The case AGAINST

1. **It changes `ew_benchmark`, which every book's excess is measured against.**
   Every stored result — 65 fold JSONs, four completed sweeps, the whole
   walk-forward report — was produced under `all`. Flipping the default makes
   new numbers incomparable to all of them, and the BUILDLOG's own 2026-08-20
   lesson is that silently incomparable numbers are this codebase's
   characteristic failure.
2. **It is not free.** Measured: 4 legitimate names (CHE, MTB, OFG, QCRH) fell
   out of the 2026-08-19 screen as pure collateral from the percentile shift.
   That is ~0.8% of the passing set lost to a filter aimed at something else.
3. **It does not fix the data-quality bug it is partly justified by.** TNXP's
   $19.2bn close survives the exclusion untouched. If the real problem is
   back-adjusted prices, a price-sanity guard in the fill model is the
   proportionate fix and would cover all 84 tickers, not 35.
4. **A name-string classifier is a heuristic on a vendor field.** It is
   validated today (0/94 missed, 0/33 false positives) and it will rot the first
   time an issuer renames a fund. An exclusion that silently deletes universe
   members deserves a periodic re-audit, and nothing schedules one.
5. **It is arguably the wrong layer.** The screen's job is to rank; deciding
   what is investable is a portfolio-construction concern. A per-book universe
   filter would let `ew_benchmark` stay fixed while a book opts out.

### What I would actually do

1. Keep the default at `all`. Do not touch the live nightly.
2. Run **`ew_benchmark` walk-forward under both policies** and publish the pair.
   That converts "the screen picks 3x funds" from an argument into a number, and
   it is the only version of this decision that is comparable to the existing
   board.
3. **Fix the price-sanity bug separately and first** — it is bigger (84
   tickers, $19.2bn worst case), it is independent of the strategy question, and
   it is the one that produced `DRIP buy 0.7027 shares @ $47,988.54`.
4. **Retain fold `sim_fills` for at least one replay per book**, or add a
   per-ticker fill summary to the result JSON. This audit could not answer
   "which historical book held which leveraged fund" from 65 stored results, and
   that should not be true.

---

## Appendix — every LIQUID flagged name (265)

These are the only flagged names that can ever reach a screen:
`classify_universe` filters on `active AND liquid`. The other 547 flagged rows
are illiquid and unreachable. Regenerate the full 812 with:

```python
import sys, duckdb; sys.path.insert(0, "engine")
from lib import leverage
con = duckdb.connect("store/market.duckdb", read_only=True)
for row in leverage.flagged_rows(con):
    print(row)
```

| # | Ticker | Rule | Ever passed | Name |
|---|---|---|---|---|
| 1 | AAOG | leveraged_word | · | Leverage Shares 2X Long AAOI Daily ETF |
| 2 | AAOX | multiplier | · | Tradr 2X Long AAOI Daily ETF |
| 3 | AAPD | direxion_bull_bear | · | Direxion Daily AAPL Bear 1X ETF |
| 4 | AAPU | direxion_bull_bear | · | Direxion Daily AAPL Bull 2X ETF |
| 5 | ADBG | leveraged_word | · | Leverage Shares 2X Long ADBE Daily ETF |
| 6 | AGQ | proshares_ultra | · | ProShares Ultra Silver |
| 7 | AMA | multiplier | · | Defiance Daily Target 2X Long AMAT ETF |
| 8 | AMDD | direxion_bull_bear | · | Direxion Daily AMD Bear 1X ETF |
| 9 | AMDG | leveraged_word | **YES** | Leverage Shares 2X Long AMD Daily ETF |
| 10 | AMDL | multiplier | **YES** | GraniteShares 2x Long AMD Daily ETF |
| 11 | AMUU | direxion_bull_bear | **YES** | Direxion Daily AMD Bull 2X ETF |
| 12 | AMZD | direxion_bull_bear | · | Direxion Daily AMZN Bear 1X ETF |
| 13 | AMZU | direxion_bull_bear | · | Direxion Daily AMZN Bull 2X ETF |
| 14 | AMZZ | multiplier | · | GraniteShares 2x Long AMZN Daily ETF |
| 15 | APLX | multiplier | · | Tradr 2X Long APLD Daily ETF |
| 16 | APLZ | multiplier | · | Tradr 2X Short APLD Daily ETF |
| 17 | APPX | multiplier | · | Tradr 2X Long APP Daily ETF |
| 18 | ARMG | leveraged_word | · | Leverage Shares 2X Long ARM Daily ETF |
| 19 | ASMG | leveraged_word | **YES** | Leverage Shares 2X Long ASML Daily ETF |
| 20 | ASTN | multiplier | · | Defiance Daily Target 2X Short ASTS ETF |
| 21 | ASTX | multiplier | · | Tradr 2X Long ASTS Daily ETF |
| 22 | AVGG | leveraged_word | · | Leverage Shares 2X Long AVGO Daily ETF |
| 23 | AVGX | multiplier | · | Defiance Daily Target 2X Long AVGO ETF |
| 24 | AVL | direxion_bull_bear | · | Direxion Daily AVGO Bull 2X ETF |
| 25 | AVS | direxion_bull_bear | · | Direxion Daily AVGO Bear 1X ETF |
| 26 | AXTX | multiplier | · | Tradr 2X Long AXTI Daily ETF |
| 27 | BABX | multiplier | · | GraniteShares 2x Long BABA Daily ETF |
| 28 | BEG | leveraged_word | · | Leverage Shares 2x Long BE Daily ETF |
| 29 | BEX | multiplier | · | Tradr 2X Long BE Daily ETF |
| 30 | BEZ | multiplier | · | Tradr 2X Short BE Daily ETF |
| 31 | BITI | proshares_short | **YES** | ProShares Short Bitcoin ETF |
| 32 | BITU | proshares_ultra | · | ProShares Ultra Bitcoin ETF |
| 33 | BITX | multiplier_etp | · | 2x Bitcoin ETF |
| 34 | BMNG | leveraged_word | · | Leverage Shares 2X Long BMNR Daily ETF |
| 35 | BMNU | multiplier | · | T-REX 2X Long BMNR Daily Target ETF |
| 36 | BMNZ | multiplier | · | Defiance Daily Target 2X Short BMNR ETF |
| 37 | BOIL | proshares_ultra | · | ProShares Ultra Bloomberg Natural Gas |
| 38 | BTCZ | inverse | **YES** | T-Rex 2X Inverse Bitcoin Daily Target ETF |
| 39 | BULZ | leveraged_word | · | MicroSectors FANG & Innovation 3x Leveraged ETN |
| 40 | CBRG | leveraged_word | · | Leverage Shares 2X Long CBRS Daily ETF |
| 41 | CLSX | multiplier | · | Tradr 2X Long CLSK Daily ETF |
| 42 | COHX | multiplier | · | Tradr 2X Long COHR Daily ETF |
| 43 | CONI | multiplier | · | GraniteShares 2x Short COIN Daily ETF |
| 44 | CONL | multiplier | · | GraniteShares 2x Long COIN Daily ETF |
| 45 | CORD | inverse | · | T-REX 2X Inverse CRWV Daily Target ETF |
| 46 | CRCA | proshares_ultra | · | ProShares Ultra CRCL |
| 47 | CRCD | inverse | · | T-REX 2X Inverse CRCL Daily Target ETF |
| 48 | CRCG | leveraged_word | · | Leverage Shares 2X Long CRCL Daily ETF |
| 49 | CRDU | multiplier | · | Tradr 2X Long CRDO Daily ETF |
| 50 | CRMG | leveraged_word | · | Leverage Shares 2X Long CRM Daily ETF |
| 51 | CRWG | leveraged_word | · | Leverage Shares 2X Long CRWV Daily ETF |
| 52 | CRWL | multiplier | **YES** | GraniteShares 2x Long CRWD Daily ETF |
| 53 | CRWU | multiplier | · | T-REX 2X Long CRWV Daily Target ETF |
| 54 | CURE | direxion_bull_bear | **YES** | Direxion Daily Healthcare Bull 3X ETF |
| 55 | CWEB | direxion_bull_bear | · | Direxion Daily CSI China Internet Index Bull 2X ETF |
| 56 | CWVX | multiplier | · | Tradr 2X Long CRWV Daily ETF |
| 57 | DDM | proshares_ultra | **YES** | ProShares Ultra Dow30 |
| 58 | DFEN | direxion_bull_bear | **YES** | Direxion Daily Aerospace & Defense Bull 3X ETF |
| 59 | DLLL | multiplier | **YES** | GraniteShares 2x Long DELL Daily ETF |
| 60 | DOG | proshares_short | · | ProShares Short Dow30 |
| 61 | DPST | direxion_bull_bear | **YES** | Direxion Daily Regional Banks Bull 3X ETF |
| 62 | DRAL | multiplier | · | Defiance Daily Target 2X Long DRAM ETF |
| 63 | DRIP | direxion_bull_bear | · | Direxion Daily S&P Oil & Gas Exp. & Prod. Bear 2X ETF |
| 64 | DRN | direxion_bull_bear | **YES** | Direxion Daily Real Estate Bull 3X ETF |
| 65 | DUST | direxion_bull_bear | · | Direxion Daily Gold Miners Index Bear 2X ETF |
| 66 | DXD | proshares_ultra | · | ProShares UltraShort Dow30 |
| 67 | EDC | direxion_bull_bear | **YES** | Direxion Emerging Markets Bull 3X ETF |
| 68 | ERX | direxion_bull_bear | **YES** | Direxion Energy Bull 2X ETF |
| 69 | ERY | direxion_bull_bear | · | Direxion Daily Energy Bear 2X ETF |
| 70 | ETHD | proshares_ultra | · | ProShares UltraShort Ether ETF |
| 71 | ETHT | proshares_ultra | · | ProShares Ultra Ether ETF |
| 72 | ETHU | multiplier_etp | · | 2x Ether ETF |
| 73 | FAS | direxion_bull_bear | · | Direxion Financial Bull 3X ETF |
| 74 | FAZ | direxion_bull_bear | · | Direxion Financial Bear 3X ETF |
| 75 | FBL | multiplier | · | GraniteShares 2x Long META Daily ETF |
| 76 | FNGD | inverse | · | MicroSectors FANG  Index -3X Inverse Leveraged ETNs due January 8, 2038 |
| 77 | FNGU | leveraged_word | · | MicroSectors FANG+ 3X Leveraged ETNs |
| 78 | GDXD | inverse | · | MicroSectors Gold Miners -3X Inverse Leveraged ETNs |
| 79 | GDXU | leveraged_word | · | MicroSectors Gold Miners 3X Leveraged ETN |
| 80 | GEVX | multiplier | **YES** | Tradr 2X Long GEV Daily ETF |
| 81 | GGLL | direxion_bull_bear | **YES** | Direxion Daily GOOGL Bull 2X ETF |
| 82 | GGLS | direxion_bull_bear | · | Direxion Daily GOOGL Bear 1X ETF |
| 83 | GLL | proshares_ultra | · | ProShares UltraShort Gold |
| 84 | GLWG | leveraged_word | · | Leverage Shares 2X Long GLW Daily ETF |
| 85 | GOOX | multiplier | **YES** | T-Rex 2X Long Alphabet Daily Target ETF |
| 86 | GUSH | direxion_bull_bear | **YES** | Direxion Daily S&P Oil & Gas Exp. & Prod. Bull 2X ETF |
| 87 | HIBL | direxion_bull_bear | **YES** | Direxion Daily S&P 500 High Beta Bull 3X ETF |
| 88 | HIMZ | multiplier | · | Defiance Daily Target 2X Long HIMS ETF |
| 89 | HOOG | leveraged_word | · | Leverage Shares 2X Long HOOD Daily ETF |
| 90 | HYNX | multiplier | · | T-REX 2X Long SKHY Daily Target ETF |
| 91 | IBX | multiplier | · | Tradr 2X Long IBM Daily ETF |
| 92 | INTW | multiplier | · | GraniteShares 2x Long INTC Daily ETF |
| 93 | IONL | multiplier | · | GraniteShares 2x Long IONQ Daily ETF |
| 94 | IONX | multiplier | · | Defiance Daily Target 2X Long IONQ ETF |
| 95 | IONZ | multiplier | · | Defiance Daily Target 2x Short IONQ ETF |
| 96 | IRE | multiplier | · | Defiance Daily Target 2X Long IREN ETF |
| 97 | IREG | leveraged_word | · | Leverage Shares 2X Long IREN Daily ETF |
| 98 | IREX | multiplier | · | Tradr 2X Long IREN Daily ETF |
| 99 | IREZ | multiplier | · | Tradr 2X Short IREN Daily ETF |
| 100 | JDST | direxion_bull_bear | · | Direxion Daily Junior Gold Miners Index Bear 2X ETF |
| 101 | JNUG | direxion_bull_bear | · | Direxion Daily Junior Gold Miners Index Bull 2X ETF |
| 102 | KOLD | proshares_ultra | · | ProShares UltraShort Bloomberg Natural Gas |
| 103 | KORU | direxion_bull_bear | · | Direxion Daily South Korea Bull 3X ETF |
| 104 | LABD | direxion_bull_bear | · | Direxion Daily S&P Biotech Bear 3X ETF |
| 105 | LABU | direxion_bull_bear | **YES** | Direxion Daily S&P Biotech Bull 3X ETF |
| 106 | LABX | multiplier | · | Tradr 2X Long ALAB Daily ETF |
| 107 | LINT | direxion_bull_bear | · | Direxion Daily INTC Bull 2X ETF |
| 108 | LITX | multiplier | · | Tradr 2X Long LITE Daily ETF |
| 109 | LITZ | multiplier | · | Tradr 2X Short LITE Daily ETF |
| 110 | LLYX | multiplier | **YES** | Defiance Daily Target 2X Long LLY ETF |
| 111 | LNOK | multiplier | · | Defiance Daily Target 2X Long NOK ETF |
| 112 | LOFF | direxion_bull_bear | · | Direxion Daily SpaceX Bull 2X ETF |
| 113 | LRCU | multiplier | · | Tradr 2X Long LRCX Daily ETF |
| 114 | LUNL | multiplier | · | Defiance Daily Target 2X Long LUNR ETF |
| 115 | METU | direxion_bull_bear | · | Direxion Daily META Bull 2X ETF |
| 116 | MQQQ | multiplier | **YES** | Tradr 2X Long Innovation 100 Monthly ETF |
| 117 | MRAL | multiplier | · | GraniteShares 2x Long MARA Daily ETF |
| 118 | MRVU | direxion_bull_bear | · | Direxion Daily MRVL Bull 2X ETF |
| 119 | MSFD | direxion_bull_bear | **YES** | Direxion Daily MSFT Bear 1X ETF |
| 120 | MSFL | multiplier | · | GraniteShares 2x Long MSFT Daily ETF |
| 121 | MSFU | direxion_bull_bear | · | Direxion Daily MSFT Bull 2X ETF |
| 122 | MSTX | multiplier | · | Defiance Daily Target 2x Long MSTR ETF |
| 123 | MSTZ | inverse | · | T-Rex 2X Inverse MSTR Daily Target ETF |
| 124 | MUD | direxion_bull_bear | · | Direxion Daily MU Bear 1X ETF |
| 125 | MULL | multiplier | · | GraniteShares 2x Long MU Daily ETF |
| 126 | MUU | direxion_bull_bear | · | Direxion Daily MU Bull 2X ETF |
| 127 | MUZ | multiplier | · | Defiance Daily Target 2X Short MU ETF |
| 128 | MVLL | multiplier | · | GraniteShares 2x Long MRVL Daily ETF |
| 129 | NAIL | direxion_bull_bear | · | Direxion Daily Homebuilders & Supplies Bull 3X ETF |
| 130 | NBIG | leveraged_word | · | Leverage Shares 2X Long NBIS Daily ETF |
| 131 | NBIL | multiplier | · | GraniteShares 2x Long NBIS Daily ETF |
| 132 | NBIZ | multiplier | · | Tradr 2X Short NBIS Daily ETF |
| 133 | NEBX | multiplier | · | Tradr 2X Long NBIS Daily ETF |
| 134 | NFXL | direxion_bull_bear | · | Direxion Daily NFLX Bull 2X ETF |
| 135 | NOWL | multiplier | · | GraniteShares 2x Long NOW Daily ETF |
| 136 | NUGT | direxion_bull_bear | · | Direxion Daily Gold Miners Index Bull 2X ETF |
| 137 | NVD | multiplier | · | GraniteShares 2x Short NVDA Daily ETF |
| 138 | NVDG | leveraged_word | · | Leverage Shares 2X Long NVDA Daily ETF |
| 139 | NVDL | multiplier | · | GraniteShares 2x Long NVDA Daily ETF |
| 140 | NVDQ | inverse | · | T-Rex 2X Inverse NVIDIA Daily Target ETF |
| 141 | NVDS | multiplier | · | Tradr 1.5X Short NVDA Daily ETF |
| 142 | NVDU | direxion_bull_bear | · | Direxion Daily NVDA Bull 2X ETF |
| 143 | NVDX | multiplier | · | T-Rex 2X Long NVIDIA Daily Target ETF |
| 144 | NVOX | multiplier | · | Defiance Daily Target 2X Long NVO ETF |
| 145 | NVTX | multiplier | · | Tradr 2X Long NVTS Daily ETF |
| 146 | OILU | leveraged_word | · | MicroSectors Oil & Gas Exp. & Prod. 3x Leveraged ETN |
| 147 | OKLL | multiplier | · | Defiance Daily Target 2x Long OKLO ETF |
| 148 | OKLS | multiplier | · | Defiance Daily Target 2X Short OKLO ETF |
| 149 | ONDL | multiplier | · | Defiance Daily Target 2X Long ONDS ETF |
| 150 | ORCU | direxion_bull_bear | · | Direxion Daily ORCL Bull 2X ETF |
| 151 | ORCX | multiplier | · | Defiance Daily Target 2X Long ORCL ETF |
| 152 | PLTD | direxion_bull_bear | · | Direxion Daily PLTR Bear 1X ETF |
| 153 | PLTU | direxion_bull_bear | · | Direxion Daily PLTR Bull 2X ETF |
| 154 | PLTZ | multiplier | · | Defiance Daily Target 2x Short PLTR ETF |
| 155 | PLU | multiplier | · | Defiance Daily Target 2x Long PL ETF |
| 156 | POEL | multiplier | · | Defiance Daily Target 2X Long POET ETF |
| 157 | PSQ | proshares_short | · | ProShares Short QQQ |
| 158 | PTIR | multiplier | · | GraniteShares 2x Long PLTR Daily ETF |
| 159 | QBTX | multiplier | · | Tradr 2X Long QBTS Daily ETF |
| 160 | QBTZ | multiplier | · | Defiance Daily Target 2x Short QBTS ETF |
| 161 | QCML | multiplier | · | GraniteShares 2x Long QCOM Daily ETF |
| 162 | QCMU | direxion_bull_bear | · | Direxion Daily QCOM Bull 2X ETF |
| 163 | QID | proshares_ultra | · | ProShares UltraShort QQQ |
| 164 | QLD | proshares_ultra | **YES** | ProShares Ultra QQQ |
| 165 | QPUX | multiplier | · | Defiance 2X Daily Long Pure Quantum ETF |
| 166 | RAM | multiplier | · | Roundhill T-REX 2X Long DRAM Daily Target ETF |
| 167 | RDTL | multiplier | · | GraniteShares 2x Long RDDT Daily ETF |
| 168 | RDWU | multiplier | · | T-REX 2X Long RDW Daily Target ETF |
| 169 | RETL | direxion_bull_bear | · | Direxion Daily Retail Bull 3X ETF |
| 170 | RGTX | multiplier | · | Defiance Daily Target 2X Long RGTI ETF |
| 171 | RGTZ | multiplier | · | Defiance Daily Target 2x Short RGTI ETF |
| 172 | RIOX | multiplier | · | Defiance Daily Target 2X Long RIOT ETF |
| 173 | RKLX | multiplier | · | Defiance Daily Target 2X Long RKLB ETF |
| 174 | RKLZ | multiplier | · | Defiance Daily Target 2x Short RKLB ETF |
| 175 | ROBN | multiplier | · | T-Rex 2X Long HOOD Daily Target ETF |
| 176 | ROM | proshares_ultra | **YES** | ProShares Ultra Technology |
| 177 | RWM | proshares_short | · | ProShares Short Russell2000 |
| 178 | SARK | multiplier | · | Tradr 1X Short Innovation Daily ETF |
| 179 | SBIT | proshares_ultra | **YES** | ProShares UltraShort Bitcoin ETF |
| 180 | SCO | proshares_ultra | · | ProShares UltraShort Bloomberg Crude Oil |
| 181 | SDOW | ultrapro | · | UltraPro Short Dow30 |
| 182 | SDS | proshares_ultra | · | ProShares UltraShort S&P500 |
| 183 | SH | proshares_short | · | ProShares Short S&P500 |
| 184 | SHNY | leveraged_word | · | MicroSectors Gold 3X Leveraged ETNs due January 29, 2043 |
| 185 | SK | multiplier | · | Corgi SK hynix 2x Daily ETF |
| 186 | SKDD | multiplier | · | GraniteShares 2x Short SK Hynix Daily ETF |
| 187 | SKHL | direxion_bull_bear | · | Direxion Daily SK Hynix Bull 2X ETF |
| 188 | SKHU | proshares_ultra | · | ProShares Ultra SK hynix |
| 189 | SKHX | leveraged_word | · | Leverage Shares 2X Long SK Hynix Daily ETF |
| 190 | SKHZ | leveraged_word | · | Leverage Shares 1X Short SK Hynix Daily ETF |
| 191 | SKUU | multiplier | · | GraniteShares 2x Long SK Hynix Daily ETF |
| 192 | SMCL | multiplier | · | GraniteShares 2x Long SMCI Daily ETF |
| 193 | SMCX | multiplier | · | Defiance Daily Target 2X Long SMCI ETF |
| 194 | SMCZ | multiplier | · | Defiance Daily Target 2X Short SMCI ETF |
| 195 | SMST | multiplier | · | Defiance Daily Target 2x Short MSTR ETF |
| 196 | SMU | multiplier | · | Tradr 2X Long SMR Daily ETF |
| 197 | SNDG | leveraged_word | · | Leverage Shares 2X Long SNDK Daily ETF |
| 198 | SNDQ | multiplier | · | Tradr 2X Short SNDK Daily ETF |
| 199 | SNDU | multiplier | · | T-REX 2X Long SNDK Daily Target ETF |
| 200 | SNK | multiplier | · | GraniteShares 2x Short SpaceX Daily ETF |
| 201 | SNXX | multiplier | · | Tradr 2X Long SNDK Daily ETF |
| 202 | SOFX | multiplier | · | Defiance Daily Target 2X Long SOFI ETF |
| 203 | SOLT | multiplier_etp | · | 2x Solana ETF |
| 204 | SOXL | direxion_bull_bear | · | Direxion Daily Semiconductor Bull 3X ETF |
| 205 | SOXS | direxion_bull_bear | · | Direxion Daily Semiconductor Bear 3X ETF |
| 206 | SPAL | multiplier | · | GraniteShares 2x Long SpaceX Daily ETF |
| 207 | SPAX | multiplier | · | T-REX 2X Long SPCX Daily Target ETF |
| 208 | SPCF | proshares_ultra | · | ProShares Ultra SpaceX |
| 209 | SPCG | multiplier | · | Tradr 2X Short SpaceX Daily ETF |
| 210 | SPCH | leveraged_word | · | Leverage Shares 2X Long SPCX Daily ETF |
| 211 | SPCM | multiplier | · | Tradr 2X Long SpaceX Daily ETF |
| 212 | SPCQ | multiplier | · | Defiance Daily Target 2X Short SPCX ETF |
| 213 | SPCU | multiplier | · | Defiance Daily Target 2X Long SPCX ETF |
| 214 | SPDN | direxion_bull_bear | · | Direxion Daily S&P 500 Bear 1X ETF |
| 215 | SPXL | direxion_bull_bear | **YES** | Direxion Daily S&P 500 Bull 3X ETF |
| 216 | SPXS | direxion_bull_bear | · | Direxion Daily S&P 500 Bear 3X ETF |
| 217 | SPXU | ultrapro | · | ProShares UltraPro Short S&P500 |
| 218 | SPYU | leveraged_word | **YES** | MAX S&P 500 4X Leveraged ETNs due October 30, 2043 |
| 219 | SQQQ | ultrapro | · | ProShares UltraPro Short QQQ |
| 220 | SRTY | ultrapro | · | ProShares UltraPro Short Russell2000 |
| 221 | SSG | proshares_ultra | · | ProShares UltraShort Semiconductors |
| 222 | SSO | proshares_ultra | **YES** | ProShares Ultra S&P500 |
| 223 | SSPC | leveraged_word | · | Leverage Shares 2X Short SPCX Daily ETF |
| 224 | STXL | multiplier | · | Defiance Daily Target 2x Long STX ETF |
| 225 | SVIX | multiplier | **YES** | -1x Short VIX Futures ETF |
| 226 | SVXY | proshares_short | **YES** | ProShares Short VIX Short Term Futures ETF |
| 227 | TBT | proshares_ultra | · | ProShares UltraShort Lehman 20  Year Treasury |
| 228 | TECL | direxion_bull_bear | **YES** | Direxion Daily Technology Bull 3X ETF |
| 229 | TECS | direxion_bull_bear | · | Direxion Technology Bear 3X ETF |
| 230 | TEMT | multiplier | · | Tradr 2X Long TEM Daily ETF |
| 231 | TMF | direxion_bull_bear | · | Direxion Daily 20-Yr Treasury Bull 3x Shrs |
| 232 | TMV | direxion_bull_bear | · | Direxion Daily 20-Year Treasury Bear 3X |
| 233 | TNA | direxion_bull_bear | **YES** | Direxion Small Cap Bull 3X ETF |
| 234 | TQQQ | ultrapro | **YES** | ProShares UltraPro QQQ |
| 235 | TSDD | multiplier | · | GraniteShares 2x Short TSLA Daily ETF |
| 236 | TSL | multiplier | · | GraniteShares 1.25x Long TSLA Daily ETF |
| 237 | TSLG | leveraged_word | · | Leverage Shares 2X Long TSLA Daily ETF |
| 238 | TSLL | direxion_bull_bear | · | Direxion Daily TSLA Bull 2X ETF |
| 239 | TSLQ | multiplier | · | Tradr 2X Short TSLA Daily ETF |
| 240 | TSLR | multiplier | · | GraniteShares 2x Long TSLA Daily ETF |
| 241 | TSLS | direxion_bull_bear | · | Direxion Daily TSLA Bear 1X ETF |
| 242 | TSLT | multiplier | · | T-REX 2X Long Tesla Daily Target ETF |
| 243 | TSLZ | inverse | · | T-Rex 2X Inverse Tesla Daily Target ETF |
| 244 | TSMU | multiplier | · | GraniteShares 2x Long TSM Daily ETF |
| 245 | TSMX | direxion_bull_bear | · | Direxion Daily TSM Bull 2X ETF |
| 246 | TWM | proshares_ultra | · | ProShares UltraShort Russell2000 |
| 247 | TZA | direxion_bull_bear | · | Direxion Small Cap Bear 3X ETF |
| 248 | UCO | proshares_ultra | **YES** | ProShares Ultra Bloomberg Crude Oil |
| 249 | UDOW | ultrapro | **YES** | ProShares UltraPro Dow30 |
| 250 | UGL | proshares_ultra | · | ProShares Ultra Gold |
| 251 | UNHG | leveraged_word | · | Leverage Shares 2X Long UNH Daily ETF |
| 252 | UPRO | ultrapro | **YES** | ProShares UltraPro S&P 500 |
| 253 | URTY | ultrapro | **YES** | ProShares UltraPro Russell2000 |
| 254 | USD | proshares_ultra | **YES** | ProShares Ultra Semiconductors |
| 255 | UVIX | multiplier | · | 2x Long VIX Futures ETF |
| 256 | UVXY | proshares_ultra | · | ProShares Ultra VIX Short Term Futures ETF |
| 257 | UWM | proshares_ultra | **YES** | ProShares Ultra Russell2000 |
| 258 | VRTL | multiplier | · | GraniteShares 2x Long VRT Daily ETF |
| 259 | WDCX | multiplier | · | Tradr 2X Long WDC Daily ETF |
| 260 | WEBL | direxion_bull_bear | · | Direxion Daily Dow Jones Internet Bull 3X ETF |
| 261 | WULX | multiplier | · | Tradr 2X Long WULF Daily ETF |
| 262 | XXRP | multiplier | · | Teucrium 2x Long Daily XRP ETF |
| 263 | YANG | direxion_bull_bear | **YES** | Direxion Daily FTSE China Bear 3X ETF |
| 264 | YINN | direxion_bull_bear | · | Direxion Daily FTSE China Bull 3X ETF |
| 265 | ZSL | proshares_ultra | · | ProShares UltraShort Silver |
