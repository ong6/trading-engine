# P3 shorting-stress data audit — 2026-10-02

## Method

All raw responses are held outside Git in a content-addressed owner-only cache.
The isolated database records measurement, official publication, and ingestion
clocks. `short_data_asof(as_of)` excludes rows before publication. Exact symbols
are matched on observation date against the read-only Tiingo listing intervals and
SEC insider CIK/ticker history. The current SEC company-ticker snapshot is used only
on or after its snapshot date. Unique normalized punctuation variants are mapped on
the same date; ambiguous or out-of-interval identities remain flagged or unmatched.

## Overall ranges

| Source | First date | Last date | Rows |
|---|---|---|---:|
| Cboe | 2014-09-02 | 2026-10-01 | 22,976 |
| FINRA OTC | 2016-01-04 | 2026-10-01 | 61,236 |
| FINRA short interest | 2014-11-14 | 2026-09-15 | 4,200,011 |
| NYSE | 2008-10-14 | 2026-10-02 | 178,547 |
| Nasdaq | 2005-01-07 | 2026-10-01 | 368,708 |
| SEC FTD | 2004-03-22 | 2026-09-14 | 28,089,776 |

## Coverage by source and year

| Source | Year | Rows | Dates |
|---|---:|---:|---:|
| Cboe | 2014 | 181 | 80 |
| Cboe | 2015 | 391 | 196 |
| Cboe | 2016 | 771 | 240 |
| Cboe | 2017 | 843 | 234 |
| Cboe | 2018 | 776 | 240 |
| Cboe | 2019 | 1,507 | 252 |
| Cboe | 2020 | 3,082 | 253 |
| Cboe | 2021 | 1,660 | 252 |
| Cboe | 2022 | 2,142 | 251 |
| Cboe | 2023 | 1,511 | 250 |
| Cboe | 2024 | 1,656 | 252 |
| Cboe | 2025 | 2,855 | 250 |
| Cboe | 2026 | 5,601 | 188 |
| FINRA OTC | 2016 | 7,146 | 250 |
| FINRA OTC | 2017 | 6,486 | 249 |
| FINRA OTC | 2018 | 8,398 | 250 |
| FINRA OTC | 2019 | 6,977 | 252 |
| FINRA OTC | 2020 | 7,048 | 253 |
| FINRA OTC | 2021 | 7,789 | 252 |
| FINRA OTC | 2022 | 4,735 | 251 |
| FINRA OTC | 2023 | 2,525 | 250 |
| FINRA OTC | 2024 | 3,601 | 252 |
| FINRA OTC | 2025 | 3,532 | 251 |
| FINRA OTC | 2026 | 2,999 | 188 |
| FINRA short interest | 2014 | 29,276 | 4 |
| FINRA short interest | 2015 | 175,996 | 24 |
| FINRA short interest | 2016 | 171,665 | 24 |
| FINRA short interest | 2017 | 170,286 | 24 |
| FINRA short interest | 2018 | 173,841 | 24 |
| FINRA short interest | 2019 | 284,033 | 24 |
| FINRA short interest | 2020 | 414,562 | 24 |
| FINRA short interest | 2021 | 478,429 | 24 |
| FINRA short interest | 2022 | 496,296 | 24 |
| FINRA short interest | 2023 | 470,207 | 24 |
| FINRA short interest | 2024 | 468,759 | 24 |
| FINRA short interest | 2025 | 493,428 | 24 |
| FINRA short interest | 2026 | 373,233 | 17 |
| NYSE | 2008 | 1,749 | 54 |
| NYSE | 2009 | 8,919 | 250 |
| NYSE | 2010 | 12,036 | 250 |
| NYSE | 2011 | 18,499 | 250 |
| NYSE | 2012 | 15,457 | 248 |
| NYSE | 2013 | 16,646 | 250 |
| NYSE | 2014 | 15,316 | 250 |
| NYSE | 2015 | 18,178 | 250 |
| NYSE | 2016 | 14,428 | 250 |
| NYSE | 2017 | 8,354 | 249 |
| NYSE | 2018 | 5,579 | 249 |
| NYSE | 2019 | 6,536 | 251 |
| NYSE | 2020 | 9,641 | 251 |
| NYSE | 2021 | 6,085 | 250 |
| NYSE | 2022 | 6,779 | 249 |
| NYSE | 2023 | 3,630 | 248 |
| NYSE | 2024 | 3,444 | 250 |
| NYSE | 2025 | 3,518 | 248 |
| NYSE | 2026 | 3,753 | 189 |
| Nasdaq | 2005 | 52,038 | 248 |
| Nasdaq | 2006 | 50,740 | 251 |
| Nasdaq | 2007 | 65,936 | 250 |
| Nasdaq | 2008 | 59,728 | 252 |
| Nasdaq | 2009 | 9,895 | 252 |
| Nasdaq | 2010 | 9,904 | 252 |
| Nasdaq | 2011 | 11,544 | 252 |
| Nasdaq | 2012 | 8,071 | 250 |
| Nasdaq | 2013 | 11,546 | 252 |
| Nasdaq | 2014 | 10,918 | 252 |
| Nasdaq | 2015 | 4,759 | 252 |
| Nasdaq | 2016 | 5,876 | 252 |
| Nasdaq | 2017 | 5,915 | 251 |
| Nasdaq | 2018 | 4,386 | 251 |
| Nasdaq | 2019 | 4,033 | 252 |
| Nasdaq | 2020 | 4,897 | 253 |
| Nasdaq | 2021 | 6,227 | 252 |
| Nasdaq | 2022 | 4,884 | 251 |
| Nasdaq | 2023 | 4,993 | 250 |
| Nasdaq | 2024 | 8,521 | 252 |
| Nasdaq | 2025 | 11,660 | 250 |
| Nasdaq | 2026 | 12,237 | 188 |
| SEC FTD | 2004 | 534,488 | 194 |
| SEC FTD | 2005 | 622,182 | 250 |
| SEC FTD | 2006 | 657,217 | 249 |
| SEC FTD | 2007 | 734,274 | 250 |
| SEC FTD | 2008 | 1,143,439 | 251 |
| SEC FTD | 2009 | 1,625,584 | 250 |
| SEC FTD | 2010 | 1,575,431 | 250 |
| SEC FTD | 2011 | 1,536,824 | 250 |
| SEC FTD | 2012 | 1,433,315 | 250 |
| SEC FTD | 2013 | 1,396,893 | 250 |
| SEC FTD | 2014 | 1,518,621 | 250 |
| SEC FTD | 2015 | 1,547,612 | 250 |
| SEC FTD | 2016 | 1,245,231 | 250 |
| SEC FTD | 2017 | 1,121,046 | 250 |
| SEC FTD | 2018 | 1,194,854 | 250 |
| SEC FTD | 2019 | 1,050,602 | 250 |
| SEC FTD | 2020 | 1,206,764 | 251 |
| SEC FTD | 2021 | 1,460,785 | 250 |
| SEC FTD | 2022 | 1,477,590 | 249 |
| SEC FTD | 2023 | 1,400,306 | 249 |
| SEC FTD | 2024 | 1,285,064 | 250 |
| SEC FTD | 2025 | 1,326,583 | 249 |
| SEC FTD | 2026 | 995,071 | 175 |

## Ticker mapping

| Dataset | Rows | Matched | Match rate | Collisions |
|---|---:|---:|---:|---:|
| finra_short_interest | 4,200,011 | 1,279,384 | 30.5% | 8,338 |
| regsho_threshold | 631,467 | 174,392 | 27.6% | 564 |
| sec_fails_to_deliver | 28,089,776 | 14,660,501 | 52.2% | 109,462 |

### Match quality by source and segment

An `exchange_us_stock_candidate` is a non-OTC source row whose normalized symbol
appears in Tiingo's USD U.S. Stock master in at least one listing interval. A match
still requires a unique Tiingo, SEC insider-history, or current company-ticker
identity valid on the observation date. Thus the denominator includes reused and
out-of-interval symbols rather than defining success by the match itself.

| Source | Segment | Rows | Before normalization | After normalization | Collisions |
|---|---|---:|---:|---:|---:|
| Cboe | exchange_other_or_outside_master | 21,068 | 0.0% | 0.0% | 0 |
| Cboe | exchange_us_stock_candidate | 1,908 | 75.6% | 75.6% | 0 |
| FINRA OTC | otc | 61,236 | 7.1% | 7.2% | 12 |
| FINRA short interest | exchange_other_or_outside_master | 831,422 | 16.9% | 17.0% | 184 |
| FINRA short interest | exchange_us_stock_candidate | 1,032,683 | 95.7% | 98.6% | 7,704 |
| FINRA short interest | otc | 2,335,906 | 5.1% | 5.2% | 450 |
| NYSE | exchange_other_or_outside_master | 164,673 | 4.2% | 4.2% | 12 |
| NYSE | exchange_us_stock_candidate | 13,874 | 79.4% | 81.3% | 126 |
| Nasdaq | exchange_other_or_outside_master | 109,375 | 41.2% | 41.2% | 95 |
| Nasdaq | exchange_us_stock_candidate | 82,603 | 94.4% | 94.4% | 317 |
| Nasdaq | otc | 176,730 | 15.4% | 15.4% | 2 |
| SEC FTD | cusip_only | 2,359 | 0.0% | 0.0% | 0 |
| SEC FTD | exchange_us_stock_candidate | 11,187,437 | 95.2% | 96.3% | 94,571 |
| SEC FTD | foreign_cins | 289,664 | 18.6% | 18.6% | 927 |
| SEC FTD | otc | 5,883,127 | 19.7% | 19.7% | 924 |
| SEC FTD | unclassified_ftd | 10,727,189 | 24.8% | 24.9% | 13,040 |

The combined exchange-listed U.S. Stock candidate match rate is 96.5% (11,884,845/12,318,505), above the 90% target.
Per-source shortfalls remain: Cboe 75.6% (1,443/1,908); NYSE 81.3% (11,273/13,874). Their remaining candidate misses have a
Tiingo symbol only outside the observation-date interval or a reused/ambiguous key;
using a current identity would introduce look-ahead, so they remain unmatched.

### Defensible mappings added

| Source | Reference basis | Rows |
|---|---|---:|
| Cboe | cik_normalized | 6 |
| FINRA OTC | cik_normalized | 48 |
| FINRA short interest | cik_normalized | 498 |
| FINRA short interest | tiingo+cik_normalized | 834 |
| FINRA short interest | tiingo_normalized | 28,909 |
| NYSE | cik_normalized | 20 |
| NYSE | company_tickers_asof | 4 |
| NYSE | tiingo+cik_normalized | 24 |
| NYSE | tiingo_normalized | 229 |
| Nasdaq | cik_normalized | 121 |
| Nasdaq | tiingo_normalized | 77 |
| SEC FTD | cik_normalized | 10,064 |
| SEC FTD | tiingo+cik_normalized | 4,685 |
| SEC FTD | tiingo_normalized | 118,308 |

### Remaining unmatched rows by cause

| Source | Segment | Cause | Rows |
|---|---|---|---:|
| Cboe | exchange_other_or_outside_master | exchange_noncommon_or_outside_master | 21,061 |
| Cboe | exchange_us_stock_candidate | outside_listing_interval | 465 |
| FINRA OTC | otc | otc_outside_us_stock_master | 56,687 |
| FINRA OTC | otc | outside_listing_interval | 143 |
| FINRA short interest | exchange_other_or_outside_master | exchange_noncommon_or_outside_master | 690,365 |
| FINRA short interest | exchange_us_stock_candidate | outside_listing_interval | 13,952 |
| FINRA short interest | exchange_us_stock_candidate | reused_or_ambiguous_ticker | 1,005 |
| FINRA short interest | otc | otc_outside_us_stock_master | 2,209,745 |
| FINRA short interest | otc | outside_listing_interval | 5,539 |
| FINRA short interest | otc | reused_or_ambiguous_ticker | 21 |
| NYSE | exchange_other_or_outside_master | exchange_noncommon_or_outside_master | 157,789 |
| NYSE | exchange_us_stock_candidate | outside_listing_interval | 2,414 |
| NYSE | exchange_us_stock_candidate | reused_or_ambiguous_ticker | 187 |
| Nasdaq | exchange_other_or_outside_master | exchange_noncommon_or_outside_master | 64,258 |
| Nasdaq | exchange_us_stock_candidate | outside_listing_interval | 4,442 |
| Nasdaq | exchange_us_stock_candidate | reused_or_ambiguous_ticker | 170 |
| Nasdaq | otc | otc_outside_us_stock_master | 145,215 |
| Nasdaq | otc | outside_listing_interval | 4,226 |
| Nasdaq | otc | reused_or_ambiguous_ticker | 18 |
| SEC FTD | cusip_only | cusip_only | 2,359 |
| SEC FTD | exchange_us_stock_candidate | outside_listing_interval | 384,318 |
| SEC FTD | exchange_us_stock_candidate | reused_or_ambiguous_ticker | 26,707 |
| SEC FTD | foreign_cins | foreign_cins | 235,821 |
| SEC FTD | otc | otc_outside_us_stock_master | 4,725,673 |
| SEC FTD | unclassified_ftd | unclassified_outside_masters | 8,054,397 |

## Publication lag distribution

Calendar days from measurement/settlement through official publication.

| Source | Min | Median | P90 | Max |
|---|---:|---:|---:|---:|
| Cboe | 0 | 0.0 | 0.0 | 0 |
| FINRA OTC | 0 | 0.0 | 0.0 | 0 |
| FINRA short interest | 9 | 11.0 | 12.0 | 13 |
| NYSE | 0 | 0.0 | 0.0 | 19 |
| Nasdaq | 0 | 0.0 | 0.0 | 393 |
| SEC FTD | 0 | 23.0 | 32.0 | 91 |

## Source limitations

FINRA coverage is 2014-11-14 through 2021-05-28. The 1,615,228 rows on 158 settlement dates before June 2021 are OTC-only; exchange-listed consolidated history is unavailable there.
FINRA publication is the seventh business day after settlement. SEC FTD uses the
SEC's stated availability schedule: month-end for first-half data and the 15th of
the next month for second-half data; pre-July-2009 rows wait until their source
quarter ends. The SEC cautions that posting can be later, so these are date-level
availability rules rather than intraday timestamps.
SEC FTD is an aggregate outstanding settlement balance, not short interest and not
a daily flow. Threshold membership is a venue list, not evidence of abusive shorting.
Reg SHO ranges report nonempty observations. Nasdaq serves data from 2005-01-07;
NYSE's first nonempty dated file is 2008-10-14; Cboe's official date floor is
2014-08-20 and its first nonempty file is 2014-09-02; FINRA OTC partitions begin
2016-01-04. Empty dated responses remain in the private receipt cache.
CUSIPs remain only in the private raw cache and isolated local database.
