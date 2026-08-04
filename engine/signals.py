#!/usr/bin/env python
"""Macro / market-regime signal collector — the feed behind `macro_composite`.

Two modes, one module:

  --mode backfill      full available history for every source (one-time, and
                       safe to repeat: the insert is an anti-join).
  --mode incremental   nightly; only each source's recent window. Seconds for
                       everything except the internal breadth pass.

A §12.7 job-queue citizen (job kind `signals`, non-archive): the queue dispatches
to `run(params, con, meta_path)`; `__main__` here runs it standalone.

WARN-AND-CONTINUE, per source (the actions-fetch rule, applied harder). Every
source runs inside its own try/except: a night without DIX is not a night with
wrong data. The strategy reading this table votes 0 on a series it cannot see and
says so out loud, so a missing source degrades the allocation toward neutral
rather than silently freezing a stale view. Nothing here is ever fatal.

HTTP CLIENT — curl_cffi with impersonate='chrome', NOT requests. This is not
cargo cult: this network filters on TLS fingerprint, and plain `requests`/`curl`
die mid-stream on fredgraph.csv (verified 2026-07-16 environment pass and again
2026-07-31). Every source below was verified live from this box on 2026-07-31.

POINT-IN-TIME. Rows carry obs_date (what the data is about) and fetch_as_of (when
we first stored it) — see lib/db.init_signals_schema, decision D-MS1. The live
gate is fetch_as_of; LAG_DAYS below records each series' real-world publication
delay so a future backtest can shift a series by its release lag instead.

DECISION D-MS2 — `--pit-lag` (backfill only, OFF by default, scratch copies only).
A plain backfill stamps every historical row with today's date, which is the
truth: we first stored it today. That truth also makes every backfilled row
invisible to any as-of BEFORE today, so a historical replay of the strategy sees
nothing. `--pit-lag` instead stamps fetch_as_of = obs_date + LAG_DAYS[series] —
a labelled RECONSTRUCTION of when the value would have been publicly available.
It is not a claim about our own store and must never be used on the live DB; the
nightly path cannot reach it (the queue params ignore it unless explicitly set,
and every run prints loudly which stamping it used).

Sources (verified 2026-07-31 from this box):
  dix, gex                 SqueezeMetrics DIX.csv (2011-05 →)
  vix, vix3m               CBOE VIX_History.csv / VIX3M_History.csv (1990 / 2009 →)
  t10y2y, icsa, nfci,      FRED keyless fredgraph.csv
  hy_oas                   ... hy_oas is hard-capped by FRED to a trailing ~3y
                           window regardless of cosd (ICE licensing) — we take
                           what it gives and WARN once, never fabricate the rest.
  pc_total, pc_equity      CBOE, TWO ERAS: the archived era-1 CSVs (2006-11 →
                           2019-10-04) and the era-2 per-day JSON, backfilled
                           from PC_ERA2_BACKFILL_START. GAP 2019-10-05 →
                           2022-12-31: the data EXISTS (era-2 files were spot-
                           checked back to 2019-10-07 and return ratios), the gap
                           is OUR request-budget bound, not CBOE's absence. See
                           PC_ERA2_BACKFILL_START to close it.
  naaim_exposure           NAAIM weekly (Wednesday) exposure index, .xlsx
  aaii_bull, aaii_bear     AAII weekly sentiment survey, legacy .xls (1987 →)
  margin_debt, free_credit FINRA monthly margin statistics .xlsx (1997 →)
  short_interest_dtc       FINRA consolidated short interest, aggregated to one
                           market-wide days-to-cover per settlement date
  cot_es_lev_net           CFTC TFF, E-mini S&P leveraged-money net. CONTEXT
                           ONLY — the strategy never reads it (see the research
                           note: COT positioning is a weak, much-abused signal).
  breadth_pct_200,         INTERNAL, computed from `prices` — no network.
  breadth_nh_nl,           Survivor-bias disclosure: the ticker set is TODAY's
  zweig_ratio              liquid universe_snapshot, so delisted names are absent
                           entirely. Same honest caveat as farm/backtest.
"""
from __future__ import annotations

import io
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from curl_cffi import requests as cr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402
from lib import resources as rsc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_META = REPO_ROOT / "data" / "_meta.json"
STORE_DIR = REPO_ROOT / "store"

HTTP_TIMEOUT = 120         # seconds; the FRED/AAII files are big and slow
HOST_SLEEP = 0.3           # politeness pause between requests to the SAME host
RETRY_SLEEP = 10           # one backoff before giving up on a request

# Real-world publication delay per series, in CALENDAR days. Not used by the live
# strategy (which gates on fetch_as_of); it exists so a future backtest can shift
# each series by its actual release lag, and it is what `--pit-lag` reconstructs.
LAG_DAYS: dict[str, int] = {
    "dix": 0, "gex": 0,
    "vix": 0, "vix3m": 0,
    "t10y2y": 1,
    "icsa": 5,
    "nfci": 5,
    "hy_oas": 1,
    "pc_total": 1, "pc_equity": 1,
    "naaim_exposure": 1,
    "aaii_bull": 1, "aaii_bear": 1,
    "margin_debt": 21, "free_credit": 21,
    "short_interest_dtc": 10,
    "cot_es_lev_net": 3,
    "breadth_pct_200": 0, "breadth_nh_nl": 0, "zweig_ratio": 0,
}

# Era-2 put/call backfill bound: one GET per weekday, so ~935 polite requests
# from 2023-01-01. Declared here and logged at run time rather than silently
# capped, per the no-silent-caps rule. NOT a data boundary — era-2 files were
# spot-checked live on 2026-07-31 back to 2019-10-07 and all returned ratios, so
# moving this to date(2019, 10, 7) closes the era-1/era-2 gap entirely at the
# cost of ~830 more requests (~12 min). Left at 2023 because that is the window
# the strategy's put/call reads (252 obs) actually need.
PC_ERA2_BACKFILL_START = date(2023, 1, 1)
SI_BACKFILL_YEARS = 3           # FINRA consolidated short interest
BREADTH_BACKFILL_START = date(2012, 1, 1)
BREADTH_MIN_NAMES = 1000        # a session with fewer eligible names is skipped
BREADTH_WARMUP_SESSIONS = 260   # >= 252 so the 52wk windows are exact


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
_last_hit: dict[str, float] = {}


def _pace(url: str) -> None:
    """Sleep so consecutive requests to the same host are >= HOST_SLEEP apart."""
    host = url.split("/")[2] if "://" in url else url
    prev = _last_hit.get(host)
    now = time.monotonic()
    if prev is not None and now - prev < HOST_SLEEP:
        time.sleep(HOST_SLEEP - (now - prev))
    _last_hit[host] = time.monotonic()


def _request(method: str, url: str, *, absent_codes: tuple = (), **kw):
    """One paced curl_cffi request with a single backoff retry.

    Returns the response, or None when the server answered with one of
    `absent_codes` — for CBOE's per-day file a market holiday answers 404 and a
    not-yet-published session answers 403, and both are an ABSENCE of data, not a
    failure. The caller counts absences and prints the with-data/without split,
    so a genuine block (every day absent) is still visible rather than silent.
    Anything else raises, and the caller's per-source except turns it into a WARN.
    """
    kw.setdefault("timeout", HTTP_TIMEOUT)
    kw.setdefault("impersonate", "chrome")
    for attempt in (1, 2):
        _pace(url)
        try:
            r = cr.request(method, url, **kw)
        except Exception:  # noqa: BLE001 - network flake; retry once then raise
            if attempt == 2:
                raise
            time.sleep(RETRY_SLEEP)
            continue
        if r.status_code in absent_codes:
            return None
        if r.status_code == 200:
            return r
        if attempt == 2:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        time.sleep(RETRY_SLEEP)
    raise RuntimeError(f"unreachable: {url}")


def _get(url: str, **kw):
    return _request("GET", url, **kw)


# Spreadsheet magic bytes: legacy BIFF .xls (OLE2) and .xlsx (a zip).
XLS_MAGIC = b"\xd0\xcf\x11\xe0"
XLSX_MAGIC = b"PK\x03\x04"


def _expect_spreadsheet(body: bytes, magic: bytes, what: str) -> bytes:
    """Fail with a USEFUL message when a spreadsheet URL serves something else.

    Observed live 2026-07-31: aaii.com intermittently answers the .xls URL with
    an HTML interstitial and HTTP 200. Handed straight to xlrd that surfaces as
    "Expected BOF record; found b'<!DOCTYP'", which reads like data corruption
    and sends the next reader hunting for a parser bug. It is a blocked fetch,
    and the WARN should say so.
    """
    if body[:len(magic)] != magic:
        head = body[:40]
        kind = ("an HTML page (bot challenge / interstitial)"
                if head.lstrip()[:1] == b"<" else f"unexpected bytes {head!r}")
        raise RuntimeError(f"{what}: server returned {kind}, not a spreadsheet "
                           f"({len(body)} bytes) — treating as a blocked fetch")
    return body


def _num(x) -> float | None:
    """Parse a CSV/JSON cell to a float, or None. '.' is FRED's missing marker."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    s = str(x).strip().replace(",", "")
    if s in ("", ".", "n/a", "N/A", "-", "null", "None"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _month_end(y: int, m: int) -> date:
    return date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)


# --------------------------------------------------------------------------- #
# sources — each returns list[(series, obs_date, value)] and may print WARN lines
# --------------------------------------------------------------------------- #
def src_squeezemetrics(con, mode: str) -> list[tuple]:
    """DIX (dark-pool index) + GEX (gamma exposure). One CSV, full history, both
    modes — it is 220 KB and the anti-join makes a re-read free."""
    r = _get("https://squeezemetrics.com/monitor/static/DIX.csv")
    out = []
    lines = r.text.splitlines()
    hdr = [h.strip().lower() for h in lines[0].split(",")]
    ix = {h: i for i, h in enumerate(hdr)}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < len(hdr):
            continue
        try:
            d = date.fromisoformat(parts[ix["date"]].strip())
        except ValueError:
            continue
        for series, col in (("dix", "dix"), ("gex", "gex")):
            v = _num(parts[ix[col]]) if col in ix else None
            if v is not None:
                out.append((series, d, v))
    return out


def _cboe_index_csv(url: str, series: str) -> list[tuple]:
    r = _get(url)
    out = []
    lines = r.text.splitlines()
    hdr = [h.strip().upper() for h in lines[0].split(",")]
    if "CLOSE" not in hdr:
        raise RuntimeError(f"{series}: no CLOSE column in {hdr}")
    di, ci = hdr.index("DATE"), hdr.index("CLOSE")
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= ci:
            continue
        try:
            d = datetime.strptime(parts[di].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        v = _num(parts[ci])
        if v is not None:
            out.append((series, d, v))
    return out


def src_vix(con, mode: str) -> list[tuple]:
    """VIX + VIX3M daily closes. The term-structure ratio is the vol block."""
    base = "https://cdn.cboe.com/api/global/us_indices/daily_prices/"
    return (_cboe_index_csv(base + "VIX_History.csv", "vix")
            + _cboe_index_csv(base + "VIX3M_History.csv", "vix3m"))


FRED_IDS = [("T10Y2Y", "t10y2y"), ("ICSA", "icsa"),
            ("NFCI", "nfci"), ("BAMLH0A0HYM2", "hy_oas")]


def src_fred(con, mode: str) -> list[tuple]:
    """Keyless fredgraph.csv. Backfill asks for everything (cosd=1900-01-01);
    incremental asks for a trailing 60 days, which comfortably covers ICSA/NFCI
    weekly revisions arriving as new obs_dates."""
    cosd = ("1900-01-01" if mode == "backfill"
            else (datetime.now(timezone.utc).date() - timedelta(days=60)).isoformat())
    out = []
    for fred_id, series in FRED_IDS:
        url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?"
               f"id={fred_id}&cosd={cosd}")
        try:
            r = _get(url)
        except Exception as exc:  # noqa: BLE001 - one FRED id must not sink the rest
            print(f"[signals] WARN fred/{series}: {type(exc).__name__}: {exc}")
            continue
        rows = []
        for line in r.text.splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                d = date.fromisoformat(parts[0].strip())
            except ValueError:
                continue
            v = _num(parts[1])          # '.' (missing) is skipped, never zero-filled
            if v is not None:
                rows.append((series, d, v))
        if series == "hy_oas" and rows and mode == "backfill":
            span_years = (rows[-1][1] - rows[0][1]).days / 365.25
            if span_years < 10:
                print(f"[signals] WARN hy_oas: FRED served only "
                      f"{rows[0][1]} → {rows[-1][1]} ({span_years:.1f}y) despite "
                      f"cosd={cosd} — BAMLH0A0HYM2 is hard-capped to a trailing "
                      f"window by ICE licensing. Taking what it gives; the credit "
                      f"block falls back to the internal HYG/LQD proxy when the "
                      f"126-session window is short.")
        out.extend(rows)
    return out


def _pc_era1() -> list[tuple]:
    """The archived CBOE ratio CSVs, 2006-11-01 → 2019-10-04. Four lines of
    disclaimer/product junk sit above the real header, so find the DATE row."""
    out = []
    for url, series in (
        ("https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/"
         "totalpc.csv", "pc_total"),
        ("https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/"
         "equitypc.csv", "pc_equity"),
    ):
        r = _get(url)
        lines = r.text.splitlines()
        start = None
        for i, line in enumerate(lines[:20]):
            if line.split(",")[0].strip().upper() == "DATE":
                start = i + 1
                break
        if start is None:
            raise RuntimeError(f"{series}: no DATE header row in era-1 CSV")
        for line in lines[start:]:
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                d = datetime.strptime(parts[0].strip(), "%m/%d/%Y").date()
            except ValueError:
                continue
            v = _num(parts[4])
            if v is not None:
                out.append((series, d, v))
    return out


_PC_ERA2_NAMES = {"TOTAL PUT/CALL RATIO": "pc_total",
                  "EQUITY PUT/CALL RATIO": "pc_equity"}


def _pc_era2_day(d: date) -> list[tuple]:
    url = ("https://cdn.cboe.com/data/us/options/market_statistics/daily/"
           f"{d.isoformat()}_daily_options")
    r = _get(url, absent_codes=(403, 404))
    if r is None:
        return []           # holiday (404) or not yet published (403) — an absence
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001 - a truncated body is not data
        return []
    out = []
    for item in payload.get("ratios", []):
        series = _PC_ERA2_NAMES.get(str(item.get("name", "")).strip().upper())
        v = _num(item.get("value"))
        if series and v is not None:
            out.append((series, d, v))
    return out


def src_putcall(con, mode: str) -> list[tuple]:
    """CBOE put/call ratios across the two publication eras.

    backfill    = era-1 archive (2006-11 → 2019-10-04) + era-2 daily JSON from
                  PC_ERA2_BACKFILL_START. The 2019-10-05 → 2022-12-31 gap is
                  CBOE's, not ours, and is left as a hole rather than filled.
    incremental = the last 10 sessions of era-2 only.
    """
    out: list[tuple] = []
    today = datetime.now(timezone.utc).date()
    if mode == "backfill":
        out.extend(_pc_era1())
        days = [PC_ERA2_BACKFILL_START + timedelta(days=i)
                for i in range((today - PC_ERA2_BACKFILL_START).days + 1)]
        days = [d for d in days if d.weekday() < 5]
        print(f"[signals] pc: era-2 backfill bound = {len(days)} weekday requests "
              f"({PC_ERA2_BACKFILL_START} → {today}) at {HOST_SLEEP}s pacing "
              f"≈ {len(days) * (HOST_SLEEP + 0.15) / 60:.0f} min")
    else:
        days = [today - timedelta(days=i) for i in range(14)]
        days = sorted(d for d in days if d.weekday() < 5)[-10:]

    got = miss = 0
    for i, d in enumerate(days, 1):
        try:
            rows = _pc_era2_day(d)
        except Exception as exc:  # noqa: BLE001 - one day must not sink the source
            print(f"[signals] WARN pc {d}: {type(exc).__name__}: {exc}")
            miss += 1
            continue
        if rows:
            got += 1
            out.extend(rows)
        else:
            miss += 1
        if mode == "backfill" and i % 100 == 0:
            print(f"[signals] pc era-2 {i}/{len(days)} days "
                  f"(with_data={got} empty_or_holiday={miss})", flush=True)
    print(f"[signals] pc era-2: {got} days with data, {miss} without "
          f"(holidays/404s), {len(days)} requested")
    return out


def src_naaim(con, mode: str) -> list[tuple]:
    """NAAIM Exposure Index — weekly (Wednesday) mean manager equity exposure.

    The .xlsx is re-dated every week, so the filename is scraped from the page
    rather than guessed. Both modes take the whole file (one request, ~85 KB).

    The sheet carries two duplicated legacy rows at the very start of the series
    (2006-07-05 and 2006-07-12 each appear twice, once rounded). The insert's
    in-batch dedup keeps the first occurrence, which is why a fetch of 1,049 rows
    stores 1,047 — expected, not a parse bug.
    """
    r = _get("https://naaim.org/programs/naaim-exposure-index/")
    hrefs = re.findall(r'href=["\']([^"\']+\.xlsx?)["\']', r.text, flags=re.I)
    if not hrefs:
        raise RuntimeError("naaim: no .xlsx link found on the programme page")
    if len(hrefs) > 1:
        print(f"[signals] WARN naaim: {len(hrefs)} spreadsheet links on the page, "
              f"using the first ({hrefs[0]})")
    rr = _get(hrefs[0])
    body = _expect_spreadsheet(rr.content, XLSX_MAGIC, "naaim")

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out = []
    for row in ws.iter_rows(values_only=True):
        if not row or not isinstance(row[0], datetime):
            continue            # header + any trailing notes
        v = _num(row[1] if len(row) > 1 else None)
        if v is not None:
            out.append(("naaim_exposure", row[0].date(), v))
    wb.close()
    return out


def src_aaii(con, mode: str) -> list[tuple]:
    """AAII weekly sentiment survey (1987 →). Legacy BIFF .xls, needs xlrd.

    The sheet stores fractions (0.36 = 36% bulls) and pads the bottom with
    per-year count rows; we keep only rows whose date cell is a real Excel serial
    and whose bull/bear cells are numeric, and store PERCENT 0-100 so the
    strategy's percentile thresholds read in the units everyone quotes.

    INTERMITTENT BLOCK (observed 2026-07-31): aaii.com sits behind Imperva and
    starts answering this URL with a "Pardon Our Interruption" HTML page (HTTP
    200) after a handful of pulls in a short window. Nothing to defeat here and
    nothing to fix: the nightly asks once a day, _expect_spreadsheet turns the
    interstitial into a clear WARN, and because the file carries the WHOLE
    history back to 1987 a missed night is fully recovered by the next
    successful one — the anti-join simply fills the gap.
    """
    r = _get("https://www.aaii.com/files/surveys/sentiment.xls")
    body = _expect_spreadsheet(r.content, XLS_MAGIC, "aaii")
    import xlrd
    bk = xlrd.open_workbook(file_contents=body)
    sh = bk.sheet_by_name("SENTIMENT") if "SENTIMENT" in bk.sheet_names() \
        else bk.sheet_by_index(0)

    out = []
    for i in range(sh.nrows):
        vals = sh.row_values(i)
        if len(vals) < 4 or not isinstance(vals[0], float) or vals[0] < 20000:
            continue            # header rows and the "Count '21" footer block
        try:
            y, m, dd = xlrd.xldate_as_tuple(vals[0], bk.datemode)[:3]
            d = date(y, m, dd)
        except Exception:  # noqa: BLE001 - not a date cell
            continue
        for col, series in ((1, "aaii_bull"), (3, "aaii_bear")):
            v = _num(vals[col])
            if v is None or v <= 0:
                continue
            out.append((series, d, v * 100.0 if v <= 1.0 else v))
    return out


def src_finra_margin(con, mode: str) -> list[tuple]:
    """FINRA monthly margin statistics. The 2021-03 path is stable; the file
    behind it is overwritten each month with the full history (1997 →).

    margin_debt = debit balances in customers' securities margin accounts ($M).
    free_credit = free credit balances in cash accounts + in margin accounts ($M)
                  — the two columns summed, which is the "net investor credit"
                  numerator everyone quotes against margin debt.
    obs_date    = the last calendar day of the stat month.

    KNOWN COVERAGE GAP (verified 2026-07-31): FINRA split free credit into the
    two columns only from 2010-02. Rows before that carry a single free-credit
    figure and a NULL in the second column, so `free_credit` starts 2010-02 while
    `margin_debt` runs from 1997-01. We do NOT relabel the older single column as
    the total — it is headed "cash accounts", and quietly redefining a column is
    exactly the kind of invented fact this store forbids. No strategy reads
    free_credit today; if one ever needs pre-2010 net credit, add it as a
    separate, differently-named series.
    """
    r = _get("https://www.finra.org/sites/default/files/2021-03/"
             "margin-statistics.xlsx")
    body = _expect_spreadsheet(r.content, XLSX_MAGIC, "finra_margin")
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out = []
    for row in ws.iter_rows(values_only=True):
        if not row or not isinstance(row[0], str):
            continue
        m = re.fullmatch(r"(\d{4})-(\d{2})", row[0].strip())
        if not m:
            continue            # header line
        d = _month_end(int(m.group(1)), int(m.group(2)))
        debit = _num(row[1] if len(row) > 1 else None)
        fc_cash = _num(row[2] if len(row) > 2 else None)
        fc_marg = _num(row[3] if len(row) > 3 else None)
        if debit is not None:
            out.append(("margin_debt", d, debit))
        if fc_cash is not None and fc_marg is not None:
            out.append(("free_credit", d, fc_cash + fc_marg))
    wb.close()
    return out


SI_URL = ("https://api.finra.org/data/group/otcMarket/name/"
          "consolidatedShortInterest")
SI_PAGE = 5000              # the API's record-max-limit


def _si_range(start: date, end: date) -> dict[date, list[int]]:
    """Paginate one settlementDate range; return {settle_date: [Σshort, Σadv]}."""
    agg: dict[date, list[int]] = {}
    offset = 0
    while True:
        body = {
            "limit": SI_PAGE, "offset": offset,
            "fields": ["settlementDate", "currentShortPositionQuantity",
                       "averageDailyVolumeQuantity"],
            "dateRangeFilters": [{"fieldName": "settlementDate",
                                  "startDate": start.isoformat(),
                                  "endDate": end.isoformat()}],
        }
        r = _request("POST", SI_URL, json=body,
                     headers={"Content-Type": "application/json",
                              "Accept": "application/json"})
        rows = r.json()
        if not isinstance(rows, list):
            raise RuntimeError(f"short interest: unexpected payload {type(rows)}")
        for row in rows:
            try:
                d = date.fromisoformat(str(row["settlementDate"])[:10])
            except (KeyError, ValueError):
                continue
            sq = _num(row.get("currentShortPositionQuantity"))
            av = _num(row.get("averageDailyVolumeQuantity"))
            if sq is None or av is None:
                continue
            slot = agg.setdefault(d, [0.0, 0.0])
            slot[0] += sq
            slot[1] += av
        if len(rows) < SI_PAGE:
            return agg
        offset += SI_PAGE


def src_short_interest(con, mode: str) -> list[tuple]:
    """Market-wide days-to-cover per FINRA settlement date.

    Σ(current short position) / Σ(average daily volume) over every reported
    security — a breadth-weighted DTC rather than a mean of ratios, so thin
    names cannot swing it. Guarded against a zero denominator.

    READ THE DENOMINATOR. This is a ratio of two market-wide sums and the ADV
    sum moves far more than the short sum, so a quiet fortnight can lift DTC
    without a single new short being opened. Measured 2026-07-31 on real data:
    settlement 2026-06-30 Σshort 56.81bn / Σadv 27.35bn = 2.077; settlement
    2026-07-15 Σshort 56.71bn (−0.2%) / Σadv 19.14bn (−30%) = 2.963. Same shorts,
    a summer volume lull, and a +43% "signal". Anything reading this series
    should treat a spike as a volume question first.

    Backfill walks SI_BACKFILL_YEARS one MONTH at a time: the range filter is
    fine with three years, but the offset would climb past 700k and month chunks
    keep each paginated walk short and restartable.
    """
    today = datetime.now(timezone.utc).date()
    if mode == "backfill":
        start = date(today.year - SI_BACKFILL_YEARS, today.month, 1)
        chunks = []
        y, m = start.year, start.month
        while date(y, m, 1) <= today:
            chunks.append((date(y, m, 1), _month_end(y, m)))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        print(f"[signals] short_interest backfill bound = {len(chunks)} month "
              f"chunks ({start} → {today}), ~5 paginated requests each")
    else:
        chunks = [(today - timedelta(days=40), today)]

    agg: dict[date, list[float]] = {}
    for i, (a, b) in enumerate(chunks, 1):
        try:
            for d, (sq, av) in _si_range(a, b).items():
                slot = agg.setdefault(d, [0.0, 0.0])
                slot[0] += sq
                slot[1] += av
        except Exception as exc:  # noqa: BLE001 - one month must not sink the rest
            print(f"[signals] WARN short_interest {a}..{b}: "
                  f"{type(exc).__name__}: {exc}")
        if mode == "backfill" and i % 6 == 0:
            print(f"[signals] short_interest {i}/{len(chunks)} months "
                  f"({len(agg)} settlement dates)", flush=True)

    out = []
    for d, (sq, av) in sorted(agg.items()):
        if av <= 0:
            print(f"[signals] WARN short_interest {d}: zero total ADV — skipped")
            continue
        out.append(("short_interest_dtc", d, sq / av))
    if mode != "backfill" and out:
        out = out[-2:]          # the spec's "last 2 settlement dates"
    return out


def src_cot(con, mode: str) -> list[tuple]:
    """CFTC Traders-in-Financial-Futures, E-mini S&P 500 (code 13874A):
    leveraged-money long minus short. CONTEXT ONLY — macro_composite never reads
    this series (Sanders-Irwin-Merrin 2009 / Kyriacou 2013: COT positioning is a
    poor timing signal and an over-fitted one)."""
    base = ("https://publicreporting.cftc.gov/resource/gpe5-46if.json?"
            "$where=cftc_contract_market_code='13874A'"
            "&$order=report_date_as_yyyy_mm_dd DESC")
    out = []
    if mode == "backfill":
        offset, page = 0, 1000
        while True:
            r = _get(f"{base}&$limit={page}&$offset={offset}")
            rows = r.json()
            for row in rows:
                d = str(row.get("report_date_as_yyyy_mm_dd", ""))[:10]
                lo = _num(row.get("lev_money_positions_long"))
                sh = _num(row.get("lev_money_positions_short"))
                if not d or lo is None or sh is None:
                    continue
                try:
                    out.append(("cot_es_lev_net", date.fromisoformat(d), lo - sh))
                except ValueError:
                    continue
            if len(rows) < page:
                break
            offset += page
    else:
        r = _get(f"{base}&$limit=10")
        for row in r.json():
            d = str(row.get("report_date_as_yyyy_mm_dd", ""))[:10]
            lo = _num(row.get("lev_money_positions_long"))
            sh = _num(row.get("lev_money_positions_short"))
            if not d or lo is None or sh is None:
                continue
            try:
                out.append(("cot_es_lev_net", date.fromisoformat(d), lo - sh))
            except ValueError:
                continue
    return out


# --------------------------------------------------------------------------- #
# internal breadth — no network, one set-based pass (farm/backtest/hist_screen
# style: never loop tickers in Python for the backfill)
# --------------------------------------------------------------------------- #
_BREADTH_SQL = """
WITH b AS (
    SELECT p.ticker, p.date, p.close, p.high, p.low,
           ROW_NUMBER() OVER w                                              AS rn,
           AVG(p.close) OVER (w ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200,
           MAX(p.high)  OVER (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS hi252,
           MIN(p.low)   OVER (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS lo252,
           LAG(p.close) OVER w                                              AS pclose
    FROM prices p
    JOIN _sig_universe u ON u.ticker = p.ticker
    WHERE p.date >= ? AND p.date <= ? AND p.close IS NOT NULL
    WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
)
SELECT date,
       COUNT(*) FILTER (WHERE rn >= 200 AND sma200 IS NOT NULL)         AS n200,
       COUNT(*) FILTER (WHERE rn >= 200 AND close > sma200)             AS above200,
       COUNT(*) FILTER (WHERE rn >= 252)                                AS n252,
       COUNT(*) FILTER (WHERE rn >= 252 AND high >= hi252)              AS nh,
       COUNT(*) FILTER (WHERE rn >= 252 AND low  <= lo252)              AS nl,
       COUNT(*) FILTER (WHERE pclose IS NOT NULL AND close > pclose)    AS adv,
       COUNT(*) FILTER (WHERE pclose IS NOT NULL AND close < pclose)    AS dec
FROM b
GROUP BY date
ORDER BY date
"""


def _session_n_back(con, anchor: date, n: int) -> date:
    rows = con.execute(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
        [anchor, n + 1],
    ).fetchall()
    return rows[-1][0] if rows else anchor


def _breadth_chunk(con, emit_from: date, emit_to: date) -> list[tuple]:
    """Breadth rows for sessions in [emit_from, emit_to]. Reads a
    BREADTH_WARMUP_SESSIONS run-up so the 200d SMA and 52-week extremes are
    exact, and so the 10-session Zweig average has its own history."""
    warm = _session_n_back(con, emit_from, BREADTH_WARMUP_SESSIONS)
    rows = con.execute(_BREADTH_SQL, [warm, emit_to]).fetchall()
    out: list[tuple] = []
    ratios: list[float | None] = []
    for i, (d, n200, above, n252, nh, nl, adv, dec) in enumerate(rows):
        tot = adv + dec
        ratios.append(adv / tot if tot else None)
        if d < emit_from or n200 < BREADTH_MIN_NAMES:
            continue
        out.append(("breadth_pct_200", d, 100.0 * above / n200))
        if n252 >= BREADTH_MIN_NAMES:
            out.append(("breadth_nh_nl", d, 100.0 * (nh - nl) / n252))
        win = ratios[max(0, i - 9):i + 1]
        if len(win) == 10 and all(x is not None for x in win):
            out.append(("zweig_ratio", d, sum(win) / 10.0))
    return out


def src_breadth(con, mode: str) -> list[tuple]:
    """breadth_pct_200 (% of the liquid universe above its own 200d SMA),
    breadth_nh_nl (net new 52-week highs minus lows, per 100 names) and
    zweig_ratio (10-session average of advancers / (advancers + decliners)).

    Universe = the liquid set of the LATEST universe_snapshot. Survivor-biased by
    construction — `prices` only holds names listed today — and that is disclosed
    rather than papered over; it is the same population the backtest farm uses.

    Backfill walks one calendar year at a time (each pass loads ~510 sessions of
    the universe, a couple of million rows) so the memory profile stays flat
    instead of scaling with the 15-year window.
    """
    have = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'universe_snapshot'").fetchone()[0]
    if not have:
        raise RuntimeError("universe_snapshot missing — no breadth universe")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _sig_universe AS "
        "SELECT DISTINCT ticker FROM universe_snapshot "
        "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM universe_snapshot) "
        "AND liquid")
    n_u = con.execute("SELECT COUNT(*) FROM _sig_universe").fetchone()[0]
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if latest is None or n_u == 0:
        raise RuntimeError(f"breadth: prices empty or universe empty (n={n_u})")

    if mode == "backfill":
        print(f"[signals] breadth: {n_u} liquid names, "
              f"{BREADTH_BACKFILL_START} → {latest}, one year per pass")
        out: list[tuple] = []
        for y in range(BREADTH_BACKFILL_START.year, latest.year + 1):
            a = max(BREADTH_BACKFILL_START, date(y, 1, 1))
            b = min(latest, date(y, 12, 31))
            if a > b:
                continue
            t0 = time.time()
            chunk = _breadth_chunk(con, a, b)
            out.extend(chunk)
            print(f"[signals] breadth {y}: {len(chunk):,} rows "
                  f"[{time.time() - t0:.0f}s]", flush=True)
    else:
        out = _breadth_chunk(con, latest, latest)
    con.execute("DROP TABLE IF EXISTS _sig_universe")
    return out


SOURCES: dict[str, callable] = {
    "squeezemetrics": src_squeezemetrics,
    "vix": src_vix,
    "fred": src_fred,
    "putcall": src_putcall,
    "naaim": src_naaim,
    "aaii": src_aaii,
    "finra_margin": src_finra_margin,
    "short_interest": src_short_interest,
    "cot": src_cot,
    "breadth": src_breadth,
}


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def collect(con, params: dict, mode: str) -> dict:
    only = params.get("only")
    if isinstance(only, str):
        only = [s.strip() for s in only.split(",") if s.strip()]
    names = [n for n in SOURCES if (not only or n in only)]

    pit_lag = bool(params.get("pit_lag")) and mode == "backfill"
    today = datetime.now(timezone.utc).date()
    if pit_lag:
        print("[signals] *** --pit-lag: fetch_as_of stamped as "
              "obs_date + LAG_DAYS (a RECONSTRUCTION of public availability, "
              "decision D-MS2). Scratch copies only — never the live store. ***")

        def stamp(series: str, obs: date) -> date:
            return obs + timedelta(days=LAG_DAYS.get(series, 0))
    else:
        stamp = today

    print(f"[signals] mode={mode} sources={len(names)} "
          f"({', '.join(names)}) fetch_as_of={'obs+lag' if pit_lag else today}")

    per_source: dict[str, dict] = {}
    warnings: list[str] = []
    total = 0
    for name in names:
        t0 = time.time()
        try:
            rows = SOURCES[name](con, mode)
        except Exception as exc:  # noqa: BLE001 - warn-and-continue, ALWAYS
            line = f"{name} failed: {type(exc).__name__}: {exc}"
            warnings.append(line)
            print(f"[signals] WARN {line} — continuing with the other sources")
            per_source[name] = {"status": "failed", "error": str(exc)[:300],
                                "rows_fetched": 0, "rows_inserted": 0}
            continue
        try:
            n = db.insert_macro_signals(con, rows, stamp)
        except Exception as exc:  # noqa: BLE001 - a bad batch is not a bad night
            line = f"{name} insert failed: {type(exc).__name__}: {exc}"
            warnings.append(line)
            print(f"[signals] WARN {line}")
            per_source[name] = {"status": "insert_failed", "error": str(exc)[:300],
                                "rows_fetched": len(rows), "rows_inserted": 0}
            continue
        total += n
        series = sorted({r[0] for r in rows})
        if not rows:
            # The source did not raise, but it handed back nothing. Sources that
            # fetch several endpoints (fred, putcall, short_interest) swallow a
            # per-endpoint failure into their own WARN and return what they got,
            # so "0 rows" is the only remaining tell that the source is down.
            # Count it as degraded rather than letting it read as a clean run.
            line = f"{name} returned no rows this run"
            warnings.append(line)
            print(f"[signals] WARN {line}")
        per_source[name] = {"status": "ok" if rows else "empty",
                            "rows_fetched": len(rows),
                            "rows_inserted": n, "series": series,
                            "secs": round(time.time() - t0, 1)}
        print(f"[signals] {name}: fetched {len(rows):,} → inserted {n:,} new "
              f"({', '.join(series) or 'none'}) [{time.time() - t0:.0f}s]")

    table = con.execute(
        "SELECT series, COUNT(*), MIN(obs_date), MAX(obs_date), MAX(fetch_as_of) "
        "FROM macro_signals GROUP BY series ORDER BY series").fetchall()
    print(f"\n[signals] macro_signals now holds {sum(r[1] for r in table):,} rows")
    print(f"{'series':<20} {'rows':>8}  {'first':<12} {'last':<12} last_fetch")
    for s, n, lo, hi, fa in table:
        print(f"{s:<20} {n:>8,}  {str(lo):<12} {str(hi):<12} {fa}")
    if warnings:
        print(f"\n[signals] {len(warnings)} source(s) degraded this run:")
        for w in warnings:
            print(f"[signals]   WARN {w}")

    return {
        "mode": mode,
        "pit_lag": pit_lag,
        "sources": per_source,
        "rows_inserted": total,
        "warnings": warnings,
        "series_totals": {s: n for s, n, _lo, _hi, _fa in table},
    }


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """§12.7 job entry. params: mode ('backfill'|'incremental'), only, pit_lag."""
    params = params or {}
    db.init_signals_schema(con)
    mode = params.get("mode", "incremental")
    acc = collect(con, params, mode)

    store_gb = rsc.dir_size_gb(STORE_DIR)
    acc["last_run"] = datetime.now(timezone.utc).isoformat()
    acc["store_gb"] = round(store_gb, 2)
    rsc.merge_meta(meta_path, {f"signals_{mode}": acc})
    rsc.update_disk_warning(meta_path, store_gb)
    return acc


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Macro / regime signal collector.")
    ap.add_argument("--mode", default="incremental",
                    choices=["backfill", "incremental"])
    ap.add_argument("--db", default=None, help="DuckDB path (default store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--only", default=None,
                    help=f"comma list of sources ({', '.join(SOURCES)})")
    ap.add_argument("--pit-lag", action="store_true",
                    help="BACKFILL ONLY, SCRATCH COPIES ONLY: stamp fetch_as_of as "
                         "obs_date + LAG_DAYS (a labelled reconstruction of public "
                         "availability, decision D-MS2) instead of today")
    args = ap.parse_args()

    params: dict = {"mode": args.mode, "pit_lag": args.pit_lag}
    if args.only:
        params["only"] = args.only

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)
    run(params, con, meta_path=args.meta)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
