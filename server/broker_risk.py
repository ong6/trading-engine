"""Pure, fail-closed pre-trade risk decisions for broker-neutral intents.

The evaluator has no database, model, network, clock, or adapter dependency.
Callers must supply a complete immutable snapshot. A passing decision is
evidence only; this module cannot submit, cancel, or otherwise mutate an order.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from engine.lib.provenance import canonical_sha256

from .broker_contract import SubmitOrderRequest, require_identifier, require_symbol

RISK_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
GATE_NAMES = (
    "identity",
    "account",
    "instrument",
    "order_constraints",
    "market_session",
    "dependency_health",
    "reconciliation",
    "operational_control",
    "corporate_action",
    "market_data",
    "order_notional",
    "cash",
    "capital_allocation",
    "gross_exposure",
    "position_concentration",
    "daily_turnover",
    "daily_order_count",
    "liquidity_participation",
    "daily_loss",
    "drawdown",
)


class RiskContractError(ValueError):
    """A risk policy or snapshot violates the closed contract."""


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


def _fraction(value: object, label: str) -> float:
    number = _nonnegative(value, label)
    if number > 1:
        raise RiskContractError(f"{label} must be from zero through one")
    return number


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RiskContractError(f"{label} must be a lowercase SHA-256")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise RiskContractError(f"{label} must be boolean")
    return value


def _validate_policy_symbols(policy: RiskPolicy) -> None:
    if (
        not isinstance(policy.allowed_symbols, tuple)
        or not policy.allowed_symbols
        or policy.allowed_symbols != tuple(sorted(set(policy.allowed_symbols)))
    ):
        raise RiskContractError("allowed symbols must be a sorted unique tuple")
    try:
        for symbol in policy.allowed_symbols:
            require_symbol(symbol)
    except ValueError as exc:
        raise RiskContractError(str(exc)) from exc


def _normalize_policy_limits(policy: RiskPolicy) -> None:
    for field, validator, label in (
        ("capital_ceiling", _positive, "capital ceiling"),
        ("max_gross_exposure", _positive, "gross exposure ceiling"),
        ("max_position_fraction", _fraction, "position fraction ceiling"),
        ("max_order_notional", _positive, "order-notional ceiling"),
        ("max_daily_turnover", _positive, "daily turnover ceiling"),
        ("max_participation", _fraction, "participation ceiling"),
        ("max_daily_loss_fraction", _fraction, "daily loss ceiling"),
        ("max_drawdown_fraction", _fraction, "drawdown ceiling"),
        (
            "max_reference_deviation_fraction",
            _fraction,
            "reference deviation ceiling",
        ),
    ):
        object.__setattr__(policy, field, validator(getattr(policy, field), label))
    if policy.max_order_notional > policy.capital_ceiling:
        raise RiskContractError("order-notional ceiling exceeds capital ceiling")
    if policy.max_gross_exposure > policy.capital_ceiling:
        raise RiskContractError("gross exposure ceiling exceeds capital ceiling")
    if policy.max_daily_turnover < policy.max_order_notional:
        raise RiskContractError("daily turnover ceiling is below order-notional ceiling")


def _validate_policy_counts(policy: RiskPolicy) -> None:
    if (
        isinstance(policy.max_daily_orders, bool)
        or not isinstance(policy.max_daily_orders, int)
        or policy.max_daily_orders <= 0
    ):
        raise RiskContractError("daily order-count ceiling must be positive")
    for field in (
        "max_quote_age_seconds",
        "max_reconciliation_age_seconds",
        "decision_ttl_seconds",
    ):
        value = getattr(policy, field)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 300:
            raise RiskContractError(f"{field.replace('_', ' ')} must be from 1 through 300")


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    policy_id: str
    account_id: str
    strategy_id: str
    release_sha256: str
    strategy_config_sha256: str
    execution_profile_id: str
    execution_profile_sha256: str
    allowed_symbols: tuple[str, ...]
    capital_ceiling: float
    max_gross_exposure: float
    max_position_fraction: float
    max_order_notional: float
    max_daily_turnover: float
    max_daily_orders: int
    max_participation: float
    max_daily_loss_fraction: float
    max_drawdown_fraction: float
    max_reference_deviation_fraction: float
    max_quote_age_seconds: int
    max_reconciliation_age_seconds: int
    decision_ttl_seconds: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.policy_id, "risk policy identifier"),
            (self.account_id, "risk account identifier"),
            (self.strategy_id, "risk strategy identifier"),
            (self.execution_profile_id, "risk execution profile identifier"),
        ):
            try:
                require_identifier(value, label)
            except ValueError as exc:
                raise RiskContractError(str(exc)) from exc
        for value, label in (
            (self.release_sha256, "release identity"),
            (self.strategy_config_sha256, "strategy config identity"),
            (self.execution_profile_sha256, "execution profile identity"),
        ):
            _sha256(value, label)
        _validate_policy_symbols(self)
        _normalize_policy_limits(self)
        _validate_policy_counts(self)


@dataclass(frozen=True, slots=True)
class RiskIdentity:
    policy_id: str
    strategy_id: str
    release_sha256: str
    strategy_config_sha256: str
    execution_profile_id: str
    execution_profile_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.policy_id, "risk policy identifier"),
            (self.strategy_id, "risk strategy identifier"),
            (self.execution_profile_id, "risk execution profile identifier"),
        ):
            try:
                require_identifier(value, label)
            except ValueError as exc:
                raise RiskContractError(str(exc)) from exc
        for value, label in (
            (self.release_sha256, "release identity"),
            (self.strategy_config_sha256, "strategy config identity"),
            (self.execution_profile_sha256, "execution profile identity"),
        ):
            _sha256(value, label)


@dataclass(frozen=True, slots=True)
class PreTradeSnapshot:
    as_of: date
    quote_date: date
    observed_at: datetime
    quote_at: datetime
    reconciliation_at: datetime
    account_snapshot_sha256: str
    reconciliation_sha256: str
    market_state_sha256: str
    performance_state_sha256: str
    operational_control_sha256: str
    quote_price: float
    reference_price: float
    median_dollar_volume: float | None
    account_active: bool
    margin_enabled: bool
    instrument_type: str
    instrument_active: bool
    instrument_liquid: bool
    instrument_quarantined: bool
    market_session_open: bool
    clock_synchronized: bool
    storage_healthy: bool
    broker_healthy: bool
    reconciled: bool
    operational_halt: bool
    corporate_action_clear: bool
    currency: str
    cash: float
    buying_power: float
    equity: float
    gross_exposure: float
    symbol_exposure: float
    held_quantity: float
    pending_sell_quantity: float
    reserved_buy_notional: float
    reserved_symbol_buy_notional: float
    reserved_turnover_notional: float
    reserved_order_count: int
    daily_turnover: float
    daily_order_count: int
    daily_pnl: float
    drawdown_fraction: float

    def __post_init__(self) -> None:
        if type(self.as_of) is not date or type(self.quote_date) is not date:
            raise RiskContractError("risk dates are invalid")
        for field in ("observed_at", "quote_at", "reconciliation_at"):
            timestamp = getattr(self, field)
            if (
                type(timestamp) is not datetime
                or timestamp.utcoffset() is None
                or timestamp.utcoffset().total_seconds() != 0
            ):
                raise RiskContractError(f"{field.replace('_', ' ')} must be UTC")
        for field in (
            "account_snapshot_sha256",
            "reconciliation_sha256",
            "market_state_sha256",
            "performance_state_sha256",
            "operational_control_sha256",
        ):
            _sha256(getattr(self, field), field.replace("_", " "))
        for field in (
            "account_active",
            "margin_enabled",
            "instrument_active",
            "instrument_liquid",
            "instrument_quarantined",
            "market_session_open",
            "clock_synchronized",
            "storage_healthy",
            "broker_healthy",
            "reconciled",
            "operational_halt",
            "corporate_action_clear",
        ):
            _boolean(getattr(self, field), field.replace("_", " "))
        if self.instrument_type not in {"equity", "etf"}:
            raise RiskContractError("instrument type must be equity or etf")
        if self.currency != "USD":
            raise RiskContractError("risk currency must be USD")
        for field in (
            "quote_price",
            "reference_price",
            "equity",
        ):
            object.__setattr__(self, field, _positive(getattr(self, field), field))
        if self.median_dollar_volume is not None:
            object.__setattr__(
                self,
                "median_dollar_volume",
                _positive(self.median_dollar_volume, "median dollar volume"),
            )
        for field in (
            "cash",
            "buying_power",
            "gross_exposure",
            "symbol_exposure",
            "held_quantity",
            "pending_sell_quantity",
            "reserved_buy_notional",
            "reserved_symbol_buy_notional",
            "reserved_turnover_notional",
            "daily_turnover",
        ):
            object.__setattr__(self, field, _nonnegative(getattr(self, field), field))
        for field in ("reserved_order_count", "daily_order_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RiskContractError(f"{field.replace('_', ' ')} must be nonnegative")
        if (
            isinstance(self.daily_pnl, bool)
            or not isinstance(self.daily_pnl, (int, float))
            or not math.isfinite(self.daily_pnl)
        ):
            raise RiskContractError("daily P&L must be finite")
        object.__setattr__(
            self,
            "daily_pnl",
            float(self.daily_pnl),
        )
        object.__setattr__(
            self,
            "drawdown_fraction",
            _fraction(self.drawdown_fraction, "drawdown fraction"),
        )


def _gate(name: str, passed: bool, detail: str) -> dict:
    if name not in GATE_NAMES or not detail or len(detail) > 512:
        raise RiskContractError("risk gate is invalid")
    return {"name": name, "status": "pass" if passed else "fail", "detail": detail}


def _snapshot_payload(snapshot: PreTradeSnapshot) -> dict:
    payload = asdict(snapshot)
    payload["as_of"] = snapshot.as_of.isoformat()
    payload["quote_date"] = snapshot.quote_date.isoformat()
    payload["observed_at"] = snapshot.observed_at.isoformat()
    payload["quote_at"] = snapshot.quote_at.isoformat()
    payload["reconciliation_at"] = snapshot.reconciliation_at.isoformat()
    return payload


def _request_payload(request: SubmitOrderRequest) -> dict:
    payload = asdict(request)
    payload["signal_date"] = request.signal_date.isoformat()
    return payload


def _policy_payload(policy: RiskPolicy) -> dict:
    payload = asdict(policy)
    payload["allowed_symbols"] = list(policy.allowed_symbols)
    return payload


def evaluate(
    policy: RiskPolicy,
    identity: RiskIdentity,
    request: SubmitOrderRequest,
    snapshot: PreTradeSnapshot,
) -> dict:
    """Return a complete, hash-bound pass/fail decision without side effects."""
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (policy, RiskPolicy),
            (identity, RiskIdentity),
            (request, SubmitOrderRequest),
            (snapshot, PreTradeSnapshot),
        )
    ):
        raise TypeError("risk evaluation inputs violate the typed contract")

    notional = request.quantity * snapshot.reference_price
    signed_notional = notional if request.side == "buy" else -notional
    resulting_gross = (
        snapshot.gross_exposure + snapshot.reserved_buy_notional + signed_notional
    )
    resulting_symbol = (
        snapshot.symbol_exposure
        + snapshot.reserved_symbol_buy_notional
        + signed_notional
    )
    available_to_sell = max(
        0.0,
        snapshot.held_quantity - snapshot.pending_sell_quantity,
    )
    participation = (
        None
        if snapshot.median_dollar_volume is None
        else notional / snapshot.median_dollar_volume
    )
    reference_deviation = abs(
        snapshot.reference_price / snapshot.quote_price - 1.0
    )
    quote_age_seconds = (snapshot.observed_at - snapshot.quote_at).total_seconds()
    reconciliation_age_seconds = (
        snapshot.observed_at - snapshot.reconciliation_at
    ).total_seconds()
    daily_loss_fraction = max(0.0, -snapshot.daily_pnl / snapshot.equity)
    identity_matches = (
        request.account_id == policy.account_id
        and identity.policy_id == policy.policy_id
        and identity.strategy_id == policy.strategy_id
        and identity.release_sha256 == policy.release_sha256
        and identity.strategy_config_sha256 == policy.strategy_config_sha256
        and identity.execution_profile_id == policy.execution_profile_id
        and identity.execution_profile_sha256 == policy.execution_profile_sha256
    )
    instrument_allowed = (
        request.symbol in policy.allowed_symbols
        and snapshot.instrument_type in {"equity", "etf"}
        and snapshot.instrument_active
        and snapshot.instrument_liquid
        and not snapshot.instrument_quarantined
    )
    inventory_consistent = snapshot.pending_sell_quantity <= snapshot.held_quantity
    close_only = inventory_consistent and (
        request.side == "buy" or request.quantity <= available_to_sell
    )
    order_constraints = (
        request.order_type == "market"
        and request.time_in_force == "day"
        and request.extended_hours is False
        and close_only
    )
    gates = [
        _gate("identity", identity_matches, "all immutable policy identities must match"),
        _gate(
            "account",
            (
                snapshot.account_active
                and not snapshot.margin_enabled
                and snapshot.currency == "USD"
                and snapshot.buying_power <= snapshot.cash
            ),
            "account must be active, USD cash-only, and have no margin buying power",
        ),
        _gate(
            "instrument",
            instrument_allowed,
            "symbol must be allowlisted, active, liquid, and not quarantined",
        ),
        _gate(
            "order_constraints",
            order_constraints,
            "market/day/regular-session and close-only sell constraints",
        ),
        _gate(
            "market_session",
            (
                snapshot.market_session_open
                and snapshot.as_of == request.signal_date
                and snapshot.observed_at.date() == snapshot.as_of
            ),
            "market session must be open and observed on the signal date",
        ),
        _gate(
            "dependency_health",
            (
                snapshot.clock_synchronized
                and snapshot.storage_healthy
                and snapshot.broker_healthy
            ),
            "clock, storage, and broker health must all pass",
        ),
        _gate(
            "reconciliation",
            (
                snapshot.reconciled
                and 0
                <= reconciliation_age_seconds
                <= policy.max_reconciliation_age_seconds
            ),
            (
                "cash, positions, and open orders must be reconciled; "
                f"evidence age {reconciliation_age_seconds:.3f}s"
            ),
        ),
        _gate(
            "operational_control",
            not snapshot.operational_halt,
            "durable account halt must be clear",
        ),
        _gate(
            "corporate_action",
            snapshot.corporate_action_clear,
            "instrument must have no unresolved corporate action",
        ),
        _gate(
            "market_data",
            (
                snapshot.quote_date == snapshot.as_of
                and snapshot.quote_at.date() == snapshot.quote_date
                and 0 <= quote_age_seconds <= policy.max_quote_age_seconds
                and reference_deviation <= policy.max_reference_deviation_fraction
            ),
            (
                f"quote date {snapshot.quote_date.isoformat()}, age "
                f"{quote_age_seconds:.3f}s, and reference deviation "
                f"{reference_deviation:.8f}"
            ),
        ),
        _gate(
            "order_notional",
            notional <= policy.max_order_notional,
            f"notional {notional:.8f} vs ceiling {policy.max_order_notional:.8f}",
        ),
        _gate(
            "cash",
            request.side == "sell"
            or snapshot.reserved_buy_notional + notional
            <= min(snapshot.cash, snapshot.buying_power),
            "reserved and proposed buy notional must not exceed cash or buying power",
        ),
        _gate(
            "capital_allocation",
            resulting_gross <= policy.capital_ceiling,
            (
                f"resulting gross {resulting_gross:.8f} vs capital ceiling "
                f"{policy.capital_ceiling:.8f}"
            ),
        ),
        _gate(
            "gross_exposure",
            0 <= resulting_gross <= policy.max_gross_exposure,
            (
                f"resulting gross {resulting_gross:.8f} vs exposure ceiling "
                f"{policy.max_gross_exposure:.8f}"
            ),
        ),
        _gate(
            "position_concentration",
            0 <= resulting_symbol <= policy.max_position_fraction * snapshot.equity,
            (
                f"resulting symbol exposure {resulting_symbol:.8f} vs ceiling "
                f"{policy.max_position_fraction * snapshot.equity:.8f}"
            ),
        ),
        _gate(
            "daily_turnover",
            snapshot.daily_turnover
            + snapshot.reserved_turnover_notional
            + notional
            <= policy.max_daily_turnover,
            (
                "resulting turnover "
                f"{snapshot.daily_turnover + snapshot.reserved_turnover_notional + notional:.8f} "
                "vs "
                f"ceiling {policy.max_daily_turnover:.8f}"
            ),
        ),
        _gate(
            "daily_order_count",
            snapshot.daily_order_count + snapshot.reserved_order_count + 1
            <= policy.max_daily_orders,
            (
                "resulting order count "
                f"{snapshot.daily_order_count + snapshot.reserved_order_count + 1} "
                "vs ceiling "
                f"{policy.max_daily_orders}"
            ),
        ),
        _gate(
            "liquidity_participation",
            participation is not None and participation <= policy.max_participation,
            (
                "median dollar volume is unavailable"
                if participation is None
                else f"participation {participation:.8f} vs ceiling "
                f"{policy.max_participation:.8f}"
            ),
        ),
        _gate(
            "daily_loss",
            daily_loss_fraction <= policy.max_daily_loss_fraction,
            (
                f"daily loss fraction {daily_loss_fraction:.8f} vs ceiling "
                f"{policy.max_daily_loss_fraction:.8f}"
            ),
        ),
        _gate(
            "drawdown",
            snapshot.drawdown_fraction <= policy.max_drawdown_fraction,
            (
                f"drawdown {snapshot.drawdown_fraction:.8f} vs ceiling "
                f"{policy.max_drawdown_fraction:.8f}"
            ),
        ),
    ]
    if tuple(gate["name"] for gate in gates) != GATE_NAMES:
        raise RiskContractError("risk gate contract changed")
    failed_gates = [gate["name"] for gate in gates if gate["status"] == "fail"]
    policy_payload = _policy_payload(policy)
    identity_payload = asdict(identity)
    request_payload = _request_payload(request)
    snapshot_payload = _snapshot_payload(snapshot)
    evaluated_at = snapshot.observed_at.isoformat()
    expires_at = (
        snapshot.observed_at + timedelta(seconds=policy.decision_ttl_seconds)
    ).isoformat()
    body = {
        "schema_version": RISK_SCHEMA_VERSION,
        "status": "pass" if not failed_gates else "fail",
        "execution_authority": "none",
        "policy_sha256": canonical_sha256(policy_payload),
        "identity_sha256": canonical_sha256(identity_payload),
        "request_sha256": canonical_sha256(request_payload),
        "snapshot_sha256": canonical_sha256(snapshot_payload),
        "evaluated_at": evaluated_at,
        "expires_at": expires_at,
        "policy": policy_payload,
        "identity": identity_payload,
        "request": request_payload,
        "snapshot": snapshot_payload,
        "computed": {
            "notional": notional,
            "resulting_gross_exposure": resulting_gross,
            "resulting_symbol_exposure": resulting_symbol,
            "available_to_sell": available_to_sell,
            "reserved_buy_notional": snapshot.reserved_buy_notional,
            "reserved_symbol_buy_notional": snapshot.reserved_symbol_buy_notional,
            "reserved_turnover_notional": snapshot.reserved_turnover_notional,
            "reserved_order_count": snapshot.reserved_order_count,
            "participation": participation,
            "reference_deviation_fraction": reference_deviation,
            "quote_age_seconds": quote_age_seconds,
            "reconciliation_age_seconds": reconciliation_age_seconds,
            "daily_loss_fraction": daily_loss_fraction,
        },
        "gates": gates,
        "failed_gates": failed_gates,
    }
    return {
        **body,
        "decision_sha256": canonical_sha256(body),
    }


def verify(decision: object) -> dict:
    """Validate a retained risk decision and its self-contained hash."""
    if not isinstance(decision, dict):
        raise RiskContractError("risk decision is invalid")
    expected_fields = {
        "schema_version",
        "status",
        "execution_authority",
        "policy_sha256",
        "identity_sha256",
        "request_sha256",
        "snapshot_sha256",
        "evaluated_at",
        "expires_at",
        "policy",
        "identity",
        "request",
        "snapshot",
        "computed",
        "gates",
        "failed_gates",
        "decision_sha256",
    }
    if (
        set(decision) != expected_fields
        or decision["schema_version"] != RISK_SCHEMA_VERSION
        or decision["status"] not in {"pass", "fail"}
        or decision["execution_authority"] != "none"
    ):
        raise RiskContractError("risk decision shape is invalid")
    for field in (
        "policy_sha256",
        "identity_sha256",
        "request_sha256",
        "snapshot_sha256",
        "decision_sha256",
    ):
        _sha256(decision[field], field.replace("_", " "))
    try:
        evaluated_at = datetime.fromisoformat(decision["evaluated_at"])
        expires_at = datetime.fromisoformat(decision["expires_at"])
    except (TypeError, ValueError) as exc:
        raise RiskContractError("risk decision validity interval is invalid") from exc
    if (
        evaluated_at.utcoffset() is None
        or evaluated_at.utcoffset().total_seconds() != 0
        or expires_at.utcoffset() is None
        or expires_at.utcoffset().total_seconds() != 0
        or expires_at <= evaluated_at
    ):
        raise RiskContractError("risk decision validity interval is invalid")
    for payload_field, hash_field in (
        ("policy", "policy_sha256"),
        ("identity", "identity_sha256"),
        ("request", "request_sha256"),
        ("snapshot", "snapshot_sha256"),
    ):
        if (
            not isinstance(decision[payload_field], dict)
            or canonical_sha256(decision[payload_field]) != decision[hash_field]
        ):
            raise RiskContractError(f"risk decision {payload_field} is invalid")
    computed = decision["computed"]
    expected_computed_fields = {
        "notional",
        "resulting_gross_exposure",
        "resulting_symbol_exposure",
        "available_to_sell",
        "reserved_buy_notional",
        "reserved_symbol_buy_notional",
        "reserved_turnover_notional",
        "reserved_order_count",
        "participation",
        "reference_deviation_fraction",
        "quote_age_seconds",
        "reconciliation_age_seconds",
        "daily_loss_fraction",
    }
    if not isinstance(computed, dict) or set(computed) != expected_computed_fields:
        raise RiskContractError("risk decision computed values are invalid")
    for field, value in computed.items():
        if value is None and field == "participation":
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise RiskContractError("risk decision computed values are invalid")
    gates = decision["gates"]
    if (
        not isinstance(gates, list)
        or len(gates) != len(GATE_NAMES)
        or tuple(gate.get("name") for gate in gates if isinstance(gate, dict))
        != GATE_NAMES
        or any(
            set(gate) != {"name", "status", "detail"}
            or gate["status"] not in {"pass", "fail"}
            or not isinstance(gate["detail"], str)
            or not gate["detail"]
            or len(gate["detail"]) > 512
            for gate in gates
        )
    ):
        raise RiskContractError("risk decision gates are invalid")
    failed = [gate["name"] for gate in gates if gate["status"] == "fail"]
    if decision["failed_gates"] != failed or decision["status"] != (
        "fail" if failed else "pass"
    ):
        raise RiskContractError("risk decision outcome is inconsistent")
    body = {key: value for key, value in decision.items() if key != "decision_sha256"}
    if canonical_sha256(body) != decision["decision_sha256"]:
        raise RiskContractError("risk decision hash does not match")
    try:
        policy_payload = dict(decision["policy"])
        allowed_symbols = policy_payload.get("allowed_symbols")
        if not isinstance(allowed_symbols, (list, tuple)):
            raise RiskContractError("risk decision policy is invalid")
        policy_payload["allowed_symbols"] = tuple(allowed_symbols)
        policy = RiskPolicy(**policy_payload)
        identity = RiskIdentity(**decision["identity"])
        request_payload = dict(decision["request"])
        request_payload["signal_date"] = datetime.strptime(
            request_payload["signal_date"], "%Y-%m-%d"
        ).date()
        request = SubmitOrderRequest(**request_payload)
        snapshot_payload = dict(decision["snapshot"])
        snapshot_payload["as_of"] = datetime.strptime(
            snapshot_payload["as_of"], "%Y-%m-%d"
        ).date()
        snapshot_payload["quote_date"] = datetime.strptime(
            snapshot_payload["quote_date"], "%Y-%m-%d"
        ).date()
        snapshot_payload["observed_at"] = datetime.fromisoformat(
            snapshot_payload["observed_at"]
        )
        snapshot_payload["quote_at"] = datetime.fromisoformat(
            snapshot_payload["quote_at"]
        )
        snapshot_payload["reconciliation_at"] = datetime.fromisoformat(
            snapshot_payload["reconciliation_at"]
        )
        snapshot = PreTradeSnapshot(**snapshot_payload)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, RiskContractError):
            raise
        raise RiskContractError("risk decision inputs are invalid") from exc
    if evaluate(policy, identity, request, snapshot) != decision:
        raise RiskContractError("risk decision does not recompute")
    return decision
