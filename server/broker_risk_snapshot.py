"""Deterministic assembly of pre-trade risk inputs from bounded evidence.

This module reads a stable broker-adapter snapshot and immutable caller-owned
market/performance evidence. It has no submission, cancellation, model,
network, authorization, or control-enable capability.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Literal

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import broker_reconciliation, broker_risk_control
from .broker_contract import (
    BrokerAdapter,
    BrokerStateError,
    SubmitOrderRequest,
    require_identifier,
    require_symbol,
)
from .broker_risk import PreTradeSnapshot, RiskContractError


def _positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskContractError(f"{label} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise RiskContractError(f"{label} must be a positive finite number")
    return number


def _nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskContractError(f"{label} must be a nonnegative finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise RiskContractError(f"{label} must be a nonnegative finite number")
    return number


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise RiskContractError(f"{label} must be UTC")
    return value


@dataclass(frozen=True, slots=True)
class PositionMark:
    symbol: str
    price: float

    def __post_init__(self) -> None:
        try:
            require_symbol(self.symbol)
        except ValueError as exc:
            raise RiskContractError(str(exc)) from exc
        object.__setattr__(self, "price", _positive(self.price, "position mark"))


@dataclass(frozen=True, slots=True)
class MarketRiskEvidence:
    as_of: date
    observed_at: datetime
    quote_date: date
    quote_at: datetime
    quote_price: float
    reference_price: float
    median_dollar_volume: float | None
    position_marks: tuple[PositionMark, ...]
    instrument_type: str
    instrument_active: bool
    instrument_liquid: bool
    instrument_quarantined: bool
    market_session_open: bool
    clock_synchronized: bool
    storage_healthy: bool
    broker_healthy: bool
    corporate_action_clear: bool

    def __post_init__(self) -> None:
        if type(self.as_of) is not date or type(self.quote_date) is not date:
            raise RiskContractError("market evidence dates are invalid")
        _utc(self.observed_at, "market evidence observation time")
        _utc(self.quote_at, "market evidence quote time")
        object.__setattr__(
            self, "quote_price", _positive(self.quote_price, "quote price")
        )
        object.__setattr__(
            self,
            "reference_price",
            _positive(self.reference_price, "reference price"),
        )
        if self.median_dollar_volume is not None:
            object.__setattr__(
                self,
                "median_dollar_volume",
                _positive(self.median_dollar_volume, "median dollar volume"),
            )
        if (
            not isinstance(self.position_marks, tuple)
            or not all(isinstance(mark, PositionMark) for mark in self.position_marks)
            or tuple(mark.symbol for mark in self.position_marks)
            != tuple(sorted({mark.symbol for mark in self.position_marks}))
        ):
            raise RiskContractError("position marks must be a sorted unique tuple")
        if self.instrument_type not in {"equity", "etf"}:
            raise RiskContractError("instrument type must be equity or etf")
        for field in (
            "instrument_active",
            "instrument_liquid",
            "instrument_quarantined",
            "market_session_open",
            "clock_synchronized",
            "storage_healthy",
            "broker_healthy",
            "corporate_action_clear",
        ):
            if type(getattr(self, field)) is not bool:
                raise RiskContractError(f"{field.replace('_', ' ')} must be boolean")

    def payload(self) -> dict:
        value = asdict(self)
        value["as_of"] = self.as_of.isoformat()
        value["quote_date"] = self.quote_date.isoformat()
        value["observed_at"] = self.observed_at.isoformat()
        value["quote_at"] = self.quote_at.isoformat()
        return value


@dataclass(frozen=True, slots=True)
class PerformanceRiskEvidence:
    daily_turnover: float
    daily_order_count: int
    daily_pnl: float
    drawdown_fraction: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "daily_turnover",
            _nonnegative(self.daily_turnover, "daily turnover"),
        )
        if (
            isinstance(self.daily_order_count, bool)
            or not isinstance(self.daily_order_count, int)
            or self.daily_order_count < 0
        ):
            raise RiskContractError("daily order count must be nonnegative")
        if (
            isinstance(self.daily_pnl, bool)
            or not isinstance(self.daily_pnl, (int, float))
            or not math.isfinite(self.daily_pnl)
        ):
            raise RiskContractError("daily P&L must be finite")
        object.__setattr__(self, "daily_pnl", float(self.daily_pnl))
        drawdown = _nonnegative(self.drawdown_fraction, "drawdown fraction")
        if drawdown > 1:
            raise RiskContractError("drawdown fraction must be from zero through one")
        object.__setattr__(self, "drawdown_fraction", drawdown)

    def payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    status: Literal["match", "difference", "unavailable"]
    observed_at: datetime
    evidence_sha256: str


def verified_reconciliation_evidence(
    con: duckdb.DuckDBPyConnection,
    reconciliation_key: str,
    *,
    account_id: str,
    snapshot_sha256: str,
) -> ReconciliationEvidence:
    try:
        require_identifier(reconciliation_key, "reconciliation key")
        require_identifier(account_id, "account identifier")
    except ValueError as exc:
        raise BrokerStateError(str(exc)) from exc
    if not table_exists(con, "broker_reconciliations"):
        raise BrokerStateError("broker reconciliation evidence is unavailable")
    row = con.execute(
        "SELECT account_id, status, expected_sha256, observed_sha256, "
        "expected_payload, observed_payload, detail, observed_at "
        "FROM broker_reconciliations WHERE reconciliation_key = ?",
        [reconciliation_key],
    ).fetchone()
    if row is None:
        raise BrokerStateError("broker reconciliation evidence is unavailable")
    (
        stored_account,
        status,
        expected_sha256,
        observed_sha256,
        expected_payload,
        observed_payload,
        detail,
        observed_at,
    ) = row
    if (
        stored_account != account_id
        or status not in {"match", "difference", "unavailable"}
        or not isinstance(detail, str)
        or not detail
        or type(observed_at) is not datetime
    ):
        raise BrokerStateError("broker reconciliation evidence is invalid")
    # DuckDB stores TIMESTAMP without zone. Existing broker ledgers write UTC;
    # interpret naive reads as UTC and reject any non-UTC aware value.
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    _utc(observed_at, "reconciliation observation time")
    try:
        computed_expected_sha256 = (
            None
            if expected_payload is None
            else canonical_sha256(json.loads(expected_payload))
        )
        computed_observed_sha256 = (
            None
            if observed_payload is None
            else canonical_sha256(json.loads(observed_payload))
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("broker reconciliation evidence is invalid") from exc
    if (
        (expected_payload is None) != (expected_sha256 is None)
        or (observed_payload is None) != (observed_sha256 is None)
        or computed_expected_sha256 != expected_sha256
        or computed_observed_sha256 != observed_sha256
        or expected_sha256 != snapshot_sha256
        or (status == "match" and expected_sha256 != observed_sha256)
    ):
        raise BrokerStateError("broker reconciliation evidence is invalid")
    body = {
        "reconciliation_key": reconciliation_key,
        "account_id": stored_account,
        "status": status,
        "expected_sha256": expected_sha256,
        "observed_sha256": observed_sha256,
        "detail": detail,
        "observed_at": observed_at.isoformat(),
    }
    return ReconciliationEvidence(
        status=status,
        observed_at=observed_at,
        evidence_sha256=canonical_sha256(body),
    )


def assemble(
    con: duckdb.DuckDBPyConnection,
    adapter: BrokerAdapter,
    request: SubmitOrderRequest,
    *,
    reconciliation_key: str,
    market: MarketRiskEvidence,
    performance: PerformanceRiskEvidence,
) -> PreTradeSnapshot:
    """Assemble one hash-bound snapshot; current control always makes it halted."""
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    if not isinstance(market, MarketRiskEvidence):
        raise TypeError("market must be MarketRiskEvidence")
    if not isinstance(performance, PerformanceRiskEvidence):
        raise TypeError("performance must be PerformanceRiskEvidence")

    snapshot = broker_reconciliation.capture_snapshot(adapter, request.account_id)
    snapshot_payload = snapshot.comparable_payload()
    snapshot_sha256 = canonical_sha256(snapshot_payload)
    reconciliation = verified_reconciliation_evidence(
        con,
        reconciliation_key,
        account_id=request.account_id,
        snapshot_sha256=snapshot_sha256,
    )
    control = broker_risk_control.status(con, request.account_id)
    control_sha256 = canonical_sha256(asdict(control))
    market_sha256 = canonical_sha256(market.payload())
    performance_sha256 = canonical_sha256(performance.payload())
    closing_snapshot = broker_reconciliation.capture_snapshot(
        adapter,
        request.account_id,
    )
    if closing_snapshot.retained_payload() != snapshot.retained_payload():
        raise BrokerStateError(
            "broker state changed while the risk snapshot was assembled"
        )

    marks = {mark.symbol: mark.price for mark in market.position_marks}
    positions = {position.symbol: position for position in snapshot.positions}
    required_marks = {
        request.symbol,
        *(position.symbol for position in snapshot.positions),
        *(order.symbol for order in snapshot.open_orders),
    }
    if set(marks) != required_marks or marks[request.symbol] != market.quote_price:
        raise BrokerStateError(
            "market evidence marks do not exactly cover broker exposure"
        )
    held_quantity = (
        positions.get(request.symbol).quantity
        if request.symbol in positions
        else 0.0
    )
    symbol_exposure = sum(
        position.quantity * marks[position.symbol]
        for position in snapshot.positions
        if position.symbol == request.symbol
    )
    gross_exposure = sum(
        position.quantity * marks[position.symbol] for position in snapshot.positions
    )
    open_orders = snapshot.open_orders
    reserved_buy_notional = sum(
        (order.quantity - order.filled_quantity) * marks[order.symbol]
        for order in open_orders
        if order.side == "buy"
    )
    reserved_symbol_buy_notional = sum(
        (order.quantity - order.filled_quantity) * marks[order.symbol]
        for order in open_orders
        if order.side == "buy" and order.symbol == request.symbol
    )
    pending_sell_quantity = sum(
        order.quantity - order.filled_quantity
        for order in open_orders
        if order.side == "sell" and order.symbol == request.symbol
    )
    reserved_turnover_notional = sum(
        (order.quantity - order.filled_quantity) * marks[order.symbol]
        for order in open_orders
    )
    return PreTradeSnapshot(
        as_of=market.as_of,
        quote_date=market.quote_date,
        observed_at=market.observed_at,
        quote_at=market.quote_at,
        reconciliation_at=reconciliation.observed_at,
        account_snapshot_sha256=snapshot_sha256,
        reconciliation_sha256=reconciliation.evidence_sha256,
        market_state_sha256=market_sha256,
        performance_state_sha256=performance_sha256,
        operational_control_sha256=control_sha256,
        quote_price=market.quote_price,
        reference_price=market.reference_price,
        median_dollar_volume=market.median_dollar_volume,
        account_active=snapshot.account.active,
        margin_enabled=snapshot.account.margin_enabled,
        instrument_type=market.instrument_type,
        instrument_active=market.instrument_active,
        instrument_liquid=market.instrument_liquid,
        instrument_quarantined=market.instrument_quarantined,
        market_session_open=market.market_session_open,
        clock_synchronized=market.clock_synchronized,
        storage_healthy=market.storage_healthy,
        broker_healthy=market.broker_healthy,
        reconciled=reconciliation.status == "match",
        operational_halt=control.halted,
        corporate_action_clear=market.corporate_action_clear,
        currency=snapshot.account.currency,
        cash=snapshot.account.cash,
        buying_power=snapshot.account.buying_power,
        equity=snapshot.account.cash + gross_exposure,
        gross_exposure=gross_exposure,
        symbol_exposure=symbol_exposure,
        held_quantity=held_quantity,
        pending_sell_quantity=pending_sell_quantity,
        reserved_buy_notional=reserved_buy_notional,
        reserved_symbol_buy_notional=reserved_symbol_buy_notional,
        reserved_turnover_notional=reserved_turnover_notional,
        reserved_order_count=len(open_orders),
        daily_turnover=performance.daily_turnover,
        daily_order_count=performance.daily_order_count,
        daily_pnl=performance.daily_pnl,
        drawdown_fraction=performance.drawdown_fraction,
    )
