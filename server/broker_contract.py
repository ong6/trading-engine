"""Typed, broker-neutral boundary for paper execution adapters.

This module defines shapes and failure semantics only. It has no network,
credential, database, strategy, portfolio-allocation, or execution authority.
Concrete adapters remain responsible for validating their own stored/provider
state before returning these types.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, runtime_checkable

BrokerSide = Literal["buy", "sell"]
BrokerOrderStatus = Literal[
    "pending",
    "partially_filled",
    "filled",
    "rejected",
    "cancelled",
    "expired",
]
BrokerEnvironment = Literal["simulator", "paper", "live-disabled"]

IDENTIFIER_MAX_CHARS = 128
SYMBOL_MAX_CHARS = 32
MAX_FILL_BATCH = 500
MAX_ACCOUNT_ROWS = 1_000
MAX_REASON_CHARS = 4_096
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.^=-]{0,31}$")


class BrokerAdapterError(RuntimeError):
    """Base error for a fail-closed broker-adapter operation."""


class BrokerAccountNotFound(BrokerAdapterError):
    """The requested adapter account does not exist."""


class BrokerAccountInactive(BrokerAdapterError):
    """A mutation targeted an account that is not active."""


class BrokerOrderNotFound(BrokerAdapterError):
    """The requested adapter order does not exist in the requested account."""


class BrokerOrderNotCancelable(BrokerAdapterError):
    """The requested adapter order is in a non-cancellable state."""


class BrokerIdempotencyConflict(BrokerAdapterError):
    """An idempotency key was reused for different immutable order terms."""


class BrokerSubmissionUncertain(BrokerAdapterError):
    """A prior submission may have reached its venue and must be reconciled."""


class BrokerCancellationUncertain(BrokerAdapterError):
    """A prior cancellation may have reached its venue and must be reconciled."""


class BrokerStateUnavailable(BrokerAdapterError):
    """Authoritative account state cannot be observed through this adapter."""


class LiveTradingDisabled(BrokerAdapterError):
    """A live-capital mutation was rejected by a structurally disabled adapter."""


class BrokerRiskRejected(BrokerAdapterError):
    """Independent pre-trade risk did not authorize an adapter mutation."""


class BrokerStateError(BrokerAdapterError):
    """Stored or provider state violates the adapter contract."""


def require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def require_symbol(value: object) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError("symbol is invalid")
    return value


def require_positive_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return number


def require_nonnegative_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a nonnegative finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a nonnegative finite number")
    return number


@dataclass(frozen=True, slots=True)
class SubmitOrderRequest:
    """One already-approved order intent presented to an adapter.

    ``idempotency_key`` is caller-owned and stable. An exact replay must return
    the original order; reuse for different terms must fail closed.
    """

    idempotency_key: str
    account_id: str
    symbol: str
    side: BrokerSide
    quantity: float
    signal_date: date
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day"] = "day"
    extended_hours: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.idempotency_key, "idempotency key")
        require_identifier(self.account_id, "account identifier")
        require_symbol(self.symbol)
        if self.side not in {"buy", "sell"}:
            raise ValueError("side is invalid")
        object.__setattr__(
            self,
            "quantity",
            require_positive_finite(self.quantity, "quantity"),
        )
        if type(self.signal_date) is not date:
            raise ValueError("signal date is invalid")
        if self.order_type != "market":
            raise ValueError("only market orders are supported")
        if self.time_in_force != "day":
            raise ValueError("only day time-in-force is supported")
        if self.extended_hours is not False:
            raise ValueError("extended-hours orders are unsupported")


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    account_id: str
    venue: str
    environment: BrokerEnvironment
    active: bool
    currency: str
    cash: float
    buying_power: float
    initial_cash: float
    margin_enabled: bool

    def __post_init__(self) -> None:
        require_identifier(self.account_id, "account identifier")
        require_identifier(self.venue, "venue")
        if self.environment not in {"simulator", "paper", "live-disabled"}:
            raise ValueError("environment is invalid")
        if type(self.active) is not bool:
            raise ValueError("account active state is invalid")
        if type(self.margin_enabled) is not bool:
            raise ValueError("account margin state is invalid")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isupper()
        ):
            raise ValueError("currency is invalid")
        object.__setattr__(self, "cash", require_nonnegative_finite(self.cash, "cash"))
        object.__setattr__(
            self,
            "buying_power",
            require_nonnegative_finite(self.buying_power, "buying power"),
        )
        object.__setattr__(
            self,
            "initial_cash",
            require_positive_finite(self.initial_cash, "initial cash"),
        )


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    account_id: str
    symbol: str
    quantity: float
    average_price: float

    def __post_init__(self) -> None:
        require_identifier(self.account_id, "account identifier")
        require_symbol(self.symbol)
        object.__setattr__(
            self,
            "quantity",
            require_positive_finite(self.quantity, "position quantity"),
        )
        object.__setattr__(
            self,
            "average_price",
            require_positive_finite(self.average_price, "position average price"),
        )


def _validate_order_state(order: BrokerOrder) -> None:
    if order.status not in {
        "pending",
        "partially_filled",
        "filled",
        "rejected",
        "cancelled",
        "expired",
    }:
        raise ValueError("order status is invalid")
    if order.status in {"rejected", "cancelled", "expired"}:
        if (
            not isinstance(order.rejection_reason, str)
            or not order.rejection_reason.strip()
            or len(order.rejection_reason) > MAX_REASON_CHARS
        ):
            raise ValueError("terminal order reason is invalid")
    elif order.rejection_reason is not None:
        raise ValueError("terminal order reason is invalid")
    if order.status == "pending" and order.filled_quantity != 0:
        raise ValueError("pending order cannot have filled quantity")
    if order.status == "partially_filled" and not (
        0 < order.filled_quantity < order.quantity
    ):
        raise ValueError("partially filled order quantity is invalid")
    if order.status == "filled" and order.filled_quantity != order.quantity:
        raise ValueError("filled order quantity is invalid")


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    broker_order_id: str
    idempotency_key: str
    account_id: str
    symbol: str
    side: BrokerSide
    quantity: float
    signal_date: date
    status: BrokerOrderStatus
    rejection_reason: str | None
    filled_quantity: float = 0.0
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day"] = "day"
    extended_hours: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.broker_order_id, "broker order identifier")
        require_identifier(self.idempotency_key, "idempotency key")
        require_identifier(self.account_id, "account identifier")
        require_symbol(self.symbol)
        if self.side not in {"buy", "sell"}:
            raise ValueError("side is invalid")
        object.__setattr__(
            self,
            "quantity",
            require_positive_finite(self.quantity, "order quantity"),
        )
        object.__setattr__(
            self,
            "filled_quantity",
            require_nonnegative_finite(self.filled_quantity, "filled quantity"),
        )
        if self.filled_quantity > self.quantity:
            raise ValueError("filled quantity exceeds order quantity")
        if type(self.signal_date) is not date:
            raise ValueError("order signal date is invalid")
        _validate_order_state(self)
        if self.order_type != "market":
            raise ValueError("only market orders are supported")
        if self.time_in_force != "day":
            raise ValueError("only day time-in-force is supported")
        if self.extended_hours is not False:
            raise ValueError("extended-hours orders are unsupported")


@dataclass(frozen=True, slots=True)
class BrokerFill:
    execution_id: str
    broker_order_id: str
    idempotency_key: str
    account_id: str
    symbol: str
    side: BrokerSide
    quantity: float
    occurred_on: date
    reference_price: float
    price: float
    total_cost_bps: float

    def __post_init__(self) -> None:
        require_identifier(self.execution_id, "execution identifier")
        require_identifier(self.broker_order_id, "broker order identifier")
        require_identifier(self.idempotency_key, "idempotency key")
        require_identifier(self.account_id, "account identifier")
        require_symbol(self.symbol)
        if self.side not in {"buy", "sell"}:
            raise ValueError("side is invalid")
        object.__setattr__(
            self,
            "quantity",
            require_positive_finite(self.quantity, "fill quantity"),
        )
        if type(self.occurred_on) is not date:
            raise ValueError("fill date is invalid")
        object.__setattr__(
            self,
            "reference_price",
            require_positive_finite(self.reference_price, "fill reference price"),
        )
        object.__setattr__(
            self,
            "price",
            require_positive_finite(self.price, "fill price"),
        )
        object.__setattr__(
            self,
            "total_cost_bps",
            require_nonnegative_finite(self.total_cost_bps, "fill total cost"),
        )


@dataclass(frozen=True, slots=True)
class FillBatch:
    """A bounded, deterministic page of fill observations."""

    fills: tuple[BrokerFill, ...]
    next_cursor: str | None
    truncated: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fills, tuple)
            or len(self.fills) > MAX_FILL_BATCH
            or not all(isinstance(fill, BrokerFill) for fill in self.fills)
        ):
            raise ValueError("fill batch is invalid")
        if self.next_cursor is not None:
            require_identifier(self.next_cursor, "fill cursor")
        if type(self.truncated) is not bool:
            raise ValueError("fill truncation state is invalid")
        if self.truncated and not self.fills:
            raise ValueError("truncated fill batch cannot be empty")


@runtime_checkable
class BrokerAdapter(Protocol):
    """Minimal execution boundary shared by simulator and future adapters."""

    def get_account(self, account_id: str) -> BrokerAccount:
        ...

    def get_positions(self, account_id: str) -> tuple[BrokerPosition, ...]:
        ...

    def get_open_orders(self, account_id: str) -> tuple[BrokerOrder, ...]:
        ...

    def submit_order(self, request: SubmitOrderRequest) -> BrokerOrder:
        ...

    def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        ...

    def stream_fills(
        self,
        account_id: str,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> FillBatch:
        ...
