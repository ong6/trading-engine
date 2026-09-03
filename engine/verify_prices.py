#!/usr/bin/env python
"""Nightly EOD price cross-validator — a VERIFIER, not a failover.

The store has ONE price source (yfinance); stooq has been blocked since
2026-07-16. The obvious reaction is "add a failover", but the collector is
incremental and resumable, so a one-day yfinance outage costs almost nothing.
The expensive failure is yfinance being silently WRONG — a bad split
adjustment, a stale bar, a restated close — with nobody noticing. The repo
already carries a whole corporate-actions reconciler because of exactly that
class of problem. So this stage samples names each night, compares them against
an INDEPENDENT source, and reports disagreements honestly.

Source: Nasdaq's own quote-history API
    https://api.nasdaq.com/api/quote/{TICKER}/historical?assetclass={CLASS}&fromdate=&todate=
Verified live from this box (docs/data-sources-audit-2026-08-20.md + its
addendum, and re-verified on the day this file was written). Key-free, browser
UA required, genuinely independent of yfinance/Yahoo.

`assetclass` is REQUIRED and is NOT guessable from the symbol — `SPY` with
`assetclass=stocks` returns {"rCode":400,"errorMessage":"Symbol not exists."}.
The `universe` table carries the `etf` boolean, so the information exists; a
caller that ignores it silently loses ~45% of the universe including SPY, the
regime signal for the whole league. A name whose asset class we cannot look up
is `not_checked`, never guessed at.

WHAT IS COMPARED, AND WHAT IS DELIBERATELY NOT
    Two exemptions, both measured rather than assumed, and both for the same
    reason: a verifier that fires on an expected difference cries wolf nightly
    and is ignored within a week, which is the same as not having one.

    1. VOLUME IS NEVER A DISAGREEMENT. Measured 2026-08-20 over 875 bars: on
       SETTLED sessions the two sources agree to the share; on the newest
       session they differ by ~1-5% (SPY 1.2%, VITL 5.2%). Our stored same-day
       volume is captured before the tape settles.
    2. THE NEWEST SESSION'S OPEN/HIGH/LOW IS NEVER A DISAGREEMENT — but its
       CLOSE IS CHECKED. First real run, 177 names: 46 names disagreed, and
       every one of those 50 disagreements was on `as_of`, on open/high/low
       only. Re-probing the worst 18 over their settled sessions: worst gap
       3.1bp, and CLOSE never disagreed on any session anywhere. Same-day
       O/H/L are provisional in the store and get restated. The close is the
       number the league marks its books against tonight, so it is verified on
       every name, every session, with no exemption.

    Everything else — O/H/L/C on every settled session, close on all of them —
    is compared at the pre-registered tolerance below.

HARD RULES
  * This module NEVER writes a price row. It opens the store read-only and its
    only write anywhere is the `price_verify` key in data/_meta.json (merged,
    never clobbered). If the two sources disagree the honest output is a flagged
    disagreement, not a silent correction — we do not know which one is right.
  * It NEVER invents a number. A name the source does not return, cannot be
    parsed, or that shares no session with the store is `not_checked` with a
    reason. It is never counted as agreeing. (BUILDLOG 2026-08-20: in this
    codebase the dangerous outcome is not a crash, it is quietly reporting a
    number for a non-measurement.)
  * It is NON-CRITICAL and ALWAYS EXITS 0 — same posture as
    the retired news_analyst.sh (archive/agentic-2026-08/). A network failure,
    a source schema change or a locked store logs a breadcrumb and leaves the
    nightly untouched.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.settings import DEFAULT_DB, REPO_ROOT  # noqa: F401
from engine.lib.settings import META_PATH as DEFAULT_META
from engine.lib.log import get_logger

log = get_logger("verify")
META_KEY = "price_verify"

API_URL = "https://api.nasdaq.com/api/quote/{sym}/historical"
SOURCE_LABEL = "api.nasdaq.com/api/quote/{ticker}/historical"
# A plain requests/curl default UA is refused by this endpoint; a browser UA is
# not a disguise here, it is the documented cost of entry (verified 2026-08-20).
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "accept": "application/json"}

PER_NAME_SLEEP = 0.4     # matches engine/earnings.py — do not hammer a free endpoint
RETRY_SLEEP = 3.0        # one short backoff, then the name is recorded as a gap
HTTP_TIMEOUT = 20.0

# --------------------------------------------------------------------------- #
# Pre-registered tolerance (decided BEFORE the first run, per house discipline)
# --------------------------------------------------------------------------- #
# A bar disagrees when BOTH of these are exceeded on any of open/high/low/close:
TOLERANCE_BP = 10.0        # 10 basis points = 0.10% relative
TOLERANCE_ABS_USD = 0.01   # ...and at least one cent absolute
#
# Why 10bp:
#   * Nasdaq publishes at most 4 decimal places (observed: 776.775, 775.4301,
#     11.1212); the store holds float64 straight off yfinance. Worst-case pure
#     ROUNDING error is 0.00005 absolute, which on the $3 price floor of the
#     liquid universe is 1.7bp. 10bp clears that with ~6x headroom, so a 4th
#     decimal difference can never register as a disagreement.
#   * Every defect class this is built to catch is one to three ORDERS OF
#     MAGNITUDE larger: a missed 2:1 split is 5000bp, a 10:1 is 9000bp, a stale
#     (previous-session) bar on a liquid name is typically 50-200bp, a restated
#     close is usually >>10bp. There is no real defect that hides under 10bp and
#     no rounding artefact that pokes above it — the gap between the two is why
#     a single flat threshold works.
#   * The 1-cent absolute floor stops a low-priced name generating a flag from
#     the last cent of a tick (1c on a $3 stock is 33bp on its own).
# A second, louder band is reported separately for triage:
MATERIAL_BP = 200.0        # >2% — not a rounding story under any explanation


class SourceError(RuntimeError):
    """Transport, HTTP, or API-level failure from the second source."""


class SymbolNotFound(SourceError):
    """The source does not carry this symbol at all (rCode 400 / code 1001).

    Distinct from a fetch failure and NOT retried: it is the normal answer for a
    delisted or acquired name the store still holds a position in (measured
    2026-08-20: EA and TALK, both held, both gone from the source). Reported as
    its own `not_checked` reason so "the source is down" and "this name no longer
    trades" never get averaged into one number.
    """


# --------------------------------------------------------------------------- #
# The fetch — structured so a FAILOVER collector could reuse it unchanged.
# It returns parsed bars and never touches the store. (Not building the failover
# now: the value here is the cross-check, not the redundancy.)
# --------------------------------------------------------------------------- #
def _num(raw, field: str) -> float | None:
    """Parse a Nasdaq numeric string ('$770.36', '40,306,020', 'N/A', '')."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "")
    if s in ("", "N/A", "--", "n/a"):
        return None
    try:
        return float(s)
    except ValueError as exc:
        raise ValueError(f"{field}={raw!r}: {exc}") from exc


def fetch_nasdaq_history(ticker: str, *, assetclass: str,
                         start: date, end: date,
                         session: requests.Session | None = None,
                         timeout: float = HTTP_TIMEOUT) -> dict:
    """Daily OHLCV for one name from api.nasdaq.com.

    Returns {"symbol": str, "bars": {date: {open/high/low/close/volume}},
             "parse_errors": [str], "rows": int}.
    Raises SourceError on transport/HTTP/API-code failure or an unrecognisable
    envelope — the caller records that as `not_checked`, never as agreement.

    Parsing is defensive but LOUD: a row that will not parse is collected into
    `parse_errors` and reported upward, never silently dropped.

    `assetclass` is a required argument on purpose. There is no default and no
    inference from the symbol: 'etf' for ETFs, 'stocks' for equities.
    """
    if assetclass not in ("etf", "stocks"):
        raise SourceError(f"bad assetclass {assetclass!r} for {ticker}")
    # Class shares: the store's canonical 'BRK.B' is accepted and normalised by
    # the API to 'BRK/B' (verified). The yfinance form 'BRK-B' is NOT.
    url = API_URL.format(sym=urllib.parse.quote(ticker, safe=""))
    params = {"assetclass": assetclass,
              "fromdate": start.isoformat(), "todate": end.isoformat()}
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(url, params=params, headers=HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise SourceError(f"transport: {exc}") from exc
    if resp.status_code != 200:
        raise SourceError(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SourceError(f"non-JSON body ({len(resp.content)} bytes): {exc}") from exc

    status = (payload or {}).get("status") or {}
    rcode = status.get("rCode")
    if rcode != 200:
        msg = status.get("bCodeMessage") or payload.get("message")
        if "not exists" in str(msg).lower():
            raise SymbolNotFound(f"rCode {rcode}: {msg}")
        raise SourceError(f"rCode {rcode}: {msg}")
    data = (payload or {}).get("data") or {}
    table = data.get("tradesTable") or {}
    rows = table.get("rows")
    if rows is None:
        raise SourceError("no data.tradesTable.rows in response (schema change?)")

    bars: dict[date, dict] = {}
    parse_errors: list[str] = []
    for row in rows:
        try:
            d = datetime.strptime(str(row["date"]).strip(), "%m/%d/%Y").date()
        except (KeyError, ValueError) as exc:
            parse_errors.append(f"{ticker}: date {row.get('date')!r}: {exc}")
            continue
        bar: dict = {}
        bad = False
        for field in ("open", "high", "low", "close", "volume"):
            try:
                bar[field] = _num(row.get(field), field)
            except ValueError as exc:
                parse_errors.append(f"{ticker} {d}: {exc}")
                bad = True
        if not bad:
            bars[d] = bar
    return {"symbol": data.get("symbol") or ticker, "bars": bars,
            "parse_errors": parse_errors, "rows": len(rows)}


# --------------------------------------------------------------------------- #
# Name selection
# --------------------------------------------------------------------------- #
CORE_ETFS = ["SPY", "QQQ", "IWM", "BIL"]


def _held_tickers(con) -> list[str]:
    """Names a league book actually holds. A wrong price on a held name is the
    one that costs money, so these are checked every night, never sampled."""
    try:
        rows = con.execute(
            """
            SELECT DISTINCT p.ticker
            FROM sim_positions p
            JOIN portfolios f ON f.id = p.portfolio_id
            WHERE p.qty > 0
            ORDER BY 1
            """
        ).fetchall()
    except duckdb.Error:
        return []
    return [r[0] for r in rows]


def select_names(con, as_of: date, sample_n: int, max_names: int) -> list[tuple[str, str]]:
    """(ticker, why) in check order: core ETFs, then held names, then a
    date-seeded deterministic sample of the liquid universe. Seeding by date
    means the same night re-runs identically (a re-run is a re-measurement, not
    a new lottery) while coverage still rotates across the universe over time.

    `sample_n` names are drawn and then deduped against the mandatory ones, so a
    name that is both held and sampled is checked once and the run is a few
    names short of core + held + sample_n. Counted honestly either way:
    `names_selected` in the output is the deduped list actually contacted."""
    picks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(ticker: str, why: str) -> None:
        if ticker and ticker not in seen:
            seen.add(ticker)
            picks.append((ticker, why))

    for t in CORE_ETFS:
        add(t, "core")
    for t in _held_tickers(con):
        add(t, "held")

    pool = [r[0] for r in con.execute(
        """
        SELECT u.ticker
        FROM universe u
        WHERE u.active AND u.liquid
          AND EXISTS (SELECT 1 FROM prices p
                      WHERE p.ticker = u.ticker AND p.date = ?)
        ORDER BY u.ticker
        """, [as_of]).fetchall()]
    rng = random.Random(f"price-verify::{as_of.isoformat()}")
    for t in rng.sample(pool, k=min(sample_n, len(pool))):
        add(t, "sample")

    return picks[:max_names]


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
FIELDS = ("open", "high", "low", "close")
# The newest stored session is PROVISIONAL. Measured over the first real runs
# (177 names, 875 bars): every single OHLC disagreement sat on `as_of` and on
# open/high/low only — 46 of 175 names, worst 180bp — while every SETTLED
# session agreed to within 3.1bp across the worst 18 of them, and CLOSE never
# disagreed anywhere. yfinance's same-day open/high/low (and volume) are taken
# before the tape settles and are restated afterwards; Nasdaq publishes the
# consolidated figures. So the same discipline the audit demanded for volume
# applies to same-day O/H/L: measure it, report it, never alarm on it. The
# newest session's CLOSE is still checked on every name, because that is the
# number the league marks its books against tonight.
PROVISIONAL_FIELDS = ("open", "high", "low")


def _diff_bp(store_v: float, src_v: float) -> float:
    denom = max(abs(store_v), abs(src_v))
    if denom == 0:
        return 0.0
    return abs(store_v - src_v) / denom * 10_000.0


def compare_bars(ticker: str, store_bars: dict, src_bars: dict,
                 tolerance_bp: float, tolerance_abs: float,
                 as_of: date) -> dict:
    """Compare the overlapping sessions of one name. Returns a per-name verdict.

    Only dates present in BOTH series are compared. On a settled session all of
    O/H/L/C count; on `as_of` only the close counts and O/H/L are measured into
    `prov` (see PROVISIONAL_FIELDS). A date the source has and the store does
    not is counted (`store_missing`) and reported, but it is not a price
    disagreement — the collector is incremental and legitimately lags.
    """
    common = sorted(set(store_bars) & set(src_bars))
    # A source session the store lacks is only meaningful INSIDE the window the
    # store actually covers (or after it — a stale name). The source window is
    # deliberately wider than `sessions` so holidays never shorten the compare;
    # counting those extra older dates as "missing" would be reporting a number
    # for something we never asked the store for.
    floor = min(store_bars) if store_bars else None
    missing = sorted(d.isoformat() for d in set(src_bars) - set(store_bars)
                     if floor is not None and d >= floor)
    out = {
        "ticker": ticker,
        "sessions_compared": len(common),
        "bars_compared": 0,
        "fields_compared": 0,
        "disagreements": [],
        "worst": None,
        "store_missing": missing,
        "volume_diffs_pct": [],
        "prov": [],          # (field, bp) on the provisional session — never alarmed on
    }
    if not common:
        out["status"] = "not_checked"
        out["reason"] = "no_overlapping_sessions"
        return out

    for d in common:
        sb, nb = store_bars[d], src_bars[d]
        out["bars_compared"] += 1
        provisional = d >= as_of
        for field in FIELDS:
            sv, nv = sb.get(field), nb.get(field)
            if sv is None or nv is None:
                continue
            bp = _diff_bp(float(sv), float(nv))
            item = {"ticker": ticker, "date": d.isoformat(), "field": field,
                    "store": round(float(sv), 6), "source": round(float(nv), 6),
                    "diff_bp": round(bp, 2)}
            if provisional and field in PROVISIONAL_FIELDS:
                out["prov"].append((field, bp))
                continue
            out["fields_compared"] += 1
            if out["worst"] is None or bp > out["worst"]["diff_bp"]:
                out["worst"] = item
            if bp > tolerance_bp and abs(float(sv) - float(nv)) >= tolerance_abs:
                out["disagreements"].append(item)
        # Volume is measured, NEVER alarmed on. Tagged by date so the run can
        # separate the newest (still-settling) session from settled history.
        svol, nvol = sb.get("volume"), nb.get("volume")
        if svol and nvol:
            out["volume_diffs_pct"].append(
                (d, abs(float(svol) - float(nvol)) / max(float(svol), float(nvol)) * 100.0))

    if out["fields_compared"] == 0:
        out["status"] = "not_checked"
        out["reason"] = "no_comparable_fields"
    else:
        out["status"] = "disagrees" if out["disagreements"] else "agrees"
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Sample, cross-check, and return the accounting dict written under the
    `price_verify` key of data/_meta.json. `con` must be a READ-ONLY handle."""
    p = dict(params or {})
    sample_n = int(p.get("sample", 40))
    sessions = int(p.get("sessions", 5))
    tol_bp = float(p.get("tolerance_bp", TOLERANCE_BP))
    tol_abs = float(p.get("tolerance_abs", TOLERANCE_ABS_USD))
    max_names = int(p.get("max_names", 250))
    max_secs = float(p.get("max_secs", 900))
    self_test_bp = float(p.get("self_test_bp", 0.0))
    t0 = time.time()

    as_of = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if as_of is None:
        raise RuntimeError("prices table is empty — nothing to verify")
    if isinstance(as_of, datetime):
        as_of = as_of.date()

    explicit = p.get("tickers")
    if explicit:
        if isinstance(explicit, str):
            explicit = [t.strip().upper() for t in explicit.split(",") if t.strip()]
        names = [(t, "explicit") for t in explicit][:max_names]
    else:
        names = select_names(con, as_of, sample_n, max_names)

    # Asset class comes from the universe table — never inferred from the symbol.
    etf_flag = {r[0]: r[1] for r in con.execute(
        "SELECT ticker, etf FROM universe").fetchall()}

    # A window wide enough that `sessions` trading days always fit (holidays,
    # long weekends). Extra sessions are simply not compared.
    start = as_of - timedelta(days=sessions * 2 + 12)
    tickers = [t for t, _ in names]
    store: dict[str, dict] = {t: {} for t in tickers}
    if tickers:
        ph = ",".join("?" * len(tickers))
        for tk, d, o, h, l, c, v in con.execute(
                f"""SELECT ticker, date, open, high, low, close, volume
                    FROM prices WHERE ticker IN ({ph}) AND date BETWEEN ? AND ?""",
                tickers + [start, as_of]).fetchall():
            store[tk][d.date() if isinstance(d, datetime) else d] = {
                "open": o, "high": h, "low": l, "close": c, "volume": v}
    # Keep only the last `sessions` stored sessions per name.
    for tk, bars in store.items():
        for d in sorted(bars)[:-sessions] if len(bars) > sessions else []:
            bars.pop(d)

    results: list[dict] = []
    reasons: dict[str, int] = {}
    parse_errors: list[str] = []
    vol_diffs: list[tuple] = []
    prov_diffs: list[tuple] = []
    sess = requests.Session()

    def not_checked(ticker: str, why: str, reason: str, detail: str = "") -> None:
        reasons[reason] = reasons.get(reason, 0) + 1
        results.append({"ticker": ticker, "why": why, "status": "not_checked",
                        "reason": reason, "detail": detail})

    for i, (ticker, why) in enumerate(names, 1):
        if time.time() - t0 > max_secs:
            not_checked(ticker, why, "time_budget", f"{max_secs:.0f}s budget spent")
            continue
        is_etf = etf_flag.get(ticker)
        if is_etf is None:
            # Not in the universe table -> asset class unknown. Never guess: a
            # guessed assetclass returns "Symbol not exists" and would look like
            # a source outage rather than our own gap.
            not_checked(ticker, why, "unknown_assetclass", "no universe row")
            continue
        assetclass = "etf" if is_etf else "stocks"

        fetched = None
        last_err = ""
        gone = False
        for attempt in (1, 2):
            try:
                fetched = fetch_nasdaq_history(
                    ticker, assetclass=assetclass, start=start, end=as_of, session=sess)
                break
            except SymbolNotFound as exc:   # a settled fact, not a flaky call
                last_err, gone = str(exc), True
                break
            except SourceError as exc:
                last_err = str(exc)
                if attempt == 1:
                    time.sleep(RETRY_SLEEP)
        time.sleep(PER_NAME_SLEEP)
        if fetched is None:
            not_checked(ticker, why,
                        "symbol_not_found" if gone else "fetch_failed", last_err[:200])
            continue
        if fetched["parse_errors"]:
            parse_errors.extend(fetched["parse_errors"][:5])
        # The API normalises class shares ('BRK.B' -> 'BRK/B'); anything else is
        # a symbol we did not ask for and must not be compared as if we had.
        got = str(fetched["symbol"]).replace("/", ".").replace("-", ".").upper()
        if got != ticker.replace("-", ".").upper():
            not_checked(ticker, why, "symbol_mismatch", f"source returned {fetched['symbol']}")
            continue
        if not fetched["bars"]:
            not_checked(ticker, why, "no_source_rows",
                        f"{fetched['rows']} rows, none parseable"
                        if fetched["rows"] else "0 rows returned")
            continue

        store_bars = store.get(ticker) or {}
        if not store_bars:
            not_checked(ticker, why, "no_store_rows", f"no stored bars since {start}")
            continue

        # --- self-test only: corrupt ONE stored close so the detector has
        # something to find. Never runs in the nightly (--self-test refuses to
        # write _meta.json), and it is stamped in the output when it does.
        if self_test_bp and i == 1:
            d0 = max(store_bars)
            store_bars = dict(store_bars)
            b = dict(store_bars[d0])
            b["close"] = float(b["close"]) * (1.0 + self_test_bp / 10_000.0)
            store_bars[d0] = b

        verdict = compare_bars(ticker, store_bars, fetched["bars"], tol_bp, tol_abs, as_of)
        verdict["why"] = why
        vol_diffs.extend(verdict.pop("volume_diffs_pct", []))
        prov_diffs.extend(verdict.pop("prov", []))
        if verdict["status"] == "not_checked":
            reasons[verdict["reason"]] = reasons.get(verdict["reason"], 0) + 1
        results.append(verdict)
        log.info(f"[verify] {i}/{len(names)} {ticker:<6} {why:<7} {verdict['status']}"
              + (f"  worst {verdict['worst']['diff_bp']:.2f}bp"
                 if verdict.get("worst") else ""))

    agreeing = [r for r in results if r["status"] == "agrees"]
    disagreeing = [r for r in results if r["status"] == "disagrees"]
    unchecked = [r for r in results if r["status"] == "not_checked"]
    all_disagreements = [d for r in disagreeing for d in r["disagreements"]]
    all_disagreements.sort(key=lambda d: -d["diff_bp"])
    by_field: dict[str, int] = {}
    by_date: dict[str, int] = {}
    for d in all_disagreements:
        by_field[d["field"]] = by_field.get(d["field"], 0) + 1
        by_date[d["date"]] = by_date.get(d["date"], 0) + 1
    checked = agreeing + disagreeing
    worsts = [r["worst"] for r in checked if r.get("worst")]
    worst_overall = max(worsts, key=lambda w: w["diff_bp"]) if worsts else None
    store_missing = {r["ticker"]: r["store_missing"] for r in checked if r.get("store_missing")}

    accounting = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "source": SOURCE_LABEL,
        "role": "verify-only; this source never writes a price row",
        "sessions_requested": sessions,
        "tolerance_bp": tol_bp,
        "tolerance_abs_usd": tol_abs,
        "material_bp": MATERIAL_BP,
        "fields": list(FIELDS),
        "names_selected": len(names),
        "names_checked": len(checked),
        "names_agreeing": len(agreeing),
        "names_disagreeing": len(disagreeing),
        "names_not_checked": len(unchecked),
        "not_checked_reasons": reasons,
        # Named, not just counted: "2 not_checked" is not an answer anyone can
        # act on, and a HELD name that silently stops being checkable is exactly
        # the thing this stage exists to make visible.
        "not_checked_names": [{"ticker": r["ticker"], "why": r.get("why"),
                               "reason": r["reason"], "detail": r.get("detail", "")[:120]}
                              for r in unchecked][:25],
        "bars_compared": sum(r.get("bars_compared", 0) for r in checked),
        "field_comparisons": sum(r.get("fields_compared", 0) for r in checked),
        # The single worst gap ANYWHERE, disagreement or not — so a clean night
        # still publishes the measured noise floor instead of a bare zero.
        "worst": worst_overall,
        "worst_is_disagreement": bool(worst_overall
                                      and worst_overall["diff_bp"] > tol_bp
                                      and abs(worst_overall["store"] - worst_overall["source"])
                                      >= tol_abs),
        "disagreements": all_disagreements[:20],
        "n_disagreements": len(all_disagreements),
        "disagreements_by_field": by_field,
        "disagreements_by_date": by_date,
        "n_material": sum(1 for d in all_disagreements if d["diff_bp"] > MATERIAL_BP),
        "parse_errors": parse_errors[:20],
        "n_parse_errors": len(parse_errors),
        # Volume: EXPECTED to differ, NEVER counted as a disagreement. Measured
        # here only so a change in the pattern is visible. The pattern, measured
        # over the first real runs: SETTLED sessions match to the share, and only
        # the newest session differs (~1-5%) because our stored same-day volume
        # is captured before the tape settles and the vendor restates it later.
        # (The 2026-08-20 audit saw only the newest session and read the gap as
        # consolidated-vs-composite tape; over five sessions it is plainly a
        # settlement lag, not a tape difference.) Either way it is not a price
        # error, and a verifier that alarmed on it would cry wolf nightly.
        "volume_note": "volume differs by design on the newest session (same-day "
                       "volume settles after the close); measured, never alarmed on",
        "volume_median_abs_diff_pct_latest_session": (
            round(_median([v for d, v in vol_diffs if d == as_of]), 2)
            if any(d == as_of for d, _ in vol_diffs) else None),
        "volume_median_abs_diff_pct_prior_sessions": (
            round(_median([v for d, v in vol_diffs if d != as_of]), 2)
            if any(d != as_of for d, _ in vol_diffs) else None),
        "volume_bars_compared": len(vol_diffs),
        # Same story as volume, and measured the same way: the newest session's
        # open/high/low are provisional in the store and are NOT counted as
        # disagreements. Reported so the exemption stays visible and auditable —
        # if this median ever collapses to ~0, the exemption can be dropped.
        "provisional_note": (f"on {as_of.isoformat()} (newest stored session) "
                             "open/high/low are measured but never flagged; the "
                             "close IS checked on every name"),
        "provisional_ohl_median_bp": (round(_median([bp for _, bp in prov_diffs]), 2)
                                      if prov_diffs else None),
        "provisional_ohl_max_bp": (round(max(bp for _, bp in prov_diffs), 2)
                                   if prov_diffs else None),
        "provisional_ohl_over_tolerance": sum(1 for _, bp in prov_diffs if bp > tol_bp),
        "provisional_comparisons": len(prov_diffs),
        "store_missing_sessions": {k: v for k, v in list(store_missing.items())[:10]},
        "n_names_store_missing_sessions": len(store_missing),
        "secs": round(time.time() - t0, 1),
    }
    if self_test_bp:
        accounting["self_test_bp"] = self_test_bp
        accounting["self_test"] = ("SYNTHETIC: one stored close was corrupted in "
                                   "memory to exercise the detector — not a real run")
    return accounting


def _connect_ro(path: str | Path, tries: int = 6, retry_s: float = 5.0):
    """Read-only handle, retrying while another process holds the writer lock.
    DuckDB is single-writer on disk, so a transient failure here is normal, not
    exceptional — and it is a `not_checked` night, never a failed nightly."""
    # Thin wrapper over the one connection factory (engine.lib.db.connect).
    try:
        return db.connect(path, read_only=True, wait_s=max(1, tries) * retry_s)
    except Exception as exc:
        raise RuntimeError(f"could not open {path} read-only after {tries} attempts: {exc}") from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--sample", type=int, default=40,
                    help="random names sampled from the liquid universe (default 40)")
    ap.add_argument("--sessions", type=int, default=5,
                    help="most recent stored sessions to compare (default 5)")
    ap.add_argument("--tolerance-bp", type=float, default=TOLERANCE_BP)
    ap.add_argument("--tolerance-abs", type=float, default=TOLERANCE_ABS_USD)
    ap.add_argument("--max-names", type=int, default=250,
                    help="hard cap on names contacted in one run")
    ap.add_argument("--max-secs", type=float, default=900,
                    help="wall-clock budget; names past it are not_checked")
    ap.add_argument("--tickers", default=None, help="comma list, overrides sampling")
    ap.add_argument("--self-test", type=float, default=0.0, metavar="BP",
                    help="corrupt the first name's latest stored close by BP "
                         "basis points to prove the detector fires; implies "
                         "--no-meta")
    ap.add_argument("--no-meta", action="store_true", help="print only, write nothing")
    args = ap.parse_args()
    # Redirected to a log, stdout is block-buffered and a multi-minute run looks
    # like a hung one until it finishes (BUILDLOG 2026-08-20: the defect is the
    # silence). run_daily.sh exports PYTHONUNBUFFERED, but a hand-run does not.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    # Everything below is best-effort. This stage is observability, not
    # trading data: it must never fail a nightly. Exit 0 on every path.
    try:
        con = _connect_ro(args.db)
    except Exception as exc:
        log.error(f"TODO: price verify could not open the store read-only ({exc}) — "
              f"skipped this run, nothing written, nightly unaffected")
        return 0
    try:
        acc = run({"sample": args.sample, "sessions": args.sessions,
                   "tolerance_bp": args.tolerance_bp,
                   "tolerance_abs": args.tolerance_abs,
                   "max_names": args.max_names, "max_secs": args.max_secs,
                   "tickers": args.tickers, "self_test_bp": args.self_test},
                  con, meta_path=args.meta)
    except Exception as exc:
        log.error(f"TODO: price verify failed ({type(exc).__name__}: {exc}) — no "
              f"_meta.json update, nightly unaffected")
        return 0
    finally:
        try:
            con.close()
        except Exception:
            pass

    print(json.dumps(acc, indent=2))
    if args.no_meta or args.self_test:
        log.info("[verify] --no-meta/--self-test: _meta.json NOT written")
        return 0
    try:
        rsc.merge_meta(args.meta, {META_KEY: acc})
        log.info(f"[verify] merged '{META_KEY}' into {args.meta}")
    except Exception as exc:
        log.error(f"TODO: price verify could not write _meta.json ({exc}) — result above only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
