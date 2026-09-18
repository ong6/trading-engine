"""Append-only operator adjudication for verified data discrepancies.

This ledger records an operator's disposition of one exact provider-source and
operational-cache state. It deliberately cannot repair cache data, change
quarantine state, grant trading authority, or carry out the selected follow-up.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import agent_data_discrepancy_review
from .json_utils import loads_object

SCHEMA_VERSION = 1
TABLE = "agent_data_discrepancy_decisions"
MAX_IDENTIFIER_CHARS = 128
MAX_JUSTIFICATION_CHARS = 2_000
DISPOSITIONS = agent_data_discrepancy_review.OPERATOR_DECISIONS
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLUMNS = (
    ("decision_sequence", "BIGINT"),
    ("decision_id", "VARCHAR"),
    ("discrepancy_state_sha256", "VARCHAR"),
    ("review_packet_sha256", "VARCHAR"),
    ("dataset", "VARCHAR"),
    ("ticker", "VARCHAR"),
    ("fact_date", "VARCHAR"),
    ("kind", "VARCHAR"),
    ("discrepancy_classification", "VARCHAR"),
    ("source_observation_sha256", "VARCHAR"),
    ("source_value_sha256", "VARCHAR"),
    ("cache_value_sha256", "VARCHAR"),
    ("disposition", "VARCHAR"),
    ("operator_id", "VARCHAR"),
    ("justification", "VARCHAR"),
    ("decided_at", "VARCHAR"),
    ("prior_decision_sha256", "VARCHAR"),
    ("decision_payload", "VARCHAR"),
    ("decision_sha256", "VARCHAR"),
)
_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "decision_sequence",
        "decision_id",
        "discrepancy_state_sha256",
        "review_packet_sha256",
        "dataset",
        "ticker",
        "fact_date",
        "kind",
        "discrepancy_classification",
        "source_observation_sha256",
        "source_value_sha256",
        "cache_value_sha256",
        "disposition",
        "operator_id",
        "justification",
        "decided_at",
        "prior_decision_sha256",
        "operational_effect",
        "cache_mutation_implemented",
        "quarantine_mutation_implemented",
        "execution_authority",
    }
)


class DataDiscrepancyAdjudicationError(ValueError):
    """A discrepancy adjudication request or retained event is invalid."""


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_IDENTIFIER_CHARS
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise DataDiscrepancyAdjudicationError(f"{label} is invalid")
    return value


def _hash(value: object, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DataDiscrepancyAdjudicationError(f"{label} is invalid")
    return value


def _justification(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_JUSTIFICATION_CHARS
        or not value.isprintable()
    ):
        raise DataDiscrepancyAdjudicationError(
            "adjudication justification is invalid"
        )
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise DataDiscrepancyAdjudicationError(f"{label} must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DataDiscrepancyAdjudicationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataDiscrepancyAdjudicationError(f"{label} is invalid") from exc
    if _timestamp(parsed, label) != value:
        raise DataDiscrepancyAdjudicationError(f"{label} is invalid")
    return parsed


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _schema(con: duckdb.DuckDBPyConnection) -> str:
    if not table_exists(con, TABLE):
        return "missing"
    rows = con.execute(f"DESCRIBE {TABLE}").fetchall()
    actual = tuple((row[0], row[1]) for row in rows)
    if actual != _COLUMNS:
        raise DataDiscrepancyAdjudicationError(
            "data discrepancy adjudication schema is invalid"
        )
    return "pass"


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create only the non-authorizing adjudication ledger."""
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            decision_sequence          BIGINT PRIMARY KEY,
            decision_id                VARCHAR UNIQUE NOT NULL,
            discrepancy_state_sha256   VARCHAR UNIQUE NOT NULL,
            review_packet_sha256       VARCHAR NOT NULL,
            dataset                    VARCHAR NOT NULL,
            ticker                     VARCHAR NOT NULL,
            fact_date                  VARCHAR NOT NULL,
            kind                       VARCHAR NOT NULL,
            discrepancy_classification VARCHAR NOT NULL,
            source_observation_sha256  VARCHAR NOT NULL,
            source_value_sha256        VARCHAR NOT NULL,
            cache_value_sha256         VARCHAR,
            disposition                VARCHAR NOT NULL,
            operator_id                VARCHAR NOT NULL,
            justification              VARCHAR NOT NULL,
            decided_at                 VARCHAR NOT NULL,
            prior_decision_sha256      VARCHAR,
            decision_payload           VARCHAR NOT NULL,
            decision_sha256            VARCHAR NOT NULL
        )
        """
    )
    _schema(con)


def _state(packet: dict) -> tuple[dict, str]:
    body = {
        "dataset": packet["dataset"],
        "ticker": packet["ticker"],
        "fact_date": packet["fact_date"],
        "kind": packet["kind"],
        "discrepancy_classification": packet["discrepancy_classification"],
        "source_observation_sha256": packet["source_observation"][
            "observation_sha256"
        ],
        "source_value_sha256": packet["source_observation"]["value_sha256"],
        "cache_value_sha256": (
            None
            if packet["current_cache"] is None
            else packet["current_cache"]["value_sha256"]
        ),
    }
    return body, canonical_sha256(body)


def _payload(
    *,
    sequence: int,
    decision_id: str,
    state_sha256: str,
    packet: dict,
    disposition: str,
    operator_id: str,
    justification: str,
    decided_at: str,
    prior_sha256: str | None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_sequence": sequence,
        "decision_id": decision_id,
        "discrepancy_state_sha256": state_sha256,
        "review_packet_sha256": packet["review_packet_sha256"],
        "dataset": packet["dataset"],
        "ticker": packet["ticker"],
        "fact_date": packet["fact_date"],
        "kind": packet["kind"],
        "discrepancy_classification": packet["discrepancy_classification"],
        "source_observation_sha256": packet["source_observation"][
            "observation_sha256"
        ],
        "source_value_sha256": packet["source_observation"]["value_sha256"],
        "cache_value_sha256": (
            None
            if packet["current_cache"] is None
            else packet["current_cache"]["value_sha256"]
        ),
        "disposition": disposition,
        "operator_id": operator_id,
        "justification": justification,
        "decided_at": decided_at,
        "prior_decision_sha256": prior_sha256,
        "operational_effect": "record_only_separate_follow_up_required",
        "cache_mutation_implemented": False,
        "quarantine_mutation_implemented": False,
        "execution_authority": "none",
    }


def _verify_payload(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise DataDiscrepancyAdjudicationError(
            "stored data discrepancy decision is invalid"
        )
    try:
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != SCHEMA_VERSION
            or isinstance(payload["decision_sequence"], bool)
            or not isinstance(payload["decision_sequence"], int)
            or payload["decision_sequence"] < 1
            or payload["disposition"] not in DISPOSITIONS
            or payload["discrepancy_classification"]
            not in {"current_cache_value_drift", "missing_current_cache_row"}
            or payload["operational_effect"]
            != "record_only_separate_follow_up_required"
            or payload["cache_mutation_implemented"] is not False
            or payload["quarantine_mutation_implemented"] is not False
            or payload["execution_authority"] != "none"
        ):
            raise DataDiscrepancyAdjudicationError(
                "stored data discrepancy decision is invalid"
            )
        _identifier(payload["decision_id"], "decision identifier")
        _identifier(payload["operator_id"], "operator identifier")
        _justification(payload["justification"])
        for field in (
            "discrepancy_state_sha256",
            "review_packet_sha256",
            "source_observation_sha256",
            "source_value_sha256",
        ):
            _hash(payload[field], field)
        _hash(
            payload["cache_value_sha256"],
            "cache value identity",
            nullable=True,
        )
        _hash(
            payload["prior_decision_sha256"],
            "prior decision identity",
            nullable=True,
        )
        _parse_timestamp(payload["decided_at"], "decision time")
        agent_data_discrepancy_review._key(
            payload["dataset"],
            payload["ticker"],
            agent_data_discrepancy_review.iso_date(payload["fact_date"]),
            payload["kind"],
        )
        state = {
            field: payload[field]
            for field in (
                "dataset",
                "ticker",
                "fact_date",
                "kind",
                "discrepancy_classification",
                "source_observation_sha256",
                "source_value_sha256",
                "cache_value_sha256",
            )
        }
        if canonical_sha256(state) != payload["discrepancy_state_sha256"]:
            raise DataDiscrepancyAdjudicationError(
                "stored data discrepancy decision is invalid"
            )
    except (
        KeyError,
        TypeError,
        ValueError,
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
    ) as exc:
        raise DataDiscrepancyAdjudicationError(
            "stored data discrepancy decision is invalid"
        ) from exc
    return dict(payload)


def _verified_events(con: duckdb.DuckDBPyConnection) -> list[dict]:
    if _schema(con) == "missing":
        return []
    rows = con.execute(
        f"SELECT {', '.join(name for name, _type in _COLUMNS)} "
        f"FROM {TABLE} ORDER BY decision_sequence"
    ).fetchall()
    events = []
    prior_sha256 = None
    prior_time = None
    seen_states = set()
    seen_ids = set()
    for expected_sequence, row in enumerate(rows, 1):
        stored = dict(zip((name for name, _type in _COLUMNS), row, strict=True))
        try:
            payload = loads_object(stored["decision_payload"])
            payload = _verify_payload(payload)
            decided_at = _parse_timestamp(payload["decided_at"], "decision time")
        except (
            TypeError,
            ValueError,
            UnicodeDecodeError,
            DataDiscrepancyAdjudicationError,
        ) as exc:
            raise DataDiscrepancyAdjudicationError(
                "stored data discrepancy decision is invalid"
            ) from exc
        row_payload = {
            key: stored[key]
            for key in _PAYLOAD_FIELDS
            if key
            not in {
                "schema_version",
                "operational_effect",
                "cache_mutation_implemented",
                "quarantine_mutation_implemented",
                "execution_authority",
            }
        }
        expected_row_payload = {
            key: payload[key]
            for key in row_payload
        }
        if (
            payload["decision_sequence"] != expected_sequence
            or payload["prior_decision_sha256"] != prior_sha256
            or prior_time is not None
            and decided_at < prior_time
            or payload["decision_id"] in seen_ids
            or payload["discrepancy_state_sha256"] in seen_states
            or row_payload != expected_row_payload
            or stored["decision_payload"] != _canonical(payload)
            or not isinstance(stored["decision_sha256"], str)
            or _SHA256.fullmatch(stored["decision_sha256"]) is None
            or stored["decision_sha256"] != canonical_sha256(payload)
        ):
            raise DataDiscrepancyAdjudicationError(
                "stored data discrepancy decision is invalid"
            )
        event = {**payload, "decision_sha256": stored["decision_sha256"]}
        events.append(event)
        seen_ids.add(payload["decision_id"])
        seen_states.add(payload["discrepancy_state_sha256"])
        prior_sha256 = stored["decision_sha256"]
        prior_time = decided_at
    return events


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return aggregate verified ledger status without exposing justifications."""
    events = _verified_events(con)
    counts = {disposition: 0 for disposition in DISPOSITIONS}
    for event in events:
        counts[event["disposition"]] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "initialized" if _schema(con) == "pass" else "not_initialized",
        "decision_count": len(events),
        "decisions_by_disposition": counts,
        "latest_decided_at": None if not events else events[-1]["decided_at"],
        "latest_decision_sha256": (
            None if not events else events[-1]["decision_sha256"]
        ),
        "operational_effect": "record_only_separate_follow_up_required",
        "cache_mutation_implemented": False,
        "quarantine_mutation_implemented": False,
        "execution_authority": "none",
    }


def record_decision(
    con: duckdb.DuckDBPyConnection,
    packet: object,
    *,
    decision_id: str,
    disposition: str,
    operator_id: str,
    justification: str,
    decided_at: datetime,
) -> dict:
    """Append one exact operator decision after retained-evidence revalidation."""
    decision_id = _identifier(decision_id, "decision identifier")
    operator_id = _identifier(operator_id, "operator identifier")
    justification = _justification(justification)
    if disposition not in DISPOSITIONS:
        raise DataDiscrepancyAdjudicationError(
            "data discrepancy disposition is invalid"
        )
    decided = _timestamp(decided_at, "decision time")
    try:
        with engine_db.transaction(con):
            verified = agent_data_discrepancy_review.verify(packet)
            _state_body, state_sha256 = _state(verified)
            events = _verified_events(con)
            matching = [
                event
                for event in events
                if event["decision_id"] == decision_id
                or event["discrepancy_state_sha256"] == state_sha256
            ]
            if matching:
                if len(matching) != 1:
                    raise DataDiscrepancyAdjudicationError(
                        "data discrepancy decision identity is ambiguous"
                    )
                event = matching[0]
                requested = {
                    "decision_id": decision_id,
                    "discrepancy_state_sha256": state_sha256,
                    "review_packet_sha256": verified["review_packet_sha256"],
                    "disposition": disposition,
                    "operator_id": operator_id,
                    "justification": justification,
                }
                if any(event[key] != value for key, value in requested.items()):
                    raise DataDiscrepancyAdjudicationError(
                        "data discrepancy decision conflicts with retained event"
                    )
                return event
            verified = agent_data_discrepancy_review.verify_retained(
                con,
                verified,
                reviewed_at=decided_at,
            )
            init_schema(con)
            if events and _parse_timestamp(
                events[-1]["decided_at"], "latest decision time"
            ) > decided_at:
                raise DataDiscrepancyAdjudicationError(
                    "decision time precedes the latest retained event"
                )
            payload = _payload(
                sequence=len(events) + 1,
                decision_id=decision_id,
                state_sha256=state_sha256,
                packet=verified,
                disposition=disposition,
                operator_id=operator_id,
                justification=justification,
                decided_at=decided,
                prior_sha256=(
                    None if not events else events[-1]["decision_sha256"]
                ),
            )
            decision_sha256 = canonical_sha256(payload)
            con.execute(
                f"INSERT INTO {TABLE} VALUES "
                f"({', '.join('?' for _ in _COLUMNS)})",
                [
                    payload.get(name)
                    if name not in {"decision_payload", "decision_sha256"}
                    else (
                        _canonical(payload)
                        if name == "decision_payload"
                        else decision_sha256
                    )
                    for name, _type in _COLUMNS
                ],
            )
            if _verified_events(con)[-1]["decision_sha256"] != decision_sha256:
                raise DataDiscrepancyAdjudicationError(
                    "data discrepancy decision failed post-write verification"
                )
    except agent_data_discrepancy_review.DataDiscrepancyReviewError as exc:
        raise DataDiscrepancyAdjudicationError(str(exc)) from exc
    return {**payload, "decision_sha256": decision_sha256}
