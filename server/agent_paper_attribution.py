"""Read-only verification of isolated agent/hybrid simulator attribution.

This module recognizes retained attribution evidence and defines an explicit,
unwired initializer for only its two empty attribution ledgers. It does not
create a portfolio, order, fill, equity row, or scheduler route. Until both
tables exist and every retained row verifies, return attribution remains
unavailable.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from sim.strategies.configs import config_by_id

from .json_utils import loads_object
from .read_model_utils import require_public_nonnegative_integer

BOOK_ATTRIBUTION_TABLE = "agent_paper_book_attribution"
ORDER_ATTRIBUTION_TABLE = "agent_paper_order_attribution"
BOOK_ATTRIBUTION_SCHEMA = (
    ("portfolio_id", "VARCHAR"),
    ("policy_id", "VARCHAR"),
    ("policy_registration_sha256", "VARCHAR"),
    ("mode", "VARCHAR"),
    ("contract_payload", "VARCHAR"),
    ("contract_sha256", "VARCHAR"),
    ("recorded_at", "TIMESTAMP"),
)
ORDER_ATTRIBUTION_SCHEMA = (
    ("order_id", "BIGINT"),
    ("portfolio_id", "VARCHAR"),
    ("policy_id", "VARCHAR"),
    ("policy_registration_sha256", "VARCHAR"),
    ("mode", "VARCHAR"),
    ("attempt_id", "BIGINT"),
    ("decision_order_sequence", "INTEGER"),
    ("decision_window", "VARCHAR"),
    ("terminal_event_sha256", "VARCHAR"),
    ("decision_evidence_sha256", "VARCHAR"),
    ("attribution_payload", "VARCHAR"),
    ("attribution_sha256", "VARCHAR"),
    ("recorded_at", "TIMESTAMP"),
)
BOOK_ATTRIBUTION_PRIMARY_KEY = ("portfolio_id",)
BOOK_ATTRIBUTION_UNIQUE_KEYS = (("policy_id",),)
ORDER_ATTRIBUTION_PRIMARY_KEY = ("order_id",)
ORDER_ATTRIBUTION_UNIQUE_KEYS = (
    ("policy_id", "attempt_id", "decision_order_sequence"),
)
CONTRACT_SCHEMA_VERSION = 1
ORDER_ATTRIBUTION_SCHEMA_VERSION = 1
STATUS_NO_PORTFOLIO = "unavailable_no_isolated_paper_portfolio"
STATUS_NO_CONTRACT = "unavailable_no_persisted_attribution_contract"
STATUS_NO_EQUITY = "unavailable_no_attributable_equity"
STATUS_AVAILABLE = "available"
MAX_ATTRIBUTED_ORDERS = 10_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperAttributionError(ValueError):
    """Persisted isolated-book attribution is malformed or inconsistent."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create only the two attribution ledgers; never create or activate a book."""
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {BOOK_ATTRIBUTION_TABLE} (
            portfolio_id               VARCHAR PRIMARY KEY,
            policy_id                  VARCHAR NOT NULL UNIQUE,
            policy_registration_sha256 VARCHAR NOT NULL,
            mode                       VARCHAR NOT NULL,
            contract_payload           VARCHAR NOT NULL,
            contract_sha256            VARCHAR NOT NULL,
            recorded_at                TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ORDER_ATTRIBUTION_TABLE} (
            order_id                   BIGINT PRIMARY KEY,
            portfolio_id               VARCHAR NOT NULL,
            policy_id                  VARCHAR NOT NULL,
            policy_registration_sha256 VARCHAR NOT NULL,
            mode                       VARCHAR NOT NULL,
            attempt_id                 BIGINT NOT NULL,
            decision_order_sequence    INTEGER NOT NULL,
            decision_window            VARCHAR NOT NULL,
            terminal_event_sha256       VARCHAR NOT NULL,
            decision_evidence_sha256    VARCHAR NOT NULL,
            attribution_payload         VARCHAR NOT NULL,
            attribution_sha256          VARCHAR NOT NULL,
            recorded_at                 TIMESTAMP NOT NULL,
            UNIQUE (policy_id, attempt_id, decision_order_sequence)
        )
        """
    )


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperAttributionError(f"paper attribution {field} is invalid")
    return value


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime:
        raise PaperAttributionError(f"paper attribution {field} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if aware.utcoffset() is None or aware.utcoffset().total_seconds() != 0:
        raise PaperAttributionError(f"paper attribution {field} is invalid")
    return aware.astimezone(timezone.utc)


def _finite(value: object, field: str, *, nonnegative: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (nonnegative and value < 0)
    ):
        raise PaperAttributionError(f"paper attribution {field} is invalid")
    return float(value)


def _empty(policy: dict, *, status: str, portfolio_created: bool) -> dict:
    return {
        "status": status,
        "portfolio_id": policy["reserved_portfolio_id"],
        "portfolio_created": portfolio_created,
        "persisted_contract_present": False,
        "book_contract_sha256": None,
        "attribution_start_date": None,
        "order_count": 0,
        "attributed_order_count": 0,
        "fill_count": 0,
        "position_count": 0,
        "dividend_count": 0,
        "equity_observation_count": 0,
        "equity_start_date": None,
        "equity_end_date": None,
        "equity_path_sha256": None,
        "comparison_portfolio_ids": [
            policy["attribution"]["algorithm_control_id"],
            policy["attribution"]["strategy_control_id"],
        ],
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
    }


def expected_book_contract(policy: dict, attribution_start_date: date) -> dict:
    """Return the exact config/contract envelope accepted by the verifier."""
    if type(attribution_start_date) is not date:
        raise TypeError("attribution_start_date must be a date")
    mode = policy["mode"]
    if mode not in {"agent_only", "hybrid"}:
        raise PaperAttributionError("paper attribution policy mode is invalid")
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_kind": "isolated_agent_paper_book_attribution",
        "portfolio_id": policy["reserved_portfolio_id"],
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "registry_sha256": policy["registry_sha256"],
        "mode": mode,
        "strategy_id": policy["strategy_id"],
        "strategy_config_sha256": policy["strategy_config_sha256"],
        "source_portfolio_id": policy["source_portfolio_id"],
        "control_id": policy["control_id"],
        "algorithm_control_id": policy["attribution"]["algorithm_control_id"],
        "strategy_control_id": policy["attribution"]["strategy_control_id"],
        "book_strategy": f"{mode}_policy",
        "initial_cash": float(policy["capital_ceiling"]),
        "execution_profile_id": policy["execution_profile_id"],
        "execution_profile_sha256": policy["execution_profile_sha256"],
        "attribution_start_date": attribution_start_date.isoformat(),
        "model_role": policy["model_role"],
        "model_failure_policy": policy["model_failure_policy"],
        "hybrid_behavior": policy["hybrid_behavior"],
        "scheduler_route": "separate_policy_attributed",
        "order_attribution": "required",
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
    }


def _portfolio_row(con: duckdb.DuckDBPyConnection, portfolio_id: str) -> tuple | None:
    rows = con.execute(
        "SELECT id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile FROM portfolios WHERE id = ? LIMIT 2",
        [portfolio_id],
    ).fetchall()
    if len(rows) > 1:  # pragma: no cover - the simulator schema owns this PK
        raise PaperAttributionError("paper attribution portfolio is duplicated")
    return None if not rows else rows[0]


def _contract(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    portfolio: tuple,
) -> tuple[dict, str, datetime] | None:
    book_table_exists = table_exists(con, BOOK_ATTRIBUTION_TABLE)
    order_table_exists = table_exists(con, ORDER_ATTRIBUTION_TABLE)
    if not book_table_exists and not order_table_exists:
        return None
    if not book_table_exists or not order_table_exists:
        raise PaperAttributionError(
            "paper attribution persistence contract is incomplete"
        )
    rows = con.execute(
        "SELECT portfolio_id, policy_id, policy_registration_sha256, mode, "
        "contract_payload, contract_sha256, recorded_at "
        f"FROM {BOOK_ATTRIBUTION_TABLE} "
        "WHERE portfolio_id = ? OR policy_id = ? LIMIT 3",
        [policy["reserved_portfolio_id"], policy["id"]],
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise PaperAttributionError(
            "paper attribution book contract is duplicated or pooled"
        )
    (
        portfolio_id,
        policy_id,
        registration_sha256,
        mode,
        raw_payload,
        contract_sha256,
        recorded_at,
    ) = rows[0]
    try:
        payload = loads_object(raw_payload)
        start = date.fromisoformat(payload["attribution_start_date"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise PaperAttributionError(
            "paper attribution book contract is invalid"
        ) from exc
    expected = expected_book_contract(policy, start)
    expected_sha256 = canonical_sha256(expected)
    recorded = _utc(recorded_at, "book contract time")
    (
        stored_id,
        name,
        strategy,
        raw_config,
        created,
        active,
        cash,
        initial_cash,
        execution_profile,
    ) = portfolio
    try:
        config = loads_object(raw_config)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise PaperAttributionError(
            "paper attribution portfolio config is invalid"
        ) from exc
    if (
        portfolio_id != policy["reserved_portfolio_id"]
        or policy_id != policy["id"]
        or registration_sha256 != policy["registration_sha256"]
        or mode != policy["mode"]
        or payload != expected
        or _sha256(contract_sha256, "book contract identity") != expected_sha256
        or config != expected
        or stored_id != policy["reserved_portfolio_id"]
        or not isinstance(name, str)
        or not name.strip()
        or strategy != expected["book_strategy"]
        or type(created) is not date
        or created != start
        or type(active) is not bool
        or (active and mode != "agent_only")
        or _finite(cash, "portfolio cash", nonnegative=True) < 0
        or _finite(initial_cash, "portfolio initial cash", nonnegative=True)
        != expected["initial_cash"]
        or execution_profile != policy["execution_profile_id"]
        or recorded.date() > start
    ):
        raise PaperAttributionError(
            "paper attribution portfolio does not match its contract"
        )
    return expected, expected_sha256, recorded


def _verify_controls(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    *,
    start: date,
) -> list[str]:
    control_ids = [
        policy["attribution"]["algorithm_control_id"],
        policy["attribution"]["strategy_control_id"],
    ]
    if (
        len(set(control_ids)) != len(control_ids)
        or policy["reserved_portfolio_id"] in control_ids
    ):
        raise PaperAttributionError(
            "paper attribution comparison identities are not isolated"
        )
    for control_id in control_ids:
        row = _portfolio_row(con, control_id)
        if row is None:
            raise PaperAttributionError(
                "paper attribution comparison portfolio is unavailable"
            )
        try:
            config = loads_object(row[3])
            expected_config = config_by_id(control_id)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PaperAttributionError(
                "paper attribution comparison config is invalid"
            ) from exc
        if (
            row[0] != control_id
            or row[2] != expected_config["strategy"]
            or canonical_sha256(config) != canonical_sha256(expected_config)
            or type(row[4]) is not date
            or row[4] > start
            or row[5] is not True
            or _finite(row[7], "comparison initial cash", nonnegative=True)
            != float(policy["capital_ceiling"])
            or row[8] != policy["execution_profile_id"]
        ):
            raise PaperAttributionError(
                "paper attribution comparison portfolio is incompatible"
            )
    return control_ids


def _expected_order(record: dict, sequence: int) -> dict:
    orders = record.get("_attributable_orders")
    if not isinstance(orders, list):
        raise PaperAttributionError(
            "paper attribution decision evidence is unavailable"
        )
    matching = [item for item in orders if item.get("sequence") == sequence]
    if len(matching) != 1:
        raise PaperAttributionError(
            "paper attribution order is not in the retained decision"
        )
    return matching[0]


def _verify_orders(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    *,
    start: date,
    decision_records: list[dict],
) -> tuple[int, int, set[int], set[str], dict[int, str]]:
    portfolio_id = policy["reserved_portfolio_id"]
    orders = con.execute(
        "SELECT id, ticker, side, qty, signal_date, status FROM sim_orders "
        "WHERE portfolio_id = ? ORDER BY id",
        [portfolio_id],
    ).fetchall()
    if len(orders) > MAX_ATTRIBUTED_ORDERS:
        raise PaperAttributionError("paper attribution order count exceeds the bound")
    ownership = con.execute(
        "SELECT order_id, portfolio_id, policy_id, "
        "policy_registration_sha256, mode, attempt_id, "
        "decision_order_sequence, decision_window, terminal_event_sha256, "
        "decision_evidence_sha256, attribution_payload, attribution_sha256, "
        "recorded_at "
        f"FROM {ORDER_ATTRIBUTION_TABLE} "
        "WHERE portfolio_id = ? OR policy_id = ? OR order_id IN ("
        "SELECT id FROM sim_orders WHERE portfolio_id = ?) "
        "ORDER BY order_id LIMIT ?",
        [
            portfolio_id,
            policy["id"],
            portfolio_id,
            MAX_ATTRIBUTED_ORDERS + 1,
        ],
    ).fetchall()
    if len(ownership) > MAX_ATTRIBUTED_ORDERS:
        raise PaperAttributionError(
            "paper attribution ownership count exceeds the bound"
        )
    by_order = {row[0]: row for row in orders}
    records = {record["attempt_id"]: record for record in decision_records}
    seen_orders: set[int] = set()
    seen_decisions: set[tuple[int, int]] = set()
    tickers: set[str] = set()
    for row in ownership:
        (
            order_id,
            attributed_portfolio_id,
            policy_id,
            registration_sha256,
            mode,
            attempt_id,
            sequence,
            decision_window,
            terminal_sha256,
            decision_sha256,
            raw_payload,
            attribution_sha256,
            recorded_at,
        ) = row
        if order_id in seen_orders or (attempt_id, sequence) in seen_decisions:
            raise PaperAttributionError(
                "paper attribution order ownership is duplicated"
            )
        order = by_order.get(order_id)
        record = records.get(attempt_id)
        if order is None or record is None:
            raise PaperAttributionError(
                "paper attribution order has no retained decision evidence"
            )
        expected_order = _expected_order(record, sequence)
        recorded = _utc(recorded_at, "order attribution time")
        try:
            payload = loads_object(raw_payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PaperAttributionError(
                "paper attribution order payload is invalid"
            ) from exc
        expected_payload = {
            "schema_version": ORDER_ATTRIBUTION_SCHEMA_VERSION,
            "order_id": order_id,
            "portfolio_id": portfolio_id,
            "policy_id": policy["id"],
            "policy_registration_sha256": policy["registration_sha256"],
            "mode": policy["mode"],
            "attempt_id": attempt_id,
            "decision_order_sequence": sequence,
            "decision_window": record["decision_window"],
            "terminal_event_sha256": record["_terminal_event_sha256"],
            "decision_evidence_sha256": record["_decision_evidence_sha256"],
            "ticker": order[1],
            "side": order[2],
            "quantity": float(order[3]),
            "signal_date": order[4].isoformat(),
            "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
            "execution_authority": "none",
        }
        exact_quantity = expected_order["quantity_rule"] == "exact"
        quantity_matches = (
            float(order[3]) == expected_order["quantity"]
            if exact_quantity
            else 0 < float(order[3]) <= expected_order["quantity"]
        )
        if (
            attributed_portfolio_id != portfolio_id
            or policy_id != policy["id"]
            or registration_sha256 != policy["registration_sha256"]
            or mode != policy["mode"]
            or record["policy_id"] != policy["id"]
            or record["mode"] != policy["mode"]
            or decision_window != record["decision_window"]
            or _sha256(terminal_sha256, "terminal event identity")
            != record["_terminal_event_sha256"]
            or _sha256(decision_sha256, "decision evidence identity")
            != record["_decision_evidence_sha256"]
            or payload != expected_payload
            or _sha256(attribution_sha256, "order attribution identity")
            != canonical_sha256(expected_payload)
            or order[1] != expected_order["ticker"]
            or order[2] != expected_order["side"]
            or type(order[4]) is not date
            or order[4] != expected_order["signal_date"]
            or order[4] < start
            or not quantity_matches
            or order[5] not in {"pending", "filled", "rejected", "cancelled"}
            or recorded < _utc(record["completed_at"], "decision completion time")
        ):
            raise PaperAttributionError(
                "paper attribution order ownership is inconsistent"
            )
        seen_orders.add(order_id)
        seen_decisions.add((attempt_id, sequence))
        tickers.add(order[1])
    if seen_orders != set(by_order):
        raise PaperAttributionError(
            "paper attribution contains unattributed simulator orders"
        )
    return (
        len(orders),
        len(ownership),
        seen_orders,
        tickers,
        {order[0]: order[5] for order in orders},
    )


def _reconstructed_state(
    con: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: str,
    initial_cash: float,
    fills: list[tuple],
    dividends: list[tuple],
) -> tuple[float, dict[str, tuple[float, float]]]:
    if table_exists(con, "sim_settlements"):
        settlement_count = require_public_nonnegative_integer(
            con.execute(
                "SELECT COUNT(*) FROM sim_settlements WHERE portfolio_id = ?",
                [portfolio_id],
            ).fetchone()[0]
        )
        if settlement_count:
            raise PaperAttributionError(
                "paper attribution settlement ownership is unsupported"
            )
    splits: dict[str, list[tuple[date, float]]] = {}
    if table_exists(con, "split_adjustments"):
        for ticker, ex_date, ratio in con.execute(
            "SELECT ticker, ex_date, ratio FROM split_adjustments "
            "WHERE outcome = 'applied' AND ratio IS NOT NULL AND ratio > 0"
        ).fetchall():
            splits.setdefault(ticker, []).append((ex_date, float(ratio)))
    cash = initial_cash + sum(float(row[4]) for row in dividends)
    positions: dict[str, tuple[float, float]] = {}
    for (
        _order_id,
        ticker,
        side,
        fill_date,
        quantity,
        fill_price,
        _order_ticker,
        _order_side,
        _order_quantity,
        _order_status,
        _portfolio_id,
    ) in sorted(
        fills,
        key=lambda row: (row[3], 0 if row[2] == "sell" else 1, row[0]),
    ):
        factor = math.prod(
            ratio for ex_date, ratio in splits.get(ticker, ()) if fill_date < ex_date
        )
        adjusted_quantity = float(quantity) * factor
        adjusted_price = float(fill_price) / factor
        current_quantity, current_cost = positions.get(ticker, (0.0, 0.0))
        if side == "buy":
            next_quantity = current_quantity + adjusted_quantity
            next_cost = (
                (current_quantity * current_cost)
                + (adjusted_quantity * adjusted_price)
            ) / next_quantity
            cash -= float(quantity) * float(fill_price)
        else:
            if adjusted_quantity > current_quantity + 1e-9:
                raise PaperAttributionError(
                    "paper attribution fills imply a short position"
                )
            next_quantity = max(0.0, current_quantity - adjusted_quantity)
            next_cost = current_cost
            cash += float(quantity) * float(fill_price)
        positions[ticker] = (next_quantity, next_cost)
    if not math.isfinite(cash) or cash < -1e-6:
        raise PaperAttributionError(
            "paper attribution fills imply invalid portfolio cash"
        )
    return cash, positions


def _verify_book_rows(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    *,
    start: date,
    order_ids: set[int],
    order_tickers: set[str],
    order_statuses: dict[int, str],
) -> tuple[int, int, int, float, int]:
    fills = con.execute(
        "SELECT f.order_id, f.ticker, f.side, f.fill_date, f.qty, f.fill_px, "
        "o.ticker, o.side, o.qty, o.status, f.portfolio_id FROM sim_fills f "
        "JOIN sim_orders o ON o.id = f.order_id "
        "WHERE f.portfolio_id = ? ORDER BY f.order_id",
        [portfolio_id],
    ).fetchall()
    seen_fill_orders = set()
    for (
        order_id,
        ticker,
        side,
        fill_date,
        qty,
        fill_px,
        order_ticker,
        order_side,
        order_qty,
        order_status,
        _fill_portfolio_id,
    ) in fills:
        if (
            order_id not in order_ids
            or order_id in seen_fill_orders
            or ticker not in order_tickers
            or ticker != order_ticker
            or side != order_side
            or type(fill_date) is not date
            or fill_date < start
            or _finite(qty, "fill quantity") <= 0
            or float(qty) > _finite(order_qty, "order quantity")
            or _finite(fill_px, "fill price") <= 0
            or order_status != "filled"
        ):
            raise PaperAttributionError(
                "paper attribution fill ownership is inconsistent"
            )
        seen_fill_orders.add(order_id)
    cross_book = con.execute(
        "SELECT COUNT(*) FROM sim_fills f FULL OUTER JOIN sim_orders o "
        "ON o.id = f.order_id "
        "WHERE (f.portfolio_id = ? AND (o.portfolio_id IS NULL "
        "OR o.portfolio_id != f.portfolio_id)) "
        "OR (o.portfolio_id = ? AND f.portfolio_id IS NOT NULL "
        "AND f.portfolio_id != o.portfolio_id)",
        [portfolio_id, portfolio_id],
    ).fetchone()[0]
    if require_public_nonnegative_integer(cross_book):
        raise PaperAttributionError("paper attribution contains a cross-book fill")
    expected_fill_orders = {
        order_id
        for order_id, status in order_statuses.items()
        if status == "filled"
    }
    if seen_fill_orders != expected_fill_orders:
        raise PaperAttributionError(
            "paper attribution order and fill states are inconsistent"
        )

    positions = con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    for ticker, qty, avg_cost in positions:
        if (
            ticker not in order_tickers
            or _finite(qty, "position quantity", nonnegative=True) < 0
            or _finite(avg_cost, "position average cost", nonnegative=True) < 0
        ):
            raise PaperAttributionError(
                "paper attribution position ownership is inconsistent"
            )

    dividends = con.execute(
        "SELECT ticker, ex_date, qty, dps, amount FROM sim_dividends "
        "WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    for ticker, ex_date, qty, dps, amount in dividends:
        if (
            ticker not in order_tickers
            or type(ex_date) is not date
            or ex_date < start
            or _finite(qty, "dividend quantity") <= 0
            or _finite(dps, "dividend per share") <= 0
            or _finite(amount, "dividend amount") <= 0
            or not math.isclose(
                float(amount),
                float(qty) * float(dps),
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            raise PaperAttributionError(
                "paper attribution dividend ownership is inconsistent"
            )
    current_cash = _finite(
        con.execute(
            "SELECT cash FROM portfolios WHERE id = ?",
            [portfolio_id],
        ).fetchone()[0],
        "portfolio cash",
        nonnegative=True,
    )
    initial_cash = _finite(
        con.execute(
            "SELECT initial_cash FROM portfolios WHERE id = ?",
            [portfolio_id],
        ).fetchone()[0],
        "portfolio initial cash",
        nonnegative=True,
    )
    reconstructed_cash, reconstructed_positions = _reconstructed_state(
        con,
        portfolio_id=portfolio_id,
        initial_cash=initial_cash,
        fills=fills,
        dividends=dividends,
    )
    stored_positions = {
        ticker: (float(qty), float(avg_cost))
        for ticker, qty, avg_cost in positions
    }
    if not math.isclose(
        current_cash,
        reconstructed_cash,
        rel_tol=1e-12,
        abs_tol=1e-6,
    ):
        raise PaperAttributionError(
            "paper attribution cash does not reconcile to its ledger"
        )
    if set(stored_positions) != set(reconstructed_positions):
        raise PaperAttributionError(
            "paper attribution positions do not reconcile to its ledger"
        )
    for ticker, (quantity, average_cost) in reconstructed_positions.items():
        stored_quantity, stored_cost = stored_positions[ticker]
        if not (
            math.isclose(stored_quantity, quantity, rel_tol=1e-12, abs_tol=1e-9)
            and math.isclose(
                stored_cost,
                average_cost,
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            raise PaperAttributionError(
                "paper attribution positions do not reconcile to its ledger"
            )
    open_position_count = sum(
        quantity > 1e-12 for quantity, _cost in stored_positions.values()
    )
    return (
        len(fills),
        len(positions),
        len(dividends),
        current_cash,
        open_position_count,
    )


def _verify_equity(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    control_ids: list[str],
    *,
    start: date,
    initial_cash: float,
    current_cash: float,
    current_position_count: int,
) -> tuple[int, date, date, str]:
    rows = con.execute(
        "SELECT date, equity, cash, n_positions FROM sim_equity "
        "WHERE portfolio_id = ? ORDER BY date",
        [portfolio_id],
    ).fetchall()
    if not rows:
        raise PaperAttributionError("paper attribution equity path is unavailable")
    normalized = []
    for equity_date, equity, cash, n_positions in rows:
        if (
            type(equity_date) is not date
            or equity_date < start
            or _finite(equity, "equity", nonnegative=True) < 0
            or _finite(cash, "equity cash", nonnegative=True) < 0
            or isinstance(n_positions, bool)
            or not isinstance(n_positions, int)
            or n_positions < 0
        ):
            raise PaperAttributionError(
                "paper attribution equity path is invalid"
            )
        normalized.append(
            {
                "date": equity_date.isoformat(),
                "equity": float(equity),
                "cash": float(cash),
                "n_positions": n_positions,
            }
        )
    if (
        rows[0][0] != start
        or not math.isclose(
            float(rows[0][1]),
            initial_cash,
            rel_tol=1e-12,
            abs_tol=1e-6,
        )
        or not math.isclose(
            float(rows[0][2]),
            initial_cash,
            rel_tol=1e-12,
            abs_tol=1e-6,
        )
        or rows[0][3] != 0
        or not math.isclose(
            float(rows[-1][2]),
            current_cash,
            rel_tol=1e-12,
            abs_tol=1e-6,
        )
        or rows[-1][3] != current_position_count
    ):
        raise PaperAttributionError(
            "paper attribution equity start or current state is inconsistent"
        )
    book_dates = [row[0] for row in rows]
    end = book_dates[-1]
    for control_id in control_ids:
        control_dates = [
            row[0]
            for row in con.execute(
                "SELECT date FROM sim_equity WHERE portfolio_id = ? "
                "AND date >= ? AND date <= ? ORDER BY date",
                [control_id, start, end],
            ).fetchall()
        ]
        if control_dates != book_dates:
            raise PaperAttributionError(
                "paper attribution equity dates do not align with controls"
            )
    return len(rows), start, end, canonical_sha256(normalized)


def assess_policy(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    *,
    decision_records: list[dict],
) -> dict:
    """Verify one pre-existing isolated book without changing database state."""
    portfolio = _portfolio_row(con, policy["reserved_portfolio_id"])
    if portfolio is None:
        for table in (BOOK_ATTRIBUTION_TABLE, ORDER_ATTRIBUTION_TABLE):
            if table_exists(con, table):
                count = con.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE portfolio_id = ? OR policy_id = ?",
                    [policy["reserved_portfolio_id"], policy["id"]],
                ).fetchone()[0]
                if require_public_nonnegative_integer(count):
                    raise PaperAttributionError(
                        "paper attribution evidence references an absent portfolio"
                    )
        return _empty(policy, status=STATUS_NO_PORTFOLIO, portfolio_created=False)

    retained = _contract(con, policy, portfolio)
    if retained is None:
        return _empty(policy, status=STATUS_NO_CONTRACT, portfolio_created=True)
    contract, contract_sha256, _recorded_at = retained
    start = date.fromisoformat(contract["attribution_start_date"])
    controls = _verify_controls(con, policy, start=start)
    (
        order_count,
        attributed_count,
        order_ids,
        order_tickers,
        order_statuses,
    ) = _verify_orders(
        con,
        policy,
        start=start,
        decision_records=decision_records,
    )
    (
        fill_count,
        position_count,
        dividend_count,
        current_cash,
        current_position_count,
    ) = _verify_book_rows(
        con,
        policy["reserved_portfolio_id"],
        start=start,
        order_ids=order_ids,
        order_tickers=order_tickers,
        order_statuses=order_statuses,
    )
    try:
        equity_count, equity_start, equity_end, equity_sha256 = _verify_equity(
            con,
            policy["reserved_portfolio_id"],
            controls,
            start=start,
            initial_cash=float(portfolio[7]),
            current_cash=current_cash,
            current_position_count=current_position_count,
        )
    except PaperAttributionError as exc:
        if str(exc) == "paper attribution equity path is unavailable":
            result = _empty(
                policy,
                status=STATUS_NO_EQUITY,
                portfolio_created=True,
            )
            return {
                **result,
                "persisted_contract_present": True,
                "book_contract_sha256": contract_sha256,
                "attribution_start_date": start,
                "order_count": order_count,
                "attributed_order_count": attributed_count,
                "fill_count": fill_count,
                "position_count": position_count,
                "dividend_count": dividend_count,
            }
        raise
    return {
        "status": STATUS_AVAILABLE,
        "portfolio_id": policy["reserved_portfolio_id"],
        "portfolio_created": True,
        "persisted_contract_present": True,
        "book_contract_sha256": contract_sha256,
        "attribution_start_date": start,
        "order_count": order_count,
        "attributed_order_count": attributed_count,
        "fill_count": fill_count,
        "position_count": position_count,
        "dividend_count": dividend_count,
        "equity_observation_count": equity_count,
        "equity_start_date": equity_start,
        "equity_end_date": equity_end,
        "equity_path_sha256": equity_sha256,
        "comparison_portfolio_ids": controls,
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
    }
