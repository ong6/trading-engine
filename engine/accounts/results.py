"""Deterministic, private per-account result projection."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean, stdev

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.paper_accounts import AccountRefused
from sim import ledger
from sim.schema import portfolio_account
from sim.strategies.base import total_return_between

FEE_COMPONENTS = (
    "commission", "exchange_fee", "clearing_fee", "pass_through", "cat_fee", "sec_fee",
    "finra_taf", "occ_fee", "orf_fee", "total_usd",
)


def _drawdowns(values: list[float], initial_cash: float) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    peak, maximum, worst_day = initial_cash, 0.0, 0.0
    for index, value in enumerate(values):
        peak = max(peak, value)
        if peak > 0:
            maximum = min(maximum, value / peak - 1.0)
        prior = initial_cash if index == 0 else values[index - 1]
        if prior > 0:
            worst_day = min(worst_day, value / prior - 1.0)
    return maximum, worst_day


def _costs(con, account_id: str) -> dict:
    totals = {component: 0.0 for component in FEE_COMPONENTS}
    if table_exists(con, "sim_fill_fees"):
        expressions = ",".join(f"COALESCE(SUM(ff.{name}),0)" for name in FEE_COMPONENTS)
        row = con.execute(
            f"SELECT {expressions} FROM sim_fill_fees ff JOIN sim_fills f "
            "ON f.order_id=ff.order_id WHERE f.portfolio_id=?", [account_id]
        ).fetchone()
        totals.update({name: float(value) for name, value in zip(FEE_COMPONENTS, row, strict=True)})
    totals["borrow"] = 0.0
    totals["interest"] = 0.0
    if table_exists(con, "sim_cash_events"):
        for kind, amount in con.execute(
            "SELECT kind,COALESCE(SUM(amount),0) FROM sim_cash_events "
            "WHERE portfolio_id=? AND kind IN ('borrow_fee','margin_interest') GROUP BY kind",
            [account_id],
        ).fetchall():
            totals["borrow" if kind == "borrow_fee" else "interest"] = -float(amount)
    totals["slippage_estimate"] = 0.0
    if table_exists(con, "sim_fill_details"):
        value = con.execute(
            "SELECT COALESCE(SUM(ABS(f.fill_px-fd.reference_px)*f.qty*"
            "COALESCE(fd.multiplier,1)),0) FROM sim_fills f JOIN sim_fill_details fd "
            "ON fd.order_id=f.order_id WHERE f.portfolio_id=?", [account_id]
        ).fetchone()[0]
        totals["slippage_estimate"] = float(value)
    return totals


def _trade_stats(con, account_id: str) -> dict:
    trades = ledger.closed_trades(con, account_id)
    clustered: dict[date, list[float]] = defaultdict(list)
    outcomes = []
    for trade in trades:
        outcomes.append(trade['net_bp'])
        clustered[trade['entry_session']].append(trade['net_bp'])
    cluster_means = [mean(values) for _day, values in sorted(clustered.items())]
    t_stat = None
    if len(cluster_means) > 1:
        dispersion = stdev(cluster_means)
        t_stat = 0.0 if dispersion == 0 else mean(cluster_means) / (
            dispersion / math.sqrt(len(cluster_means))
        )
    return {
        "n": len(outcomes),
        "win_rate": sum(value > 0 for value in outcomes) / len(outcomes) if outcomes else None,
        "mean_net_bp": mean(outcomes) if outcomes else None,
        "entry_session_clustered_t": t_stat,
    }


def _event_count(con, account_id: str, kinds: tuple[str, ...]) -> int:
    placeholders = ",".join("?" for _ in kinds)
    return int(con.execute(
        f"SELECT COUNT(*) FROM account_events WHERE portfolio_id=? AND kind IN ({placeholders})",
        [account_id, *kinds],
    ).fetchone()[0])


def _trailing_day_trades(con, account_id: str, end: date | None) -> int:
    if end is None or not table_exists(con, "sim_day_trades"):
        return 0
    rows = con.execute(
        "SELECT COUNT(*) FROM sim_day_trades WHERE portfolio_id=? AND session_date IN "
        "(SELECT DISTINCT date FROM prices WHERE date<=? ORDER BY date DESC LIMIT 5)",
        [account_id, end],
    ).fetchone()
    return int(rows[0])


def build(con, account_id: str) -> dict:
    """Only return results backed by a complete fold; failures halt after rollback."""
    from engine.accounts import service

    service._account(con, account_id)
    now = datetime.now(timezone.utc)
    try:
        with db.transaction(con):
            service.require_verified(con, account_id, now=now, manage_transaction=False)
            return _build(con, account_id)
    except Exception as exc:
        result = service.failure_result(account_id, exc)
        with db.transaction(con):
            service.persist_mismatch(con, account_id, result, now=now)
        raise service.VerificationError(result) from exc


def _build(con, account_id: str) -> dict:
    """Return metrics plus a hash of the canonical metrics payload."""
    account = con.execute(
        "SELECT created,initial_cash FROM portfolios WHERE id=?", [account_id]
    ).fetchone()
    if account is None or portfolio_account(con, account_id)["engine"] != "account":
        raise AccountRefused("unknown account")
    curve_rows = con.execute(
        "SELECT date,equity,cash FROM sim_equity WHERE portfolio_id=? ORDER BY date", [account_id]
    ).fetchall()
    curve = []
    for session_date, equity, cash in curve_rows:
        benchmark_return = total_return_between(con, "SPY", account[0], session_date)
        curve.append({"date": session_date.isoformat(), "equity": float(equity),
                      "cash": float(cash), "benchmark_total_return": benchmark_return})
    values = [row["equity"] for row in curve]
    last_date = curve_rows[-1][0] if curve_rows else None
    total_return = values[-1] / float(account[1]) - 1.0 if values else None
    benchmark = curve[-1]["benchmark_total_return"] if curve else None
    maximum_drawdown, worst_day = _drawdowns(values, float(account[1]))
    fills = con.execute(
        "SELECT COUNT(*),COALESCE(SUM(ABS(qty*fill_px)),0) FROM sim_fills "
        "WHERE portfolio_id=?", [account_id]
    ).fetchone()
    break_row = con.execute(
        "SELECT break_date FROM sim_book_breaks WHERE portfolio_id=? ORDER BY break_date DESC LIMIT 1",
        [account_id],
    ).fetchone()
    return_since_break = None
    if break_row is not None and values:
        base = con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id=? AND date<? "
            "ORDER BY date DESC LIMIT 1", [account_id, break_row[0]]
        ).fetchone()
        if base is not None and base[0]:
            return_since_break = values[-1] / float(base[0]) - 1.0
    reconciliation = con.execute(
        "SELECT status FROM account_reconciliations WHERE portfolio_id=? "
        "ORDER BY session_date DESC LIMIT 1", [account_id]
    ).fetchone()
    state = con.execute(
        "SELECT pdt_flagged_at,pdt_restricted_until FROM account_state WHERE portfolio_id=?",
        [account_id],
    ).fetchone()
    late = con.execute(
        "SELECT COUNT(*) FROM sim_fill_details fd JOIN sim_fills f ON f.order_id=fd.order_id "
        "WHERE f.portfolio_id=? AND fd.late_settled", [account_id]
    ).fetchone()[0]
    body = {
        "schema_version": 1,
        "account_id": account_id,
        "as_of": last_date.isoformat() if last_date else None,
        "equity_curve": curve,
        "total_return": total_return,
        "return_since_break": return_since_break,
        "benchmark_total_return": benchmark,
        "excess": total_return - benchmark if total_return is not None and benchmark is not None else None,
        "max_drawdown": maximum_drawdown,
        "daily_loss_worst": worst_day,
        "fills": {"count": int(fills[0]), "notional": float(fills[1])},
        "costs_paid": _costs(con, account_id),
        "trade_stats": _trade_stats(con, account_id),
        "day_trades_trailing_5": _trailing_day_trades(con, account_id, last_date),
        "halts": _event_count(con, account_id,
                              ("halt_drawdown", "halt_daily_loss", "halt_reconciliation")),
        "alerts": _event_count(con, account_id, ("alert",)),
        "pdt": {"flagged_at": state[0].isoformat() if state and state[0] else None,
                "restricted_until": state[1].isoformat() if state and state[1] else None},
        "margin_calls": _event_count(con, account_id, ("margin_call",)),
        "late_settled_fills": int(late),
        "reconciliation_status": reconciliation[0] if reconciliation else None,
    }
    return {**body, "sha256": canonical_sha256(body)}


account_results = build
