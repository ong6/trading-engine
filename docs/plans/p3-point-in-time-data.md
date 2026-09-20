---
plan: P3
title: Survivorship-free point-in-time data
status: approved
opened: 2026-09-18
owner_decision: set a spend ceiling and confirm purchase
---

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
