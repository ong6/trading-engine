"""Broker-neutral adapter over the existing long-only paper simulator.

This is an internal boundary, not a new execution path. It has no HTTP route,
schedule, model integration, external broker, credentials, or network access.
The nightly league remains the only component that attempts fills.
"""

from __future__ import annotations

import math
from datetime import date

import duckdb

from engine.lib import db
from engine.lib.util import table_exists

from .broker_contract import (
    MAX_ACCOUNT_ROWS,
    MAX_FILL_BATCH,
    BrokerAccount,
    BrokerAccountInactive,
    BrokerAccountNotFound,
    BrokerAdapter,
    BrokerFill,
    BrokerIdempotencyConflict,
    BrokerOrder,
    BrokerOrderNotCancelable,
    BrokerOrderNotFound,
    BrokerPosition,
    BrokerStateError,
    FillBatch,
    SubmitOrderRequest,
    require_identifier,
    require_nonnegative_finite,
    require_positive_finite,
    require_symbol,
)

VENUE = "local-simulator"
CURRENCY = "USD"
ORDER_ID_PREFIX = "sim-order:"
EXECUTION_ID_PREFIX = "sim-fill:"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ORDER_STATUSES = frozenset({"pending", "filled", "rejected", "cancelled"})


def _simulator_id(value: str, *, prefix: str, label: str) -> int:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{label} is invalid")
    raw = value[len(prefix) :]
    if not raw or not raw.isascii() or not raw.isdecimal() or raw.startswith("0"):
        raise ValueError(f"{label} is invalid")
    identifier = int(raw)
    if identifier > MAX_SAFE_INTEGER:
        raise ValueError(f"{label} is invalid")
    return identifier


def _broker_order_id(order_id: int) -> str:
    return f"{ORDER_ID_PREFIX}{order_id}"


def _execution_id(order_id: int) -> str:
    return f"{EXECUTION_ID_PREFIX}{order_id}"


def _require_stored_id(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_SAFE_INTEGER
    ):
        raise BrokerStateError(f"stored {label} is invalid")
    return value


def _require_stored_date(value: object, label: str) -> date:
    if type(value) is not date:
        raise BrokerStateError(f"stored {label} is invalid")
    return value


def _require_stored_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrokerStateError(f"stored {label} is invalid")
    return value


def _stored_positive(value: object, label: str) -> float:
    try:
        return require_positive_finite(value, label)
    except ValueError as exc:
        raise BrokerStateError(f"stored {label} is invalid") from exc


def _stored_nonnegative(value: object, label: str) -> float:
    try:
        return require_nonnegative_finite(value, label)
    except ValueError as exc:
        raise BrokerStateError(f"stored {label} is invalid") from exc


class SimulatorBrokerAdapter(BrokerAdapter):
    """Expose simulator account/order state through the broker-neutral contract."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._con = con

    def init_schema(self) -> None:
        """Create the adapter-owned idempotency mapping."""
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS simulator_broker_order_keys (
                idempotency_key VARCHAR PRIMARY KEY,
                order_id       BIGINT UNIQUE NOT NULL
            )
            """
        )

    def _account_row(self, account_id: str) -> tuple:
        require_identifier(account_id, "account identifier")
        row = self._con.execute(
            "SELECT id, active, cash, initial_cash FROM portfolios WHERE id = ?",
            [account_id],
        ).fetchone()
        if row is None:
            raise BrokerAccountNotFound(f"simulator account {account_id!r} does not exist")
        return row

    def get_account(self, account_id: str) -> BrokerAccount:
        stored_id, active, cash, initial_cash = self._account_row(account_id)
        if stored_id != account_id or type(active) is not bool:
            raise BrokerStateError("stored simulator account identity is invalid")
        cash = _stored_nonnegative(cash, "account cash")
        initial_cash = _stored_positive(initial_cash, "account initial cash")
        return BrokerAccount(
            account_id=account_id,
            venue=VENUE,
            environment="simulator",
            active=active,
            currency=CURRENCY,
            cash=cash,
            buying_power=cash,
            initial_cash=initial_cash,
            margin_enabled=False,
        )

    def get_positions(self, account_id: str) -> tuple[BrokerPosition, ...]:
        self._account_row(account_id)
        result = []
        for stored_account, raw_symbol, quantity, average_price in self._con.execute(
            "SELECT portfolio_id, ticker, qty, avg_cost FROM sim_positions "
            "WHERE portfolio_id = ? AND (qty != 0 OR qty IS NULL) "
            "ORDER BY ticker LIMIT ?",
            [account_id, MAX_ACCOUNT_ROWS + 1],
        ).fetchall():
            if len(result) >= MAX_ACCOUNT_ROWS:
                raise BrokerStateError("simulator position count exceeds adapter limit")
            if stored_account != account_id:
                raise BrokerStateError("stored position account is invalid")
            try:
                symbol = require_symbol(raw_symbol)
            except ValueError as exc:
                raise BrokerStateError("stored position symbol is invalid") from exc
            result.append(
                BrokerPosition(
                    account_id=account_id,
                    symbol=symbol,
                    quantity=_stored_positive(quantity, "position quantity"),
                    average_price=_stored_positive(
                        average_price, "position average price"
                    ),
                )
            )
        return tuple(result)

    def _order(self, row: tuple, *, idempotency_key: str | None = None) -> BrokerOrder:
        (
            order_id,
            account_id,
            symbol,
            side,
            quantity,
            signal_date,
            status,
            rejection_reason,
        ) = row
        order_id = _require_stored_id(order_id, "order identifier")
        try:
            require_identifier(account_id, "account identifier")
            symbol = require_symbol(symbol)
        except ValueError as exc:
            raise BrokerStateError("stored order identity is invalid") from exc
        if side not in {"buy", "sell"}:
            raise BrokerStateError("stored order side is invalid")
        if status not in ORDER_STATUSES:
            raise BrokerStateError("stored order status is invalid")
        if status in {"rejected", "cancelled"}:
            rejection_reason = _require_stored_text(
                rejection_reason, "order terminal reason"
            )
        elif rejection_reason is not None:
            raise BrokerStateError("stored order terminal reason is invalid")
        return BrokerOrder(
            broker_order_id=_broker_order_id(order_id),
            idempotency_key=idempotency_key or str(order_id),
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=_stored_positive(quantity, "order quantity"),
            signal_date=_require_stored_date(signal_date, "order signal date"),
            status=status,
            rejection_reason=rejection_reason,
            filled_quantity=quantity if status == "filled" else 0.0,
        )

    def _order_row(self, account_id: str, order_id: int) -> tuple | None:
        return self._con.execute(
            "SELECT id, portfolio_id, ticker, side, qty, signal_date, status, "
            "reject_reason FROM sim_orders WHERE id = ? AND portfolio_id = ?",
            [order_id, account_id],
        ).fetchone()

    def _idempotency_key(self, order_id: int) -> str:
        if not table_exists(self._con, "simulator_broker_order_keys"):
            return str(order_id)
        row = self._con.execute(
            "SELECT idempotency_key FROM simulator_broker_order_keys WHERE order_id = ?",
            [order_id],
        ).fetchone()
        return str(order_id) if row is None else row[0]

    def get_open_orders(self, account_id: str) -> tuple[BrokerOrder, ...]:
        self._account_row(account_id)
        if not table_exists(self._con, "simulator_broker_order_keys"):
            rows = self._con.execute(
                "SELECT id, portfolio_id, ticker, side, qty, signal_date, status, "
                "reject_reason, NULL AS idempotency_key FROM sim_orders "
                "WHERE portfolio_id = ? AND status = 'pending' ORDER BY id LIMIT ?",
                [account_id, MAX_ACCOUNT_ROWS + 1],
            ).fetchall()
            if len(rows) > MAX_ACCOUNT_ROWS:
                raise BrokerStateError("simulator open-order count exceeds adapter limit")
            return tuple(self._order(row[:8]) for row in rows)
        rows = self._con.execute(
            "SELECT o.id, o.portfolio_id, o.ticker, o.side, o.qty, o.signal_date, "
            "o.status, o.reject_reason, k.idempotency_key FROM sim_orders o "
            "LEFT JOIN simulator_broker_order_keys k ON k.order_id = o.id "
            "WHERE o.portfolio_id = ? AND o.status = 'pending' ORDER BY o.id LIMIT ?",
            [account_id, MAX_ACCOUNT_ROWS + 1],
        ).fetchall()
        if len(rows) > MAX_ACCOUNT_ROWS:
            raise BrokerStateError("simulator open-order count exceeds adapter limit")
        return tuple(self._order(row[:8], idempotency_key=row[8]) for row in rows)

    def submit_order(self, request: SubmitOrderRequest) -> BrokerOrder:
        if not isinstance(request, SubmitOrderRequest):
            raise TypeError("request must be a SubmitOrderRequest")
        with db.transaction(self._con):
            self.init_schema()
            account = self.get_account(request.account_id)
            if not account.active:
                raise BrokerAccountInactive(
                    f"simulator account {request.account_id!r} is inactive"
                )
            mapped = self._con.execute(
                "SELECT order_id FROM simulator_broker_order_keys "
                "WHERE idempotency_key = ?",
                [request.idempotency_key],
            ).fetchone()
            existing = None if mapped is None else self._con.execute(
                "SELECT id, portfolio_id, ticker, side, qty, signal_date, status, "
                "reject_reason FROM sim_orders WHERE id = ?",
                [mapped[0]],
            ).fetchone()
            if mapped is not None:
                if existing is None:
                    raise BrokerStateError(
                        "simulator idempotency mapping references a missing order"
                    )
                order = self._order(
                    existing,
                    idempotency_key=request.idempotency_key,
                )
                expected = (
                    request.account_id,
                    request.symbol,
                    request.side,
                    request.quantity,
                    request.signal_date,
                )
                actual = (
                    order.account_id,
                    order.symbol,
                    order.side,
                    order.quantity,
                    order.signal_date,
                )
                if actual != expected:
                    raise BrokerIdempotencyConflict(
                        f"idempotency key {request.idempotency_key!r} "
                        "is already bound to different order terms"
                    )
                return order
            order_id = self._con.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders"
            ).fetchone()[0]
            order_id = _require_stored_id(order_id, "next order identifier")
            self._con.execute(
                "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status, reject_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
                [
                    order_id,
                    request.account_id,
                    request.symbol,
                    request.side,
                    request.quantity,
                    request.signal_date,
                ],
            )
            self._con.execute(
                "INSERT INTO simulator_broker_order_keys (idempotency_key, order_id) "
                "VALUES (?, ?)",
                [request.idempotency_key, order_id],
            )
            row = self._order_row(request.account_id, order_id)
            if row is None:
                raise BrokerStateError("submitted simulator order is unavailable")
            return self._order(row, idempotency_key=request.idempotency_key)

    def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        require_identifier(account_id, "account identifier")
        order_id = _simulator_id(
            broker_order_id,
            prefix=ORDER_ID_PREFIX,
            label="broker order identifier",
        )
        with db.transaction(self._con):
            self.init_schema()
            self._account_row(account_id)
            row = self._order_row(account_id, order_id)
            if row is None:
                raise BrokerOrderNotFound(
                    f"simulator order {broker_order_id!r} does not exist in "
                    f"account {account_id!r}"
                )
            idempotency_key = self._idempotency_key(order_id)
            order = self._order(row, idempotency_key=idempotency_key)
            if order.status == "cancelled":
                return order
            if order.status != "pending":
                raise BrokerOrderNotCancelable(
                    f"simulator order {broker_order_id!r} has status {order.status!r}"
                )
            self._con.execute(
                "UPDATE sim_orders SET status = 'cancelled', "
                "reject_reason = 'cancelled through simulator adapter' "
                "WHERE id = ? AND portfolio_id = ? AND status = 'pending'",
                [order_id, account_id],
            )
            row = self._order_row(account_id, order_id)
            if row is None:
                raise BrokerStateError("cancelled simulator order is unavailable")
            return self._order(row, idempotency_key=idempotency_key)

    def stream_fills(
        self,
        account_id: str,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> FillBatch:
        self._account_row(account_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_FILL_BATCH:
            raise ValueError(f"fill limit must be from 1 through {MAX_FILL_BATCH}")
        after_id = (
            0
            if after is None
            else _simulator_id(
                after,
                prefix=EXECUTION_ID_PREFIX,
                label="fill cursor",
            )
        )
        rows = self._con.execute(
            "WITH fills_with_count AS ("
            "SELECT f.*, COUNT(*) OVER (PARTITION BY f.order_id) AS fill_count "
            "FROM sim_fills f"
            ") SELECT f.order_id, f.portfolio_id, f.ticker, f.side, f.qty, "
            "f.fill_date, f.open_px, f.fill_px, f.cost_bps, "
            "o.status, o.portfolio_id, o.ticker, o.side, "
            "f.fill_count FROM fills_with_count f "
            "LEFT JOIN sim_orders o ON o.id = f.order_id "
            "WHERE f.portfolio_id = ? AND f.order_id > ? "
            "ORDER BY f.order_id LIMIT ?",
            [account_id, after_id, limit + 1],
        ).fetchall()
        truncated = len(rows) > limit
        visible = rows[:limit]
        fills = tuple(self._fill(row, account_id) for row in visible)
        next_cursor = fills[-1].execution_id if fills else after
        return FillBatch(
            fills=fills,
            next_cursor=next_cursor,
            truncated=truncated,
        )

    def _fill(self, row: tuple, account_id: str) -> BrokerFill:
        (
            order_id,
            fill_account,
            symbol,
            side,
            quantity,
            occurred_on,
            reference_price,
            price,
            total_cost_bps,
            order_status,
            order_account,
            order_symbol,
            order_side,
            fill_count,
        ) = row
        order_id = _require_stored_id(order_id, "fill order identifier")
        if (
            fill_count != 1
            or fill_account != account_id
            or order_account != account_id
            or symbol != order_symbol
            or side != order_side
            or order_status != "filled"
        ):
            raise BrokerStateError("stored fill does not match its simulator order")
        try:
            symbol = require_symbol(symbol)
        except ValueError as exc:
            raise BrokerStateError("stored fill symbol is invalid") from exc
        if side not in {"buy", "sell"}:
            raise BrokerStateError("stored fill side is invalid")
        cost = _stored_nonnegative(total_cost_bps, "fill total cost")
        if not math.isfinite(cost):
            raise BrokerStateError("stored fill total cost is invalid")
        return BrokerFill(
            execution_id=_execution_id(order_id),
            broker_order_id=_broker_order_id(order_id),
            idempotency_key=self._idempotency_key(order_id),
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=_stored_positive(quantity, "fill quantity"),
            occurred_on=_require_stored_date(occurred_on, "fill date"),
            reference_price=_stored_positive(reference_price, "fill reference price"),
            price=_stored_positive(price, "fill price"),
            total_cost_bps=cost,
        )
