"""Weekly Yahoo history re-asks and absence cooldowns in existing job metadata."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pandas as pd
import requests

from engine.lib import db

ABSENCE_RETRY_DAYS = 90
NO_HISTORY = "No data found, symbol may be delisted"


def probe(ticker: str) -> tuple[str, pd.DataFrame | None]:
    """Ask the same chart source for max history, preserving its explicit reason.

    A missing timezone in yfinance is ambiguous. Only Yahoo's actual 404 chart
    answer establishes absence; HTTP failures and unexplained emptiness stay failed.
    """
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}",
            params={"range": "max", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
        )
        chart = response.json()["chart"]
        error = chart.get("error") or {}
        if (response.status_code == 404 and not chart.get("result")
                and error.get("code") == "Not Found"
                and error.get("description") == NO_HISTORY):
            return "no_data", None
        response.raise_for_status()
        result = chart["result"][0]
        values = result["indicators"]["quote"][0]
        # Chart stamps are UTC epochs; daily dates belong to the exchange timezone.
        index = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert(
            result["meta"]["exchangeTimezoneName"]
        ).tz_localize(None).normalize()
        frame = pd.DataFrame({k.title(): v for k, v in values.items()}, index=index)
        return ("data", frame) if not frame.empty else ("empty_response", None)
    except Exception as exc:  # noqa: BLE001 - preserve resumability on any source failure
        return f"fetch_error:{type(exc).__name__}", None


def identities(con, tickers):
    with db.registered_frame(con, "_liquid_history_names", pd.DataFrame({"ticker": tickers})):
        return {
            ticker: [yft, name, str(added)]
            for ticker, yft, name, added in con.execute(
                "SELECT ticker,yf_ticker,name,added FROM universe "
                "JOIN _liquid_history_names USING(ticker)"
            ).fetchall()
        }


def exclude_absences(path, mapping, *, mode="refresh-liquid"):
    """Retry after 90 days, or immediately on directory identity changes.

    A source absence never changes active/liquid/backfill_done or writes a bar.
    Old plain-text job params remain readable and mean no recorded absences.
    """
    if not mapping:
        return mapping, []
    con = db.connect(path, read_only=True)
    try:
        current = identities(con, list(mapping.values()))
        rows = con.execute(
            "SELECT params FROM jobs WHERE kind IN ('backfill','refresh-liquid') "
            "AND state='done' AND updated_at >= ? ORDER BY id DESC",
            [datetime.now(timezone.utc) - timedelta(days=ABSENCE_RETRY_DAYS)],
        ).fetchall()
    finally:
        con.close()
    suppressed = set()
    for (params,) in rows:
        try:
            payload = json.loads(params)
            recorded = payload.get("no_data", {})
        except (TypeError, ValueError, AttributeError):
            continue
        for ticker, identity in recorded.items():
            if mode == "backfill" and payload.get("no_data_reasons", {}).get(ticker) == "no_recent_history":
                continue
            if current.get(ticker) == identity:
                suppressed.add(ticker)
    return {y: t for y, t in mapping.items() if t not in suppressed}, sorted(suppressed)


def record(con, jid, *, with_data, no_data, failed):
    """Keep per-symbol outcomes in the job that performed the requests."""
    payload = {"with_data": sorted(with_data), "failed": failed,
               "no_data": identities(con, sorted(no_data)) if no_data else {},
               "no_data_reasons": no_data,
               "absence_retry_days": ABSENCE_RETRY_DAYS}
    con.execute("UPDATE jobs SET params=? WHERE id=?", [json.dumps(payload), jid])
