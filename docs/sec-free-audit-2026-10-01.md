# P3 Phase 0 free SEC audit — 2026-10-01

## Method

All SEC responses were retained outside Git by URL and SHA-256 and loaded only into
`store/pit/free-sources.duckdb`. Store comparisons used a disposable consistent
`tools.backup_database create` copy, which was removed after this audit. A Form 25 maps
to the latest insider-observed ticker for its CIK on or before filing; the current SEC
ticker file is only a 2026-10-01 observation. Tiingo overlap means the mapped ticker has
an interval end within ten sessions on the copied store calendar.

The capture covers 123 Form indexes, 21,394 unique notice accessions,
13,675 primary XML details, 82 contiguous
insider quarters from 2006Q1 through the official page's latest link (2026Q2), and
10,431 current company-ticker rows. SEC had not published a
2026Q3 insider ZIP on the audit date.

Insider facts become available at EDGAR acceptance when the quarterly source supplies it.
The published quarterly files are filing-date-granular otherwise, so consumers must not
use those rows until after that filing date. Transaction date is never availability.

## Form 25 coverage

| Year | Form 25 | Form 25-NSE | Total | Mapped | Mapped share |
|---:|---:|---:|---:|---:|---:|
| 1999 | 1 | 0 | 1 | 0 | 0.0% |
| 2001 | 16 | 0 | 16 | 0 | 0.0% |
| 2002 | 406 | 0 | 406 | 0 | 0.0% |
| 2003 | 468 | 0 | 468 | 0 | 0.0% |
| 2004 | 445 | 0 | 445 | 0 | 0.0% |
| 2005 | 426 | 0 | 426 | 0 | 0.0% |
| 2006 | 340 | 569 | 909 | 423 | 46.5% |
| 2007 | 344 | 995 | 1,339 | 637 | 47.6% |
| 2008 | 295 | 768 | 1,063 | 496 | 46.7% |
| 2009 | 208 | 645 | 853 | 543 | 63.7% |
| 2010 | 117 | 641 | 758 | 440 | 58.0% |
| 2011 | 112 | 568 | 680 | 383 | 56.3% |
| 2012 | 108 | 752 | 860 | 427 | 49.7% |
| 2013 | 100 | 694 | 794 | 347 | 43.7% |
| 2014 | 90 | 622 | 712 | 306 | 43.0% |
| 2015 | 68 | 661 | 729 | 333 | 45.7% |
| 2016 | 97 | 807 | 904 | 387 | 42.8% |
| 2017 | 98 | 761 | 859 | 409 | 47.6% |
| 2018 | 100 | 829 | 929 | 436 | 46.9% |
| 2019 | 107 | 829 | 936 | 450 | 48.1% |
| 2020 | 109 | 902 | 1,011 | 450 | 44.5% |
| 2021 | 100 | 1,025 | 1,125 | 551 | 49.0% |
| 2022 | 117 | 994 | 1,111 | 543 | 48.9% |
| 2023 | 128 | 1,154 | 1,282 | 606 | 47.3% |
| 2024 | 123 | 852 | 975 | 449 | 46.1% |
| 2025 | 130 | 898 | 1,028 | 456 | 44.4% |
| 2026 | 89 | 686 | 775 | 333 | 43.0% |

## Mapped notices near Tiingo interval ends

| Year | Mapped notices | Within ±10 sessions | Share |
|---:|---:|---:|---:|
| 2006 | 423 | 1 | 0.2% |
| 2007 | 637 | 0 | 0.0% |
| 2008 | 496 | 3 | 0.6% |
| 2009 | 543 | 16 | 2.9% |
| 2010 | 440 | 11 | 2.5% |
| 2011 | 383 | 12 | 3.1% |
| 2012 | 427 | 9 | 2.1% |
| 2013 | 347 | 23 | 6.6% |
| 2014 | 306 | 52 | 17.0% |
| 2015 | 333 | 104 | 31.2% |
| 2016 | 387 | 124 | 32.0% |
| 2017 | 409 | 119 | 29.1% |
| 2018 | 436 | 150 | 34.4% |
| 2019 | 450 | 127 | 28.2% |
| 2020 | 450 | 135 | 30.0% |
| 2021 | 551 | 157 | 28.5% |
| 2022 | 543 | 195 | 35.9% |
| 2023 | 606 | 250 | 41.3% |
| 2024 | 449 | 115 | 25.6% |
| 2025 | 456 | 102 | 22.4% |
| 2026 | 333 | 103 | 30.9% |

The low pre-2015 overlap and its step-up from 2015 calibrate the Tiingo
archive's sparse early interval ends. The 2026 overlap is not a delisting-rate
estimate because the Tiingo archive boundary right-censors current intervals.

## Insider coverage

| Year | Submissions | Purchases (`P`) | Sales (`S`) | Submission store share | Submission Tiingo share | Purchase store share | Purchase Tiingo share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2006 | 268,475 | 56,113 | 337,872 | 26.2% | 44.9% | 10.6% | 34.5% |
| 2007 | 276,449 | 76,528 | 441,097 | 26.5% | 49.5% | 13.9% | 40.9% |
| 2008 | 250,098 | 114,876 | 253,593 | 28.1% | 54.4% | 15.3% | 47.3% |
| 2009 | 212,985 | 54,722 | 105,034 | 30.4% | 59.0% | 13.7% | 46.7% |
| 2010 | 221,535 | 38,405 | 119,258 | 33.1% | 63.3% | 13.5% | 46.1% |
| 2011 | 215,688 | 45,286 | 98,047 | 33.6% | 66.2% | 20.4% | 54.1% |
| 2012 | 216,759 | 38,558 | 103,229 | 36.5% | 70.9% | 23.8% | 62.0% |
| 2013 | 217,457 | 29,392 | 102,578 | 37.9% | 73.6% | 15.8% | 57.3% |
| 2014 | 220,111 | 33,889 | 94,782 | 37.8% | 74.3% | 15.0% | 62.6% |
| 2015 | 216,398 | 41,664 | 80,598 | 39.6% | 75.8% | 14.6% | 58.3% |
| 2016 | 204,322 | 35,440 | 69,863 | 42.6% | 79.4% | 17.1% | 65.3% |
| 2017 | 202,496 | 28,818 | 77,479 | 45.1% | 80.0% | 16.5% | 56.5% |
| 2018 | 202,051 | 41,695 | 75,370 | 46.5% | 79.6% | 14.0% | 70.6% |
| 2019 | 196,336 | 37,313 | 74,002 | 49.8% | 80.4% | 14.2% | 70.3% |
| 2020 | 203,570 | 32,047 | 92,578 | 51.8% | 80.7% | 27.7% | 68.9% |
| 2021 | 224,474 | 26,636 | 134,440 | 51.8% | 79.6% | 27.8% | 69.3% |
| 2022 | 202,918 | 34,205 | 72,833 | 54.3% | 82.9% | 27.9% | 71.6% |
| 2023 | 199,808 | 28,839 | 70,359 | 57.8% | 85.3% | 26.4% | 65.8% |
| 2024 | 195,095 | 22,623 | 92,376 | 62.5% | 87.8% | 29.1% | 66.1% |
| 2025 | 186,023 | 22,381 | 83,135 | 65.9% | 89.7% | 30.1% | 70.7% |
| 2026 | 125,361 | 11,230 | 50,216 | 93.1% | 92.3% | 84.8% | 75.4% |

## Data-quality notes

- Amendments retained: 349 Form 25-family notices and 117,674 insider submissions.
- Duplicate insider accession rows across quarterly archives: 0.
- Non-derivative transactions with zero or missing price: 1,750,587.
- Submissions with missing symbols: 60,611; with non-standard symbols: 65,460.
- Submissions with a missing issuer name: 1,188.
- Form 25-NSE details with an empty security class: 1.
- Amendments are retained as distinct accessions. Exact symbols are not rewritten; class,
  preferred, warrant, slash, and punctuation conventions therefore remain visible rather
  than being guessed into a match.
