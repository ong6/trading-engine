# SEC bulk point-in-time audit — 2026-10-02

## Method

The two official nightly bulk ZIPs and every older submissions page were cached
outside Git by URL and SHA-256. Facts are available at the matching accession's
timezone-aware SEC acceptance timestamp; unmatched accessions become available only
at the end of their filing date in America/New_York. Restated accessions remain
separate source rows. Tickers come from the read-only `free_cik_ticker_history` view.

The isolated store contains 12,170,777 facts across 17,096 distinct companies and 421,723 item 2.02 earnings events.

Tag fallbacks, in priority order, are:

- `revenue`: `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`, `us-gaap:Revenues`, `us-gaap:SalesRevenueNet`, `us-gaap:SalesRevenueGoodsNet`, `us-gaap:SalesRevenueServicesNet`, `ifrs-full:Revenue`
- `net_income`: `us-gaap:NetIncomeLoss`, `us-gaap:ProfitLoss`, `ifrs-full:ProfitLoss`
- `eps_basic`: `us-gaap:EarningsPerShareBasic`, `ifrs-full:BasicEarningsLossPerShare`
- `eps_diluted`: `us-gaap:EarningsPerShareDiluted`, `ifrs-full:DilutedEarningsLossPerShare`
- `operating_cash_flow`: `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations`, `ifrs-full:CashFlowsFromUsedInOperatingActivities`
- `total_assets`: `us-gaap:Assets`, `ifrs-full:Assets`
- `total_liabilities`: `us-gaap:Liabilities`, `ifrs-full:Liabilities`
- `stockholders_equity`: `us-gaap:StockholdersEquity`, `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, `us-gaap:PartnersCapital`, `ifrs-full:Equity`
- `shares_outstanding`: `dei:EntityCommonStockSharesOutstanding`, `us-gaap:CommonStockSharesOutstanding`, `ifrs-full:NumberOfSharesOutstanding`
- `dividends_per_share`: `us-gaap:CommonStockDividendsPerShareDeclared`, `us-gaap:CommonStockDividendsPerShareCashPaid`, `ifrs-full:DividendsPaidPerShare`
- `research_and_development`: `us-gaap:ResearchAndDevelopmentExpense`, `ifrs-full:ResearchAndDevelopmentExpense`
- `selling_general_and_administrative`: `us-gaap:SellingGeneralAndAdministrativeExpense`, `ifrs-full:GeneralAndAdministrativeExpense`

## Fundamental coverage

| Year | Facts | Companies |
|---:|---:|---:|
| 2009 | 29,856 | 478 |
| 2010 | 120,604 | 1,503 |
| 2011 | 484,985 | 7,952 |
| 2012 | 821,133 | 8,460 |
| 2013 | 857,605 | 8,133 |
| 2014 | 841,684 | 7,957 |
| 2015 | 806,978 | 7,738 |
| 2016 | 761,876 | 7,204 |
| 2017 | 733,319 | 6,867 |
| 2018 | 734,096 | 7,107 |
| 2019 | 767,123 | 6,963 |
| 2020 | 752,987 | 6,896 |
| 2021 | 794,319 | 7,806 |
| 2022 | 822,234 | 8,001 |
| 2023 | 806,000 | 7,674 |
| 2024 | 765,555 | 7,214 |
| 2025 | 743,786 | 7,114 |
| 2026 | 526,637 | 6,981 |

## Earnings events

| Year | 8-K item 2.02 events |
|---:|---:|
| 2004 | 6,486 |
| 2005 | 23,789 |
| 2006 | 23,138 |
| 2007 | 22,650 |
| 2008 | 22,056 |
| 2009 | 20,208 |
| 2010 | 19,446 |
| 2011 | 18,900 |
| 2012 | 18,626 |
| 2013 | 18,289 |
| 2014 | 18,697 |
| 2015 | 18,773 |
| 2016 | 18,172 |
| 2017 | 17,710 |
| 2018 | 17,497 |
| 2019 | 17,095 |
| 2020 | 17,648 |
| 2021 | 18,396 |
| 2022 | 18,871 |
| 2023 | 18,328 |
| 2024 | 17,569 |
| 2025 | 16,952 |
| 2026 | 12,427 |

## Mapping and overlap

- Combined fact/event ticker match: 11,805,636/12,592,500 (93.8%).
- Fundamental ticker match: 11,398,481/12,170,777; earnings-event ticker match: 407,155/421,723.
- SEC earnings events within ±1 calendar day of an existing engine earnings date: 2,162/421,723 (0.5%); 407,155 events had a ticker mapping.

The overlap denominator is every SEC item 2.02 event, so an unmapped CIK cannot count
as an overlap. The engine snapshot was attached read-only and was not modified.
