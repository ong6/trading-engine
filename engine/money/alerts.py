"""Non-blocking cross-account concentration alerts."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from engine.paper_accounts import init_schema

from .halts import record_event

ACCOUNT_COUNT_THRESHOLD = 3
MDV60_FRACTION = 0.02


def _close(con, ticker: str, session_date: date) -> float | None:
    row = con.execute(
        "SELECT close FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
        [ticker, session_date],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def _mdv60(con, ticker: str, session_date: date) -> float | None:
    rows = con.execute(
        "SELECT close*volume FROM prices WHERE ticker=? AND date<? AND close IS NOT NULL "
        "AND volume IS NOT NULL ORDER BY date DESC LIMIT 60", [ticker, session_date]
    ).fetchall()
    if not rows:
        return None
    values = sorted(float(row[0]) for row in rows)
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _already_recorded(con, account_id: str, session_date: date, ticker: str) -> bool:
    rows = con.execute(
        "SELECT payload FROM account_events WHERE portfolio_id=? AND kind='alert'",
        [account_id],
    ).fetchall()
    return any(
        (payload := json.loads(row[0])).get("session_date") == session_date.isoformat()
        and payload.get("instrument_id") == ticker
        for row in rows
    )


def concentration(con, session_date: date, *,
                  now: datetime | None = None) -> list[dict]:
    """Record one daily alert per affected account/instrument, never refuse."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    init_schema(con)
    rows = con.execute(
        "SELECT sp.ticker,sp.portfolio_id,sp.qty FROM sim_positions sp "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=sp.portfolio_id "
        "WHERE pa.pa_engine='account' AND pa.pa_status IN ('active','halted') "
        "AND sp.qty<>0 ORDER BY sp.ticker,sp.portfolio_id"
    ).fetchall()
    grouped: dict[str, list[tuple[str, float]]] = {}
    for ticker, account_id, quantity in rows:
        grouped.setdefault(ticker, []).append((account_id, float(quantity)))
    created = []
    for ticker, holdings in grouped.items():
        close = _close(con, ticker, session_date)
        if close is None:
            continue
        notional = sum(abs(quantity * close) for _account, quantity in holdings)
        mdv = _mdv60(con, ticker, session_date)
        reasons = []
        if len(holdings) >= ACCOUNT_COUNT_THRESHOLD:
            reasons.append("account_count")
        if mdv is not None and notional > MDV60_FRACTION * mdv:
            reasons.append("mdv60_fraction")
        if not reasons:
            continue
        for account_id, _quantity in holdings:
            if _already_recorded(con, account_id, session_date, ticker):
                continue
            payload = {
                "code": "cross_account_concentration",
                "session_date": session_date.isoformat(),
                "instrument_id": ticker,
                "account_count": len(holdings),
                "gross_notional": notional,
                "mdv60": mdv,
                "triggers": reasons,
            }
            record_event(con, account_id, "alert", payload, now=now)
            created.append({"account_id": account_id, **payload})
    return created
