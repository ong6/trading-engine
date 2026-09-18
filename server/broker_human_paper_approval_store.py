"""Durable replay protection for authenticated human paper-decision evidence.

The ledger records only decisions that pass the retained-evidence and detached
authenticator composition in :mod:`broker_human_paper_approval`. It retains the
exact policy, envelope, review packet, and verification result; globally
sequences and hash-chains observations; and rejects reuse of an approval,
envelope, packet, or request identity for different evidence.

This is not authority consumption. An authenticated ``approve_exact_intent``
observation still grants no approval, creates no route, and cannot submit.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import broker_human_paper_approval, broker_human_paper_review
from .json_utils import loads_object

SCHEMA_VERSION = 1
TABLE = "broker_human_paper_approval_observations"
MAX_OBSERVATIONS = 4_096
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLUMNS = (
    ("observation_sequence", "BIGINT"),
    ("approval_id", "VARCHAR"),
    ("envelope_sha256", "VARCHAR"),
    ("review_request_sha256", "VARCHAR"),
    ("request_sha256", "VARCHAR"),
    ("decision", "VARCHAR"),
    ("approval_source_id", "VARCHAR"),
    ("signer_policy_id", "VARCHAR"),
    ("signer_policy_version", "VARCHAR"),
    ("signer_identity", "VARCHAR"),
    ("authenticator_algorithm", "VARCHAR"),
    ("selected_policy_sha256", "VARCHAR"),
    ("signing_payload_sha256", "VARCHAR"),
    ("authenticated_at", "VARCHAR"),
    ("recorded_at", "VARCHAR"),
    ("prior_observation_sha256", "VARCHAR"),
    ("policy_payload", "VARCHAR"),
    ("envelope_payload", "VARCHAR"),
    ("review_packet_payload", "VARCHAR"),
    ("verification_payload", "VARCHAR"),
    ("verification_sha256", "VARCHAR"),
    ("observation_payload", "VARCHAR"),
    ("observation_sha256", "VARCHAR"),
)
_VERIFICATION_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "decision",
        "approval_id",
        "approval_source_id",
        "signer_policy_id",
        "signer_policy_version",
        "signer_identity",
        "authenticator_algorithm",
        "review_request_sha256",
        "request_sha256",
        "envelope_sha256",
        "signing_payload_sha256",
        "selected_policy_sha256",
        "observed_at",
        "packet_integrity_verified",
        "retained_evidence_revalidated",
        "authenticator_verified",
        "policy_scope_verified",
        "trust_source_loader_implemented",
        "one_use_enforcement_implemented",
        "human_order_approval_granted",
        "persistence_implemented",
        "paper_order_route",
        "submission_authority",
        "verification_sha256",
    }
)
_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "observation_sequence",
        "status",
        "approval_id",
        "envelope_sha256",
        "review_request_sha256",
        "request_sha256",
        "decision",
        "approval_source_id",
        "signer_policy_id",
        "signer_policy_version",
        "signer_identity",
        "authenticator_algorithm",
        "selected_policy_sha256",
        "signing_payload_sha256",
        "authenticated_at",
        "recorded_at",
        "prior_observation_sha256",
        "policy_payload_sha256",
        "envelope_payload_sha256",
        "review_packet_payload_sha256",
        "verification_sha256",
        "authenticated_evidence_replay_protection",
        "production_authority_consumption_implemented",
        "human_order_approval_granted",
        "paper_order_route",
        "submission_authority",
    }
)
_UNIQUE_FIELDS = (
    "approval_id",
    "envelope_sha256",
    "review_request_sha256",
    "request_sha256",
)


class HumanPaperApprovalStoreError(ValueError):
    """Authenticated approval evidence cannot be safely retained or verified."""


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash(value: object, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HumanPaperApprovalStoreError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise HumanPaperApprovalStoreError(f"{label} must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanPaperApprovalStoreError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanPaperApprovalStoreError(f"{label} is invalid") from exc
    if _timestamp(parsed, label) != value:
        raise HumanPaperApprovalStoreError(f"{label} is invalid")
    return parsed


def _schema(con: duckdb.DuckDBPyConnection) -> str:
    if not table_exists(con, TABLE):
        return "missing"
    actual = tuple(
        (row[0], row[1]) for row in con.execute(f"DESCRIBE {TABLE}").fetchall()
    )
    if actual != _COLUMNS:
        raise HumanPaperApprovalStoreError(
            "human paper approval observation schema is invalid"
        )
    return "pass"


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create only the non-authorizing authenticated-evidence ledger."""
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            observation_sequence       BIGINT PRIMARY KEY,
            approval_id                VARCHAR UNIQUE NOT NULL,
            envelope_sha256            VARCHAR UNIQUE NOT NULL,
            review_request_sha256      VARCHAR UNIQUE NOT NULL,
            request_sha256             VARCHAR UNIQUE NOT NULL,
            decision                   VARCHAR NOT NULL,
            approval_source_id         VARCHAR NOT NULL,
            signer_policy_id           VARCHAR NOT NULL,
            signer_policy_version      VARCHAR NOT NULL,
            signer_identity            VARCHAR NOT NULL,
            authenticator_algorithm    VARCHAR NOT NULL,
            selected_policy_sha256     VARCHAR NOT NULL,
            signing_payload_sha256     VARCHAR NOT NULL,
            authenticated_at           VARCHAR NOT NULL,
            recorded_at                VARCHAR NOT NULL,
            prior_observation_sha256   VARCHAR,
            policy_payload             VARCHAR NOT NULL,
            envelope_payload           VARCHAR NOT NULL,
            review_packet_payload      VARCHAR NOT NULL,
            verification_payload       VARCHAR NOT NULL,
            verification_sha256        VARCHAR NOT NULL,
            observation_payload        VARCHAR NOT NULL,
            observation_sha256         VARCHAR NOT NULL UNIQUE
        )
        """
    )
    _schema(con)


def _verification(
    value: object,
    *,
    policy: broker_human_paper_approval.HumanApprovalPolicy,
    envelope: broker_human_paper_approval.HumanApprovalEnvelope,
    packet: dict,
) -> dict:
    if not isinstance(value, dict) or set(value) != _VERIFICATION_FIELDS:
        raise HumanPaperApprovalStoreError(
            "authenticated human paper decision evidence is invalid"
        )
    body = {
        key: item for key, item in value.items() if key != "verification_sha256"
    }
    hashes = (
        "review_request_sha256",
        "request_sha256",
        "envelope_sha256",
        "signing_payload_sha256",
        "selected_policy_sha256",
        "verification_sha256",
    )
    try:
        for field in hashes:
            _hash(value[field], field)
        _parse_timestamp(value["observed_at"], "authentication observation time")
    except (KeyError, TypeError, ValueError) as exc:
        raise HumanPaperApprovalStoreError(
            "authenticated human paper decision evidence is invalid"
        ) from exc
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"]
        != broker_human_paper_approval.VERIFICATION_SCHEMA_VERSION
        or value["status"] != "authenticated_decision_design_evidence"
        or value["decision"] != envelope.decision
        or value["approval_id"] != envelope.approval_id
        or value["approval_source_id"] != envelope.approval_source_id
        or value["signer_policy_id"] != envelope.signer_policy_id
        or value["signer_policy_version"] != envelope.signer_policy_version
        or value["signer_identity"] != envelope.signer_identity
        or value["authenticator_algorithm"] != envelope.authenticator_algorithm
        or value["review_request_sha256"] != packet["review_request_sha256"]
        or value["request_sha256"] != packet["request_sha256"]
        or value["envelope_sha256"] != envelope.sha256()
        or value["signing_payload_sha256"]
        != canonical_sha256(envelope.signing_payload())
        or value["selected_policy_sha256"] != policy.sha256()
        or value["packet_integrity_verified"] is not True
        or value["retained_evidence_revalidated"] is not True
        or value["authenticator_verified"] is not True
        or value["policy_scope_verified"] is not True
        or value["trust_source_loader_implemented"] is not False
        or value["one_use_enforcement_implemented"] is not False
        or value["human_order_approval_granted"] is not False
        or value["persistence_implemented"] is not False
        or value["paper_order_route"] != "absent"
        or value["submission_authority"] != "none"
        or value["verification_sha256"] != canonical_sha256(body)
    ):
        raise HumanPaperApprovalStoreError(
            "authenticated human paper decision evidence is invalid"
        )
    return dict(value)


def _observation_payload(
    verification: dict,
    *,
    sequence: int,
    recorded_at: str,
    prior_sha256: str | None,
    policy_payload: dict,
    envelope_payload: dict,
    packet: dict,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_sequence": sequence,
        "status": "authenticated_decision_observed_non_authorizing",
        "approval_id": verification["approval_id"],
        "envelope_sha256": verification["envelope_sha256"],
        "review_request_sha256": verification["review_request_sha256"],
        "request_sha256": verification["request_sha256"],
        "decision": verification["decision"],
        "approval_source_id": verification["approval_source_id"],
        "signer_policy_id": verification["signer_policy_id"],
        "signer_policy_version": verification["signer_policy_version"],
        "signer_identity": verification["signer_identity"],
        "authenticator_algorithm": verification["authenticator_algorithm"],
        "selected_policy_sha256": verification["selected_policy_sha256"],
        "signing_payload_sha256": verification["signing_payload_sha256"],
        "authenticated_at": verification["observed_at"],
        "recorded_at": recorded_at,
        "prior_observation_sha256": prior_sha256,
        "policy_payload_sha256": canonical_sha256(policy_payload),
        "envelope_payload_sha256": canonical_sha256(envelope_payload),
        "review_packet_payload_sha256": canonical_sha256(packet),
        "verification_sha256": verification["verification_sha256"],
        "authenticated_evidence_replay_protection": True,
        "production_authority_consumption_implemented": False,
        "human_order_approval_granted": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def _verify_observation_payload(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _OBSERVATION_FIELDS:
        raise HumanPaperApprovalStoreError(
            "stored human paper approval observation is invalid"
        )
    try:
        for field in (
            "envelope_sha256",
            "review_request_sha256",
            "request_sha256",
            "selected_policy_sha256",
            "signing_payload_sha256",
            "prior_observation_sha256",
            "policy_payload_sha256",
            "envelope_payload_sha256",
            "review_packet_payload_sha256",
            "verification_sha256",
        ):
            _hash(
                value[field],
                field,
                nullable=field == "prior_observation_sha256",
            )
        _parse_timestamp(value["authenticated_at"], "authentication observation time")
        _parse_timestamp(value["recorded_at"], "approval evidence record time")
    except (KeyError, TypeError, ValueError) as exc:
        raise HumanPaperApprovalStoreError(
            "stored human paper approval observation is invalid"
        ) from exc
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or isinstance(value["observation_sequence"], bool)
        or not isinstance(value["observation_sequence"], int)
        or value["observation_sequence"] < 1
        or value["status"] != "authenticated_decision_observed_non_authorizing"
        or value["decision"] not in broker_human_paper_approval.DECISIONS
        or value["authenticated_evidence_replay_protection"] is not True
        or value["production_authority_consumption_implemented"] is not False
        or value["human_order_approval_granted"] is not False
        or value["paper_order_route"] != "absent"
        or value["submission_authority"] != "none"
    ):
        raise HumanPaperApprovalStoreError(
            "stored human paper approval observation is invalid"
        )
    for field, label in (
        ("approval_id", "approval identifier"),
        ("approval_source_id", "approval source identifier"),
        ("signer_policy_id", "signer policy identifier"),
        ("signer_policy_version", "signer policy version"),
        ("signer_identity", "signer identity"),
        ("authenticator_algorithm", "authenticator algorithm"),
    ):
        broker_human_paper_approval._identifier(value[field], label)
    return dict(value)


def _stored_document(value: object, label: str) -> dict:
    if not isinstance(value, str):
        raise HumanPaperApprovalStoreError(f"stored {label} is invalid")
    try:
        parsed = loads_object(value)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise HumanPaperApprovalStoreError(f"stored {label} is invalid") from exc
    if value != _canonical(parsed):
        raise HumanPaperApprovalStoreError(f"stored {label} is invalid")
    return parsed


def _capture_rows(
    con: duckdb.DuckDBPyConnection,
) -> tuple[str, tuple[tuple[object, ...], ...]]:
    if _schema(con) == "missing":
        return "missing", ()
    rows = tuple(
        tuple(row)
        for row in con.execute(
            f"SELECT {', '.join(name for name, _type in _COLUMNS)} "
            f"FROM {TABLE} ORDER BY observation_sequence LIMIT ?",
            [MAX_OBSERVATIONS + 1],
        ).fetchall()
    )
    if len(rows) > MAX_OBSERVATIONS:
        raise HumanPaperApprovalStoreError(
            "human paper approval observation count exceeds the verification bound"
        )
    return "present", rows


def _verified_events(
    con: duckdb.DuckDBPyConnection,
    rows: tuple[tuple[object, ...], ...] | None = None,
) -> list[dict]:
    rows = _capture_rows(con)[1] if rows is None else rows
    events = []
    seen = {field: set() for field in _UNIQUE_FIELDS}
    prior_sha256 = None
    prior_recorded_at = None
    for expected_sequence, row in enumerate(rows, 1):
        stored = dict(zip((name for name, _type in _COLUMNS), row, strict=True))
        policy_payload = _stored_document(stored["policy_payload"], "approval policy")
        envelope_payload = _stored_document(
            stored["envelope_payload"], "approval envelope"
        )
        packet = _stored_document(
            stored["review_packet_payload"], "human review packet"
        )
        verification_payload = _stored_document(
            stored["verification_payload"], "approval verification"
        )
        observation_payload = _stored_document(
            stored["observation_payload"], "approval observation"
        )
        try:
            policy = broker_human_paper_approval.policy_from_payload(policy_payload)
            envelope = broker_human_paper_approval.envelope_from_payload(
                envelope_payload
            )
            packet = broker_human_paper_review.verify(packet)
            verification = _verification(
                verification_payload,
                policy=policy,
                envelope=envelope,
                packet=packet,
            )
            observation = _verify_observation_payload(observation_payload)
            authenticated_at = _parse_timestamp(
                observation["authenticated_at"],
                "authentication observation time",
            )
            recorded_at = _parse_timestamp(
                observation["recorded_at"],
                "approval evidence record time",
            )
            retained_packet = broker_human_paper_review.verify_retained(
                con,
                packet,
                reviewed_at=authenticated_at,
            )
        except (
            broker_human_paper_approval.HumanPaperApprovalError,
            broker_human_paper_review.HumanPaperReviewError,
            HumanPaperApprovalStoreError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise HumanPaperApprovalStoreError(
                "stored human paper approval observation is invalid"
            ) from exc
        row_payload = {
            field: stored[field]
            for field in _OBSERVATION_FIELDS
            if field
            not in {
                "schema_version",
                "status",
                "policy_payload_sha256",
                "envelope_payload_sha256",
                "review_packet_payload_sha256",
                "authenticated_evidence_replay_protection",
                "production_authority_consumption_implemented",
                "human_order_approval_granted",
                "paper_order_route",
                "submission_authority",
            }
        }
        expected_row_payload = {
            field: observation[field] for field in row_payload
        }
        duplicates = any(
            observation[field] in seen[field] for field in _UNIQUE_FIELDS
        )
        if (
            observation["observation_sequence"] != expected_sequence
            or observation["prior_observation_sha256"] != prior_sha256
            or authenticated_at > recorded_at
            or prior_recorded_at is not None
            and recorded_at < prior_recorded_at
            or duplicates
            or observation["policy_payload_sha256"] != policy.sha256()
            or observation["envelope_payload_sha256"] != envelope.sha256()
            or observation["review_packet_payload_sha256"]
            != canonical_sha256(packet)
            or retained_packet != packet
            or observation["verification_sha256"]
            != verification["verification_sha256"]
            or row_payload != expected_row_payload
            or stored["verification_sha256"]
            != verification["verification_sha256"]
            or stored["observation_sha256"] != canonical_sha256(observation)
        ):
            raise HumanPaperApprovalStoreError(
                "stored human paper approval observation is invalid"
            )
        event = {
            **observation,
            "observation_sha256": stored["observation_sha256"],
        }
        events.append(event)
        for field in _UNIQUE_FIELDS:
            seen[field].add(observation[field])
        prior_sha256 = stored["observation_sha256"]
        prior_recorded_at = recorded_at
    return events


def verify_complete_history(
    con: duckdb.DuckDBPyConnection,
    *,
    trusted_observation_count: int,
    trusted_latest_observation_sha256: str | None,
) -> dict:
    """Verify the complete stable ledger against an independently trusted head."""
    if (
        isinstance(trusted_observation_count, bool)
        or not isinstance(trusted_observation_count, int)
        or not 0 <= trusted_observation_count <= MAX_OBSERVATIONS
    ):
        raise HumanPaperApprovalStoreError(
            "trusted approval observation count is invalid"
        )
    trusted_latest_observation_sha256 = _hash(
        trusted_latest_observation_sha256,
        "trusted latest approval observation identity",
        nullable=trusted_observation_count == 0,
    )
    if (
        trusted_observation_count == 0
        and trusted_latest_observation_sha256 is not None
        or trusted_observation_count > 0
        and trusted_latest_observation_sha256 is None
    ):
        raise HumanPaperApprovalStoreError(
            "trusted approval observation count and head are inconsistent"
        )
    try:
        first = _capture_rows(con)
        events = _verified_events(con, first[1])
        second = _capture_rows(con)
    except duckdb.Error as exc:
        raise HumanPaperApprovalStoreError(
            "human paper approval observation ledger is unreadable"
        ) from exc
    if first != second:
        raise HumanPaperApprovalStoreError(
            "human paper approval observation ledger changed during verification"
        )
    actual_head = None if not events else events[-1]["observation_sha256"]
    if (
        len(events) != trusted_observation_count
        or actual_head != trusted_latest_observation_sha256
    ):
        raise HumanPaperApprovalStoreError(
            "human paper approval observation ledger does not match the trusted head"
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_history_verified_non_authorizing",
        "trusted_observation_count": trusted_observation_count,
        "trusted_latest_observation_sha256": (
            trusted_latest_observation_sha256
        ),
        "approve_observation_count": sum(
            event["decision"] == "approve_exact_intent" for event in events
        ),
        "reject_observation_count": sum(
            event["decision"] == "reject" for event in events
        ),
        "latest_recorded_at": None if not events else events[-1]["recorded_at"],
        "independent_head_required": True,
        "approval_selection_implemented": False,
        "trust_source_loader_implemented": False,
        "production_authority_consumption_implemented": False,
        "human_order_approval_granted": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {**body, "history_evidence_sha256": canonical_sha256(body)}


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded verified replay-protection status without signer material."""
    events = _verified_events(con)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "initialized" if _schema(con) == "pass" else "not_initialized",
        "observation_count": len(events),
        "approve_observation_count": sum(
            event["decision"] == "approve_exact_intent" for event in events
        ),
        "reject_observation_count": sum(
            event["decision"] == "reject" for event in events
        ),
        "latest_recorded_at": None if not events else events[-1]["recorded_at"],
        "latest_observation_sha256": (
            None if not events else events[-1]["observation_sha256"]
        ),
        "authenticated_evidence_replay_protection_implemented": True,
        "production_authority_consumption_implemented": False,
        "trust_source_loader_implemented": False,
        "human_order_approval_granted": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def _recording_inputs(
    envelope: object,
    review_packet: object,
    policy: object,
    selected_policy_sha256: str,
) -> tuple[
    broker_human_paper_approval.HumanApprovalEnvelope,
    broker_human_paper_approval.HumanApprovalPolicy,
    dict,
]:
    if not isinstance(
        policy,
        broker_human_paper_approval.HumanApprovalPolicy,
    ):
        raise TypeError("policy must be a HumanApprovalPolicy")
    if not isinstance(
        envelope,
        broker_human_paper_approval.HumanApprovalEnvelope,
    ):
        raise TypeError("envelope must be a HumanApprovalEnvelope")
    if selected_policy_sha256 != policy.sha256():
        raise HumanPaperApprovalStoreError(
            "signer policy does not match the explicitly selected policy identity"
        )
    return envelope, policy, broker_human_paper_review.verify(review_packet)


def record_retained_authenticated_decision(
    con: duckdb.DuckDBPyConnection,
    envelope: broker_human_paper_approval.HumanApprovalEnvelope,
    review_packet: object,
    policy: broker_human_paper_approval.HumanApprovalPolicy,
    *,
    selected_policy_sha256: str,
    authenticator_verifier: broker_human_paper_approval.AuthenticatorVerifier,
    observed_at: datetime,
    recorded_at: datetime,
) -> dict:
    """Authenticate retained evidence and append one non-authorizing observation."""
    recorded = _timestamp(recorded_at, "approval evidence record time")
    try:
        with engine_db.transaction(con):
            envelope, policy, packet = _recording_inputs(
                envelope,
                review_packet,
                policy,
                selected_policy_sha256,
            )
            if _schema(con) != "pass":
                raise HumanPaperApprovalStoreError(
                    "human paper approval observation ledger is not initialized"
                )
            events = _verified_events(con)
            policy_payload = policy.payload()
            envelope_payload = envelope.payload()
            candidate = {
                "approval_id": envelope.approval_id,
                "envelope_sha256": envelope.sha256(),
                "review_request_sha256": packet["review_request_sha256"],
                "request_sha256": packet["request_sha256"],
            }
            matching = [
                event
                for event in events
                if any(event[field] == candidate[field] for field in _UNIQUE_FIELDS)
            ]
            if matching:
                event = matching[0] if len(matching) == 1 else None
                exact = (
                    event is not None
                    and all(event[field] == candidate[field] for field in _UNIQUE_FIELDS)
                    and event["decision"] == envelope.decision
                    and event["selected_policy_sha256"] == policy.sha256()
                    and event["policy_payload_sha256"]
                    == canonical_sha256(policy_payload)
                    and event["envelope_payload_sha256"]
                    == canonical_sha256(envelope_payload)
                    and event["review_packet_payload_sha256"]
                    == canonical_sha256(packet)
                )
                if not exact:
                    raise HumanPaperApprovalStoreError(
                        "human paper approval identity conflicts with retained evidence"
                    )
                return event
            verification = (
                broker_human_paper_approval.verify_retained_authenticated_decision(
                    con,
                    envelope,
                    review_packet,
                    policy,
                    selected_policy_sha256=selected_policy_sha256,
                    authenticator_verifier=authenticator_verifier,
                    observed_at=observed_at,
                )
            )
            verified = _verification(
                verification,
                policy=policy,
                envelope=envelope,
                packet=packet,
            )
            authenticated_at = _parse_timestamp(
                verified["observed_at"],
                "authentication observation time",
            )
            recorded_value = _parse_timestamp(
                recorded,
                "approval evidence record time",
            )
            if recorded_value < authenticated_at:
                raise HumanPaperApprovalStoreError(
                    "approval evidence record precedes authentication"
                )
            if events and recorded_value < _parse_timestamp(
                events[-1]["recorded_at"],
                "latest approval evidence record time",
            ):
                raise HumanPaperApprovalStoreError(
                    "approval evidence record time precedes the latest observation"
                )
            observation = _observation_payload(
                verified,
                sequence=len(events) + 1,
                recorded_at=recorded,
                prior_sha256=(
                    None if not events else events[-1]["observation_sha256"]
                ),
                policy_payload=policy_payload,
                envelope_payload=envelope_payload,
                packet=packet,
            )
            observation_sha256 = canonical_sha256(observation)
            documents = {
                "policy_payload": _canonical(policy_payload),
                "envelope_payload": _canonical(envelope_payload),
                "review_packet_payload": _canonical(packet),
                "verification_payload": _canonical(verified),
                "observation_payload": _canonical(observation),
            }
            con.execute(
                f"INSERT INTO {TABLE} VALUES "
                f"({', '.join('?' for _ in _COLUMNS)})",
                [
                    documents[name]
                    if name in documents
                    else observation_sha256
                    if name == "observation_sha256"
                    else observation.get(name)
                    for name, _type in _COLUMNS
                ],
            )
            retained = _verified_events(con)
            if retained[-1]["observation_sha256"] != observation_sha256:
                raise HumanPaperApprovalStoreError(
                    "human paper approval observation failed post-write verification"
                )
    except (
        broker_human_paper_approval.HumanPaperApprovalError,
        broker_human_paper_review.HumanPaperReviewError,
    ) as exc:
        raise HumanPaperApprovalStoreError(str(exc)) from exc
    return {**observation, "observation_sha256": observation_sha256}
