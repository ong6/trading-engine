"""Account-engine helpers shared by execution and settlement.

The fallback below is temporary compatibility for P22 bases predating R13.  New
code calls the R13 accessor; once that helper is present this module delegates
to it without inspecting the legacy columns.
"""
from __future__ import annotations

from typing import Any

import duckdb

from engine.lib.util import table_exists

try:
    from sim.schema import portfolio_account as _schema_portfolio_account
except ImportError:  # pragma: no cover - removed after the refreshed L0 base
    _schema_portfolio_account = None

_DEFAULTS = {
    "engine": "league",
    "cost_profile": "baseline_v1",
    "account_type": "cash_legacy",
    "visibility": "public",
    "price_source": "prices",
    "day_trade_rule": "pdt_25k_legacy",
    "allow_short": False,
}


def portfolio_account(
    con: duckdb.DuckDBPyConnection, portfolio_id: str,
) -> dict[str, Any]:
    """Call L0's R13 accessor, with a short-lived old-base compatibility shim."""
    if _schema_portfolio_account is not None:
        return _schema_portfolio_account(con, portfolio_id)
    row = con.execute(
        "SELECT * FROM portfolios WHERE id=?", [portfolio_id]
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    names = [item[0] for item in con.description]
    legacy = dict(zip(names, row, strict=True))
    out = {"portfolio_id": portfolio_id, **_DEFAULTS}
    has_settings = False
    if table_exists(con, "portfolio_accounts"):
        settings = con.execute(
            "SELECT engine,cost_profile,account_type,visibility,status,price_source,"
            "day_trade_rule,allow_short FROM portfolio_accounts WHERE portfolio_id=?",
            [portfolio_id],
        ).fetchone()
        if settings is not None:
            has_settings = True
            out.update(dict(zip(
                (
                    "engine", "cost_profile", "account_type", "visibility",
                    "status", "price_source", "day_trade_rule", "allow_short",
                ),
                settings,
                strict=True,
            )))
    if not has_settings:
        out.update({key: legacy[key] for key in _DEFAULTS if legacy.get(key) is not None})
    out["status"] = out.get("status") or legacy.get("status") or (
        "active" if legacy.get("active", True) else "inactive"
    )
    return out


def account_portfolios(
    con: duckdb.DuckDBPyConnection, *, active_only: bool = True,
) -> list[dict[str, Any]]:
    """Return account-engine settings without depending on storage layout."""
    out = []
    for (portfolio_id,) in con.execute("SELECT id FROM portfolios ORDER BY id").fetchall():
        settings = portfolio_account(con, portfolio_id)
        if settings["engine"] != "account":
            continue
        if active_only and settings["status"] != "active":
            continue
        out.append(settings)
    return out


__all__ = ["account_portfolios", "portfolio_account"]
