"""Read-only materialization of the exact registered algorithm candidate."""

from __future__ import annotations

import math
from datetime import date

import duckdb

from engine.lib.provenance import canonical_sha256
from sim import calendar
from sim.strategies import PortfolioView, get_strategy

from . import agent_policy
from .json_utils import loads_object

CANDIDATE_SCHEMA_VERSION = 1


class CandidateError(ValueError):
    """A deterministic algorithm candidate could not be materialized safely."""


def _finite(value: object, field: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        raise CandidateError(f"algorithm candidate {field} is invalid")
    return float(value)


def _portfolio_state(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    market_date: date,
) -> tuple[dict, PortfolioView, dict]:
    row = con.execute(
        "SELECT config, cash FROM portfolios WHERE id = ? AND active",
        [portfolio_id],
    ).fetchone()
    if row is None:
        raise CandidateError("algorithm candidate source portfolio is unavailable")
    try:
        config = loads_object(row[0])
    except (TypeError, ValueError) as exc:
        raise CandidateError("algorithm candidate source config is invalid") from exc
    params = config.get("params")
    if not isinstance(params, dict):
        raise CandidateError("algorithm candidate strategy params are invalid")
    cash = _finite(row[1], "cash")
    if cash < 0:
        raise CandidateError("algorithm candidate cash is negative")

    positions = []
    quantities = {}
    for ticker, quantity, average_cost in con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty != 0 ORDER BY ticker",
        [portfolio_id],
    ).fetchall():
        qty = _finite(quantity, "position quantity", positive=True)
        avg_cost = _finite(average_cost, "position average cost", positive=True)
        mark = con.execute(
            "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? "
            "ORDER BY date DESC LIMIT 1",
            [ticker, market_date],
        ).fetchone()
        if mark is None:
            raise CandidateError("algorithm candidate position has no mark")
        close = _finite(mark[1], "position mark", positive=True)
        quantities[ticker] = qty
        positions.append(
            {
                "ticker": ticker,
                "quantity": qty,
                "average_cost": avg_cost,
                "mark_date": mark[0].isoformat(),
                "mark_close": close,
                "market_value": qty * close,
                "carried": mark[0] != market_date,
            }
        )
    equity = cash + sum(position["market_value"] for position in positions)
    if not math.isfinite(equity) or equity <= 0:
        raise CandidateError("algorithm candidate equity is invalid")

    stored = con.execute(
        "SELECT equity, cash, n_positions FROM sim_equity "
        "WHERE portfolio_id = ? AND date = ?",
        [portfolio_id, market_date],
    ).fetchone()
    equity_source = "recomputed_current_state"
    if stored is not None:
        stored_equity = _finite(stored[0], "stored equity", positive=True)
        stored_cash = _finite(stored[1], "stored cash")
        if (
            stored_cash < 0
            or not isinstance(stored[2], int)
            or stored[2] != len(positions)
            or not math.isclose(stored_cash, cash, rel_tol=0, abs_tol=1e-8)
            or not math.isclose(stored_equity, equity, rel_tol=1e-12, abs_tol=1e-8)
        ):
            raise CandidateError(
                "algorithm candidate current state disagrees with stored equity"
            )
        equity_source = "stored_equity_reconciled_to_current_state"

    state = {
        "portfolio_id": portfolio_id,
        "as_of": market_date.isoformat(),
        "cash": cash,
        "equity": equity,
        "equity_source": equity_source,
        "positions": positions,
    }
    state["state_sha256"] = canonical_sha256(state)
    view = PortfolioView(
        id=portfolio_id,
        params=params,
        cash=cash,
        positions=quantities,
        equity=equity,
    )
    return state, view, config


def materialize(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    market_date: date,
    *,
    allow_reserved_portfolio: bool = False,
) -> dict:
    """Run the registered deterministic strategy without writing simulator state."""
    if policy["mode"] != "hybrid" or policy["hybrid_behavior"] != "veto_only":
        raise CandidateError("algorithm candidate requires a hybrid veto-only policy")
    if policy["strategy_id"] != policy["source_portfolio_id"]:
        raise CandidateError("algorithm candidate source identity is invalid")
    if policy["cadence"] != "monthly":
        raise CandidateError("algorithm candidate cadence is not implemented")
    try:
        agent_policy.validate_live_registration(
            con,
            policy,
            allow_reserved_portfolio=allow_reserved_portfolio,
        )
    except agent_policy.PolicyError as exc:
        raise CandidateError(str(exc)) from exc

    state, portfolio, config = _portfolio_state(
        con,
        policy["source_portfolio_id"],
        market_date,
    )
    admitted = calendar.is_month_signal(con, market_date)
    orders = []
    if admitted:
        try:
            strategy = get_strategy(config["strategy"])
        except (KeyError, TypeError) as exc:
            raise CandidateError(
                "algorithm candidate strategy implementation is unavailable"
            ) from exc
        generated = strategy.generate_orders(con, portfolio, market_date)
        for order in generated:
            if (
                order.portfolio_id != policy["source_portfolio_id"]
                or order.signal_date != market_date
                or order.ticker not in policy["allowed_symbols"]
                or order.side not in {"buy", "sell"}
            ):
                raise CandidateError("algorithm candidate emitted an invalid order")
            quantity = _finite(order.qty, "order quantity", positive=True)
            quote = con.execute(
                "SELECT close FROM prices WHERE ticker = ? AND date = ?",
                [order.ticker, market_date],
            ).fetchone()
            if quote is None:
                raise CandidateError("algorithm candidate order has no signal close")
            close = _finite(quote[0], "order signal close", positive=True)
            orders.append(
                {
                    "sequence": len(orders) + 1,
                    "portfolio_id": order.portfolio_id,
                    "ticker": order.ticker,
                    "side": order.side,
                    "quantity": quantity,
                    "signal_date": order.signal_date.isoformat(),
                    "signal_close": close,
                    "signal_notional": quantity * close,
                    "veto_eligible": order.side == "buy",
                }
            )

    body = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "status": "materialized" if admitted else "not_signal_date",
        "market_date": market_date.isoformat(),
        "cadence": policy["cadence"],
        "cadence_admitted": admitted,
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "strategy_id": policy["strategy_id"],
        "strategy_config_sha256": policy["strategy_config_sha256"],
        "source_portfolio_id": policy["source_portfolio_id"],
        "execution_profile_id": policy["execution_profile_id"],
        "execution_profile_sha256": policy["execution_profile_sha256"],
        "portfolio_state": state,
        "orders": orders,
        "order_count": len(orders),
        "buy_order_count": sum(order["side"] == "buy" for order in orders),
        "sell_order_count": sum(order["side"] == "sell" for order in orders),
        "veto_scope": "buy_orders_only",
        "execution_authority": "none",
    }
    return {**body, "candidate_sha256": canonical_sha256(body)}
