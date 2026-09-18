"""Consume one verified agent decision into the local paper simulator only.

The model chooses proposal versus no action. This boundary reconstructs retained
evidence, applies deterministic sizing and portfolio checks, and writes at most
one pending ``sim_orders`` row. It imports no adapter, has no network operation,
and exposes no broker or live-capital authority.
"""

from __future__ import annotations

import json
import math
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import (
    agent_attribution_read_models,
    agent_paper_attribution,
    agent_paper_evidence,
    agent_policy,
)
from .broker_contract import SubmitOrderRequest
from .json_utils import loads_object
from .read_model_utils import require_public_positive_integer

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_TABLE = "agent_paper_decision_receipts"
CONFIRMATION = "consume-capital-disabled-agent-paper"
AUTH_TOKEN_ENV = "TRADING_ENGINE_AGENT_PAPER_TOKEN"
NO_ACTION_OUTCOMES = frozenset({"cadence_no_action", "no_action"})
MAX_RECEIPTS = 10_000


@dataclass(frozen=True, slots=True)
class PaperDecisionRequest:
    """Closed local-HTTP shape with an explicit simulator-only confirmation."""

    __pydantic_config__ = {"extra": "forbid"}

    decision_window: str = field(metadata={"max_length": 128})
    confirmation: str = field(metadata={"max_length": 64})


def authenticate(token: str | None) -> None:
    expected = os.environ.get(AUTH_TOKEN_ENV)
    if (
        not isinstance(expected, str)
        or len(expected) < 32
        or not isinstance(token, str)
        or not secrets.compare_digest(token, expected)
    ):
        raise PaperDecisionError(403, "agent paper authentication failed")


class PaperDecisionError(ValueError):
    """A decision cannot be consumed without violating the paper boundary."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} (
            decision_window VARCHAR PRIMARY KEY,
            policy_id VARCHAR NOT NULL,
            attempt_id BIGINT NOT NULL UNIQUE,
            outcome VARCHAR NOT NULL,
            order_id BIGINT UNIQUE,
            receipt_payload VARCHAR NOT NULL,
            receipt_sha256 VARCHAR NOT NULL,
            consumed_at TIMESTAMP NOT NULL
        )
        """
    )


def _utc(value: datetime | None) -> datetime:
    observed = datetime.now(timezone.utc) if value is None else value
    if (
        type(observed) is not datetime
        or observed.utcoffset() is None
        or observed.utcoffset().total_seconds() != 0
    ):
        raise PaperDecisionError(422, "paper decision time must be UTC")
    return observed.astimezone(timezone.utc)


def _stored_utc(value: object, label: str) -> datetime:
    if type(value) is not datetime:
        raise PaperDecisionError(503, f"{label} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if aware.utcoffset() is None or aware.utcoffset().total_seconds() != 0:
        raise PaperDecisionError(503, f"{label} is invalid")
    return aware.astimezone(timezone.utc)


def _receipt(con: duckdb.DuckDBPyConnection, decision_window: str) -> dict | None:
    if not table_exists(con, RECEIPT_TABLE):
        return None
    rows = con.execute(
        f"SELECT policy_id, attempt_id, outcome, order_id, receipt_payload, "
        f"receipt_sha256, consumed_at FROM {RECEIPT_TABLE} "
        "WHERE decision_window = ? LIMIT 2",
        [decision_window],
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise PaperDecisionError(503, "paper decision receipt is ambiguous")
    try:
        payload = loads_object(rows[0][4])
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise PaperDecisionError(503, "paper decision receipt is invalid") from exc
    expected_fields = {
        "schema_version",
        "decision_window",
        "policy_id",
        "policy_registration_sha256",
        "attempt_id",
        "terminal_outcome",
        "outcome",
        "order_id",
        "consumed_at",
        "paper_execution_authority",
        "broker_submission_authority",
        "live_capital_authority",
        "replayed",
    }
    stored_time = _stored_utc(rows[0][6], "paper receipt time")
    if (
        set(payload) != expected_fields
        or canonical_sha256(payload) != rows[0][5]
        or payload["schema_version"] != RECEIPT_SCHEMA_VERSION
        or payload["decision_window"] != decision_window
        or payload["policy_id"] != rows[0][0]
        or payload["attempt_id"] != rows[0][1]
        or payload["outcome"] != rows[0][2]
        or payload["order_id"] != rows[0][3]
        or payload["consumed_at"]
        != stored_time.isoformat().replace("+00:00", "Z")
        or payload["outcome"] not in {"no_action", "order_pending"}
        or (payload["outcome"] == "no_action") != (payload["order_id"] is None)
        or payload["paper_execution_authority"] != "local_simulator_only"
        or payload["broker_submission_authority"] != "none"
        or payload["live_capital_authority"] != "none"
        or payload["replayed"] is not False
    ):
        raise PaperDecisionError(503, "paper decision receipt identity is invalid")
    if payload["order_id"] is not None:
        order = con.execute(
            "SELECT portfolio_id FROM sim_orders WHERE id = ?",
            [payload["order_id"]],
        ).fetchone()
        attribution = con.execute(
            "SELECT policy_id, attempt_id, decision_window FROM "
            "agent_paper_order_attribution WHERE order_id = ?",
            [payload["order_id"]],
        ).fetchone()
        if (
            order is None
            or attribution
            != (payload["policy_id"], payload["attempt_id"], decision_window)
        ):
            raise PaperDecisionError(503, "paper decision receipt order is unavailable")
    return {**payload, "replayed": True}


def _book_ready(con: duckdb.DuckDBPyConnection, policy: dict) -> None:
    if policy["mode"] != "agent_only":
        raise PaperDecisionError(409, "only an agent-only policy is admitted by P5")
    if not all(
        table_exists(con, table)
        for table in (
            agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
            agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
        )
    ):
        raise PaperDecisionError(409, "isolated agent paper book is not initialized")
    row = con.execute(
        "SELECT active, cash, initial_cash, execution_profile FROM portfolios "
        "WHERE id = ?",
        [policy["reserved_portfolio_id"]],
    ).fetchone()
    contract = con.execute(
        "SELECT policy_id, policy_registration_sha256, mode "
        f"FROM {agent_paper_attribution.BOOK_ATTRIBUTION_TABLE} "
        "WHERE portfolio_id = ?",
        [policy["reserved_portfolio_id"]],
    ).fetchone()
    if (
        row is None
        or row[0] not in {False, True}
        or not isinstance(row[1], (int, float))
        or not math.isfinite(row[1])
        or row[1] < 0
        or row[2] != policy["capital_ceiling"]
        or row[3] != policy["execution_profile_id"]
        or contract
        != (policy["id"], policy["registration_sha256"], "agent_only")
    ):
        raise PaperDecisionError(409, "isolated agent paper book is not ready")


def _synchronize_empty_book_equity(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
) -> None:
    """Fill only pre-activation cash-only marks from exact control dates."""
    portfolio_id = policy["reserved_portfolio_id"]
    controls = (
        policy["attribution"]["algorithm_control_id"],
        policy["attribution"]["strategy_control_id"],
    )
    control_dates = [
        [
            row[0]
            for row in con.execute(
                "SELECT date FROM sim_equity WHERE portfolio_id = ? ORDER BY date",
                [control_id],
            ).fetchall()
        ]
        for control_id in controls
    ]
    if control_dates[0] != control_dates[1]:
        raise PaperDecisionError(409, "agent paper controls have misaligned equity dates")
    book_dates = {
        row[0]
        for row in con.execute(
            "SELECT date FROM sim_equity WHERE portfolio_id = ?", [portfolio_id]
        ).fetchall()
    }
    start = con.execute(
        f"SELECT contract_payload FROM {agent_paper_attribution.BOOK_ATTRIBUTION_TABLE} "
        "WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchone()
    try:
        start_date = date.fromisoformat(loads_object(start[0])["attribution_start_date"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise PaperDecisionError(409, "agent paper attribution start is invalid") from exc
    missing = [
        item for item in control_dates[0]
        if item >= start_date and item not in book_dates
    ]
    if not missing:
        return
    activity = sum(
        con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id = ?",
            [portfolio_id],
        ).fetchone()[0]
        for table in ("sim_orders", "sim_fills", "sim_positions", "sim_dividends")
    )
    cash = con.execute(
        "SELECT cash FROM portfolios WHERE id = ?", [portfolio_id]
    ).fetchone()[0]
    if activity or not isinstance(cash, (int, float)) or not math.isfinite(cash):
        raise PaperDecisionError(409, "agent paper equity history cannot be synchronized")
    con.executemany(
        "INSERT INTO sim_equity "
        "(portfolio_id, date, equity, cash, n_positions) VALUES (?, ?, ?, ?, 0)",
        [(portfolio_id, item, float(cash), float(cash)) for item in missing],
    )


def _quantity(
    con: duckdb.DuckDBPyConnection,
    record: dict,
    policy: dict,
) -> float:
    orders = record.get("_attributable_orders")
    if not isinstance(orders, list) or len(orders) != 1:
        raise PaperDecisionError(409, "agent proposal has no singular attributable order")
    candidate = orders[0]
    quantity = float(candidate["quantity"])
    if candidate["side"] == "buy":
        cash = con.execute(
            "SELECT cash FROM portfolios WHERE id = ?",
            [policy["reserved_portfolio_id"]],
        ).fetchone()[0]
        close = con.execute(
            "SELECT close FROM prices WHERE ticker = ? AND date = ?",
            [candidate["ticker"], candidate["signal_date"]],
        ).fetchone()
        if close is None or not isinstance(close[0], (int, float)) or close[0] <= 0:
            raise PaperDecisionError(409, "agent proposal signal close is unavailable")
        quantity = min(quantity, float(cash) / float(close[0]))
        # The retained ceiling is exact. Step one representable float toward
        # zero so binary multiplication cannot exceed it by a rounding ulp.
        quantity = math.nextafter(quantity, 0.0)
    else:
        held = con.execute(
            "SELECT COALESCE(SUM(qty), 0) FROM sim_positions "
            "WHERE portfolio_id = ? AND ticker = ? AND qty > 0",
            [policy["reserved_portfolio_id"], candidate["ticker"]],
        ).fetchone()[0]
        pending = con.execute(
            "SELECT COALESCE(SUM(qty), 0) FROM sim_orders "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'sell' "
            "AND status = 'pending'",
            [policy["reserved_portfolio_id"], candidate["ticker"]],
        ).fetchone()[0]
        quantity = min(quantity, max(float(held) - float(pending), 0.0))
    if not math.isfinite(quantity) or quantity <= 0:
        raise PaperDecisionError(409, "agent proposal has no available paper capacity")
    return quantity


def _payload(
    record: dict,
    policy: dict,
    *,
    outcome: str,
    order_id: int | None,
    consumed_at: datetime,
) -> dict:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "decision_window": record["decision_window"],
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "attempt_id": record["attempt_id"],
        "terminal_outcome": record["terminal_outcome"],
        "outcome": outcome,
        "order_id": order_id,
        "consumed_at": consumed_at.isoformat().replace("+00:00", "Z"),
        "paper_execution_authority": "local_simulator_only",
        "broker_submission_authority": "none",
        "live_capital_authority": "none",
        "replayed": False,
    }


def _persist(
    con: duckdb.DuckDBPyConnection,
    payload: dict,
    consumed_at: datetime,
) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    con.execute(
        f"INSERT INTO {RECEIPT_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            payload["decision_window"],
            payload["policy_id"],
            payload["attempt_id"],
            payload["outcome"],
            payload["order_id"],
            encoded,
            canonical_sha256(payload),
            consumed_at,
        ],
    )


def _consume_once(
    con: duckdb.DuckDBPyConnection,
    decision_window: str,
    *,
    observed_at: datetime,
) -> dict:
    replay = _receipt(con, decision_window)
    if replay is not None:
        try:
            record = agent_attribution_read_models.verified_decision_record(
                con, decision_window
            )
            policy = agent_policy.get(record["policy_id"])
        except (ValueError, agent_policy.PolicyError) as exc:
            raise PaperDecisionError(409, str(exc)) from exc
        if (
            replay["policy_id"] != policy["id"]
            or replay["policy_registration_sha256"]
            != policy["registration_sha256"]
            or replay["attempt_id"] != record["attempt_id"]
            or replay["terminal_outcome"] != record["terminal_outcome"]
            or replay["outcome"]
            != (
                "no_action"
                if record["terminal_outcome"] in NO_ACTION_OUTCOMES
                else "order_pending"
            )
        ):
            raise PaperDecisionError(503, "paper decision receipt binding is invalid")
        _book_ready(con, policy)
        con.execute(
            "UPDATE portfolios SET active = TRUE WHERE id = ? AND active = FALSE",
            [policy["reserved_portfolio_id"]],
        )
        agent_attribution_read_models.attribution(con)
        return replay
    try:
        agent_attribution_read_models.attribution(con)
        record = agent_attribution_read_models.verified_decision_record(
            con, decision_window
        )
        policy = agent_policy.get(record["policy_id"])
    except (ValueError, agent_policy.PolicyError) as exc:
        raise PaperDecisionError(409, str(exc)) from exc
    _book_ready(con, policy)
    _synchronize_empty_book_equity(con, policy)
    con.execute(
        "UPDATE portfolios SET active = TRUE WHERE id = ? AND active = FALSE",
        [policy["reserved_portfolio_id"]],
    )
    if record["terminal_outcome"] in NO_ACTION_OUTCOMES:
        payload = _payload(
            record, policy, outcome="no_action", order_id=None, consumed_at=observed_at
        )
        _persist(con, payload, observed_at)
        return payload
    if (
        record["terminal_outcome"] != "proposal_result"
        or record.get("proposal_status") != "shadow_accepted"
        or record.get("validation_status") != "pass"
    ):
        raise PaperDecisionError(409, "agent decision is not executable paper evidence")
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if type(latest) is not date or latest != record["market_date"]:
        raise PaperDecisionError(409, "agent decision is not for the latest market date")
    candidate = record["_attributable_orders"][0]
    quantity = _quantity(con, record, policy)
    request = SubmitOrderRequest(
        idempotency_key=decision_window,
        account_id=policy["reserved_portfolio_id"],
        symbol=candidate["ticker"],
        side=candidate["side"],
        quantity=quantity,
        signal_date=candidate["signal_date"],
    )
    try:
        evidence = agent_paper_evidence.load_agent_only_intent(
            con, request, decision_window_id=decision_window
        )
    except agent_paper_evidence.AgentPaperEvidenceError as exc:
        raise PaperDecisionError(409, str(exc)) from exc
    if (
        observed_at
        < _stored_utc(record["completed_at"], "decision completion time")
        or observed_at >= evidence.bindings.proposal_expires_at
    ):
        raise PaperDecisionError(409, "agent proposal is outside its consumption window")
    account_id = request.account_id
    symbol = request.symbol
    side = request.side
    signal_date = request.signal_date
    if con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? AND ticker = ? "
        "AND side = ? AND status = 'pending'",
        [account_id, symbol, side],
    ).fetchone()[0]:
        raise PaperDecisionError(409, "an equivalent agent paper order is already pending")
    order_id = require_public_positive_integer(
        con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0]
    )
    con.execute(
        "INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
        [order_id, account_id, symbol, side, quantity, signal_date],
    )
    attribution = {
        "schema_version": agent_paper_attribution.ORDER_ATTRIBUTION_SCHEMA_VERSION,
        "order_id": order_id,
        "portfolio_id": account_id,
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": "agent_only",
        "attempt_id": record["attempt_id"],
        "decision_order_sequence": 1,
        "decision_window": decision_window,
        "terminal_event_sha256": record["_terminal_event_sha256"],
        "decision_evidence_sha256": record["_decision_evidence_sha256"],
        "ticker": symbol,
        "side": side,
        "quantity": quantity,
        "signal_date": signal_date.isoformat(),
        "recorded_at": observed_at.isoformat().replace("+00:00", "Z"),
        "execution_authority": "none",
    }
    encoded = json.dumps(attribution, sort_keys=True, separators=(",", ":"))
    con.execute(
        f"INSERT INTO {agent_paper_attribution.ORDER_ATTRIBUTION_TABLE} VALUES "
        "(?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
        [order_id, account_id, policy["id"], policy["registration_sha256"], "agent_only", record["attempt_id"], decision_window, record["_terminal_event_sha256"], record["_decision_evidence_sha256"], encoded, canonical_sha256(attribution), observed_at],
    )
    payload = _payload(
        record, policy, outcome="order_pending", order_id=order_id, consumed_at=observed_at
    )
    _persist(con, payload, observed_at)
    return payload


def consume(
    con: duckdb.DuckDBPyConnection,
    decision_window: str,
    *,
    confirmation: str,
    now: datetime | None = None,
) -> dict:
    """Consume one complete retained decision atomically and exactly once."""
    if confirmation != CONFIRMATION:
        raise PaperDecisionError(403, "paper decision confirmation is invalid")
    observed_at = _utc(now)
    with engine_db.transaction(con):
        init_schema(con)
        return _consume_once(con, decision_window, observed_at=observed_at)


def replay_after_contention(
    con: duckdb.DuckDBPyConnection,
    decision_window: str,
) -> dict | None:
    """Read and fully verify the winner's receipt after a concurrent conflict."""
    with engine_db.transaction(con):
        return _consume_once(
            con,
            decision_window,
            observed_at=datetime.now(timezone.utc),
        ) if _receipt(con, decision_window) is not None else None


def receipts(con: duckdb.DuckDBPyConnection) -> dict:
    """Project bounded, fully verified consumption receipts newest first."""
    if not table_exists(con, RECEIPT_TABLE):
        return {"matching_count": 0, "limit": MAX_RECEIPTS, "truncated": False, "receipts": []}
    windows = [
        row[0]
        for row in con.execute(
            f"SELECT decision_window FROM {RECEIPT_TABLE} "
            "ORDER BY consumed_at DESC, decision_window LIMIT ?",
            [MAX_RECEIPTS + 1],
        ).fetchall()
    ]
    visible = windows[:MAX_RECEIPTS]
    return {
        "matching_count": len(windows),
        "limit": MAX_RECEIPTS,
        "truncated": len(windows) > MAX_RECEIPTS,
        "receipts": [
            {**_receipt(con, window), "replayed": False} for window in visible
        ],
    }
