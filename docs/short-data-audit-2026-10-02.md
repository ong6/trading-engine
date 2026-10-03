# P3 shorting-stress data audit — 2026-10-02

## Method

All raw responses are held outside Git in a content-addressed owner-only cache.
The isolated database records measurement, official publication, and ingestion
clocks. `short_data_asof(as_of)` excludes rows before publication. Exact symbols
are matched on observation date against the read-only Tiingo listing intervals and
SEC CIK/ticker history; ambiguous reference intervals are flagged, not guessed.

This is checkpoint `shorts-3`: FINRA short interest, SEC FTD, FINRA OTC,
Nasdaq, and NYSE are complete. Cboe is resumable through 2016-09-02 and will
resume after the 05:45--07:00 UTC network blackout. The final audit replaces
this note after that capture finishes.

## Overall ranges

| Source | First date | Last date | Rows |
|---|---|---|---:|
| Cboe | 2014-09-02 | 2016-09-02 | 1,062 |
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
| Cboe | 2016 | 490 | 158 |
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
| finra_short_interest | 4,200,011 | 1,249,143 | 29.7% | 7,185 |
| regsho_threshold | 609,553 | 172,419 | 28.3% | 564 |
| sec_fails_to_deliver | 28,089,776 | 14,527,444 | 51.7% | 105,560 |

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
CUSIPs remain only in the private raw cache and isolated local database.
