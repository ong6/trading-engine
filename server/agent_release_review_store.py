"""Durable replay protection for authenticated release-review evidence.

This store records only results already verified by
``agent_release_readiness.verify_review``. It re-inspects the current release
before authentication, retains exact canonical evidence, and globally
hash-chains observations. It never grants release or execution authority.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from engine.lib.util import table_exists

from . import agent_release_readiness
from .json_utils import loads_object

SCHEMA_VERSION = 1
TABLE = "agent_release_review_observations"
MAX_OBSERVATIONS = 4_096
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLUMNS = (
    ("observation_sequence", "BIGINT"),
    ("review_id", "VARCHAR"),
    ("envelope_sha256", "VARCHAR"),
    ("manifest_sha256", "VARCHAR"),
    ("release_readiness_sha256", "VARCHAR"),
    ("decision", "VARCHAR"),
    ("review_source_id", "VARCHAR"),
    ("reviewer_policy_id", "VARCHAR"),
    ("reviewer_policy_version", "VARCHAR"),
    ("reviewer_identity", "VARCHAR"),
    ("authenticator_algorithm", "VARCHAR"),
    ("selected_policy_sha256", "VARCHAR"),
    ("signing_payload_sha256", "VARCHAR"),
    ("authenticated_at", "VARCHAR"),
    ("recorded_at", "VARCHAR"),
    ("prior_observation_sha256", "VARCHAR"),
    ("policy_payload", "VARCHAR"),
    ("envelope_payload", "VARCHAR"),
    ("release_readiness_payload", "VARCHAR"),
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
        "review_id",
        "manifest_sha256",
        "release_readiness_sha256",
        "git_commit",
        "git_tree",
        "review_source_id",
        "reviewer_policy_id",
        "reviewer_policy_version",
        "reviewer_identity",
        "authenticator_algorithm",
        "selected_policy_sha256",
        "envelope_sha256",
        "signing_payload_sha256",
        "observed_at",
        "manifest_eligibility_verified",
        "authenticator_verified",
        "reviewed_release",
        "persistence_implemented",
        "readiness_integration_implemented",
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
        "review_id",
        "envelope_sha256",
        "manifest_sha256",
        "release_readiness_sha256",
        "decision",
        "review_source_id",
        "reviewer_policy_id",
        "reviewer_policy_version",
        "reviewer_identity",
        "authenticator_algorithm",
        "selected_policy_sha256",
        "signing_payload_sha256",
        "authenticated_at",
        "recorded_at",
        "prior_observation_sha256",
        "policy_payload_sha256",
        "envelope_payload_sha256",
        "release_readiness_payload_sha256",
        "verification_sha256",
        "authenticated_evidence_replay_protection",
        "production_readiness_integration_implemented",
        "reviewed_release_gate_passed",
        "paper_order_route",
        "submission_authority",
    }
)
_UNIQUE_FIELDS = (
    "review_id",
    "envelope_sha256",
    "manifest_sha256",
    "release_readiness_sha256",
)


class ReleaseReviewStoreError(ValueError):
    """Authenticated release-review evidence cannot be safely retained."""


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
        raise ReleaseReviewStoreError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise ReleaseReviewStoreError(f"{label} must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseReviewStoreError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseReviewStoreError(f"{label} is invalid") from exc
    if _timestamp(parsed, label) != value:
        raise ReleaseReviewStoreError(f"{label} is invalid")
    return parsed


def _schema(con: duckdb.DuckDBPyConnection) -> str:
    if not table_exists(con, TABLE):
        return "missing"
    actual = tuple(
        (row[0], row[1]) for row in con.execute(f"DESCRIBE {TABLE}").fetchall()
    )
    if actual != _COLUMNS:
        raise ReleaseReviewStoreError(
            "release review observation schema is invalid"
        )
    return "pass"


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create only the non-authorizing release-review evidence ledger."""
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            observation_sequence              BIGINT PRIMARY KEY,
            review_id                         VARCHAR UNIQUE NOT NULL,
            envelope_sha256                   VARCHAR UNIQUE NOT NULL,
            manifest_sha256                   VARCHAR UNIQUE NOT NULL,
            release_readiness_sha256          VARCHAR UNIQUE NOT NULL,
            decision                          VARCHAR NOT NULL,
            review_source_id                  VARCHAR NOT NULL,
            reviewer_policy_id                VARCHAR NOT NULL,
            reviewer_policy_version           VARCHAR NOT NULL,
            reviewer_identity                 VARCHAR NOT NULL,
            authenticator_algorithm           VARCHAR NOT NULL,
            selected_policy_sha256            VARCHAR NOT NULL,
            signing_payload_sha256            VARCHAR NOT NULL,
            authenticated_at                  VARCHAR NOT NULL,
            recorded_at                       VARCHAR NOT NULL,
            prior_observation_sha256          VARCHAR,
            policy_payload                    VARCHAR NOT NULL,
            envelope_payload                  VARCHAR NOT NULL,
            release_readiness_payload         VARCHAR NOT NULL,
            verification_payload              VARCHAR NOT NULL,
            verification_sha256               VARCHAR NOT NULL,
            observation_payload               VARCHAR NOT NULL,
            observation_sha256                VARCHAR NOT NULL UNIQUE
        )
        """
    )
    _schema(con)


def _verification(
    value: object,
    *,
    policy: agent_release_readiness.ReleaseReviewPolicy,
    envelope: agent_release_readiness.ReleaseReviewEnvelope,
    readiness: dict,
) -> dict:
    if not isinstance(value, dict) or set(value) != _VERIFICATION_FIELDS:
        raise ReleaseReviewStoreError(
            "authenticated release review evidence is invalid"
        )
    body = {
        key: item for key, item in value.items() if key != "verification_sha256"
    }
    try:
        for field in (
            "manifest_sha256",
            "release_readiness_sha256",
            "selected_policy_sha256",
            "envelope_sha256",
            "signing_payload_sha256",
            "verification_sha256",
        ):
            _hash(value[field], field)
        _parse_timestamp(value["observed_at"], "release authentication time")
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseReviewStoreError(
            "authenticated release review evidence is invalid"
        ) from exc
    reviewed = envelope.decision == "approve_release"
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"]
        != agent_release_readiness.REVIEW_VERIFICATION_SCHEMA_VERSION
        or value["status"]
        != (
            "reviewed_release_design_evidence"
            if reviewed
            else "release_rejected_design_evidence"
        )
        or value["decision"] != envelope.decision
        or value["review_id"] != envelope.review_id
        or value["manifest_sha256"] != readiness["manifest_sha256"]
        or value["release_readiness_sha256"]
        != readiness["release_readiness_sha256"]
        or value["git_commit"] != readiness["git_commit"]
        or value["git_tree"] != readiness["git_tree"]
        or value["review_source_id"] != envelope.review_source_id
        or value["reviewer_policy_id"] != envelope.reviewer_policy_id
        or value["reviewer_policy_version"] != envelope.reviewer_policy_version
        or value["reviewer_identity"] != envelope.reviewer_identity
        or value["authenticator_algorithm"] != envelope.authenticator_algorithm
        or value["selected_policy_sha256"] != policy.sha256()
        or value["envelope_sha256"] != envelope.sha256()
        or value["signing_payload_sha256"]
        != canonical_sha256(envelope.signing_payload())
        or value["manifest_eligibility_verified"] is not True
        or value["authenticator_verified"] is not True
        or value["reviewed_release"] is not reviewed
        or value["persistence_implemented"] is not False
        or value["readiness_integration_implemented"] is not False
        or value["paper_order_route"] != "absent"
        or value["submission_authority"] != "none"
        or value["verification_sha256"] != canonical_sha256(body)
    ):
        raise ReleaseReviewStoreError(
            "authenticated release review evidence is invalid"
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
    readiness: dict,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_sequence": sequence,
        "status": "authenticated_release_review_observed_non_authorizing",
        "review_id": verification["review_id"],
        "envelope_sha256": verification["envelope_sha256"],
        "manifest_sha256": verification["manifest_sha256"],
        "release_readiness_sha256": verification[
            "release_readiness_sha256"
        ],
        "decision": verification["decision"],
        "review_source_id": verification["review_source_id"],
        "reviewer_policy_id": verification["reviewer_policy_id"],
        "reviewer_policy_version": verification["reviewer_policy_version"],
        "reviewer_identity": verification["reviewer_identity"],
        "authenticator_algorithm": verification[
            "authenticator_algorithm"
        ],
        "selected_policy_sha256": verification["selected_policy_sha256"],
        "signing_payload_sha256": verification["signing_payload_sha256"],
        "authenticated_at": verification["observed_at"],
        "recorded_at": recorded_at,
        "prior_observation_sha256": prior_sha256,
        "policy_payload_sha256": canonical_sha256(policy_payload),
        "envelope_payload_sha256": canonical_sha256(envelope_payload),
        "release_readiness_payload_sha256": canonical_sha256(readiness),
        "verification_sha256": verification["verification_sha256"],
        "authenticated_evidence_replay_protection": True,
        "production_readiness_integration_implemented": False,
        "reviewed_release_gate_passed": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def _verify_observation_payload(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _OBSERVATION_FIELDS:
        raise ReleaseReviewStoreError(
            "stored release review observation is invalid"
        )
    try:
        for field in (
            "envelope_sha256",
            "manifest_sha256",
            "release_readiness_sha256",
            "selected_policy_sha256",
            "signing_payload_sha256",
            "prior_observation_sha256",
            "policy_payload_sha256",
            "envelope_payload_sha256",
            "release_readiness_payload_sha256",
            "verification_sha256",
        ):
            _hash(
                value[field],
                field,
                nullable=field == "prior_observation_sha256",
            )
        _parse_timestamp(value["authenticated_at"], "release authentication time")
        _parse_timestamp(value["recorded_at"], "release review record time")
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseReviewStoreError(
            "stored release review observation is invalid"
        ) from exc
    for field, label in (
        ("review_id", "release review identifier"),
        ("review_source_id", "release review source"),
        ("reviewer_policy_id", "release reviewer policy"),
        ("reviewer_policy_version", "release reviewer policy version"),
        ("reviewer_identity", "release reviewer identity"),
        ("authenticator_algorithm", "release authenticator algorithm"),
    ):
        agent_release_readiness._identifier(value[field], label)
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or isinstance(value["observation_sequence"], bool)
        or not isinstance(value["observation_sequence"], int)
        or value["observation_sequence"] < 1
        or value["status"]
        != "authenticated_release_review_observed_non_authorizing"
        or value["decision"] not in {"approve_release", "reject_release"}
        or value["authenticated_evidence_replay_protection"] is not True
        or value["production_readiness_integration_implemented"] is not False
        or value["reviewed_release_gate_passed"] is not False
        or value["paper_order_route"] != "absent"
        or value["submission_authority"] != "none"
    ):
        raise ReleaseReviewStoreError(
            "stored release review observation is invalid"
        )
    return dict(value)


def _stored_document(value: object, label: str) -> dict:
    if not isinstance(value, str):
        raise ReleaseReviewStoreError(f"stored {label} is invalid")
    try:
        parsed = loads_object(value)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReleaseReviewStoreError(f"stored {label} is invalid") from exc
    if value != _canonical(parsed):
        raise ReleaseReviewStoreError(f"stored {label} is invalid")
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
        raise ReleaseReviewStoreError(
            "release review observation count exceeds the verification bound"
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
        policy_payload = _stored_document(
            stored["policy_payload"], "release review policy"
        )
        envelope_payload = _stored_document(
            stored["envelope_payload"], "release review envelope"
        )
        readiness_payload = _stored_document(
            stored["release_readiness_payload"], "release readiness"
        )
        verification_payload = _stored_document(
            stored["verification_payload"], "release review verification"
        )
        observation_payload = _stored_document(
            stored["observation_payload"], "release review observation"
        )
        try:
            policy = agent_release_readiness.policy_from_payload(policy_payload)
            envelope = agent_release_readiness.envelope_from_payload(
                envelope_payload
            )
            readiness = agent_release_readiness.verify_projection(
                readiness_payload
            )
            verification = _verification(
                verification_payload,
                policy=policy,
                envelope=envelope,
                readiness=readiness,
            )
            observation = _verify_observation_payload(observation_payload)
            authenticated_at = _parse_timestamp(
                observation["authenticated_at"],
                "release authentication time",
            )
            recorded_at = _parse_timestamp(
                observation["recorded_at"],
                "release review record time",
            )
        except (
            agent_release_readiness.ReleaseReadinessError,
            ReleaseReviewStoreError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ReleaseReviewStoreError(
                "stored release review observation is invalid"
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
                "release_readiness_payload_sha256",
                "authenticated_evidence_replay_protection",
                "production_readiness_integration_implemented",
                "reviewed_release_gate_passed",
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
            or observation["release_readiness_payload_sha256"]
            != canonical_sha256(readiness)
            or observation["verification_sha256"]
            != verification["verification_sha256"]
            or row_payload != expected_row_payload
            or stored["verification_sha256"]
            != verification["verification_sha256"]
            or stored["observation_sha256"] != canonical_sha256(observation)
        ):
            raise ReleaseReviewStoreError(
                "stored release review observation is invalid"
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
        raise ReleaseReviewStoreError(
            "trusted release review observation count is invalid"
        )
    trusted_latest_observation_sha256 = _hash(
        trusted_latest_observation_sha256,
        "trusted latest release review observation identity",
        nullable=trusted_observation_count == 0,
    )
    if (
        trusted_observation_count == 0
        and trusted_latest_observation_sha256 is not None
        or trusted_observation_count > 0
        and trusted_latest_observation_sha256 is None
    ):
        raise ReleaseReviewStoreError(
            "trusted release review observation count and head are inconsistent"
        )
    try:
        first = _capture_rows(con)
        events = _verified_events(con, first[1])
        second = _capture_rows(con)
    except duckdb.Error as exc:
        raise ReleaseReviewStoreError(
            "release review observation ledger is unreadable"
        ) from exc
    if first != second:
        raise ReleaseReviewStoreError(
            "release review observation ledger changed during verification"
        )
    actual_head = None if not events else events[-1]["observation_sha256"]
    if (
        len(events) != trusted_observation_count
        or actual_head != trusted_latest_observation_sha256
    ):
        raise ReleaseReviewStoreError(
            "release review observation ledger does not match the trusted head"
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_history_verified_non_authorizing",
        "trusted_observation_count": trusted_observation_count,
        "trusted_latest_observation_sha256": (
            trusted_latest_observation_sha256
        ),
        "approve_observation_count": sum(
            event["decision"] == "approve_release" for event in events
        ),
        "reject_observation_count": sum(
            event["decision"] == "reject_release" for event in events
        ),
        "latest_recorded_at": None if not events else events[-1]["recorded_at"],
        "independent_head_required": True,
        "review_selection_implemented": False,
        "trust_source_loader_implemented": False,
        "production_readiness_integration_implemented": False,
        "reviewed_release_gate_passed": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {**body, "history_evidence_sha256": canonical_sha256(body)}


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded verified replay-protection status without review bytes."""
    events = _verified_events(con)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "initialized" if _schema(con) == "pass" else "not_initialized",
        "observation_count": len(events),
        "approve_observation_count": sum(
            event["decision"] == "approve_release" for event in events
        ),
        "reject_observation_count": sum(
            event["decision"] == "reject_release" for event in events
        ),
        "latest_recorded_at": None if not events else events[-1]["recorded_at"],
        "latest_observation_sha256": (
            None if not events else events[-1]["observation_sha256"]
        ),
        "authenticated_evidence_replay_protection_implemented": True,
        "production_readiness_integration_implemented": False,
        "trust_source_loader_implemented": False,
        "reviewed_release_gate_passed": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def _validated_record_inputs(
    envelope: object,
    policy: object,
    *,
    trusted_release_readiness_sha256: object,
    selected_policy_sha256: object,
) -> tuple[
    agent_release_readiness.ReleaseReviewEnvelope,
    agent_release_readiness.ReleaseReviewPolicy,
    str,
]:
    if not isinstance(
        policy, agent_release_readiness.ReleaseReviewPolicy
    ):
        raise TypeError("policy must be a ReleaseReviewPolicy")
    if not isinstance(
        envelope, agent_release_readiness.ReleaseReviewEnvelope
    ):
        raise TypeError("envelope must be a ReleaseReviewEnvelope")
    if selected_policy_sha256 != policy.sha256():
        raise ReleaseReviewStoreError(
            "reviewer policy does not match the selected policy identity"
        )
    trusted = _hash(
        trusted_release_readiness_sha256,
        "trusted release readiness identity",
    )
    return envelope, policy, trusted


def _exact_replay(
    events: list[dict],
    candidate: dict,
    *,
    envelope: agent_release_readiness.ReleaseReviewEnvelope,
    policy: agent_release_readiness.ReleaseReviewPolicy,
    readiness: dict,
) -> dict | None:
    matching = [
        event
        for event in events
        if any(
            event[field] == candidate[field]
            for field in _UNIQUE_FIELDS
        )
    ]
    if not matching:
        return None
    event = matching[0] if len(matching) == 1 else None
    exact = (
        event is not None
        and all(
            event[field] == candidate[field]
            for field in _UNIQUE_FIELDS
        )
        and event["decision"] == envelope.decision
        and event["selected_policy_sha256"] == policy.sha256()
        and event["policy_payload_sha256"]
        == canonical_sha256(policy.payload())
        and event["envelope_payload_sha256"]
        == canonical_sha256(envelope.payload())
        and event["release_readiness_payload_sha256"]
        == canonical_sha256(readiness)
    )
    if not exact:
        raise ReleaseReviewStoreError(
            "release review identity conflicts with retained evidence"
        )
    return event


def record_authenticated_review(
    con: duckdb.DuckDBPyConnection,
    envelope: agent_release_readiness.ReleaseReviewEnvelope,
    policy: agent_release_readiness.ReleaseReviewPolicy,
    *,
    trusted_release_readiness_sha256: str,
    selected_policy_sha256: str,
    authenticator_verifier: agent_release_readiness.AuthenticatorVerifier,
    observed_at: datetime,
    recorded_at: datetime,
    repo_root: Path = REPO_ROOT,
    database: Path | None = None,
    manifest_builder: agent_release_readiness.ManifestBuilder = (
        agent_release_readiness.release_manifest.build_manifest
    ),
) -> dict:
    """Re-inspect, authenticate, and append one non-authorizing observation."""
    recorded = _timestamp(recorded_at, "release review record time")
    try:
        with engine_db.transaction(con):
            envelope, policy, trusted_release_readiness_sha256 = (
                _validated_record_inputs(
                    envelope,
                    policy,
                    trusted_release_readiness_sha256=(
                        trusted_release_readiness_sha256
                    ),
                    selected_policy_sha256=selected_policy_sha256,
                )
            )
            readiness = agent_release_readiness.inspect(
                repo_root=repo_root,
                database=database,
                manifest_builder=manifest_builder,
                database_connection=con,
            )
            if (
                readiness["status"] != "eligible_awaiting_explicit_review"
                or readiness["release_readiness_sha256"]
                != trusted_release_readiness_sha256
            ):
                raise ReleaseReviewStoreError(
                    "current release does not match trusted review evidence"
                )
            if _schema(con) != "pass":
                raise ReleaseReviewStoreError(
                    "release review observation ledger is not initialized"
                )
            events = _verified_events(con)
            policy_payload = policy.payload()
            envelope_payload = envelope.payload()
            candidate = {
                "review_id": envelope.review_id,
                "envelope_sha256": envelope.sha256(),
                "manifest_sha256": readiness["manifest_sha256"],
                "release_readiness_sha256": readiness[
                    "release_readiness_sha256"
                ],
            }
            replay = _exact_replay(
                events,
                candidate,
                envelope=envelope,
                policy=policy,
                readiness=readiness,
            )
            if replay is not None:
                return replay
            verification = agent_release_readiness.verify_review(
                readiness,
                envelope,
                policy,
                trusted_release_readiness_sha256=(
                    trusted_release_readiness_sha256
                ),
                selected_policy_sha256=selected_policy_sha256,
                authenticator_verifier=authenticator_verifier,
                observed_at=observed_at,
            )
            verified = _verification(
                verification,
                policy=policy,
                envelope=envelope,
                readiness=readiness,
            )
            authenticated_at = _parse_timestamp(
                verified["observed_at"],
                "release authentication time",
            )
            recorded_value = _parse_timestamp(
                recorded,
                "release review record time",
            )
            if recorded_value < authenticated_at:
                raise ReleaseReviewStoreError(
                    "release review record precedes authentication"
                )
            if events and recorded_value < _parse_timestamp(
                events[-1]["recorded_at"],
                "latest release review record time",
            ):
                raise ReleaseReviewStoreError(
                    "release review record time precedes the latest observation"
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
                readiness=readiness,
            )
            observation_sha256 = canonical_sha256(observation)
            documents = {
                "policy_payload": _canonical(policy_payload),
                "envelope_payload": _canonical(envelope_payload),
                "release_readiness_payload": _canonical(readiness),
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
                raise ReleaseReviewStoreError(
                    "release review observation failed post-write verification"
                )
    except agent_release_readiness.ReleaseReadinessError as exc:
        raise ReleaseReviewStoreError(str(exc)) from exc
    return {**observation, "observation_sha256": observation_sha256}
