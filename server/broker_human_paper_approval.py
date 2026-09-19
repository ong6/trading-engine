"""Pure authentication contract for one exact human paper decision.

This module defines a source-neutral approval envelope and an explicitly
selected signer policy. It can authenticate detached bytes supplied by an
external verifier, but it cannot select or load trust, enforce one-use state,
approve an order, persist anything, or submit an order. A separate read-only
composition can revalidate retained database evidence before authentication.
A successful result is design evidence only.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

import duckdb

from engine.lib.provenance import canonical_sha256

from . import broker_human_paper_review
from .broker_contract import require_identifier
from .json_utils import loads_object

POLICY_SCHEMA_VERSION = 1
ENVELOPE_SCHEMA_VERSION = 1
VERIFICATION_SCHEMA_VERSION = 1
MAX_AUTHENTICATOR_BYTES = 16_384
MAX_POLICY_JSON_BYTES = 65_536
MAX_ENVELOPE_JSON_BYTES = 65_536
MAX_APPROVAL_SECONDS = broker_human_paper_review.REVIEW_TTL_SECONDS
DECISIONS = ("approve_exact_intent", "reject")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HumanPaperApprovalError(ValueError):
    """An approval policy, envelope, or authentication result is invalid."""


AuthenticatorVerifier = Callable[[str, str, bytes, bytes], bool]


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise HumanPaperApprovalError(str(exc)) from exc


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HumanPaperApprovalError(f"{label} must be a lowercase SHA-256")
    return value


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise HumanPaperApprovalError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanPaperApprovalError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanPaperApprovalError(f"{label} is invalid") from exc
    parsed = _utc(parsed, label)
    if _timestamp(parsed) != value:
        raise HumanPaperApprovalError(f"{label} is invalid")
    return parsed


def _identifiers(
    value: object,
    label: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or not value
        or value != tuple(sorted(set(value)))
        or len(value) > 128
    ):
        raise HumanPaperApprovalError(f"{label} must be a sorted unique tuple")
    for item in value:
        _identifier(item, label)
        if allowed is not None and item not in allowed:
            raise HumanPaperApprovalError(f"{label} contains an unsupported value")
    return value


def _authenticator(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > ((MAX_AUTHENTICATOR_BYTES + 2) // 3) * 4
    ):
        raise HumanPaperApprovalError("paper approval authenticator is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise HumanPaperApprovalError(
            "paper approval authenticator is invalid"
        ) from exc
    if (
        not decoded
        or len(decoded) > MAX_AUTHENTICATOR_BYTES
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise HumanPaperApprovalError("paper approval authenticator is invalid")
    return decoded


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _json_object(
    value: str | bytes | bytearray,
    *,
    label: str,
    maximum_bytes: int,
) -> dict:
    if not isinstance(value, (str, bytes, bytearray)):
        raise HumanPaperApprovalError(f"{label} must be strict JSON")
    try:
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    except UnicodeEncodeError as exc:
        raise HumanPaperApprovalError(f"{label} must be strict UTF-8 JSON") from exc
    if not encoded or len(encoded) > maximum_bytes:
        raise HumanPaperApprovalError(
            f"{label} is empty or exceeds {maximum_bytes} bytes"
        )
    try:
        return loads_object(encoded)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise HumanPaperApprovalError(f"{label} must be one strict JSON object") from exc


@dataclass(frozen=True, slots=True)
class HumanApprovalPolicy:
    """One externally selected signer policy; no default policy exists."""

    approval_source_id: str
    signer_policy_id: str
    signer_policy_version: str
    authenticator_algorithm: str
    authorized_signer_identities: tuple[str, ...]
    authorized_modes: tuple[Literal["agent_only", "hybrid"], ...]
    authorized_policy_ids: tuple[str, ...]
    authorized_account_ids: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    max_approval_seconds: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.approval_source_id, "approval source identifier"),
            (self.signer_policy_id, "signer policy identifier"),
            (self.signer_policy_version, "signer policy version"),
            (self.authenticator_algorithm, "authenticator algorithm"),
        ):
            _identifier(value, label)
        object.__setattr__(
            self,
            "authorized_signer_identities",
            _identifiers(
                self.authorized_signer_identities,
                "authorized signer identity",
            ),
        )
        object.__setattr__(
            self,
            "authorized_modes",
            _identifiers(
                self.authorized_modes,
                "authorized paper mode",
                allowed=frozenset({"agent_only", "hybrid"}),
            ),
        )
        object.__setattr__(
            self,
            "authorized_policy_ids",
            _identifiers(self.authorized_policy_ids, "authorized policy identifier"),
        )
        object.__setattr__(
            self,
            "authorized_account_ids",
            _identifiers(self.authorized_account_ids, "authorized account identifier"),
        )
        valid_from = _utc(self.valid_from, "signer policy start")
        valid_until = _utc(self.valid_until, "signer policy expiry")
        if valid_from >= valid_until:
            raise HumanPaperApprovalError("signer policy time window is invalid")
        if (
            isinstance(self.max_approval_seconds, bool)
            or not isinstance(self.max_approval_seconds, int)
            or not 1 <= self.max_approval_seconds <= MAX_APPROVAL_SECONDS
        ):
            raise HumanPaperApprovalError(
                f"maximum approval duration must be from 1 through "
                f"{MAX_APPROVAL_SECONDS} seconds"
            )
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)

    def payload(self) -> dict:
        body = asdict(self)
        body["schema_version"] = POLICY_SCHEMA_VERSION
        for field in (
            "authorized_signer_identities",
            "authorized_modes",
            "authorized_policy_ids",
            "authorized_account_ids",
        ):
            body[field] = list(getattr(self, field))
        body["valid_from"] = _timestamp(self.valid_from)
        body["valid_until"] = _timestamp(self.valid_until)
        return body

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


_POLICY_FIELDS = frozenset(HumanApprovalPolicy.__dataclass_fields__)
_POLICY_PAYLOAD_FIELDS = _POLICY_FIELDS | {"schema_version"}


def policy_from_payload(value: object) -> HumanApprovalPolicy:
    """Parse one closed policy object without selecting or trusting it."""
    if (
        not isinstance(value, dict)
        or set(value) != _POLICY_PAYLOAD_FIELDS
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != POLICY_SCHEMA_VERSION
    ):
        raise HumanPaperApprovalError("human approval policy shape is invalid")
    sequence_fields = (
        "authorized_signer_identities",
        "authorized_modes",
        "authorized_policy_ids",
        "authorized_account_ids",
    )
    if any(not isinstance(value[field], list) for field in sequence_fields):
        raise HumanPaperApprovalError("human approval policy shape is invalid")
    values = {field: value[field] for field in _POLICY_FIELDS}
    for field in sequence_fields:
        values[field] = tuple(values[field])
    values["valid_from"] = _parse_timestamp(
        values["valid_from"],
        "signer policy start",
    )
    values["valid_until"] = _parse_timestamp(
        values["valid_until"],
        "signer policy expiry",
    )
    try:
        policy = HumanApprovalPolicy(**values)
    except (HumanPaperApprovalError, TypeError, ValueError) as exc:
        raise HumanPaperApprovalError("human approval policy is invalid") from exc
    if policy.payload() != value:
        raise HumanPaperApprovalError("human approval policy is not canonical")
    return policy


def policy_from_json(value: str | bytes | bytearray) -> HumanApprovalPolicy:
    """Parse one bounded duplicate-key-safe policy JSON object."""
    return policy_from_payload(
        _json_object(
            value,
            label="human approval policy",
            maximum_bytes=MAX_POLICY_JSON_BYTES,
        )
    )


@dataclass(frozen=True, slots=True)
class HumanApprovalEnvelope:
    """One detached human decision bound to one exact review packet."""

    approval_id: str
    approval_source_id: str
    signer_policy_id: str
    signer_policy_version: str
    signer_identity: str
    authenticator_algorithm: str
    decision: Literal["approve_exact_intent", "reject"]
    review_request_sha256: str
    request_sha256: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    authenticator_base64: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.approval_id, "one-use approval identifier"),
            (self.approval_source_id, "approval source identifier"),
            (self.signer_policy_id, "signer policy identifier"),
            (self.signer_policy_version, "signer policy version"),
            (self.signer_identity, "signer identity"),
            (self.authenticator_algorithm, "authenticator algorithm"),
        ):
            _identifier(value, label)
        if self.decision not in DECISIONS:
            raise HumanPaperApprovalError("human paper decision is invalid")
        _hash(self.review_request_sha256, "review packet identity")
        _hash(self.request_sha256, "paper request identity")
        issued_at = _utc(self.issued_at, "approval issue time")
        not_before = _utc(self.not_before, "approval start")
        expires_at = _utc(self.expires_at, "approval expiry")
        if not issued_at <= not_before < expires_at:
            raise HumanPaperApprovalError("approval time window is invalid")
        _authenticator(self.authenticator_base64)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "not_before", not_before)
        object.__setattr__(self, "expires_at", expires_at)

    def signing_payload(self) -> dict:
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "approval_id": self.approval_id,
            "approval_source_id": self.approval_source_id,
            "signer_policy_id": self.signer_policy_id,
            "signer_policy_version": self.signer_policy_version,
            "signer_identity": self.signer_identity,
            "authenticator_algorithm": self.authenticator_algorithm,
            "decision": self.decision,
            "review_request_sha256": self.review_request_sha256,
            "request_sha256": self.request_sha256,
            "issued_at": _timestamp(self.issued_at),
            "not_before": _timestamp(self.not_before),
            "expires_at": _timestamp(self.expires_at),
        }

    def signing_bytes(self) -> bytes:
        return _canonical_bytes(self.signing_payload())

    def payload(self) -> dict:
        return {
            **self.signing_payload(),
            "authenticator_base64": self.authenticator_base64,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


_ENVELOPE_FIELDS = frozenset(HumanApprovalEnvelope.__dataclass_fields__)
_ENVELOPE_PAYLOAD_FIELDS = _ENVELOPE_FIELDS | {"schema_version"}


def envelope_from_payload(value: object) -> HumanApprovalEnvelope:
    """Parse one closed envelope object without accepting its decision."""
    if (
        not isinstance(value, dict)
        or set(value) != _ENVELOPE_PAYLOAD_FIELDS
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != ENVELOPE_SCHEMA_VERSION
    ):
        raise HumanPaperApprovalError("human approval envelope shape is invalid")
    values = {field: value[field] for field in _ENVELOPE_FIELDS}
    for field, label in (
        ("issued_at", "approval issue time"),
        ("not_before", "approval start"),
        ("expires_at", "approval expiry"),
    ):
        values[field] = _parse_timestamp(values[field], label)
    try:
        envelope = HumanApprovalEnvelope(**values)
    except (HumanPaperApprovalError, TypeError, ValueError) as exc:
        raise HumanPaperApprovalError("human approval envelope is invalid") from exc
    if envelope.payload() != value:
        raise HumanPaperApprovalError("human approval envelope is not canonical")
    return envelope


def envelope_from_json(value: str | bytes | bytearray) -> HumanApprovalEnvelope:
    """Parse one bounded duplicate-key-safe approval-envelope JSON object."""
    return envelope_from_payload(
        _json_object(
            value,
            label="human approval envelope",
            maximum_bytes=MAX_ENVELOPE_JSON_BYTES,
        )
    )


def _verify_policy_scope(
    envelope: HumanApprovalEnvelope, packet: dict, policy: HumanApprovalPolicy
) -> None:
    if (
        envelope.approval_source_id != policy.approval_source_id
        or envelope.signer_policy_id != policy.signer_policy_id
        or envelope.signer_policy_version != policy.signer_policy_version
        or envelope.authenticator_algorithm != policy.authenticator_algorithm
    ):
        raise HumanPaperApprovalError(
            "approval envelope does not match the selected signer policy"
        )
    if (
        envelope.signer_identity not in policy.authorized_signer_identities
        or packet["mode"] not in policy.authorized_modes
        or packet["policy_id"] not in policy.authorized_policy_ids
        or packet["reserved_portfolio_id"] not in policy.authorized_account_ids
    ):
        raise HumanPaperApprovalError(
            "signer policy does not authorize this exact paper scope"
        )


def _verify_approval_window(
    envelope: HumanApprovalEnvelope,
    policy: HumanApprovalPolicy,
    packet_generated_at: datetime,
    packet_expires_at: datetime,
    observed_at: datetime,
) -> None:
    if (
        envelope.issued_at < packet_generated_at
        or envelope.expires_at > packet_expires_at
        or envelope.issued_at < policy.valid_from
        or envelope.expires_at > policy.valid_until
        or (envelope.expires_at - envelope.not_before).total_seconds()
        > policy.max_approval_seconds
        or not envelope.not_before <= observed_at < envelope.expires_at
    ):
        raise HumanPaperApprovalError(
            "approval envelope is outside its trusted time window"
        )


def verify_authenticated_decision(
    envelope: HumanApprovalEnvelope,
    review_packet: object,
    policy: HumanApprovalPolicy,
    *,
    selected_policy_sha256: str,
    authenticator_verifier: AuthenticatorVerifier,
    observed_at: datetime,
) -> dict:
    """Authenticate an exact decision without granting or persisting authority."""
    if not isinstance(envelope, HumanApprovalEnvelope):
        raise TypeError("envelope must be a HumanApprovalEnvelope")
    if not isinstance(policy, HumanApprovalPolicy):
        raise TypeError("policy must be a HumanApprovalPolicy")
    if not callable(authenticator_verifier):
        raise HumanPaperApprovalError(
            "an external authenticator verifier must be explicitly supplied"
        )
    selected_policy_sha256 = _hash(
        selected_policy_sha256,
        "selected signer policy identity",
    )
    if selected_policy_sha256 != policy.sha256():
        raise HumanPaperApprovalError(
            "signer policy does not match the explicitly selected policy identity"
        )
    try:
        packet = broker_human_paper_review.verify(review_packet)
    except broker_human_paper_review.HumanPaperReviewError as exc:
        raise HumanPaperApprovalError(str(exc)) from exc
    observed_at = _utc(observed_at, "approval verification time")
    packet_generated_at = broker_human_paper_review._parse_timestamp(
        packet["generated_at"],
        "human paper review generation time",
    )
    packet_expires_at = broker_human_paper_review._parse_timestamp(
        packet["expires_at"],
        "human paper review expiry",
    )
    _verify_policy_scope(envelope, packet, policy)
    if (
        envelope.review_request_sha256 != packet["review_request_sha256"]
        or envelope.request_sha256 != packet["request_sha256"]
    ):
        raise HumanPaperApprovalError(
            "approval envelope does not bind the exact review packet and request"
        )
    _verify_approval_window(
        envelope, policy, packet_generated_at, packet_expires_at, observed_at
    )
    authenticator = _authenticator(envelope.authenticator_base64)
    try:
        authenticated = authenticator_verifier(
            envelope.authenticator_algorithm,
            envelope.signer_identity,
            envelope.signing_bytes(),
            authenticator,
        )
    except Exception as exc:
        raise HumanPaperApprovalError(
            "external approval authenticator verification failed"
        ) from exc
    if authenticated is not True:
        raise HumanPaperApprovalError(
            "external approval authenticator verification failed"
        )
    body = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": "authenticated_decision_design_evidence",
        "decision": envelope.decision,
        "approval_id": envelope.approval_id,
        "approval_source_id": envelope.approval_source_id,
        "signer_policy_id": envelope.signer_policy_id,
        "signer_policy_version": envelope.signer_policy_version,
        "signer_identity": envelope.signer_identity,
        "authenticator_algorithm": envelope.authenticator_algorithm,
        "review_request_sha256": envelope.review_request_sha256,
        "request_sha256": envelope.request_sha256,
        "envelope_sha256": envelope.sha256(),
        "signing_payload_sha256": canonical_sha256(envelope.signing_payload()),
        "selected_policy_sha256": selected_policy_sha256,
        "observed_at": _timestamp(observed_at),
        "packet_integrity_verified": True,
        "retained_evidence_revalidated": False,
        "authenticator_verified": True,
        "policy_scope_verified": True,
        "trust_source_loader_implemented": False,
        "one_use_enforcement_implemented": False,
        "human_order_approval_granted": False,
        "persistence_implemented": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {**body, "verification_sha256": canonical_sha256(body)}


def verify_retained_authenticated_decision(
    con: duckdb.DuckDBPyConnection,
    envelope: HumanApprovalEnvelope,
    review_packet: object,
    policy: HumanApprovalPolicy,
    *,
    selected_policy_sha256: str,
    authenticator_verifier: AuthenticatorVerifier,
    observed_at: datetime,
) -> dict:
    """Reload retained intent evidence, then authenticate without granting authority."""
    observed_at = _utc(observed_at, "approval verification time")
    try:
        packet = broker_human_paper_review.verify_retained(
            con,
            review_packet,
            reviewed_at=observed_at,
        )
    except broker_human_paper_review.HumanPaperReviewError as exc:
        raise HumanPaperApprovalError(str(exc)) from exc
    verified = verify_authenticated_decision(
        envelope,
        packet,
        policy,
        selected_policy_sha256=selected_policy_sha256,
        authenticator_verifier=authenticator_verifier,
        observed_at=observed_at,
    )
    body = {
        key: value for key, value in verified.items() if key != "verification_sha256"
    }
    body["retained_evidence_revalidated"] = True
    return {**body, "verification_sha256": canonical_sha256(body)}
