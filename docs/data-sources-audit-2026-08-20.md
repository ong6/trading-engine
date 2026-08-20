# Data Source Robustness Audit — 2026-08-20

Scope: EOD price redundancy, survivorship bias, live ticker coverage / liquidity floor.
No engine code was modified, no writes were made to `store/market.duckdb`, no jobs were
enqueued, and the running parameter sweep (PIDs `queue_runner.py --run-one 209/210`,
started 06:55) was left untouched throughout.

Legend used everywhere below:
- ✅ **VERIFIED** — a probe was run from this box during this session; exact command + result given.
- 📄 **DOCUMENTED, NOT TESTED** — read from the vendor's own docs/pricing page (fetched live
  where possible); no key was obtained or used, per the no-credentials constraint.
- ❓ **GUESSED / INFERRED** — reasoning from the above, not itself observed.

---

## Part 1 — EOD price redundancy

### ✅ VERIFIED — key-free, reachable

| Source | Command | Result |
|---|---|---|
| **stooq.com** | `curl -A "$UA" -m15 "https://stooq.com/q/d/l/?s=spy.us&i=d"` | HTTP 200, 796 bytes, body is `<!DOCTYPE html>...crypto.subtle...` JS proof-of-work page, **not CSV**. Re-confirms BUILDLOG's 2026-07-16/08-18 finding. **STILL BLOCKED.** |
| **stooq.pl** | same, host swapped | HTTP 200, 796 bytes, identical PoW challenge. **BLOCKED**, no alternate stooq host escapes it. |
| **Yahoo chart API** (`query1.finance.yahoo.com/v8/finance/chart/SPY`) | `curl -A "$UA" -m15 ".../chart/SPY?range=5d&interval=1d"` | HTTP 200, genuine JSON: `regularMarketPrice: 769.06`, 5 timestamps + close array `[777.88, 776.34, 772.67...]`. Same for VITL (`regularMarketPrice: 10.87`). **Real data.** But this is the exact endpoint `yfinance` wraps internally — **using it as a "second source" is not independent redundancy**, it just removes the Python library layer. Say so explicitly: it does not fix the single-point-of-failure. |
| **Yahoo v7 CSV download** (`.../v7/finance/download/SPY`) | same pattern | HTTP 401 `{"error":{"code":"unauthorized","description":"User is not logged in"}}`. This legacy endpoint is now crumb/cookie-gated. Dead end. |
| **Nasdaq's own API** (`api.nasdaq.com/api/quote/{T}/historical`) | `curl -A "$UA" -H "accept: application/json" -m15 "https://api.nasdaq.com/api/quote/SPY/historical?assetclass=etf&fromdate=2026-07-01&todate=2026-08-20"` | HTTP 200, 1893 bytes, genuine daily OHLCV, 35 rows, e.g. `{"date":"08/19/2026","close":"769.06","open":"770.36","high":"772.47","low":"768.10","volume":"40,306,020"}`. Same call for VITL (assetclass=stocks) also HTTP 200 with real bars. **This is genuinely independent of yfinance/Yahoo** — different vendor, different pipe. **Best redundancy candidate found.** |
| **CNBC quote API** (`quote.cnbc.com/quote-html-webservice/...`) | `curl -A "$UA" -m15 ".../restQuote/symbolType/symbol?symbols=SPY&requestMethod=quick..."` | HTTP 200, real live quote (`last: 769.06`), but this is a **snapshot quote, not historical OHLCV** — no daily bar history in this API. Tried three guessed historical-chart hosts (`ir.cnbc.com`, `chartapi.cnbc.com`): both **NXDOMAIN** (confirmed via `nslookup`, not a network block — those hosts don't exist). CNBC does not offer a discoverable key-free historical-bars endpoint. Not usable for backfill. |
| **stockanalysis.com internal API** (`stockanalysis.com/api/symbol/s/{T}/history`) | `curl -A "$UA" -m15 ".../api/symbol/s/SPY/history?range=1M&period=Daily"` | HTTP 200, genuine OHLCV JSON, 252 daily rows for `range=1M` (actually returns more — looks like it ignores range for daily), and `range=10Y` returned 246,812 bytes of real daily bars. Same confirmed for VITL. **Independent, key-free, and deep history (10Y tested).** Caveat: this is an **unofficial internal API backing the stockanalysis.com website**, not a documented public API — no SLA, no rate-limit docs, could change or block without notice. Treat as a scrape, not a vendor relationship. |
| **WSJ historical-prices download** | `curl -A "$UA" -m15 ".../SPY/historical-prices/download?..."` | HTTP 401, Cloudflare "enable JS and disable any ad blocker" challenge page. **Blocked.** |
| **MarketWatch download** | same pattern | HTTP 401, same Cloudflare challenge. **Blocked.** |

### ✅ VERIFIED — all require a key (no free no-key path exists)

Every one of these was actually probed live (not assumed) to check whether an unauthenticated
call degrades gracefully to free data or hard-fails:

| Source | Probe result |
|---|---|
| Tiingo | HTTP 403 `{"detail":"Please supply a token"}` |
| Alpha Vantage | HTTP 200 (!) but body is an error: `"the parameter apikey is invalid or missing"` — no anonymous data path |
| Financial Modeling Prep | HTTP 401 `Invalid API KEY` |
| Twelve Data | HTTP 401 `apikey parameter is incorrect or not specified` |
| Finnhub | HTTP 401 `Please use an API key` |
| Polygon | HTTP 401 `API Key was not provided` |
| EODHD | HTTP 401 `Unauthenticated` |
| Alpaca | HTTP 401 (nginx nginx auth-required page) |

**Conclusion: none of the eight offer a no-key path.** Per the constraint, no key was requested
or created for any of them.

### 📄 DOCUMENTED, NOT TESTED — free-tier limits (live-fetched from vendor pricing pages where the page was static; JS-rendered SPAs noted)

| Vendor | Free tier (as published) | How obtained |
|---|---|---|
| Alpha Vantage | **25 requests/day** | Fetched `alphavantage.co/premium/` live, parsed static HTML |
| Financial Modeling Prep | **250 calls/day**, EOD history included | Fetched `site.financialmodelingprep.com/.../pricing` live, parsed static HTML |
| Twelve Data | **8 credits/min, 800/day**, "no daily limits" wording on some tiers is for paid plans | Fetched `twelvedata.com/pricing` live, parsed static content |
| Polygon | **Stocks Basic $0/mo — 5 API calls/minute, 2 years historical data, 100% market coverage** | Fetched `polygon.io/pricing` live, parsed embedded JSON in page |
| Alpaca | Free tier: **200 API calls/min**, 7+ years historical (IEX-fed, 15-min-delayed real-time; EOD daily bars unaffected by the delay), requires a free paper-trading account signup (i.e. a key) | Fetched `alpaca.markets/data` live, parsed static HTML |
| Tiingo | Pricing page is a JS-rendered Angular SPA — curl returned only the empty shell (19,978 bytes of framework boilerplate, no plan data). **Could not extract figures live.** Public knowledge (unverified this session): free tier ~500 requests/hour, 20,000/month, EOD included. | Not independently confirmed this session — flagging the gap rather than presenting stale numbers as fresh |
| Finnhub | Pricing page content is client-rendered by JS; curl returned no plan text. **Could not extract figures live.** Public knowledge (unverified): free tier ~60 calls/min, but the historical-candle (OHLCV) endpoint specifically is gated to paid plans — quote/company-profile endpoints are free, bars are not. | Not independently confirmed this session |
| EODHD | Fetch hit the 15s timeout mid-download (194KB received, page is a heavy JS bundle); no plan figures extracted cleanly. Public knowledge (unverified): free tier ~20 API calls/day, US market only. | Not independently confirmed this session |

### ❓ GUESSED / INFERRED
- The three JS-blocked pricing pages' numeric limits above are carried from general knowledge, not from this session's probes — treat them as directional, not load-bearing for a decision. If a paid source is ever pursued, re-check the current page (or the docs endpoint, not the marketing SPA) before committing.

### Part 1 verdict
The only two genuinely **independent, key-free, reachable** sources for real daily OHLCV found
this session are **Nasdaq's own quote-history API** and the **unofficial stockanalysis.com
internal API**. Yahoo's chart API works but is not independent (yfinance already calls it).
Stooq is confirmed still fully blocked. Every named commercial vendor requires a key; none can
be tested further under this box's no-credentials constraint.

---

## Part 2 — Survivorship bias

### ✅ VERIFIED
- **No historical/dated nasdaqtrader.com symbol-directory archive exists.** Guessed dated URL
  patterns (`/dynamic/symdir/2026/nasdaqtraded0819.txt`, `/dynamic/symdir/nasdaqtraded20260819.txt`)
  both returned **HTTP 302 → `/Trader.aspx?id=http404`** — a real 404, not a network block. The
  site's own `symboldirdefs` help page (`curl -A "$UA" nasdaqtrader.com/Trader.aspx?id=symboldirdefs`,
  HTTP 200) mentions "archive" only in the context of press-release/alert archives
  (`archiveheadlines&cat_id=...`), never a symbol-directory archive. **Nasdaq only ever publishes
  today's file; there is no vendor-side historical snapshot to backfill from.**
- **SEC EDGAR `company_tickers.json` is itself survivorship-biased** — it is a current-issuer
  list, not a historical one. Fetched live (`curl www.sec.gov/files/company_tickers.json`, HTTP
  200, 794,799 bytes, ~10,000+ current tickers). Spot-checked for `SIVB` (Silicon Valley Bank,
  seized/delisted 2023) and `FRC` (First Republic Bank, seized/delisted 2023): **neither appears
  in the file.** Confirms this endpoint cannot supply delisted names.
- **EDGAR's `submissions/CIK{n}.json` API works and retains delisted companies by CIK**, but only
  if you already know which CIK to ask for. Probed `data.sec.gov/submissions/CIK0001132979.json`
  (First Republic Bank): HTTP 200, `name: "FIRST REPUBLIC BANK"`, but `tickers: []` and
  `exchanges: []` — the live ticker/exchange fields go empty on delisting while the filing history
  (visible in `filings.recent`) stays intact. **Useful for confirming/dating one already-known
  name, not for enumerating "who was in the universe on date X".**
- **EDGAR full-text search works and is key-free.** Probed
  `efts.sec.gov/LATEST/search-index?q="delisting"&forms=25-NSE&...2024`: HTTP 200, 216 hits.
  Form 25 / 25-NSE filings are exactly the notification-of-delisting filings, and this endpoint
  can enumerate them — but full-text search only indexes filings from **2001 onward**, and each
  hit still requires resolving the filer to a ticker/date to reconstruct universe membership. It
  is a research tool, not a drop-in point-in-time universe feed.
- **`universe_snapshot` starts 2026-07-16** (read-only DuckDB: `SELECT MIN(snapshot_date),
  MAX(snapshot_date), COUNT(DISTINCT snapshot_date) FROM universe_snapshot` → `2026-07-16 /
  2026-08-19 / 26 distinct dates`, one per nightly run since inception). **A genuine point-in-time
  universe is available going forward from 2026-07-16 with zero new sourcing** — every session
  from here on can reconstruct exactly who was active/liquid on any given date. It cannot reach
  back before that.
- **Live illustration, caught by this audit, not manufactured:** all 8 of today's stale tickers
  (`AVNS, CCRN, EA, NSA, ORLA, SKYT, TMHC, TOI`) are `active=FALSE` in `universe` — they dropped
  out of the nasdaqtraded.txt file within the last few weeks (last price dates 2026-07-21 through
  2026-08-11). **EA (Electronic Arts)** going inactive with a last print on 2026-08-10 is the
  large-cap case: once it leaves the file, it is gone from `prices`-driven backtests entirely.
  This is survivorship bias happening in real time, not a hypothetical.

### 📄 DOCUMENTED, NOT TESTED
- Commercial survivorship-bias-free datasets exist (CRSP, Sharadar/Nasdaq Data Link "SEP" +
  delisted tickers, Norgate) — all paid, none probed since no key work was in scope.

### ❓ GUESSED / INFERRED
- The house's "+7pp/yr" survivorship inflation estimate was not re-derived here (out of scope
  for a robustness audit); nothing found this session changes it, since no free source can
  backfill pre-2026-07-16 delistings.

### Part 2 verdict
**No free source fixes the history.** Nasdaq publishes no dated archive, and EDGAR's ticker
file is current-only — its useful primitives (submissions-by-CIK, full-text search) require
already knowing what you're looking for, which is precisely what a point-in-time universe
would need to *avoid* requiring. The only real fix is what's already running: `universe_snapshot`,
appending since 2026-07-16. **Every day forward from here is bias-free for free; every day
before it is not fixable without a paid dataset.**

---

## Part 3 — Live ticker coverage / liquidity floor

### ✅ VERIFIED (read-only DuckDB)
- Floor, from `engine/collect.py` `mode_bootstrap_floor` (lines ~154-170): `last_close >= 3`
  **and** `median(close * volume) over the ~90d bootstrap window >= 5,000,000`. Set **once**, at
  the 2026-07-16 bootstrap, and **never recomputed since** — `universe.liquid` is a frozen flag,
  not a nightly-maintained one (confirmed: `mode_incremental` in `collect.py` only reads
  `WHERE liquid = TRUE`, it never rewrites the column).
- Recomputing the same rule live, over the current 90-day window
  (`SELECT ticker, arg_max(close,date), median(close*volume) FROM prices WHERE date >= max(date)-90d GROUP BY ticker`,
  joined to `active=TRUE`): **4,076** names clear the floor today vs. the frozen **4,118** in
  `universe.liquid` / `_meta.json` — a small drift (42 names), consistent with five weeks of
  natural volume/price movement since bootstrap, not a bug, but confirms the flag is stale.
- Distribution of median-dollar-volume for `active=TRUE`, `last_close>=3` names (11,984 total),
  bucketed around the $5M floor:

  | bucket | count |
  |---|---|
  | <$1M | 4,658 |
  | $1–2M | 733 |
  | $2–3M | 433 |
  | $3–4M | 299 |
  | $4–5M | 256 |
  | **$5–6M** (floor) | 183 |
  | $6–7M | 149 |
  | $7–8M | 141 |
  | $8–10M | 232 |
  | $10–15M | 374 |
  | $15–20M | 270 |
  | $20–50M | 887 |
  | $50M+ | 1,840 |

  There is **no cliff at the floor** — the mass just below ($4-5M: 256 names) is comparable to
  the mass just above ($5-6M: 183 names), so the $5M cutoff is not obviously miscalibrated
  against a natural break in the data. It is a smooth continuum, and the floor sits inside it.
- Names gained by lowering the floor (same live recompute, price filter unchanged):

  | floor | liquid_count | vs $5M floor |
  |---|---|---|
  | $5,000,000 (current) | 4,076 | — |
  | $2,000,000 | 5,064 | **+988 (+24%)** |
  | $1,000,000 | 5,797 | **+1,721 (+42%)** |
  | $500,000 | 6,599 | **+2,523 (+62%)** |

### Part 3 verdict
The floor is throwing away real names, and the count is large in relative terms (+24% at $2M,
+42% at $1M), but the distribution shows this is smooth dilution into small/illiquid names, not
recovery of a mispriced cliff — the $5M floor is defensible for a book that needs to actually
fill orders, not evidence of an error. **Two separate findings, ranked:**
1. **The bigger issue is not the floor's level, it's that it's frozen.** `universe.liquid` hasn't
   been recomputed since 2026-07-16 bootstrap; five weeks of price/volume drift already shows a
   42-name gap versus a live recompute. This will only widen. Recommend adding a periodic
   (monthly) liquidity-floor recompute pass, reusing the exact SQL already in
   `mode_bootstrap_floor`, rather than only setting it once at inception.
2. **If more names are wanted deliberately** (e.g. a small-cap-specific strategy), $2M is the
   lowest floor that doesn't roughly double the universe — it buys +988 names (+24%) for one
   order of magnitude less liquidity per name than the current floor. Going to $1M or below adds
   proportionally more illiquid names than tradable ones (+42–62% growth, disproportionately in
   the <$1M-per-day bucket, 4,658 names already excluded at any floor tested).

---

## Ranked recommendations (bias/robustness removed ÷ effort)

1. **Add Nasdaq's `api.nasdaq.com/api/quote/{T}/historical` as a second EOD source.**
   Verified live, key-free, genuinely independent of yfinance. Highest value: closes the
   single-point-of-failure BUILDLOG has flagged since 2026-07-16, for the cost of one new
   collector function with the same WARN-and-continue posture `signals.py` already uses.
2. **Recompute the liquidity floor periodically, not once at bootstrap.** Verified the flag is
   already 42 names stale after five weeks; the fix is re-running SQL that already exists, on a
   schedule, no new source required.
3. **Do nothing further about pre-2026-07-16 survivorship bias — no free source reaches it.**
   Verified Nasdaq has no dated archive and EDGAR's ticker file is current-only. Stop re-probing
   this; the only lever is `universe_snapshot`, already running, already the answer for every day
   forward from 2026-07-16.
4. **Treat stockanalysis.com's internal API as a tertiary cross-check only, not production
   redundancy** — verified real and deep (10Y), but it is an unofficial internal API with no
   published contract; wire it as a spot-check/diff tool against yfinance and Nasdaq, not a
   third collector the nightly depends on.
5. **If budget ever opens up, Polygon's free tier (5 calls/min, 2yr history, confirmed live) is
   the cheapest paid-adjacent option to evaluate first** — but it still requires a key, which is
   out of scope for this box today.

---

## Addendum (main loop, 2026-08-20) — the cross-check the audit did not run

The audit established that `api.nasdaq.com` *returns* data. The question that decides
whether it is worth wiring in is whether it **AGREES** with the store, and that was
measured separately:

```
curl -A "<browser UA>" "https://api.nasdaq.com/api/quote/SPY/historical?assetclass=etf&fromdate=2026-08-14&todate=2026-08-19"
duckdb read_only: SELECT ticker,date,open,high,low,close,volume FROM prices
                  WHERE ticker IN ('VITL','SPY') AND date BETWEEN '2026-08-13' AND '2026-08-19'
```

| field | Nasdaq | store (yfinance) | verdict |
|---|---|---|---|
| SPY 2026-08-19 O/H/L/C | 770.36 / 772.47 / 768.10 / 769.06 | 770.359985 / 772.469971 / 768.109985 / 769.059998 | **identical to the cent** |
| VITL 2026-08-19 O/H/L/C | 10.86 / 11.1212 / 10.612 / 10.87 | 10.86 / 11.1212 / 10.612 / 10.87 | **identical to the cent** |
| SPY 2026-08-19 volume | 40,306,020 | 39,805,642 | **differs 1.3%** |
| VITL 2026-08-19 volume | 879,616 | 833,567 | **differs 5.5%** |

**Prices agree exactly; volumes do not.**

> **CORRECTION (verifier build, same day).** The "consolidated versus composite tape"
> reading below is **WRONG**. Measured over five sessions: settled sessions match **to the
> share** (NVDA 2026-08-18: 103,128,200 on both sides; median difference 0.0%), and only the
> newest session differs. It is a **settlement lag** — yfinance captures same-day O/H/L and
> volume before the tape settles, then restates. The shipping rule that follows is therefore
> stronger than the one below: on a SETTLED session all four price fields AND volume count;
> on `as_of` only the CLOSE counts, because that is what the league marks books against.

The original (superseded) reasoning: **the liquidity floor is a dollar-VOLUME test**, so the two sources
would disagree about which names are liquid at the margin. Any cross-check must compare
CLOSES and treat a volume difference as expected, not as a discrepancy — a verifier that
alarms on volume would cry wolf every night and be ignored within a week.

**Asset class is a required parameter and is not guessable from the symbol:** SPY with
`assetclass=stocks` returns `{"rCode":400,"errorMessage":"Symbol not exists."}`. The
universe already carries the ETF flag (`engine/universe.py` keeps 5,549 ETFs), so the
information exists — but a collector that ignores it silently loses every ETF, which is
~45% of the universe and includes SPY, the regime signal for the whole league.
