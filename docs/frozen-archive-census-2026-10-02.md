# Frozen Kaggle price-archive census — 2026-10-02

## Verdict

**Do not ingest.** The archive covers only **1 of 247 (0.405%)** sampled Tiingo ended
listing intervals with both first and last dates within ±5 NYSE sessions. The frozen rule requires
at least 30%. It is overwhelmingly a snapshot of names still present near its 2017 cutoff, not an
archive of names that disappeared before then. No `frozen_daily_bars` table or database was
created; rows loaded are zero.

The exact per-security census is retained outside Git beside the raw artifact as
`store/pit/frozen-archive/<sha256>.census.json`. It contains every ticker/category, first and last
date, row count, ended classification, identity-risk flags, the complete reference sample, and the
ten split checks.

## Source and licence

| Item | Recorded value |
|---|---|
| Dataset page | [Kaggle: Huge Stock Market Dataset](https://www.kaggle.com/datasets/borismarjanovic/price-volume-data-for-all-us-stocks-etfs) |
| Stable download URL | `https://www.kaggle.com/api/v1/datasets/download/borismarjanovic/price-volume-data-for-all-us-stocks-etfs` |
| Downloaded size | 515,591,518 bytes |
| SHA-256 | `d9317c8fb2d63b9b00db5f933b6c9639d2bf7ea3b918169bb5cec5903dce85a1` |
| Kaggle licence field | `CC0: Public Domain` |
| Page licence text | “This dataset belongs to me. I’m sharing it here for free. You may do with it as you wish.” |
| Page update | 2017-11-16; data stated as last updated 2017-11-10 |

The CC0 field permits this use, but the uploader's ownership statement is not independent proof of
the upstream market-data rights. The raw ZIP and derived census stay host-only.

The archive was downloaded once, resumably, during the permitted 2026-10-02 window. ZIP structure
and every canonical member were read successfully. It contains two trees with matching CRC and
uncompressed size for all 8,539 files; the census reads only the canonical `Data/` tree.

## Universe and shape

The page claims “all US-based stocks and ETFs trading on the NYSE, NASDAQ, and NYSE MKT.” That is a
stated universe, not an independently verified membership history.

| Measure | Result |
|---|---:|
| Canonical files | 8,539 |
| Stock files | 7,195 (7,163 non-empty) |
| ETF files | 1,344 (all non-empty) |
| Empty stock files | 32 |
| Parsed rows | 17,453,243 |
| Earliest / latest date | 1962-01-02 / 2017-11-10 |
| Rows with one or more nonpositive OHLC fields | 54 |
| Rows whose high/low envelope is inconsistent | 109 |

The 32 empty tickers remain in the per-ticker census with null endpoints. Quality counts can
overlap and are another reason no raw row should be admitted without validation.

## Ended names

An **ended name** has more than 30 scheduled NYSE sessions strictly after its final archive date
and on or before the archive end. Only **10 of 8,507 non-empty tickers (0.118%)** qualify; among
stock files the share is 10 of 7,163 (0.140%). By contrast, 8,025 tickers (94.33%) end exactly on
2017-11-10.

| Ticker | First date | Last date | Sessions to archive end |
|---|---:|---:|---:|
| DGLT | 2014-07-09 | 2017-08-16 | 61 |
| DTUL | 2017-03-15 | 2017-09-12 | 43 |
| GPACU | 2016-11-03 | 2017-09-13 | 42 |
| IVENC | 2016-12-02 | 2017-09-27 | 32 |
| IVFGC | 2016-12-02 | 2017-09-27 | 32 |
| IVFVC | 2016-12-02 | 2017-09-27 | 32 |
| LVNTB | 2017-04-24 | 2017-08-25 | 54 |
| MTB_C | 2016-11-08 | 2017-09-06 | 47 |
| TCBIW | 2016-12-06 | 2017-09-27 | 32 |
| WINS | 2015-10-29 | 2017-06-07 | 110 |

This distribution answers the core question: the artifact does not retain a meaningful set of
pre-2017 delistings.

## Ended-security reference sample

The read-only reference was the latest Tiingo source batch in `free_security_master`. For each end
year from 2006 through 2024, the census took 15 intervals, or every interval where fewer than 15
existed. SEC-corroborated rows came first, followed by a deterministic SHA-256 rank over the
interval identity. A Form 25 corroboration maps notice CIK to an observed historical ticker and
requires its filing date to be within 60 calendar days of the Tiingo interval end.

Tiingo has no 2005-ended interval, only 1 in 2006, 2 in 2007, and 4 in 2008. To keep the requested
2005–2024 span visible, the census separately sampled 15 of 97 unique 2005 CIK/ticker Form 25
mappings. Eleven of those tickers occur in the archive, but none ends within ±5 sessions of the
notice. They have no reference first date and therefore are not added to the two-endpoint decision
denominator. The combined stratified review is 262 securities; 247 have both Tiingo endpoints.

Matching is exact-ticker and intentionally does not translate class, unit, warrant, or preferred
conventions. The sample is strongly tied to both references: 242 of the 247 Tiingo intervals have
the SEC corroboration above. `free_delisting_notices` contains 18,255 notices in 2005–2024, but SEC
Form 25 identifies an issuer/security event rather than supplying a complete price interval.

| End year | Tiingo ended intervals | Two-endpoint sample | SEC-corroborated | Ticker present | First ±5 | Last ±5 | Both ±5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2005 | 0 | 0 | — | — | — | — | — |
| 2006 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| 2007 | 2 | 2 | 1 | 0 | 0 | 0 | 0 |
| 2008 | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| 2009 | 41 | 15 | 11 | 0 | 0 | 0 | 0 |
| 2010 | 45 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2011 | 75 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2012 | 56 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2013 | 143 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2014 | 151 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2015 | 299 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2016 | 427 | 15 | 15 | 0 | 0 | 0 | 0 |
| 2017 | 612 | 15 | 15 | 2 | 1 | 1 | 1 |
| 2018 | 609 | 15 | 15 | 14 | 3 | 0 | 0 |
| 2019 | 550 | 15 | 15 | 15 | 4 | 0 | 0 |
| 2020 | 540 | 15 | 15 | 11 | 5 | 0 | 0 |
| 2021 | 887 | 15 | 15 | 8 | 3 | 0 | 0 |
| 2022 | 1,001 | 15 | 15 | 4 | 3 | 0 | 0 |
| 2023 | 1,167 | 15 | 15 | 3 | 1 | 0 | 0 |
| 2024 | 604 | 15 | 15 | 5 | 1 | 0 | 0 |
| **Total** | — | **247** | **242** | **62** | **21** | **1** | **1** |

Exact ticker presence alone is 62/247 (25.10%). It is not coverage: many matches are later ticker
reuse or a security that was active at the archive cutoff and ended years afterward. First-date
agreement is 21/247 (8.50%); two-endpoint agreement is 1/247 (0.405%).

## Ticker reuse and data discontinuities

The census flags a ticker when its series contains either an interior calendar gap over 45 days
or an adjacent-close discontinuity of at least 10×. It flags 166 tickers in total: 127 by gaps and
43 by price jumps, with overlap between the sets. These are conservative identity-risk flags, not
automatic declarations of issuer reuse: suspensions, missing data, reverse splits, and bad prices
can create the same pattern. Examples include multi-year gaps and isolated roughly 100× or larger
price errors. The archive supplies no listing identifier, so any hypothetical ingestion would
have to resolve every row to a listing interval rather than keying on ticker alone.

## Price basis

The page explicitly states: “prices have been adjusted for dividends and splits.” Around ten split
events already recorded in the engine's corporate-action history, the archive's post/pre close is
near continuity and far from the raw split jump in every case:

| Ticker | Ex-date | Split ratio | Observed post/pre close | Adjusted-like |
|---|---:|---:|---:|---:|
| AAPL | 2014-06-09 | 7.0 | 1.016013 | yes |
| AIG | 2009-07-01 | 0.05 | 0.779402 | yes |
| BIDU | 2010-05-12 | 10.0 | 1.095071 | yes |
| C | 2011-05-09 | 0.1 | 0.977013 | yes |
| CSCO | 2000-03-23 | 2.0 | 1.077847 | yes |
| ISRG | 2017-10-06 | 3.0 | 0.995483 | yes |
| MSFT | 2003-02-18 | 2.0 | 1.033293 | yes |
| NFLX | 2015-07-15 | 7.0 | 0.977683 | yes |
| NKE | 2015-12-24 | 2.0 | 0.981752 | yes |
| SBUX | 2015-04-09 | 2.0 | 1.007280 | yes |

The source is therefore labelled `adjusted_current_vintage`. These tests verify split continuity;
the publisher statement supplies the dividend-adjustment claim. The archive has no historical
adjustment-vintage or action ledger, so it is never fit for event-time returns as downloaded.

## Massive overlap

There is none. The archive ends 2017-11-10; `free_daily_bars` begins 2024-10-02 and currently ends
2026-10-01. No close pairs exist, so zero rows were compared and there is no legitimate adjusted-
to-raw conversion to attempt.

## Frozen decision rule and result

> Recommend ingest only if at least 30% of the sampled ended securities are present with both
> first and last dates within ±5 sessions.

Observed coverage is **0.405%**, so the recommendation is **skip**. In addition to missing the
threshold by two orders of magnitude, the artifact is ticker-keyed, carries 166 identity-risk
flags, has current-vintage future-action leakage, and contains visible OHLC quality defects.
Building an interval-keyed loader would add no useful pre-2024 survivor coverage, so the
conditional loader scope did not activate.

Reproduce the host-only census with:

```bash
python -m tools.free_frozen_archive store/pit/frozen-archive/<sha256>.zip \
  --reference-database store/pit/free-sources.duckdb
```

<!-- sources: data-scout build 2 and Kaggle receipts; host-only frozen census;
docs/pit-free-audit-2026-10-01.md; engine/free_frozen_archive.py -->
