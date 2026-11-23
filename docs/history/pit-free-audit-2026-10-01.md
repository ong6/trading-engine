# Point-in-time data (P3) Phase 0 free-source audit — 2026-10-01

## Scope and method

This audit compares the latest captured Tiingo supported-ticker archive with a transactionally
consistent copy of the operational DuckDB store. The copy was made with
`tools.backup_database create`, opened read-only for the audit, and deleted afterward. Neither the
operational `prices` table nor a forward record was changed.

The master admits USD rows whose Tiingo `assetType` is `Stock` and whose exchange is a named US
venue. A listing covers a year when its interval overlaps any day in that calendar year. Store
coverage means an exact ticker has at least one `prices` bar in that year. Matching is deliberately
exact, and store rows currently marked `etf=TRUE` are excluded: no issuer identity is available
to resolve reused tickers or translate class/preferred symbol conventions. Matched and master-only
counts use the interval's master exchange; store-only counts use the store's current exchange
field. Counts are distinct tickers within each cell.

## Captured master

The public archive contained 108,908 rows. The admitted master has 16,527 listing intervals for
15,792 distinct tickers, spanning 1962-01-02 through the archive boundary of 2026-09-30. None of
the intervals has an open end.

| Exchange | Intervals | Distinct tickers |
|---|---:|---:|
| CBOE (source `BATS`) | 273 | 273 |
| NASDAQ | 9,363 | 8,998 |
| NYSE | 6,296 | 6,069 |
| NYSE American (source `AMEX` / `NYSE MKT`) | 539 | 513 |
| NYSE Arca | 53 | 53 |
| NYSE National | 3 | 3 |
| **Total** | **16,527** | **15,792** |

## Annual exact-ticker overlap, 2010–2026

The exchange detail in the last column is `matched / master-only / store-only`. The first five
numeric columns deduplicate tickers across exchanges, so they are the appropriate annual totals;
exchange subtotals can double-count a reused ticker whose intervals overlap on different venues.

| Year | Master | Store | Matched | Master-only | Store-only | By exchange: matched / master-only / store-only |
|---:|---:|---:|---:|---:|---:|---|
| 2010 | 4,428 | 1,663 | 1,577 | 2,851 | 86 | CBOE 1/6/0; NASDAQ 614/1,642/25; NYSE 952/1,069/54; NYSE American 15/131/6; NYSE Arca 0/4/1; NYSE National 0/3/0 |
| 2011 | 4,603 | 1,699 | 1,614 | 2,989 | 85 | CBOE 1/8/0; NASDAQ 625/1,709/26; NYSE 976/1,128/54; NYSE American 17/139/4; NYSE Arca 0/6/1; NYSE National 0/3/0 |
| 2012 | 4,808 | 1,752 | 1,663 | 3,145 | 89 | CBOE 1/8/0; NASDAQ 645/1,777/27; NYSE 1,004/1,211/57; NYSE American 18/144/4; NYSE Arca 0/6/1; NYSE National 0/3/0 |
| 2013 | 5,105 | 1,827 | 1,731 | 3,374 | 96 | CBOE 1/8/0; NASDAQ 671/1,884/30; NYSE 1,046/1,329/61; NYSE American 18/147/4; NYSE Arca 0/7/1; NYSE National 0/3/0 |
| 2014 | 5,643 | 1,914 | 1,821 | 3,822 | 93 | CBOE 1/8/0; NASDAQ 712/2,046/27; NYSE 1,095/1,581/61; NYSE American 18/180/4; NYSE Arca 0/8/1; NYSE National 0/3/0 |
| 2015 | 5,911 | 1,995 | 1,908 | 4,003 | 87 | CBOE 1/9/0; NASDAQ 758/2,184/23; NYSE 1,136/1,619/59; NYSE American 18/184/4; NYSE Arca 0/8/1; NYSE National 0/3/0 |
| 2016 | 6,345 | 2,053 | 1,976 | 4,369 | 77 | CBOE 1/11/0; NASDAQ 791/2,369/20; NYSE 1,171/1,779/53; NYSE American 19/202/3; NYSE Arca 0/10/1; NYSE National 0/3/0 |
| 2017 | 6,515 | 2,126 | 2,053 | 4,462 | 73 | CBOE 1/12/0; NASDAQ 829/2,434/18; NYSE 1,207/1,785/50; NYSE American 22/221/3; NYSE Arca 0/10/2; NYSE National 0/3/0 |
| 2018 | 6,452 | 2,227 | 2,154 | 4,298 | 73 | CBOE 1/11/1; NASDAQ 891/2,395/19; NYSE 1,247/1,652/47; NYSE American 22/234/3; NYSE Arca 0/8/3; NYSE National 0/3/0 |
| 2019 | 6,488 | 2,315 | 2,240 | 4,248 | 75 | CBOE 1/12/1; NASDAQ 942/2,326/21; NYSE 1,280/1,660/47; NYSE American 23/236/3; NYSE Arca 0/17/3; NYSE National 0/3/0 |
| 2020 | 6,948 | 2,449 | 2,365 | 4,583 | 84 | CBOE 1/13/1; NASDAQ 1,023/2,583/28; NYSE 1,322/1,724/49; NYSE American 25/249/3; NYSE Arca 0/19/3; NYSE National 0/3/0 |
| 2021 | 8,750 | 2,638 | 2,555 | 6,195 | 83 | CBOE 1/11/1; NASDAQ 1,143/3,762/24; NYSE 1,391/2,119/52; NYSE American 27/284/3; NYSE Arca 0/23/3; NYSE National 0/3/0 |
| 2022 | 8,559 | 2,685 | 2,603 | 5,956 | 82 | CBOE 1/12/1; NASDAQ 1,166/3,790/23; NYSE 1,410/1,855/52; NYSE American 32/286/3; NYSE Arca 0/21/3 |
| 2023 | 8,083 | 2,733 | 2,658 | 5,425 | 75 | CBOE 1/12/1; NASDAQ 1,195/3,484/19; NYSE 1,437/1,630/49; NYSE American 30/282/3; NYSE Arca 0/20/3 |
| 2024 | 7,516 | 2,806 | 2,737 | 4,779 | 69 | CBOE 1/18/1; NASDAQ 1,238/3,118/16; NYSE 1,470/1,345/46; NYSE American 30/285/3; NYSE Arca 0/17/3 |
| 2025 | 7,918 | 2,897 | 2,838 | 5,080 | 59 | CBOE 1/28/1; NASDAQ 1,295/3,406/10; NYSE 1,515/1,358/42; NYSE American 31/280/3; NYSE Arca 0/13/3 |
| 2026 | 8,758 | 6,781 | 6,358 | 2,400 | 423 | CBOE 1/264/3; NASDAQ 4,030/1,105/68; NYSE 2,087/928/300; NYSE American 249/75/38; NYSE Arca 0/31/14 |

## Listing-interval ends by year

Tiingo supplies an interval end but no active flag or delisting reason. These are therefore
coverage-end/delisting proxies, not proof that an exchange delisted a security. `With any store
bar` is an exact-ticker match anywhere in the operational history and can overstate issuer-level
coverage when a ticker was reused.

| End year | Intervals | Distinct tickers | With any store bar |
|---:|---:|---:|---:|
| 2010 | 45 | 45 | 4 |
| 2011 | 75 | 75 | 6 |
| 2012 | 56 | 56 | 1 |
| 2013 | 143 | 143 | 13 |
| 2014 | 151 | 151 | 12 |
| 2015 | 299 | 299 | 25 |
| 2016 | 427 | 427 | 25 |
| 2017 | 612 | 612 | 38 |
| 2018 | 609 | 608 | 41 |
| 2019 | 550 | 549 | 38 |
| 2020 | 540 | 536 | 37 |
| 2021 | 887 | 880 | 58 |
| 2022 | 1,001 | 987 | 52 |
| 2023 | 1,167 | 1,162 | 41 |
| 2024 | 604 | 602 | 40 |
| 2025 | 434 | 431 | 37 |
| 2026 | 8,878 | 8,758 | 6,862 |
| **2010–2026** | **16,478** | **16,321 year-local** | **7,330 year-local** |

## Coverage and identity caveats

- **Pre-2015 ends are sparse.** Only 470 intervals end across 2010–2014, versus 7,130 across
  2015–2025. The archive therefore identifies far fewer early delistings; absence from those
  early counts is not evidence that a security remained listed.
- **The current boundary is right-censored.** All intervals have an end date, and 8,878 end in
  2026 at or before the archive's 2026-09-30 boundary. Those rows cannot be interpreted as 8,878
  delistings. The 2026 annual overlap is useful; the 2026 end count is not a delisting rate.
- **Ticker reuse is material.** 697 tickers have more than one distinct interval. Exact-ticker
  matching can join different companies across time, so the survivor-gap counts are security-list
  coverage diagnostics rather than stable-issuer-identity counts.
- **The source's `Stock` label is broad.** 908 distinct admitted tickers contain the preferred-like
  marker `-P-`. Tiingo provides no common/preferred flag beyond `assetType`, and no delisting
  reason, so Phase 0 cannot cleanly separate common shares or calculate reason-specific returns.

This source establishes that the existing store omits many names that were listed in earlier
years, but it does not contain their prices or delisting returns. It also cannot distinguish a
issuer change behind a reused ticker, and its `Stock` classification is only a proxy for common
stock: odd preferred-like symbols remain visible in the counts rather than being silently treated
as clean common shares.

## What closes the gap for free

1. **Massive grouped daily, 2024-10-01 through 2026-09-30.** The implemented date-resumable
   fetcher can recover every US stock that traded on each date in that window, including names
   subsequently delisted. It remains unrun until the owner creates the individual-use free key.
2. **SEC Form 25 notices.** These add delisting notice dates and evidence after the owner supplies
   the required SEC contact identity. They do not supply the missing price history. This is the
   next free source; no SEC implementation was added in Phase 0.
3. **Irreducible without paid data.** Free sources found here cannot recover delisted names'
   prices before 2024-10 or authoritative delisting returns. Those gaps keep pre-window return
   studies survivor-biased even after the security master identifies the missing names.
