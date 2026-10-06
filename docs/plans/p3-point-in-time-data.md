---
plan: P3 # Point-in-time data
title: Survivorship-free point-in-time data
status: approved
opened: 2026-09-18
owner_decision: paid-vendor spend remains deferred; free grouped-daily capture is active
---

# Survivorship-free point-in-time data (P3)

## Vendor comparison — 2026-09-20

| Candidate | Role fit | Relevant official coverage | Decision |
|---|---|---|---|
| [Sharadar via Nasdaq Data Link](https://data.nasdaq.com/databases/SEP) | Point-in-time research | Daily US-equity prices, corporate actions, delisting reasons, ticker changes, reference data, and separately available fundamental tables | **Recommended**; verify current SF1/SEP/TICKERS licence and price before purchase |
| [Norgate Data](https://norgatedata.com/data-content-tables.php) | Point-in-time research fallback | Delisted securities and historical index constituent histories designed to avoid survivorship bias | Fallback if Sharadar licence, export, or price is unsuitable |
| [IBKR](https://ibkrcampus.com/campus/ibkr-api-page/contracts/) | Execution and live/paper market access | Stable contract identifiers, broad execution API and subscription-backed market data | Primary future broker; not the P3 historical research source |
| [Moomoo OpenAPI](https://openapi.futunn.com/futu-api-doc/en/intro/authority.html) | Secondary execution candidate | Live/paper trading through OpenD, with permission and rolling historical-candlestick quotas | Secondary broker; not the P3 historical research source |
| EODHD / Polygon | Price/reference alternatives | Delisted coverage varies; historical membership and point-in-time fundamentals are incomplete for this plan | Not preferred for P3 |

**Recommendation.** Keep execution and research-data concerns separate. Review Sharadar first,
with Norgate as fallback. The next owner input is a maximum initial and recurring spend; purchase,
credentials, ingestion, and licence acceptance remain out of scope until then.

## Phase 0: free sources (owner decision 2026-10-01)

The owner has declined data spend for now. The paid-vendor phase remains approved but blocked;
this bounded free-source phase is unblocked and runs without changing that recommendation.

**Scope.** Download Tiingo's public supported-ticker archive, retain each exact ZIP by content
hash outside Git, and load its USD `Stock` rows on US exchanges into the isolated
`free_security_master` table. The Massive Stocks Basic grouped-daily fetcher covers the rolling
free-tier window. It reads an owner-only key file, waits at least 13 seconds between calls, retains
one exact response per date, resumes from those responses, pauses in the registered quiet windows,
and loads `free_daily_bars`. Both sources default to
`store/pit/free-sources.duckdb` and
`store/pit/free-sources/`, with explicit path overrides. Audit the master against a consistent
copy of the operational store and publish `docs/pit-free-audit-2026-10-01.md`. The free SEC history
follow-up below is also complete.

**Not in scope.** No purchase, paid-vendor ingestion, readiness endpoint, strategy or replay work,
operational `prices` mutation, or change to a forward record. Free-source data remains host-only and
isolated from all operational and execution authority.

**Initial checkpoint.** The Tiingo master was loaded and audited for 2010-2026 coverage,
delistings, ticker reuse, and exact-ticker survivor gaps; recorded-fixture tests proved parsing,
idempotent reload, key refusal, pacing, and date-level resume; and Massive was reported ready but
unrun. The audit records that free sources cannot recover pre-2024-10 prices for delisted names or
delisting returns. The live capture below is a follow-up to that completed checkpoint.

## Phase 0 part 5: frozen Kaggle archive census — complete 2026-10-02

The anonymous 2017 Kaggle ZIP was downloaded once in a permitted window and retained by content
hash outside Git. `engine/free_frozen_archive.py` and its tool perform an offline structural census,
retain per-ticker endpoints in a host-only JSON result, flag gap/price-discontinuity identity risk,
check ten known splits, and compare a deterministic year-stratified sample against the Tiingo
listing intervals and SEC Form 25 notices. No running producer, operational table, or forward
record is touched.

The frozen rule admitted a loader only if at least 30% of sampled ended intervals matched both
endpoints within ±5 sessions. Only 1 of 247 (0.405%) did. Just 10 of 8,507 populated archive
tickers ended more than 30 sessions before the 2017-11-10 archive boundary, while 8,025 end exactly
on that boundary. The archive is a current-at-cutoff survivor snapshot, not a useful delisted-name
backfill. It is also split/dividend-adjusted current-vintage data without an action ledger.

**Outcome.** [`../frozen-archive-census-2026-10-02.md`](../frozen-archive-census-2026-10-02.md)
records `skip`; the conditional interval-keyed loader did not activate, zero rows were loaded, and
`frozen-archive.duckdb` was not created. The raw ZIP and full per-ticker census remain host-only.

**Budget.** One logical commit under the repository's 1,500-insertion limit, confined to the three
named `free_frozen_archive` files and P3 documentation.

**Budget.** Up to 1,200 new code-and-test lines across P3's claimed `free_*` files, split into
reviewable commits below the repository's 1,500-line limit. No dependency, service, timer,
endpoint, operational migration, or tracked raw-data file is added.

## Phase 0 part 4: SEC nightly bulk fundamentals — active 2026-10-02

Use the official nightly `companyfacts.zip` and `submissions.zip`, plus every older submissions
page named by the latter, to load core point-in-time fundamentals and 8-K item 2.02 earnings events
from 2004 onward. Requests use one connection, the private runtime contact, five-per-second pacing,
the existing quiet windows, resumable partial files, and content-addressed raw archives. The
isolated, configurable default database is `store/pit/sec-bulk.duckdb` in the main checkout.

`sec_facts` retains every selected source observation and accession. Revenue, net income, basic and
diluted EPS, operating cash flow, assets, liabilities, equity, shares outstanding, dividends per
share, R&D, and SG&A use the documented ordered tag fallbacks in the dated audit. A fact becomes
available at its matching submission acceptance timestamp; without a match it waits until end of
the filing date in America/New_York. The `sec_fundamentals_asof(as_of)` table macro chooses the
latest known company/concept fact without replacing restatements. `sec_earnings_events` retains
8-K and 8-K/A filings whose exact item list contains `2.02`, with timezone-aware acceptance.

CIK/ticker observations are copied only from the existing read-only `free_cik_ticker_history`
view. The audit reads the latest market snapshot read-only and reports facts, companies and events
by year, ticker match rates, and the share of SEC earnings events within one calendar day of an
existing engine earnings date. Raw archives and the database remain host-only.

**Claimed files.** Only `engine/free_sec_bulk.py`, `tools/free_sec_bulk.py`,
`tests/test_free_sec_bulk.py`, `docs/sec-bulk-audit-2026-10-02.md`, and this phase's P3, product,
feedback, budget and BUILDLOG entries. No P15-registered file or XS forward-contract file changes.

**Done when.** Recorded ZIP fixtures prove parsing, acceptance-time as-of behavior, retained
restatements, item filtering, pacing, resumable download, and missing-contact refusal; live HEAD
checks pass in an allowed window; all archives and pages are cached and loaded; the audit is
filled; focused and full tests, whole-repository Ruff and the metrics budget pass; and only
`p3/sec-bulk` is pushed.

**Budget.** Up to 1,800 code-and-test lines in the three claimed modules, in logical commits below
the repository's 1,500-insertion cap. The audit data and bounded plan entries do not count toward
that allowance.

### How to run this Phase 0 part

Build and prove fixtures before any request. Start with HEAD checks in a permitted window, then
load Submissions and every referenced page before Companyfacts so accession matches get their exact
clock. Resume at later windows when necessary. Audit against read-only inputs, run the required
repository gates once, publish metrics and BUILDLOG, and push the lane branch.

**Outcome.** Both live HEAD checks passed. The 1.57 GB Submissions ZIP, all 987,283 members and all
5,387 referenced older pages are cached and loaded. The 1.41 GB Companyfacts partial resumed from
its exact byte after a quiet-window stop and completed. The isolated store holds 12,170,777 core
facts across 17,096 companies and 421,723 exact item 2.02 events from 2004 onward. Combined fact and
event ticker matching is 93.8%. Of 3,649 distinct engine ticker/dates inside the mapped SEC capture
window, 62.6% have a same-ticker item 2.02 event within ±1 day and 64.8% within ±3 days. The original
0.5% event-first overlap is retained only as a full-history source diagnostic.
[`../sec-bulk-audit-2026-10-02.md`](../sec-bulk-audit-2026-10-02.md) records the annual counts,
ordered tag fallbacks, denominators and 30-miss sample. No operational or execution table changed.

## Phase 0 part 3: Massive grouped daily capture — active 2026-10-02

The individual-use free key now exists in a private owner-only file. A resumable background capture
is filling the free tier's two-year history. The rolling lower bound is the current UTC date minus
two years plus one day, and the upper bound is the most recent completed NYSE session. Requests stop
during the registered UTC and New York quiet windows and continue from retained date receipts. The
first date loaded for the live proof, 2026-09-30, contained 12,613 US securities; the historical
daily responses include names that later delisted.

The `massive --daily` mode visits missing completed sessions newest first and fetches at most ten
per run. Weekends and NYSE holidays are omitted by the engine calendar, cached dates are loaded
without another request, and a zero-row response for the current or previous UTC date is reported
as `not_yet_published` without being cached so the next run retries it. Consumers can read a bounded
bar frame with `engine.free_sources.daily_panel`. `engine.free_sources.mdv60` computes each
ticker's median dollar volume over the preceding 60 NYSE sessions, strictly before its as-of date;
it uses VWAP times volume where VWAP exists and close times volume otherwise.

Commit `74225e1` made the loader match real grouped responses. Individual malformed bars are
quarantined in `free_daily_bars_rejected` rather than failing an otherwise usable date, subject to
the 5% rejection ceiling. `free_daily_bars.volume` accepts fractional-share volume, and the ticker
validator accepts lowercase preferred-share and warrant suffixes. The response envelope remains
fail-closed, raw responses remain private, and the isolated database still has no operational-price
or execution authority.

## Phase 0 part 4: Massive small-stock minute capture — active 2026-10-02

The free minute lane is isolated in `massive-minute.duckdb` and a private content-addressed raw
cache. Its frozen manifest contains SPY, QQQ, IWM, and every exact ticker that was a Tiingo-admitted
USD Stock on a session when its grouped-daily MDV60 was between USD 1M and USD 5M. MDV60 uses the
existing point-in-time rule: the preceding 60 NYSE sessions, excluding the as-of session. The live
manifest contains 3,302 tickers, including 575 names that actually traded in the private holdout;
private names and results remain host-only.

The 2024-10-03 through 2026-10-01 window has ten chunks per ticker, each spanning at most 50 NYSE
sessions. Massive documents stock extended hours as 04:00--20:00 New York, so a fully populated
chunk has at most 48,000 minute bars under the endpoint's 50,000-result limit; `next_url` is still
validated and followed. The lower-bound request estimate is 33,020 calls: 110.1 continuous hours
at five calls per minute, or about 7.8 days after the registered no-call windows. The service
therefore visits the benchmarks first, then holdout-traded names, then all remaining names by tier
frequency.

Every Massive request, including grouped daily, reserves the same owner-only file lock and
monotonic timestamp and stays at least 13 seconds behind the previous process. The minute service
also yields around the two already-deployed daily starts until the shared implementation reaches
that producer. Per-(ticker, chunk) receipts retain every page by SHA-256, resume at the saved
pagination URL, and mark a chunk loaded transactionally. New York timestamps tag bars as `pre`,
`regular`, or `post` using the NYSE calendar and early closes. Neither the database, manifest, raw
responses, nor the private priority input enters Git.

**Done when.** Fixture tests prove pagination, holiday and early-close tagging, two-process pacing,
resume, no-call refusal, secure key handling, and the existing daily caller's shared reservation;
the full suite and Ruff pass; `p3/massive-minute` is pushed; and the transient user service is
started with `KillMode=process` and its private log under `~/.local/state/`.

**Budget.** Up to 1,200 code-and-test lines in `engine/free_massive_minute.py`,
`tools/free_massive_minute.py`, `tests/test_free_massive_minute.py`, and the shared limiter
integration. Each logical commit remains below 1,500 inserted non-data lines.

## Phase 0 part 6: bounded Massive options capture — active 2026-10-06

The free options lane is isolated in `store/pit/options.duckdb` with content-addressed raw
responses. Its tracked manifest fixes SPY, QQQ and IWM, 20--60 calendar days to expiry, strikes
within 5% of the prior adjusted grouped-daily close, at most four contract pages per underlying,
and at most 400 daily-bar requests over a five-calendar-day tail. Contract snapshots retain their
as-of date; daily bars retain the first captured source body. Every HTTP request reserves the same
process-safe Massive limiter used by grouped daily and minute capture.

This is reference and aggregate-bar research data only. The endpoints provide no bid/ask quotes,
so option execution remains refused as `instrument_not_executable` until a separately approved
quote-data and execution model exists. Tests use recorded responses only; the one permitted SPY
contracts smoke writes solely to a temporary database and cache.

## Phase 0 part 2: free SEC history — complete 2026-10-01

The SEC contact identity is now present in the owner-only environment file, so the pending
Phase 0 SEC work is active. Read every 1996Q1--2026Q3 EDGAR `form.idx`, retain Form 25 and
25-NSE notices including amendments, and fetch the primary XML for 25-NSE filings from 2010.
Load the SEC Insider Transactions Data Sets from 2006Q1--2026Q3 and the current SEC issuer
ticker map into the same isolated Phase 0 database. The resulting tables and the
`free_cik_ticker_history` view are generic point-in-time research infrastructure.

**Scope.** Add only `engine/free_sec.py`, `tools/free_sec.py`, and
`tests/test_free_sec.py`. Raw HTTP bodies are cached outside Git by URL and content hash;
requests carry the private contact at runtime, request gzip, run at no more than five per second,
obey the registered UTC and New York no-call windows, and resume from verified cache entries.
Insider availability is the EDGAR acceptance time when the quarterly dataset supplies one;
otherwise it is filing-date-granular and must not be used before the next session. Transaction
date is never availability. Publish `docs/sec-free-audit-2026-10-01.md` from the isolated database
and a temporary `tools.backup_database create` copy of the operational store.

**Not in scope.** No operational `prices` or universe mutation, live service or timer, strategy,
replay, readiness gate, paid source, Massive request, or new dependency. The current ticker map
is a dated observation, not historical-membership authority. Raw SEC data and the isolated
database remain untracked on the host.

**Done when.** Recorded fixtures prove index, Form 25 XML, and insider ZIP parsing; idempotent
reloads; pacing; interrupted-batch resume; missing-contact refusal; and the filing-date/
acceptance-time availability rule. All requested quarters and current tickers are cached and
loaded, the audit contains the requested annual mapping and quality counts, focused and full
tests pass, whole-repository Ruff and the metrics budget pass, and `p3/sec-sources` is pushed.

**Budget.** Part 2 may add up to 1,800 code-and-test lines in its three claimed files, in logical
commits below the repository's 1,500-insertion limit. Data and the audit document do not count
toward this code-and-test allowance.

### How to run this Phase 0 part

Build and prove the offline parsers and resumable capture first. Fetch only in a permitted window,
stopping cleanly at a boundary. Then audit against a consistent disposable store copy, run the
required repository gates once, publish the metrics snapshot and BUILDLOG entry, and push only the
lane branch.

**Outcome.** All 123 Form indexes through 2026Q3 and every required 2010+ 25-NSE primary XML
were retained and loaded. The official insider page supplied 82 contiguous ZIPs through 2026Q2;
2026Q3 was not yet published. The current issuer-ticker snapshot and the coverage audit are
complete; Phase 0 remains isolated research data and the paid-vendor phase remains spend-blocked.

## Goal

The store holds an independently acquired US equity dataset with delisted names, historical
index or universe membership, publication timestamps for fundamentals, and documented
corporate-action treatment. It is audited against the existing Yahoo-derived store, versioned
separately, and used to recompute the stock-selection readiness gate. Row 5 of the
next-admissible-actions table fires.

## Why now

This is the only lever on the research calendar. Without it, stock-selection research waits
for 756 qualifying dates (roughly July 2029) and every historical replay stays on today's
survivors, which the walk-forward README prices at about +7 percentage points a year of fake
return and which grows worse the further back a fold reaches. No amount of engine hardening
changes that date. Buying data does.

## Scope

1. **Vendor shortlist and audit protocol (one session, no purchase).** **Complete 2026-09-20.** Candidates known to
   carry delisted US equities and point-in-time membership: Norgate Data (Platinum tier,
   delisted securities and historical index constituents), Sharadar via Nasdaq Data Link
   (SEP prices plus the Tickers table with delisting dates, SF1 fundamentals with
   `datekey` publication dates), EODHD (delisted tickers on the higher plans), Polygon
   (delisted tickers, no membership history). Pricing changes; do not quote numbers in the
   plan, verify on the vendor page the day the owner decides. The session output is a short
   comparison table in this file: coverage start, delisted coverage, membership history,
   fundamentals publication dates, export format, licence terms for a private research box.
2. **Purchase and ingest (owner buys; one session).** New tables under a `pit_` prefix,
   append-only, never joined into `prices`. Loader is one module under `engine/` with a
   frozen availability rule (a row is usable on its publication date plus the vendor's stated
   lag, never earlier).
3. **Audit (one session).** For the overlapping period: match rate on tickers, close-price
   agreement within 10 bp on a random 500-name sample, split and dividend agreement, count of
   names present in the vendor set and absent from `prices` per year (this is the
   survivorship gap, and its shape should match the World Bank comparison already in the
   walk-forward README). Publish `docs/pit-data-audit-<date>.md` with the numbers.
4. **Readiness gate recompute.** Extend `GET /research/readiness` to report a second
   stock-selection family sourced from `pit_` tables, with its own qualifying-date count.
   The existing family and its counts stay untouched.

## Not in scope

- Any strategy work, charter, sweep, or replay against the new data. That is a separate
  charter under the backlog's evidence rules and needs its own pre-registration.
- Rewriting `prices`, the fill model, or any frozen forward record to use the new source.
- Building a generic "data provider abstraction". One loader for one vendor.
- Agent data ledgers, provider-response capture, or discrepancy adjudication for the new
  source. The audit doc is the evidence.

## Done when

- `docs/pit-data-audit-<date>.md` exists with the four audit measures filled in.
- `GET /research/readiness` reports the `pit_` stock-selection family and its counts.
- The backlog's next-admissible-actions table row 5 is marked fired, with the audit doc as
  the evidence, and a new row states what one charter it admits.

## Budget

Three agent sessions plus the owner's purchase. Under 800 lines of new code across loader,
readiness family, and tests. Raises the `engine` ceiling in `../scope-budget.json` by 800;
record the raise in `../feedback.md` when approving this plan.

## Risks

Licence terms may forbid committing derived files; keep `pit_` data out of Git like `store/`.
Vendor coverage may start later than 1996, which shrinks the usable folds; the audit will say
so and the plan still completes. The temptation to "just try one strategy" on the new data
in the same session is the main risk; the admission test forbids it.

<!-- sources: BUILDLOG.md, docs/pit-free-audit-2026-10-01.md, engine/free_sources.py, tests/test_free_sources.py, tools/free_sources.py -->
