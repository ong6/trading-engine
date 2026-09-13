"""Research data-quality labels and deterministic store fingerprints."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from engine.lib.util import table_exists

FIXED_ETF_HISTORY = "fixed_etf_history"
CURRENT_UNIVERSE_SURVIVOR_BIASED = "current_universe_survivor_biased"
STATIC_FUNDAMENTAL_LOOKAHEAD = "static_fundamental_lookahead"

FIXED_ETF_STRATEGIES = frozenset({
    "spy_benchmark", "dual_momentum", "dual_momentum_gated",
    "sector_momentum", "multi_asset_trend", "sleeve_alloc",
})
STATIC_FUNDAMENTAL_STRATEGIES = frozenset({"low_vol", "ew_sector_capped"})


def quality_class(strategy: str) -> str:
    if strategy in STATIC_FUNDAMENTAL_STRATEGIES:
        return STATIC_FUNDAMENTAL_LOOKAHEAD
    if strategy in FIXED_ETF_STRATEGIES:
        return FIXED_ETF_HISTORY
    return CURRENT_UNIVERSE_SURVIVOR_BIASED


def quarantine_reason(con, ticker: str) -> str | None:
    """Reason for an explicitly active primary-data quarantine, if any."""
    if not table_exists(con, "price_quarantine"):
        return None
    row = con.execute(
        "SELECT reason FROM price_quarantine WHERE ticker = ? AND status = 'active'",
        [ticker.upper()],
    ).fetchone()
    return None if row is None else str(row[0])


def active_quarantines(con) -> list[dict]:
    if not table_exists(con, "price_quarantine"):
        return []
    return [
        {"ticker": tk, "reason": reason, "evidence": evidence,
         "confirmed_at": _json_value(confirmed)}
        for tk, reason, evidence, confirmed in con.execute(
            "SELECT ticker, reason, evidence, confirmed_at FROM price_quarantine "
            "WHERE status = 'active' ORDER BY ticker"
        ).fetchall()
    ]


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _table_summary(con, table: str, date_col: str,
                   watermark_col: str | None = None) -> dict:
    if not table_exists(con, table):
        return {"exists": False, "rows": 0, "min_date": None,
                "max_date": None, "latest_fetch": None}
    watermark = (
        f", MAX({watermark_col})" if watermark_col else ", NULL"
    )
    row = con.execute(
        f"SELECT COUNT(*), MIN({date_col}), MAX({date_col}){watermark} FROM {table}"
    ).fetchone()
    return {
        "exists": True,
        "rows": int(row[0]),
        "min_date": _json_value(row[1]),
        "max_date": _json_value(row[2]),
        "latest_fetch": _json_value(row[3]),
    }


def data_snapshot(con) -> dict:
    """Small deterministic identity for research-relevant source tables."""
    tables = {
        "prices": _table_summary(con, "prices", "date", "fetched_at"),
        "corporate_actions": _table_summary(
            con, "corporate_actions", "ex_date", "fetched_at"),
        "universe_snapshot": _table_summary(
            con, "universe_snapshot", "snapshot_date"),
        "fundamentals": _table_summary(con, "fundamentals", "as_of", "fetched_at"),
    }
    quarantines = active_quarantines(con)
    tables["price_quarantine"] = {
        "active_count": len(quarantines),
        "active_tickers": [q["ticker"] for q in quarantines],
    }
    payload = json.dumps(tables, sort_keys=True, separators=(",", ":"))
    return {"sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "tables": tables}
