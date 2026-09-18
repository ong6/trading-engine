"""Read-only, deterministic reconciliation across broker-neutral adapters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from engine.lib import db
from engine.lib.provenance import canonical_sha256

from . import broker_ledger
from .broker_contract import (
    MAX_ACCOUNT_ROWS,
    MAX_FILL_BATCH,
    BrokerAccount,
    BrokerAdapter,
    BrokerAdapterError,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    BrokerStateError,
    FillBatch,
)

SNAPSHOT_SCHEMA_VERSION = 1
MAX_SNAPSHOT_FILLS = 10_000
MAX_DIFFERENCES = 1_000


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    account: BrokerAccount
    positions: tuple[BrokerPosition, ...]
    open_orders: tuple[BrokerOrder, ...]
    fills: tuple[BrokerFill, ...]

    def retained_payload(self) -> dict:
        """Exact adapter observations, including venue-native identifiers."""
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "account": asdict(self.account),
            "positions": [asdict(position) for position in self.positions],
            "open_orders": [
                {
                    **asdict(order),
                    "signal_date": order.signal_date.isoformat(),
                }
                for order in self.open_orders
            ],
            "fills": [
                {
                    **asdict(fill),
                    "occurred_on": fill.occurred_on.isoformat(),
                }
                for fill in self.fills
            ],
        }

    def comparable_payload(self) -> dict:
        """Economic state normalized across different account/native IDs."""
        retained = self.retained_payload()
        account = retained["account"]
        comparable_account = {
            key: account[key]
            for key in (
                "active",
                "currency",
                "cash",
                "buying_power",
                "initial_cash",
                "margin_enabled",
            )
        }
        positions = [
            {
                key: position[key]
                for key in ("symbol", "quantity", "average_price")
            }
            for position in retained["positions"]
        ]
        orders = [
            {
                key: order[key]
                for key in (
                    "idempotency_key",
                    "symbol",
                    "side",
                    "quantity",
                    "signal_date",
                    "status",
                    "rejection_reason",
                    "filled_quantity",
                    "order_type",
                    "time_in_force",
                    "extended_hours",
                )
            }
            for order in retained["open_orders"]
        ]
        fills = [
            {
                key: fill[key]
                for key in (
                    "idempotency_key",
                    "symbol",
                    "side",
                    "quantity",
                    "occurred_on",
                    "reference_price",
                    "price",
                    "total_cost_bps",
                )
            }
            for fill in retained["fills"]
        ]
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "account": comparable_account,
            "positions": positions,
            "open_orders": orders,
            "fills": fills,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationDifference:
    classification: str
    key: str
    field: str
    expected: Any
    observed: Any


def _difference_payload(difference: ReconciliationDifference) -> dict:
    return asdict(difference)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: str
    expected: BrokerSnapshot | None
    observed: BrokerSnapshot | None
    differences: tuple[ReconciliationDifference, ...]


def _validate_account_scope(
    account_id: str,
    positions: tuple[BrokerPosition, ...],
    orders: tuple[BrokerOrder, ...],
    fills: tuple[BrokerFill, ...],
) -> None:
    if any(item.account_id != account_id for item in (*positions, *orders, *fills)):
        raise BrokerStateError("adapter returned state from another account")


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise BrokerStateError(f"adapter returned duplicate {label}")


def _capture_once(
    adapter: BrokerAdapter,
    account_id: str,
    *,
    max_fills: int = MAX_SNAPSHOT_FILLS,
) -> BrokerSnapshot:
    """Read one complete, bounded adapter state."""
    if (
        isinstance(max_fills, bool)
        or not isinstance(max_fills, int)
        or not 1 <= max_fills <= MAX_SNAPSHOT_FILLS
    ):
        raise ValueError(
            f"maximum fills must be from 1 through {MAX_SNAPSHOT_FILLS}"
        )
    account = adapter.get_account(account_id)
    if not isinstance(account, BrokerAccount) or account.account_id != account_id:
        raise BrokerStateError("adapter returned a different account")
    positions = adapter.get_positions(account_id)
    orders = adapter.get_open_orders(account_id)
    if (
        not isinstance(positions, tuple)
        or len(positions) > MAX_ACCOUNT_ROWS
        or not all(isinstance(position, BrokerPosition) for position in positions)
    ):
        raise BrokerStateError("adapter position collection is invalid")
    if (
        not isinstance(orders, tuple)
        or len(orders) > MAX_ACCOUNT_ROWS
        or not all(isinstance(order, BrokerOrder) for order in orders)
        or any(
            order.status not in {"pending", "partially_filled"} for order in orders
        )
    ):
        raise BrokerStateError("adapter open-order collection is invalid")

    fills: list[BrokerFill] = []
    cursor = None
    seen_cursors: set[str] = set()
    while True:
        remaining = max_fills - len(fills)
        if remaining <= 0:
            raise BrokerStateError("adapter fill history exceeds reconciliation limit")
        batch = adapter.stream_fills(
            account_id,
            after=cursor,
            limit=min(MAX_FILL_BATCH, remaining),
        )
        if not isinstance(batch, FillBatch):
            raise BrokerStateError("adapter fill batch is invalid")
        fills.extend(batch.fills)
        if len(fills) > max_fills:
            raise BrokerStateError("adapter fill history exceeds reconciliation limit")
        if not batch.truncated:
            break
        if (
            batch.next_cursor is None
            or batch.next_cursor == cursor
            or batch.next_cursor in seen_cursors
            or not batch.fills
        ):
            raise BrokerStateError("adapter fill cursor did not advance")
        seen_cursors.add(batch.next_cursor)
        cursor = batch.next_cursor

    fill_tuple = tuple(fills)
    _validate_account_scope(account_id, positions, orders, fill_tuple)
    _require_unique([position.symbol for position in positions], "position symbols")
    _require_unique(
        [order.idempotency_key for order in orders],
        "open-order idempotency keys",
    )
    _require_unique(
        [order.broker_order_id for order in orders],
        "open-order identifiers",
    )
    _require_unique([fill.execution_id for fill in fill_tuple], "execution identifiers")
    return BrokerSnapshot(
        account=account,
        positions=tuple(sorted(positions, key=lambda item: item.symbol)),
        open_orders=tuple(sorted(orders, key=lambda item: item.idempotency_key)),
        fills=tuple(
            sorted(
                fill_tuple,
                key=lambda item: (
                    item.idempotency_key,
                    item.occurred_on,
                    item.execution_id,
                ),
            )
        ),
    )


def capture_snapshot(
    adapter: BrokerAdapter,
    account_id: str,
    *,
    max_fills: int = MAX_SNAPSHOT_FILLS,
) -> BrokerSnapshot:
    """Capture stable state or fail if it changes across the bounded read."""
    first = _capture_once(adapter, account_id, max_fills=max_fills)
    second = _capture_once(adapter, account_id, max_fills=max_fills)
    if first.retained_payload() != second.retained_payload():
        raise BrokerStateError("adapter state changed during snapshot capture")
    return second


def _difference(
    differences: list[ReconciliationDifference],
    classification: str,
    key: str,
    field: str,
    expected: Any,
    observed: Any,
) -> None:
    if len(differences) >= MAX_DIFFERENCES:
        raise BrokerStateError("reconciliation difference count exceeds limit")
    differences.append(
        ReconciliationDifference(
            classification=classification,
            key=key,
            field=field,
            expected=expected,
            observed=observed,
        )
    )


def _compare_mapping(
    differences: list[ReconciliationDifference],
    *,
    category: str,
    key: str,
    expected: dict,
    observed: dict,
) -> None:
    for field in sorted(expected):
        if expected[field] != observed[field]:
            _difference(
                differences,
                f"{category}_{field}",
                key,
                field,
                expected[field],
                observed[field],
            )


def _compare_keyed(
    differences: list[ReconciliationDifference],
    *,
    category: str,
    expected: list[dict],
    observed: list[dict],
    key_field: str,
) -> None:
    expected_by_key = {item[key_field]: item for item in expected}
    observed_by_key = {item[key_field]: item for item in observed}
    for key in sorted(expected_by_key.keys() - observed_by_key.keys()):
        _difference(
            differences,
            f"{category}_missing",
            str(key),
            category,
            expected_by_key[key],
            None,
        )
    for key in sorted(observed_by_key.keys() - expected_by_key.keys()):
        _difference(
            differences,
            f"{category}_extra",
            str(key),
            category,
            None,
            observed_by_key[key],
        )
    for key in sorted(expected_by_key.keys() & observed_by_key.keys()):
        _compare_mapping(
            differences,
            category=category,
            key=str(key),
            expected=expected_by_key[key],
            observed=observed_by_key[key],
        )


def _fills_by_intent(fills: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for fill in fills:
        grouped.setdefault(fill["idempotency_key"], []).append(fill)
    for intent_fills in grouped.values():
        intent_fills.sort(
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return grouped


def _compare_fills(
    differences: list[ReconciliationDifference],
    expected: list[dict],
    observed: list[dict],
) -> None:
    expected_by_intent = _fills_by_intent(expected)
    observed_by_intent = _fills_by_intent(observed)
    for key in sorted(expected_by_intent.keys() | observed_by_intent.keys()):
        expected_fills = expected_by_intent.get(key, [])
        observed_fills = observed_by_intent.get(key, [])
        if len(expected_fills) != len(observed_fills):
            _difference(
                differences,
                "fill_count",
                key,
                "fills",
                expected_fills,
                observed_fills,
            )
            continue
        for index, (expected_fill, observed_fill) in enumerate(
            zip(expected_fills, observed_fills, strict=True)
        ):
            _compare_mapping(
                differences,
                category="fill",
                key=f"{key}:{index}",
                expected=expected_fill,
                observed=observed_fill,
            )


def compare(
    expected: BrokerSnapshot,
    observed: BrokerSnapshot,
) -> tuple[ReconciliationDifference, ...]:
    """Classify exact economic differences between two adapter snapshots."""
    expected_payload = expected.comparable_payload()
    observed_payload = observed.comparable_payload()
    differences: list[ReconciliationDifference] = []
    _compare_mapping(
        differences,
        category="account",
        key="account",
        expected=expected_payload["account"],
        observed=observed_payload["account"],
    )
    _compare_keyed(
        differences,
        category="position",
        expected=expected_payload["positions"],
        observed=observed_payload["positions"],
        key_field="symbol",
    )
    _compare_keyed(
        differences,
        category="order",
        expected=expected_payload["open_orders"],
        observed=observed_payload["open_orders"],
        key_field="idempotency_key",
    )
    _compare_fills(
        differences,
        expected_payload["fills"],
        observed_payload["fills"],
    )
    return tuple(differences)


def _snapshot_key(reconciliation_key: str, role: str) -> str:
    digest = canonical_sha256(
        {
            "reconciliation_key": reconciliation_key,
            "role": role,
        }
    )
    return f"snapshot:{digest}"


def _unavailable_result(
    con: duckdb.DuckDBPyConnection,
    *,
    reconciliation_key: str,
    expected_account_id: str,
    observed_account_id: str,
    stage: str,
    error: BrokerAdapterError,
    expected: BrokerSnapshot | None,
) -> ReconciliationResult:
    detail = json.dumps(
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "difference_count": 1,
            "classifications": [f"{stage}_unavailable"],
            "error_type": type(error).__name__,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    difference = ReconciliationDifference(
        classification=f"{stage}_unavailable",
        key=observed_account_id if stage == "observed" else expected_account_id,
        field="account",
        expected="available",
        observed="unavailable",
    )
    broker_ledger.init_broker_ledger_schema(con)
    with db.transaction(con):
        if expected is not None:
            broker_ledger.record_snapshot(
                con,
                snapshot_key=_snapshot_key(reconciliation_key, "expected"),
                reconciliation_key=reconciliation_key,
                role="expected",
                account_id=expected_account_id,
                snapshot=expected.retained_payload(),
            )
        broker_ledger.record_reconciliation(
            con,
            reconciliation_key=reconciliation_key,
            account_id=expected_account_id,
            status="unavailable",
            expected=(
                None if expected is None else expected.comparable_payload()
            ),
            observed=None,
            detail=detail,
        )
        broker_ledger.record_reconciliation_differences(
            con,
            reconciliation_key=reconciliation_key,
            differences=(_difference_payload(difference),),
        )
    return ReconciliationResult(
        status="unavailable",
        expected=expected,
        observed=None,
        differences=(difference,),
    )


def reconcile(
    con: duckdb.DuckDBPyConnection,
    *,
    reconciliation_key: str,
    expected_adapter: BrokerAdapter,
    expected_account_id: str,
    observed_adapter: BrokerAdapter,
    observed_account_id: str,
) -> ReconciliationResult:
    """Capture, compare, and durably retain one reconciliation result."""
    try:
        expected = capture_snapshot(expected_adapter, expected_account_id)
    except BrokerAdapterError as exc:
        return _unavailable_result(
            con,
            reconciliation_key=reconciliation_key,
            expected_account_id=expected_account_id,
            observed_account_id=observed_account_id,
            stage="expected",
            error=exc,
            expected=None,
        )
    try:
        observed = capture_snapshot(observed_adapter, observed_account_id)
    except BrokerAdapterError as exc:
        return _unavailable_result(
            con,
            reconciliation_key=reconciliation_key,
            expected_account_id=expected_account_id,
            observed_account_id=observed_account_id,
            stage="observed",
            error=exc,
            expected=expected,
        )
    try:
        expected_after = capture_snapshot(expected_adapter, expected_account_id)
    except BrokerAdapterError as exc:
        return _unavailable_result(
            con,
            reconciliation_key=reconciliation_key,
            expected_account_id=expected_account_id,
            observed_account_id=observed_account_id,
            stage="expected",
            error=exc,
            expected=None,
        )
    if expected.retained_payload() != expected_after.retained_payload():
        raise BrokerStateError(
            "expected adapter state changed during cross-venue reconciliation"
        )
    differences = compare(expected, observed)
    status = "match" if not differences else "difference"
    classifications = sorted({item.classification for item in differences})
    detail = json.dumps(
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "difference_count": len(differences),
            "classifications": classifications,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    broker_ledger.init_broker_ledger_schema(con)
    with db.transaction(con):
        broker_ledger.record_snapshot(
            con,
            snapshot_key=_snapshot_key(reconciliation_key, "expected"),
            reconciliation_key=reconciliation_key,
            role="expected",
            account_id=expected_account_id,
            snapshot=expected.retained_payload(),
        )
        broker_ledger.record_snapshot(
            con,
            snapshot_key=_snapshot_key(reconciliation_key, "observed"),
            reconciliation_key=reconciliation_key,
            role="observed",
            account_id=observed_account_id,
            snapshot=observed.retained_payload(),
        )
        broker_ledger.record_reconciliation(
            con,
            reconciliation_key=reconciliation_key,
            account_id=expected_account_id,
            status=status,
            expected=expected.comparable_payload(),
            observed=observed.comparable_payload(),
            detail=detail,
        )
        broker_ledger.record_reconciliation_differences(
            con,
            reconciliation_key=reconciliation_key,
            differences=tuple(_difference_payload(item) for item in differences),
        )
    return ReconciliationResult(
        status=status,
        expected=expected,
        observed=observed,
        differences=differences,
    )
