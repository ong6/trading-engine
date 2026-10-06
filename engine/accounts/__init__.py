"""Account-engine helpers shared by execution and settlement."""
from __future__ import annotations

from typing import Any

import duckdb

from sim.schema import portfolio_account


def account_portfolios(
    con: duckdb.DuckDBPyConnection, *, active_only: bool = True,
) -> list[dict[str, Any]]:
    """Return account-engine settings without depending on storage layout."""
    out = []
    for (portfolio_id,) in con.execute("SELECT id FROM portfolios ORDER BY id").fetchall():
        settings = {"portfolio_id": portfolio_id, **portfolio_account(con, portfolio_id)}
        if settings["engine"] != "account":
            continue
        if active_only and settings["status"] != "active":
            continue
        out.append(settings)
    return out


__all__ = ["account_portfolios", "portfolio_account"]
