# The evidence ceiling — why the fold count cannot be increased

> **Historical snapshot.** This captures the 2026-08-20 evidence assessment. The current
> registered protocol uses 10 folds; see [`how-it-works.md`](how-it-works.md).

_Main-loop analysis, 2026-08-20. Every number below was measured against the live store
read-only, except the market-wide listing counts, which are World Bank WDI
`CM.MKT.LDOM.NO` and are labelled as external._

## The question this answers

The 2026-08-20 confidence pass put **26 of 30** swept candidates at `INDISTINGUISHABLE`
from `ew_benchmark` — their 90% bootstrap CI on median excess contains 0. Zero candidates
are distinguishably better; the four that are distinguishable are distinguishably *worse*.
The top-ranked `banding` cell has a CI of **[-11.83%, +27.06%]**, a 39pp span.

The obvious response is *run more folds*. `protocol.N_FOLDS` is 10, reaching back to
2014-08, and the BUILDLOG records that number as a cost trade ("10 folds costs 15% of the
universe, 2,827 -> 2,391 tickers"). If it is only a cost trade, buy more of it: the box is
idle and folds are free.

**It is not a cost trade. Going further back does not add evidence — it adds fiction.**

## Measured: how much of the past this store can see

Distinct tickers with a price bar in the first week of June, by year (read-only query
against `prices`):

| year | tickers in store | US listed domestic companies (World Bank) | coverage |
|---|---|---|---|
| 1996 | 937 | **8,090** (all-time high) | **~12%** |
| 2003 | 1,362 | 5,295 | ~26% |
| 2014 | 2,360 | ~4,300 | ~55% |

**CORRECTED (adversarial audit, same day).** The rows above compare a store count that
INCLUDES ETFs against a World Bank series that counts operating companies only. Recomputed
ex-ETF via `universe.etf`:

| year | in store, ex-ETF | ETFs excluded | coverage |
|---|---|---|---|
| 1996 | **919** | 18 | **11.4%** |
| 2003 | 1,261 | 101 | **23.8%** |
| 2014 | 1,825 | 535 | **42%** — not the ~55% first claimed |

The 1996 headline survives essentially unchanged, because there were almost no ETFs then.
The middle rows were inflated and are corrected here. ADRs and multiple share classes still
in the store would push every figure lower, so these remain upper bounds on coverage — the
argument gets stronger, not weaker.
| 2025 | 3,858 | ~4,300 | — (see caveat) |

**Caveat on the last row, stated because it cuts against the argument:** the store's counts
include ETFs (5,549 of today's universe) while the World Bank counts operating companies
only. In 1996 there were almost no ETFs, so that row is close to a clean comparison; by 2025
the two series are measuring different things and the ratio is not meaningful. **The 1996
row is the load-bearing one and it is the cleanest.**

## Why this is fatal rather than merely inconvenient

`prices` holds only tickers listed TODAY. So the 937 names visible in 1996 are not a random
12% sample of the 8,090 that existed — **they are precisely the 12% that survived thirty
years.** Every company that was acquired, went bankrupt, or was delisted between then and
now is absent, and absence is not neutral: those are disproportionately the losers.

Direct confirmation, by looking for names whose fate is not in dispute:

```
ABSENT ENTIRELY from prices:
  LEH (Lehman)      BSC (Bear Stearns)   ENE (Enron)        WCOM (WorldCom)
  CFC (Countrywide) MER (Merrill Lynch)  NT (Nortel)        CPQ (Compaq)
  SIVB (SVB)        FRC (First Republic) TWX (Time Warner)  YHOO (Yahoo)
  MON (Monsanto)    CELG (Celgene)       ATVI (Activision)  LNKD (LinkedIn)
```

Not one of the 2008 casualties is in the store. Neither are the 2023 bank failures. A
backtest over any window containing 2008 is a backtest in which Lehman, Bear Stearns,
Countrywide and Merrill Lynch **cannot be bought, cannot be held, and cannot lose money.**

## The conclusion

The survivorship bias is **not the constant ~+7pp/yr** every report currently discloses.
It grows monotonically as the window moves back, and by the late 1990s it dominates the
result entirely. Therefore:

1. **`N_FOLDS = 10` is not a compute budget. It is the honest maximum.** It sits where
   coverage is ~55% and rising. Folds 11 through 30 would reach into 12-26% coverage — the
   region where the answer is guaranteed to look good because only the winners are present.
   **Do not raise the fold count to buy statistical power.** It buys the appearance of power.
2. **The evidence ceiling is structural, not computational.** No amount of the box's 32
   idle cores can resolve a +0.5% edge from 10 overlapping folds of survivor-only data.
   That is why 30 parameter trials produced zero distinguishable improvements, and it is
   why the 31st would not either.
3. **The one lever that compounds is `universe_snapshot`**, which began 2026-07-16 (26
   snapshot dates, 320,233 rows as of today) and is append-only. It is a genuine
   point-in-time universe accruing for free, and nothing can back-fill it: the 2026-08-20
   data-source audit confirmed Nasdaq publishes no dated historical symbol-directory
   archive and SEC EDGAR's `company_tickers.json` is itself current-issuer-only (verified
   by the absence of SIVB and FRC from it).
4. **The live forward record is the only unbiased evidence in the building**, and it is 22
   sessions old with every book at |t| < 2. It cannot be hurried.

## What this changes about what to build

- **Stop expanding parameter search.** It is proven low-yield: 30 trials, 26 indistinguishable,
  0 better. Keep the Saturday sweep cron — it costs CPU and zero tokens and it rules things
  OUT, which is worth having — but do not add grids expecting a winner to fall out.
- **Spend on data quality instead of search.** A second source that catches a silently wrong
  price, and removing instruments that corrupt the screen, both raise the quality of the
  evidence we already have. Search does not.
- **Judge new strategies on the forward record**, not on a walk-forward that cannot resolve
  them. That means new books need a pre-registered horizon measured in months, and interim
  numbers get no action — the discipline the retired agentic layer already proved is needed.
- **Report the bias as time-varying.** The flat "~+7pp/yr" disclosure understates the early
  folds badly. Every fold should carry its universe size so a reader can see fold 1 rests on
  a thinner, more survivor-selected cross-section than fold 10.

## Sources
- World Bank WDI, *Listed domestic companies, total* (`CM.MKT.LDOM.NO`):
  <https://data.worldbank.org/indicator/CM.MKT.LDOM.NO?locations=US>
- Harvard Law School Forum on Corporate Governance, *Looking Behind the Declining Number of
  Public Companies* (2017-05-18):
  <https://corpgov.law.harvard.edu/2017/05/18/looking-behind-the-declining-number-of-public-companies/>
