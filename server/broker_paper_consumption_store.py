"""Internal atomic pre-call persistence for automatic-paper consumption.

The coordinator persists one authority consumption, broker intent,
authority-aware risk evaluation, and uncertain submission marker in one
transaction. It deliberately does not call an adapter or expose a route,
command, scheduler, or schema migration.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256

from . import (
    broker_ledger,
    broker_paper_consumption_plan,
    broker_paper_risk_evaluation,
    broker_paper_runtime,
    broker_paper_startup_store,
    broker_paper_usage,
)
from .broker_contract import BrokerStateError, SubmitOrderRequest, require_identifier
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_risk_evaluation import (
    AuthorityAwareRiskEvaluation,
    PaperRiskGate,
)
from .broker_paper_runtime import RuntimeControlBindings
from .broker_paper_usage import LoadedPaperLeaseUsage
from .json_utils import loads_object

RESULT_SCHEMA_VERSION = 1
RISK_EVIDENCE_SCHEMA_VERSION = 1
MAX_RISK_EVIDENCE_ROWS = broker_paper_startup_store.MAX_RETAINED_ROWS
MAX_EVIDENCE_PAYLOAD_BYTES = 262_144
RISK_EVIDENCE_TABLE = "broker_paper_authority_risk_evaluations"
RISK_EVIDENCE_COLUMNS = (
    ("idempotency_key", "VARCHAR"),
    ("account_id", "VARCHAR"),
    ("lease_id", "VARCHAR"),
    ("evaluation_sha256", "VARCHAR"),
    ("evaluation_payload", "VARCHAR"),
    ("eligibility_sha256", "VARCHAR"),
    ("eligibility_payload", "VARCHAR"),
    ("atomic_bundle_sha256", "VARCHAR"),
    ("atomic_bundle_payload", "VARCHAR"),
    ("recorded_at", "VARCHAR"),
    ("record_sha256", "VARCHAR"),
)
RISK_EVIDENCE_SCHEMA = tuple(
    (name, kind, "NO", None) for name, kind in RISK_EVIDENCE_COLUMNS
)
_RISK_COLUMN_NAMES = tuple(name for name, _kind in RISK_EVIDENCE_COLUMNS)
_EVALUATION_FIELDS = frozenset(
    field.name for field in fields(AuthorityAwareRiskEvaluation)
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperConsumptionStoreError(ValueError):
    """An atomic automatic-paper pre-call commit cannot be proven safe."""


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperConsumptionStoreError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperConsumptionStoreError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperConsumptionStoreError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise PaperConsumptionStoreError(f"{label} is not canonical")
    return _utc(parsed, label)


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _table_schema(
    con: duckdb.DuckDBPyConnection,
    table: str,
) -> tuple[tuple[str, str, str, object], ...] | None:
    tables = con.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [table],
    ).fetchall()
    if not tables:
        return None
    if tables != [("BASE TABLE",)]:
        raise PaperConsumptionStoreError(
            f"{table} table type is invalid"
        )
    rows = con.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? "
        "ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return tuple(
        (str(name), str(kind), str(nullable), default)
        for name, kind, nullable, default in rows
    )


def _require_schemas(con: duckdb.DuckDBPyConnection) -> None:
    expected = {
        broker_paper_startup_store.RETENTION_TABLE: (
            broker_paper_startup_store.RETENTION_SCHEMA
        ),
        RISK_EVIDENCE_TABLE: RISK_EVIDENCE_SCHEMA,
        "broker_intents": (
            ("idempotency_key", "VARCHAR", "NO", None),
            ("account_id", "VARCHAR", "NO", None),
            ("intent_sha256", "VARCHAR", "NO", None),
            ("intent_payload", "VARCHAR", "NO", None),
            ("created_at", "TIMESTAMP", "NO", None),
        ),
        "broker_submission_events": (
            ("idempotency_key", "VARCHAR", "NO", None),
            ("event_sequence", "INTEGER", "NO", None),
            ("account_id", "VARCHAR", "NO", None),
            ("intent_sha256", "VARCHAR", "NO", None),
            ("event_type", "VARCHAR", "NO", None),
            ("broker_order_id", "VARCHAR", "YES", None),
            ("order_sha256", "VARCHAR", "YES", None),
            ("order_payload", "VARCHAR", "YES", None),
            ("occurred_at", "TIMESTAMP", "NO", None),
        ),
    }
    if any(_table_schema(con, table) != schema for table, schema in expected.items()):
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call schemas are not exactly preinstalled"
        )


def _evaluation_from_payload(
    value: object,
    *,
    evaluation_sha256: object,
) -> AuthorityAwareRiskEvaluation:
    if not isinstance(value, str):
        raise PaperConsumptionStoreError(
            "stored authority-aware risk evaluation is invalid"
        )
    if (
        not value
        or len(value.encode("utf-8")) > MAX_EVIDENCE_PAYLOAD_BYTES
    ):
        raise PaperConsumptionStoreError(
            "stored authority-aware risk evaluation is invalid"
        )
    try:
        payload = loads_object(value)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperConsumptionStoreError(
            "stored authority-aware risk evaluation is invalid"
        ) from exc
    if (
        set(payload)
        != (_EVALUATION_FIELDS - {"evaluation_sha256"}) | {"schema_version"}
        or payload["schema_version"]
        != broker_paper_risk_evaluation.EVALUATION_SCHEMA_VERSION
        or _canonical_json(payload) != value
    ):
        raise PaperConsumptionStoreError(
            "stored authority-aware risk evaluation is invalid"
        )
    values = {
        name: (
            evaluation_sha256
            if name == "evaluation_sha256"
            else payload[name]
        )
        for name in _EVALUATION_FIELDS
    }
    for name in (
        "assessed_at",
        "risk_evaluated_at",
        "risk_expires_at",
        "lease_expires_at",
    ):
        values[name] = _parse_timestamp(
            values[name],
            f"stored authority-aware risk {name}",
        )
    values["risk_gate_names"] = tuple(values["risk_gate_names"])
    values["risk_gates"] = tuple(PaperRiskGate(**gate) for gate in values["risk_gates"])
    values["risk_failed_gates"] = tuple(values["risk_failed_gates"])
    try:
        evaluation = AuthorityAwareRiskEvaluation(**values)
        return broker_paper_risk_evaluation.verify_evaluation(evaluation)
    except (TypeError, ValueError) as exc:
        raise PaperConsumptionStoreError(
            "stored authority-aware risk evaluation is invalid"
        ) from exc


def _verified_risk_rows(
    con: duckdb.DuckDBPyConnection,
) -> tuple[tuple[object, ...], ...]:
    rows = con.execute(
        f"SELECT {', '.join(_RISK_COLUMN_NAMES)} "
        f"FROM {RISK_EVIDENCE_TABLE} ORDER BY idempotency_key LIMIT ?",
        [MAX_RISK_EVIDENCE_ROWS + 1],
    ).fetchall()
    if len(rows) > MAX_RISK_EVIDENCE_ROWS:
        raise PaperConsumptionStoreError(
            "authority-aware risk evidence exceeds the verification bound"
        )
    seen_keys = set()
    seen_evaluations = set()
    for row in rows:
        values = dict(zip(_RISK_COLUMN_NAMES, row, strict=True))
        evaluation = _evaluation_from_payload(
            values["evaluation_payload"],
            evaluation_sha256=values["evaluation_sha256"],
        )
        try:
            eligibility = loads_object(values["eligibility_payload"])
            plan = broker_paper_consumption_plan.verify_plan(
                loads_object(values["atomic_bundle_payload"])
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise PaperConsumptionStoreError(
                "stored automatic-paper commit evidence is invalid"
            ) from exc
        if any(
            not isinstance(values[name], str)
            or not values[name]
            or len(values[name].encode("utf-8"))
            > MAX_EVIDENCE_PAYLOAD_BYTES
            for name in (
                "eligibility_payload",
                "atomic_bundle_payload",
            )
        ):
            raise PaperConsumptionStoreError(
                "stored automatic-paper commit evidence is invalid"
            )
        try:
            require_identifier(
                values["idempotency_key"],
                "stored authority-aware risk idempotency key",
            )
            require_identifier(
                values["account_id"],
                "stored authority-aware risk account identifier",
            )
            require_identifier(
                values["lease_id"],
                "stored authority-aware risk lease identifier",
            )
        except ValueError as exc:
            raise PaperConsumptionStoreError(
                "stored authority-aware risk evidence is inconsistent"
            ) from exc
        expected = (
            evaluation.account_id,
            evaluation.lease_id,
            evaluation.evaluation_sha256,
        )
        row_body = {
            "schema_version": RISK_EVIDENCE_SCHEMA_VERSION,
            **{
                name: values[name]
                for name in _RISK_COLUMN_NAMES
                if name != "record_sha256"
            },
        }
        if (
            (
                values["account_id"],
                values["lease_id"],
                values["evaluation_sha256"],
            )
            != expected
            or values["idempotency_key"] in seen_keys
            or values["evaluation_sha256"] in seen_evaluations
            or values["evaluation_sha256"]
            != canonical_sha256(evaluation.payload())
            or plan["idempotency_key"] != values["idempotency_key"]
            or plan["account_id"] != values["account_id"]
            or plan["lease_id"] != values["lease_id"]
            or plan["risk_evaluation_sha256"]
            != values["evaluation_sha256"]
            or plan["eligibility"] != eligibility
            or plan["eligibility_sha256"]
            != values["eligibility_sha256"]
            != canonical_sha256(eligibility)
            or plan["atomic_bundle_sha256"]
            != values["atomic_bundle_sha256"]
            or _canonical_json(plan) != values["atomic_bundle_payload"]
            or values["record_sha256"] != canonical_sha256(row_body)
            or _parse_timestamp(
                values["recorded_at"],
                "stored authority-aware risk record time",
            )
            < evaluation.assessed_at
            or _parse_timestamp(
                values["recorded_at"],
                "stored authority-aware risk record time",
            )
            >= evaluation.risk_expires_at
        ):
            raise PaperConsumptionStoreError(
                "stored authority-aware risk evidence is inconsistent"
            )
        seen_keys.add(values["idempotency_key"])
        seen_evaluations.add(values["evaluation_sha256"])
    return tuple(tuple(row) for row in rows)


def _verified_authority_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    account_id: str,
) -> tuple[
    tuple[tuple[object, ...], ...],
    tuple[object, ...],
]:
    rows = broker_paper_startup_store._capture_rows(con)
    if rows is None:
        raise PaperConsumptionStoreError(
            "automatic-paper authority retention schema is unavailable"
        )
    epochs = broker_paper_startup_store._epochs(rows, account_id=account_id)
    return rows, epochs


def _consumption_events(
    authority_rows: tuple[tuple[object, ...], ...],
) -> dict[str, dict]:
    authority_columns = broker_paper_startup_store._COLUMN_NAMES
    consumptions = {}
    for row in authority_rows:
        values = dict(zip(authority_columns, row, strict=True))
        if values["event_type"] != "consumption_committed":
            continue
        try:
            event = loads_object(values["event_payload"])
        except (TypeError, ValueError, UnicodeError) as exc:
            raise PaperConsumptionStoreError(
                "retained automatic-paper consumption evidence is invalid"
            ) from exc
        key = event.get("idempotency_key")
        if (
            not isinstance(key, str)
            or key in consumptions
            or event.get("event_sha256") != values["event_sha256"]
        ):
            raise PaperConsumptionStoreError(
                "retained automatic-paper consumption evidence is invalid"
            )
        consumptions[key] = event
    return consumptions


def _risk_plans(
    risk_rows: tuple[tuple[object, ...], ...],
) -> dict[str, tuple[dict, dict]]:
    risks = {}
    for row in risk_rows:
        values = dict(zip(_RISK_COLUMN_NAMES, row, strict=True))
        key = values["idempotency_key"]
        try:
            plan = broker_paper_consumption_plan.verify_plan(
                loads_object(values["atomic_bundle_payload"])
            )
        except (TypeError, ValueError, UnicodeError) as exc:  # pragma: no cover
            raise PaperConsumptionStoreError(
                "stored automatic-paper commit evidence is invalid"
            ) from exc
        if key in risks:
            raise PaperConsumptionStoreError(
                "stored automatic-paper commit evidence is duplicated"
            )
        risks[key] = (values, plan)
    return risks


def _verify_commit_link(
    con: duckdb.DuckDBPyConnection,
    key: str,
    event: dict,
    values: dict,
    plan: dict,
) -> None:
    expected_event = {
        **plan["expected_consumption_event"],
        "event_sha256": plan["expected_consumption_event_sha256"],
    }
    if (
        event != expected_event
        or values["lease_id"] != event["lease_id"]
        or values["account_id"] != event["account_id"]
        or values["evaluation_sha256"] != event["risk_evaluation_sha256"]
        or broker_ledger.submission_state(con, key)
        not in {"uncertain", "acknowledged"}
        or not _submission_started_matches(con, plan)
        or not _intent_matches(con, plan)
    ):
        raise PaperConsumptionStoreError(
            "automatic-paper committed evidence bindings are inconsistent"
        )


def _verified_commit_links(
    con: duckdb.DuckDBPyConnection,
    authority_rows: tuple[tuple[object, ...], ...],
    risk_rows: tuple[tuple[object, ...], ...],
) -> None:
    consumptions = _consumption_events(authority_rows)
    risks = _risk_plans(risk_rows)
    if set(consumptions) != set(risks):
        raise PaperConsumptionStoreError(
            "automatic-paper authority and risk evidence are incomplete"
        )
    for key, event in consumptions.items():
        values, plan = risks[key]
        _verify_commit_link(con, key, event, values, plan)


def _actual_usage(
    lease: PaperAuthorityLease,
    epochs: tuple[object, ...],
    supplied: LoadedPaperLeaseUsage,
) -> LoadedPaperLeaseUsage:
    matching = [epoch for epoch in epochs if epoch.lease.lease_id == lease.lease_id]
    if len(matching) != 1:
        raise PaperConsumptionStoreError(
            "paper lease activation is unavailable or ambiguous"
        )
    epoch = matching[0]
    try:
        loaded = broker_paper_usage.load_open_usage(
            lease,
            epoch.events,
            trusted_event_count=epoch.retained_event_count,
            trusted_latest_event_sha256=epoch.retained_latest_event_sha256,
            trusted_activation_event_sha256=(
                epoch.trusted_activation_event_sha256
            ),
            candidate_assessment_sha256=epoch.candidate_assessment_sha256,
            startup_assessment_sha256=epoch.startup_assessment_sha256,
            activation_runtime_epoch_sha256=(
                epoch.activation_runtime_epoch_sha256
            ),
            current_runtime_epoch_sha256=(
                supplied.current_runtime_epoch_sha256
            ),
            current_control=supplied.current_control,
            now=supplied.observed_at,
        )
    except (TypeError, ValueError) as exc:
        raise PaperConsumptionStoreError(
            "retained paper authority usage verification failed"
        ) from exc
    if loaded != supplied:
        raise PaperConsumptionStoreError(
            "supplied paper usage does not match retained authority history"
        )
    return loaded


def _verify_inputs(
    lease: PaperAuthorityLease,
    usage: LoadedPaperLeaseUsage,
    evaluation: AuthorityAwareRiskEvaluation,
    runtime: RuntimeControlBindings,
    request: SubmitOrderRequest,
    plan: object,
) -> dict:
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    try:
        usage = broker_paper_usage.verify_loaded_usage(usage, lease)
        evaluation = broker_paper_risk_evaluation.verify_evaluation(evaluation)
        runtime = broker_paper_runtime.verify_runtime_control(
            runtime,
            account_id=lease.account_id,
        )
        verified = broker_paper_consumption_plan.verify_plan(plan)
    except (TypeError, ValueError) as exc:
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call evidence verification failed"
        ) from exc
    intent = broker_ledger._intent_payload(request)
    if (
        verified["lease_id"] != lease.lease_id
        or verified["lease_sha256"] != lease.sha256()
        or verified["account_id"] != lease.account_id
        or verified["mode"] != lease.mode
        or verified["usage_evidence_sha256"] != usage.evidence_sha256
        or verified["transcript_sha256"] != usage.transcript_sha256
        or verified["risk_evaluation_sha256"]
        != evaluation.evaluation_sha256
        or verified["request_sha256"] != evaluation.request_sha256
        or verified["expected_broker_intent"] != intent
        or runtime.runtime_epoch_sha256
        != usage.current_runtime_epoch_sha256
        != evaluation.runtime_epoch_sha256
        or runtime.control != usage.current_control
        or runtime.control.event_count != evaluation.control_event_count
        or runtime.control.latest_event_sha256
        != evaluation.control_event_sha256
    ):
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call evidence bindings do not match"
        )
    return verified


def _authority_row(
    lease: PaperAuthorityLease,
    plan: dict,
    epoch: object,
    *,
    global_sequence: int,
    prior_global_row_sha256: str,
) -> dict:
    event = {
        **plan["expected_consumption_event"],
        "event_sha256": plan["expected_consumption_event_sha256"],
    }
    values = {
        "global_sequence": global_sequence,
        "account_id": lease.account_id,
        "mode": lease.mode,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "lease_payload": _canonical_json(lease.payload()),
        "event_sequence": event["event_sequence"],
        "event_type": event["event_type"],
        "event_payload": _canonical_json(event),
        "event_sha256": event["event_sha256"],
        "trusted_activation_event_sha256": (
            epoch.trusted_activation_event_sha256
        ),
        "candidate_assessment_sha256": (
            epoch.candidate_assessment_sha256
        ),
        "startup_assessment_sha256": epoch.startup_assessment_sha256,
        "activation_runtime_epoch_sha256": (
            epoch.activation_runtime_epoch_sha256
        ),
        "prior_global_row_sha256": prior_global_row_sha256,
    }
    body = broker_paper_startup_store._retained_row_body(
        **{
            **values,
            "lease_payload": lease.payload(),
            "event_payload": event,
        }
    )
    return {**values, "row_sha256": canonical_sha256(body)}


def _risk_row(
    lease: PaperAuthorityLease,
    evaluation: AuthorityAwareRiskEvaluation,
    plan: dict,
) -> dict:
    values = {
        "idempotency_key": plan["idempotency_key"],
        "account_id": lease.account_id,
        "lease_id": lease.lease_id,
        "evaluation_sha256": evaluation.evaluation_sha256,
        "evaluation_payload": _canonical_json(evaluation.payload()),
        "eligibility_sha256": plan["eligibility_sha256"],
        "eligibility_payload": _canonical_json(plan["eligibility"]),
        "atomic_bundle_sha256": plan["atomic_bundle_sha256"],
        "atomic_bundle_payload": _canonical_json(plan),
        "recorded_at": plan["planned_at"],
    }
    body = {
        "schema_version": RISK_EVIDENCE_SCHEMA_VERSION,
        **values,
    }
    return {**values, "record_sha256": canonical_sha256(body)}


def _insert_authority_row(
    con: duckdb.DuckDBPyConnection,
    row: dict,
) -> None:
    columns = broker_paper_startup_store._COLUMN_NAMES
    con.execute(
        f"INSERT INTO {broker_paper_startup_store.RETENTION_TABLE} "
        f"({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _ in columns)})",
        [row[name] for name in columns],
    )


def _insert_risk_row(
    con: duckdb.DuckDBPyConnection,
    row: dict,
) -> None:
    con.execute(
        f"INSERT INTO {RISK_EVIDENCE_TABLE} "
        f"({', '.join(_RISK_COLUMN_NAMES)}) VALUES "
        f"({', '.join('?' for _ in _RISK_COLUMN_NAMES)})",
        [row[name] for name in _RISK_COLUMN_NAMES],
    )


def _submission_started_matches(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
) -> bool:
    rows = con.execute(
        "SELECT event_sequence, account_id, intent_sha256, event_type, "
        "broker_order_id, order_sha256, order_payload, occurred_at "
        "FROM broker_submission_events WHERE idempotency_key = ? "
        "ORDER BY event_sequence",
        [plan["idempotency_key"]],
    ).fetchall()
    if len(rows) not in {1, 2}:
        return False
    expected = plan["expected_submission_started"]
    occurred_at = rows[0][7]
    if not isinstance(occurred_at, datetime):
        return False
    return rows[0][:7] == (
        expected["event_sequence"],
        expected["account_id"],
        expected["intent_sha256"],
        expected["event_type"],
        None,
        None,
        None,
    ) and occurred_at == _parse_timestamp(
        expected["occurred_at"],
        "expected submission start time",
    ).replace(tzinfo=None)


def _intent_matches(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
) -> bool:
    row = con.execute(
        "SELECT account_id, intent_sha256, intent_payload FROM broker_intents "
        "WHERE idempotency_key = ?",
        [plan["idempotency_key"]],
    ).fetchone()
    expected = plan["expected_broker_intent"]
    return row == (
        expected["account_id"],
        plan["expected_broker_intent_sha256"],
        _canonical_json(expected),
    )


def _exact_replay(
    con: duckdb.DuckDBPyConnection,
    authority_rows: tuple[tuple[object, ...], ...],
    risk_rows: tuple[tuple[object, ...], ...],
    risk_row: dict,
    lease: PaperAuthorityLease,
    epoch: object,
    plan: dict,
) -> dict | None:
    authority_columns = broker_paper_startup_store._COLUMN_NAMES
    matching_authority = [
        row
        for row in authority_rows
        if row[authority_columns.index("event_sha256")]
        == plan["expected_consumption_event_sha256"]
    ]
    matching_risk = [
        row
        for row in risk_rows
        if row[_RISK_COLUMN_NAMES.index("idempotency_key")]
        == risk_row["idempotency_key"]
    ]
    state = broker_ledger.submission_state(con, plan["idempotency_key"])
    intent_matches = _intent_matches(con, plan)
    if len(matching_authority) == 1:
        retained = dict(
            zip(authority_columns, matching_authority[0], strict=True)
        )
        authority_row = _authority_row(
            lease,
            plan,
            epoch,
            global_sequence=retained["global_sequence"],
            prior_global_row_sha256=retained["prior_global_row_sha256"],
        )
        expected_authority = tuple(
            authority_row[name] for name in authority_columns
        )
        expected_risk = tuple(risk_row[name] for name in _RISK_COLUMN_NAMES)
    else:
        authority_row = None
        expected_authority = None
        expected_risk = None
    if (
        matching_authority == [expected_authority]
        and matching_risk == [expected_risk]
        and state == "uncertain"
        and _submission_started_matches(con, plan)
        and intent_matches
        and authority_row is not None
    ):
        return authority_row
    if (
        matching_authority
        or matching_risk
        or state is not None
        or intent_matches
    ):
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call identity conflicts with retained evidence"
        )
    return None


def _result(lease: PaperAuthorityLease, plan: dict, row: dict) -> dict:
    body = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "atomic_pre_call_persisted_for_test_harness",
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "consumption_key": plan["consumption_key"],
        "idempotency_key": plan["idempotency_key"],
        "atomic_bundle_sha256": plan["atomic_bundle_sha256"],
        "consumption_event_sha256": plan[
            "expected_consumption_event_sha256"
        ],
        "consumption_global_sequence": row["global_sequence"],
        "consumption_row_sha256": row["row_sha256"],
        "broker_intent_sha256": plan["expected_broker_intent_sha256"],
        "risk_evaluation_sha256": plan["risk_evaluation_sha256"],
        "submission_started_sha256": plan[
            "expected_submission_started_sha256"
        ],
        "submission_state": "uncertain",
        "adapter_called": False,
        "adapter_integration_implemented": False,
        "http_route": "absent",
        "scheduler": "absent",
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {**body, "pre_call_record_sha256": canonical_sha256(body)}


def _transaction_state(
    con: duckdb.DuckDBPyConnection,
    lease: PaperAuthorityLease,
    *,
    trusted_global_row_count: int,
    trusted_latest_global_row_sha256: str,
) -> tuple[
    tuple[tuple[object, ...], ...],
    object,
    tuple[tuple[object, ...], ...],
]:
    _require_schemas(con)
    authority_rows, epochs = _verified_authority_rows(
        con,
        account_id=lease.account_id,
    )
    matching = [
        epoch for epoch in epochs if epoch.lease.lease_id == lease.lease_id
    ]
    if len(matching) != 1:
        raise PaperConsumptionStoreError(
            "paper lease activation is unavailable or ambiguous"
        )
    actual_head = authority_rows[-1][
        broker_paper_startup_store._COLUMN_NAMES.index("row_sha256")
    ]
    if (
        len(authority_rows) != trusted_global_row_count
        or actual_head != trusted_latest_global_row_sha256
    ):
        raise PaperConsumptionStoreError(
            "paper authority retention table does not match the trusted global head"
        )
    risk_rows = _verified_risk_rows(con)
    _verified_commit_links(con, authority_rows, risk_rows)
    return authority_rows, matching[0], risk_rows


def _verify_resulting_commit(
    con: duckdb.DuckDBPyConnection,
    lease: PaperAuthorityLease,
    request: SubmitOrderRequest,
    plan: dict,
    *,
    runtime: RuntimeControlBindings,
    observed_at: datetime,
    prior_authority_rows: tuple[tuple[object, ...], ...],
    prior_risk_rows: tuple[tuple[object, ...], ...],
    authority_row: dict,
    risk_row: dict,
) -> None:
    resulting_rows, resulting_epochs = _verified_authority_rows(
        con,
        account_id=lease.account_id,
    )
    resulting_risk_rows = _verified_risk_rows(con)
    expected_authority = tuple(
        authority_row[name]
        for name in broker_paper_startup_store._COLUMN_NAMES
    )
    expected_risk_rows = tuple(
        sorted(
            (
                *prior_risk_rows,
                tuple(risk_row[name] for name in _RISK_COLUMN_NAMES),
            ),
            key=lambda row: row[0],
        )
    )
    matching = [
        epoch
        for epoch in resulting_epochs
        if epoch.lease.lease_id == lease.lease_id
    ]
    if len(matching) != 1:
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call commit failed verification"
        )
    epoch = matching[0]
    try:
        resulting_usage = broker_paper_usage.load_open_usage(
            lease,
            epoch.events,
            trusted_event_count=epoch.retained_event_count,
            trusted_latest_event_sha256=epoch.retained_latest_event_sha256,
            trusted_activation_event_sha256=(
                epoch.trusted_activation_event_sha256
            ),
            candidate_assessment_sha256=epoch.candidate_assessment_sha256,
            startup_assessment_sha256=epoch.startup_assessment_sha256,
            activation_runtime_epoch_sha256=(
                epoch.activation_runtime_epoch_sha256
            ),
            current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
            current_control=runtime.control,
            now=observed_at,
        )
    except (TypeError, ValueError) as exc:
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call commit failed verification"
        ) from exc
    if (
        len(resulting_rows) != len(prior_authority_rows) + 1
        or resulting_rows[:-1] != prior_authority_rows
        or resulting_rows[-1] != expected_authority
        or resulting_risk_rows != expected_risk_rows
        or resulting_usage.event_count != plan["expected_event_sequence"]
        or resulting_usage.latest_event_sha256
        != plan["expected_consumption_event_sha256"]
        or resulting_usage.usage.consumed_order_count
        != plan["resulting_consumed_order_count"]
        or resulting_usage.usage.consumed_notional
        != plan["resulting_consumed_notional"]
        or broker_ledger.submission_state(
            con,
            request.idempotency_key,
        )
        != "uncertain"
        or not _submission_started_matches(con, plan)
    ):
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call commit failed verification"
        )
    _verified_commit_links(con, resulting_rows, resulting_risk_rows)


def _commit_new(
    con: duckdb.DuckDBPyConnection,
    lease: PaperAuthorityLease,
    usage: LoadedPaperLeaseUsage,
    evaluation: AuthorityAwareRiskEvaluation,
    runtime: RuntimeControlBindings,
    request: SubmitOrderRequest,
    plan: dict,
    *,
    observed_at: datetime,
    planned_at: datetime,
    authority_rows: tuple[tuple[object, ...], ...],
    epoch: object,
    risk_rows: tuple[tuple[object, ...], ...],
    risk_row: dict,
    trusted_global_row_count: int,
    trusted_latest_global_row_sha256: str,
) -> dict:
    current_runtime = broker_paper_runtime.load_runtime_control(
        con,
        lease.account_id,
    )
    if current_runtime != runtime:
        raise PaperConsumptionStoreError(
            "paper runtime or halt-chain binding changed before commit"
        )
    loaded = _actual_usage(lease, (epoch,), usage)
    authority_row = _authority_row(
        lease,
        plan,
        epoch,
        global_sequence=trusted_global_row_count + 1,
        prior_global_row_sha256=trusted_latest_global_row_sha256,
    )
    if loaded.latest_event_sha256 != plan["expected_prior_event_sha256"]:
        raise PaperConsumptionStoreError(
            "paper consumption plan does not match the retained lease head"
        )
    if (
        observed_at < planned_at
        or observed_at >= evaluation.risk_expires_at
        or observed_at >= lease.expires_at
    ):
        raise PaperConsumptionStoreError(
            "paper consumption plan is stale at persistence time"
        )

    _insert_authority_row(con, authority_row)
    _insert_risk_row(con, risk_row)
    broker_ledger.begin_submission(
        con,
        request,
        now=planned_at,
    )
    _verify_resulting_commit(
        con,
        lease,
        request,
        plan,
        runtime=runtime,
        observed_at=observed_at,
        prior_authority_rows=authority_rows,
        prior_risk_rows=risk_rows,
        authority_row=authority_row,
        risk_row=risk_row,
    )
    return _result(lease, plan, authority_row)


def record_pre_call_for_test_harness(
    con: duckdb.DuckDBPyConnection,
    lease: PaperAuthorityLease,
    usage: LoadedPaperLeaseUsage,
    evaluation: AuthorityAwareRiskEvaluation,
    runtime: RuntimeControlBindings,
    request: SubmitOrderRequest,
    plan: object,
    *,
    trusted_global_row_count: int,
    trusted_latest_global_row_sha256: str,
    now: datetime,
) -> dict:
    """Atomically retain pre-call evidence without invoking an adapter."""
    verified = _verify_inputs(
        lease,
        usage,
        evaluation,
        runtime,
        request,
        plan,
    )
    observed_at = _utc(now, "automatic-paper pre-call persistence time")
    planned_at = _parse_timestamp(
        verified["planned_at"],
        "paper consumption plan time",
    )
    if (
        isinstance(trusted_global_row_count, bool)
        or not isinstance(trusted_global_row_count, int)
        or trusted_global_row_count < 1
        or not isinstance(trusted_latest_global_row_sha256, str)
        or _SHA256.fullmatch(trusted_latest_global_row_sha256) is None
    ):
        raise PaperConsumptionStoreError(
            "trusted authority global head is invalid"
        )

    try:
        with engine_db.transaction(con):
            authority_rows, epoch, risk_rows = _transaction_state(
                con,
                lease,
                trusted_global_row_count=trusted_global_row_count,
                trusted_latest_global_row_sha256=(
                    trusted_latest_global_row_sha256
                ),
            )
            risk_row = _risk_row(lease, evaluation, verified)
            replay_row = _exact_replay(
                con,
                authority_rows,
                risk_rows,
                risk_row,
                lease,
                epoch,
                verified,
            )
            if replay_row is not None:
                return _result(lease, verified, replay_row)
            return _commit_new(
                con,
                lease,
                usage,
                evaluation,
                runtime,
                request,
                verified,
                observed_at=observed_at,
                planned_at=planned_at,
                authority_rows=authority_rows,
                epoch=epoch,
                risk_rows=risk_rows,
                risk_row=risk_row,
                trusted_global_row_count=trusted_global_row_count,
                trusted_latest_global_row_sha256=(
                    trusted_latest_global_row_sha256
                ),
            )
    except broker_paper_startup_store.PaperAuthorityStartupStoreError as exc:
        raise PaperConsumptionStoreError(
            "paper authority retention history verification failed"
        ) from exc
    except BrokerStateError as exc:
        raise PaperConsumptionStoreError(
            "automatic-paper broker evidence verification failed"
        ) from exc
    except duckdb.Error as exc:
        raise PaperConsumptionStoreError(
            "automatic-paper pre-call transaction failed"
        ) from exc
