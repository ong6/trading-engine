"""Sanitized, non-authorizing release readiness for agent paper gates.

Mechanical release eligibility and explicit human review are separate facts.
This module verifies and summarizes the current release manifest, but it does
not create, select, authenticate, or persist human review evidence.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from tools import release_manifest

from .json_utils import loads_object

SCHEMA_VERSION = 1
REVIEW_POLICY_SCHEMA_VERSION = 1
REVIEW_ENVELOPE_SCHEMA_VERSION = 1
REVIEW_VERIFICATION_SCHEMA_VERSION = 1
MAX_REASON_COUNT = 64
MAX_REASON_CHARS = 128
MAX_AUTHENTICATOR_BYTES = 16_384
MAX_POLICY_JSON_BYTES = 65_536
MAX_ENVELOPE_JSON_BYTES = 65_536
MAX_REVIEW_SECONDS = 3_600
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "release_eligible",
        "identity_complete",
        "reasons",
        "git",
        "agent_sources",
        "audit_sources",
        "broker_boundary_sources",
        "research_runtime",
        "dependencies",
        "experiment_registrations",
        "prospective_evidence",
        "recovery_sources",
        "independent_risk_sources",
        "strategy_registrations",
        "execution_profiles",
        "schema_sources",
        "database_schema",
        "service_units",
        "schedule_sources",
        "manifest_sha256",
    }
)
_GIT_FIELDS = frozenset(
    {
        "sha",
        "tree",
        "branch",
        "dirty",
        "changed_path_count",
        "required_files_tracked",
        "untracked_required_files",
        "network_checked",
        "working_tree",
    }
)


class ReleaseReadinessError(ValueError):
    """The local release identity cannot be safely projected."""


ManifestBuilder = Callable[..., dict]
AuthenticatorVerifier = Callable[[str, str, bytes, bytes], bool]
_READINESS_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "manifest_schema_version",
        "manifest_sha256",
        "identity_complete",
        "release_eligible",
        "manifest_reasons",
        "git_commit",
        "git_tree",
        "git_branch",
        "working_tree_dirty",
        "changed_path_count",
        "required_files_tracked",
        "explicit_human_review_required",
        "review_evidence_status",
        "release_review_verifier_implemented",
        "reviewed_release",
        "paper_order_route",
        "execution_authority",
        "release_readiness_sha256",
    }
)


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ReleaseReadinessError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReleaseReadinessError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise ReleaseReadinessError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _authenticator(value: object) -> bytes:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReleaseReadinessError("release review authenticator is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise ReleaseReadinessError(
            "release review authenticator is invalid"
        ) from exc
    if (
        not decoded
        or len(decoded) > MAX_AUTHENTICATOR_BYTES
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise ReleaseReadinessError("release review authenticator is invalid")
    return decoded


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseReadinessError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseReadinessError(f"{label} is invalid") from exc
    parsed = _utc(parsed, label)
    if _timestamp(parsed) != value:
        raise ReleaseReadinessError(f"{label} is invalid")
    return parsed


def _json_object(
    value: str | bytes | bytearray,
    *,
    label: str,
    maximum_bytes: int,
) -> dict:
    if not isinstance(value, (str, bytes, bytearray)):
        raise ReleaseReadinessError(f"{label} must be strict JSON")
    try:
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    except UnicodeEncodeError as exc:
        raise ReleaseReadinessError(f"{label} must be strict UTF-8 JSON") from exc
    if not encoded or len(encoded) > maximum_bytes:
        raise ReleaseReadinessError(
            f"{label} is empty or exceeds {maximum_bytes} bytes"
        )
    try:
        return loads_object(encoded)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReleaseReadinessError(
            f"{label} must be one strict JSON object"
        ) from exc


@dataclass(frozen=True, slots=True)
class ReleaseReviewPolicy:
    """One explicitly supplied reviewer policy; no default trust source exists."""

    review_source_id: str
    reviewer_policy_id: str
    reviewer_policy_version: str
    authenticator_algorithm: str
    authorized_reviewer_identities: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    max_review_seconds: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.review_source_id, "release review source"),
            (self.reviewer_policy_id, "release reviewer policy"),
            (self.reviewer_policy_version, "release reviewer policy version"),
            (self.authenticator_algorithm, "release authenticator algorithm"),
        ):
            _identifier(value, label)
        reviewers = self.authorized_reviewer_identities
        if (
            not isinstance(reviewers, tuple)
            or not reviewers
            or reviewers != tuple(sorted(set(reviewers)))
        ):
            raise ReleaseReadinessError(
                "authorized release reviewers must be a sorted unique tuple"
            )
        for reviewer in reviewers:
            _identifier(reviewer, "authorized release reviewer")
        valid_from = _utc(self.valid_from, "release review policy start")
        valid_until = _utc(self.valid_until, "release review policy expiry")
        if valid_from >= valid_until:
            raise ReleaseReadinessError(
                "release review policy time window is invalid"
            )
        if (
            isinstance(self.max_review_seconds, bool)
            or not isinstance(self.max_review_seconds, int)
            or not 1 <= self.max_review_seconds <= MAX_REVIEW_SECONDS
        ):
            raise ReleaseReadinessError(
                "release review duration is invalid"
            )
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)

    def payload(self) -> dict:
        body = asdict(self)
        body["schema_version"] = REVIEW_POLICY_SCHEMA_VERSION
        body["authorized_reviewer_identities"] = list(
            self.authorized_reviewer_identities
        )
        body["valid_from"] = _timestamp(self.valid_from)
        body["valid_until"] = _timestamp(self.valid_until)
        return body

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


_POLICY_FIELDS = frozenset(ReleaseReviewPolicy.__dataclass_fields__)
_POLICY_PAYLOAD_FIELDS = _POLICY_FIELDS | {"schema_version"}


def policy_from_payload(value: object) -> ReleaseReviewPolicy:
    """Parse one closed policy object without selecting or trusting it."""
    if (
        not isinstance(value, dict)
        or set(value) != _POLICY_PAYLOAD_FIELDS
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != REVIEW_POLICY_SCHEMA_VERSION
        or not isinstance(value["authorized_reviewer_identities"], list)
    ):
        raise ReleaseReadinessError("release review policy shape is invalid")
    values = {field: value[field] for field in _POLICY_FIELDS}
    values["authorized_reviewer_identities"] = tuple(
        values["authorized_reviewer_identities"]
    )
    values["valid_from"] = _parse_timestamp(
        values["valid_from"],
        "release review policy start",
    )
    values["valid_until"] = _parse_timestamp(
        values["valid_until"],
        "release review policy expiry",
    )
    try:
        policy = ReleaseReviewPolicy(**values)
    except (ReleaseReadinessError, TypeError, ValueError) as exc:
        raise ReleaseReadinessError("release review policy is invalid") from exc
    if policy.payload() != value:
        raise ReleaseReadinessError("release review policy is not canonical")
    return policy


def policy_from_json(value: str | bytes | bytearray) -> ReleaseReviewPolicy:
    """Parse one bounded duplicate-key-safe release-review policy."""
    return policy_from_payload(
        _json_object(
            value,
            label="release review policy",
            maximum_bytes=MAX_POLICY_JSON_BYTES,
        )
    )


@dataclass(frozen=True, slots=True)
class ReleaseReviewEnvelope:
    """One detached decision over one exact mechanically eligible release."""

    review_id: str
    review_source_id: str
    reviewer_policy_id: str
    reviewer_policy_version: str
    reviewer_identity: str
    authenticator_algorithm: str
    decision: Literal["approve_release", "reject_release"]
    manifest_sha256: str
    release_readiness_sha256: str
    git_commit: str
    git_tree: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    authenticator_base64: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.review_id, "release review identifier"),
            (self.review_source_id, "release review source"),
            (self.reviewer_policy_id, "release reviewer policy"),
            (self.reviewer_policy_version, "release reviewer policy version"),
            (self.reviewer_identity, "release reviewer identity"),
            (self.authenticator_algorithm, "release authenticator algorithm"),
        ):
            _identifier(value, label)
        if self.decision not in {"approve_release", "reject_release"}:
            raise ReleaseReadinessError("release review decision is invalid")
        for value, label in (
            (self.manifest_sha256, "release manifest identity"),
            (self.release_readiness_sha256, "release readiness identity"),
        ):
            _sha256(value, label)
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.git_commit):
            raise ReleaseReadinessError("release Git commit is invalid")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.git_tree):
            raise ReleaseReadinessError("release Git tree is invalid")
        issued_at = _utc(self.issued_at, "release review issue time")
        not_before = _utc(self.not_before, "release review start")
        expires_at = _utc(self.expires_at, "release review expiry")
        if not issued_at <= not_before < expires_at:
            raise ReleaseReadinessError("release review time window is invalid")
        _authenticator(self.authenticator_base64)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "not_before", not_before)
        object.__setattr__(self, "expires_at", expires_at)

    def signing_payload(self) -> dict:
        body = asdict(self)
        body.pop("authenticator_base64")
        body["schema_version"] = REVIEW_ENVELOPE_SCHEMA_VERSION
        for field in ("issued_at", "not_before", "expires_at"):
            body[field] = _timestamp(getattr(self, field))
        return body

    def signing_bytes(self) -> bytes:
        return _canonical_bytes(self.signing_payload())

    def payload(self) -> dict:
        return {
            **self.signing_payload(),
            "authenticator_base64": self.authenticator_base64,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


_ENVELOPE_FIELDS = frozenset(ReleaseReviewEnvelope.__dataclass_fields__)
_ENVELOPE_PAYLOAD_FIELDS = _ENVELOPE_FIELDS | {"schema_version"}


def envelope_from_payload(value: object) -> ReleaseReviewEnvelope:
    """Parse one closed envelope object without accepting its decision."""
    if (
        not isinstance(value, dict)
        or set(value) != _ENVELOPE_PAYLOAD_FIELDS
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != REVIEW_ENVELOPE_SCHEMA_VERSION
    ):
        raise ReleaseReadinessError("release review envelope shape is invalid")
    values = {field: value[field] for field in _ENVELOPE_FIELDS}
    for field, label in (
        ("issued_at", "release review issue time"),
        ("not_before", "release review start"),
        ("expires_at", "release review expiry"),
    ):
        values[field] = _parse_timestamp(values[field], label)
    try:
        envelope = ReleaseReviewEnvelope(**values)
    except (ReleaseReadinessError, TypeError, ValueError) as exc:
        raise ReleaseReadinessError("release review envelope is invalid") from exc
    if envelope.payload() != value:
        raise ReleaseReadinessError("release review envelope is not canonical")
    return envelope


def envelope_from_json(value: str | bytes | bytearray) -> ReleaseReviewEnvelope:
    """Parse one bounded duplicate-key-safe release-review envelope."""
    return envelope_from_payload(
        _json_object(
            value,
            label="release review envelope",
            maximum_bytes=MAX_ENVELOPE_JSON_BYTES,
        )
    )


def _reason_list(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_REASON_COUNT
        or any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > MAX_REASON_CHARS
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise ReleaseReadinessError("release manifest reasons are invalid")
    return list(value)


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
    ):
        raise ReleaseReadinessError(f"{label} is invalid")
    return value


def summarize(manifest: object) -> dict:
    """Verify and sanitize one current manifest without claiming review."""
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
        raise ReleaseReadinessError("release manifest shape is invalid")
    body = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != release_manifest.SCHEMA_VERSION
        or not isinstance(manifest["manifest_sha256"], str)
        or len(manifest["manifest_sha256"]) != 64
        or canonical_sha256(body) != manifest["manifest_sha256"]
    ):
        raise ReleaseReadinessError("release manifest identity is invalid")
    eligible = manifest["release_eligible"]
    complete = manifest["identity_complete"]
    status = manifest["status"]
    reasons = _reason_list(manifest["reasons"])
    git = manifest["git"]
    if (
        type(eligible) is not bool
        or type(complete) is not bool
        or status not in {"release-candidate", "non-releasable"}
        or eligible != (status == "release-candidate")
        or not isinstance(git, dict)
        or set(git) != _GIT_FIELDS
        or type(git["dirty"]) is not bool
        or isinstance(git["changed_path_count"], bool)
        or not isinstance(git["changed_path_count"], int)
        or git["changed_path_count"] < 0
        or type(git["required_files_tracked"]) is not bool
        or type(git["network_checked"]) is not bool
    ):
        raise ReleaseReadinessError("release manifest semantics are invalid")
    commit = _optional_text(git["sha"], "release Git commit")
    tree = _optional_text(git["tree"], "release Git tree")
    branch = _optional_text(git["branch"], "release Git branch")
    if eligible and (
        not complete
        or reasons
        or git["dirty"]
        or not git["required_files_tracked"]
        or commit is None
        or tree is None
    ):
        raise ReleaseReadinessError("eligible release manifest is inconsistent")
    projection_status = (
        "eligible_awaiting_explicit_review"
        if eligible
        else "not_release_candidate"
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": projection_status,
        "manifest_schema_version": manifest["schema_version"],
        "manifest_sha256": manifest["manifest_sha256"],
        "identity_complete": complete,
        "release_eligible": eligible,
        "manifest_reasons": reasons,
        "git_commit": commit,
        "git_tree": tree,
        "git_branch": branch,
        "working_tree_dirty": git["dirty"],
        "changed_path_count": git["changed_path_count"],
        "required_files_tracked": git["required_files_tracked"],
        "explicit_human_review_required": True,
        "review_evidence_status": "not_selected",
        "release_review_verifier_implemented": True,
        "reviewed_release": False,
        "paper_order_route": "absent",
        "execution_authority": "none",
    }
    return {
        **result,
        "release_readiness_sha256": canonical_sha256(result),
    }


def unavailable(reason: str) -> dict:
    """Return a closed projection when current manifest inspection is unavailable."""
    if (
        not isinstance(reason, str)
        or not reason
        or reason != reason.strip()
        or len(reason) > MAX_REASON_CHARS
    ):
        raise ReleaseReadinessError("release readiness reason is invalid")
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "manifest_schema_version": release_manifest.SCHEMA_VERSION,
        "manifest_sha256": None,
        "identity_complete": False,
        "release_eligible": False,
        "manifest_reasons": [reason],
        "git_commit": None,
        "git_tree": None,
        "git_branch": None,
        "working_tree_dirty": None,
        "changed_path_count": None,
        "required_files_tracked": None,
        "explicit_human_review_required": True,
        "review_evidence_status": "not_selected",
        "release_review_verifier_implemented": True,
        "reviewed_release": False,
        "paper_order_route": "absent",
        "execution_authority": "none",
    }
    return {
        **result,
        "release_readiness_sha256": canonical_sha256(result),
    }


def inspect(
    *,
    repo_root: Path = REPO_ROOT,
    database: Path | None = None,
    manifest_builder: ManifestBuilder = release_manifest.build_manifest,
    database_connection: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Inspect the local candidate and fail closed to a sanitized projection."""
    try:
        if database_connection is None:
            manifest = manifest_builder(repo_root, database)
        else:
            manifest = manifest_builder(
                repo_root,
                database,
                _database_connection=database_connection,
            )
        return summarize(manifest)
    except (OSError, RuntimeError, ReleaseReadinessError, TypeError, ValueError):
        return unavailable("release-manifest-inspection-failed")


def verify_projection(value: object) -> dict:
    """Verify one closed non-authorizing release-readiness projection."""
    if not isinstance(value, dict) or set(value) != _READINESS_FIELDS:
        raise ReleaseReadinessError("release readiness evidence is invalid")
    body = {
        key: item
        for key, item in value.items()
        if key != "release_readiness_sha256"
    }
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["status"]
        not in {
            "eligible_awaiting_explicit_review",
            "not_release_candidate",
            "unavailable",
        }
        or type(value["identity_complete"]) is not bool
        or type(value["release_eligible"]) is not bool
        or value["explicit_human_review_required"] is not True
        or value["review_evidence_status"] != "not_selected"
        or value["release_review_verifier_implemented"] is not True
        or value["reviewed_release"] is not False
        or value["paper_order_route"] != "absent"
        or value["execution_authority"] != "none"
        or not isinstance(value["release_readiness_sha256"], str)
        or _SHA256.fullmatch(value["release_readiness_sha256"]) is None
        or canonical_sha256(body) != value["release_readiness_sha256"]
    ):
        raise ReleaseReadinessError("release readiness evidence is invalid")
    _reason_list(value["manifest_reasons"])
    if value["status"] == "eligible_awaiting_explicit_review":
        if (
            value["identity_complete"] is not True
            or value["release_eligible"] is not True
            or value["manifest_reasons"] != []
            or value["working_tree_dirty"] is not False
            or value["required_files_tracked"] is not True
            or value["manifest_sha256"] is None
            or value["git_commit"] is None
            or value["git_tree"] is None
        ):
            raise ReleaseReadinessError("eligible release readiness is inconsistent")
    elif value["release_eligible"] is not False:
        raise ReleaseReadinessError("blocked release readiness is inconsistent")
    return value


def _verify_review_binding(
    readiness: dict,
    envelope: ReleaseReviewEnvelope,
    policy: ReleaseReviewPolicy,
) -> None:
    actual = (
        envelope.review_source_id,
        envelope.reviewer_policy_id,
        envelope.reviewer_policy_version,
        envelope.authenticator_algorithm,
        envelope.manifest_sha256,
        envelope.release_readiness_sha256,
        envelope.git_commit,
        envelope.git_tree,
    )
    expected = (
        policy.review_source_id,
        policy.reviewer_policy_id,
        policy.reviewer_policy_version,
        policy.authenticator_algorithm,
        readiness["manifest_sha256"],
        readiness["release_readiness_sha256"],
        readiness["git_commit"],
        readiness["git_tree"],
    )
    if (
        actual != expected
        or envelope.reviewer_identity
        not in policy.authorized_reviewer_identities
    ):
        raise ReleaseReadinessError(
            "release review does not match the selected release and policy"
        )


def _verify_review_window(
    envelope: ReleaseReviewEnvelope,
    policy: ReleaseReviewPolicy,
    observed_at: datetime,
) -> None:
    if (
        envelope.issued_at < policy.valid_from
        or envelope.expires_at > policy.valid_until
        or (envelope.expires_at - envelope.not_before).total_seconds()
        > policy.max_review_seconds
        or not envelope.not_before <= observed_at < envelope.expires_at
    ):
        raise ReleaseReadinessError(
            "release review is outside its trusted time window"
        )


def verify_review(
    readiness: object,
    envelope: ReleaseReviewEnvelope,
    policy: ReleaseReviewPolicy,
    *,
    trusted_release_readiness_sha256: str,
    selected_policy_sha256: str,
    authenticator_verifier: AuthenticatorVerifier,
    observed_at: datetime,
) -> dict:
    """Authenticate explicit review of one eligible release without granting authority."""
    if not isinstance(readiness, dict):
        raise ReleaseReadinessError("release readiness evidence is invalid")
    readiness = verify_projection(readiness)
    trusted_release_readiness_sha256 = _sha256(
        trusted_release_readiness_sha256,
        "trusted release readiness identity",
    )
    if (
        readiness["status"] != "eligible_awaiting_explicit_review"
        or readiness["release_readiness_sha256"]
        != trusted_release_readiness_sha256
    ):
        raise ReleaseReadinessError(
            "release is not eligible for explicit review"
        )
    if not isinstance(envelope, ReleaseReviewEnvelope):
        raise TypeError("envelope must be a ReleaseReviewEnvelope")
    if not isinstance(policy, ReleaseReviewPolicy):
        raise TypeError("policy must be a ReleaseReviewPolicy")
    selected_policy_sha256 = _sha256(
        selected_policy_sha256,
        "selected release reviewer policy identity",
    )
    if selected_policy_sha256 != policy.sha256():
        raise ReleaseReadinessError(
            "release reviewer policy is not explicitly selected"
        )
    observed_at = _utc(observed_at, "release review verification time")
    _verify_review_binding(readiness, envelope, policy)
    _verify_review_window(envelope, policy, observed_at)
    if not callable(authenticator_verifier):
        raise ReleaseReadinessError(
            "an external release-review authenticator must be supplied"
        )
    authenticator = _authenticator(envelope.authenticator_base64)
    try:
        authenticated = authenticator_verifier(
            envelope.authenticator_algorithm,
            envelope.reviewer_identity,
            envelope.signing_bytes(),
            authenticator,
        )
    except Exception as exc:
        raise ReleaseReadinessError(
            "external release-review authentication failed"
        ) from exc
    if authenticated is not True:
        raise ReleaseReadinessError(
            "external release-review authentication failed"
        )
    reviewed = envelope.decision == "approve_release"
    body = {
        "schema_version": REVIEW_VERIFICATION_SCHEMA_VERSION,
        "status": (
            "reviewed_release_design_evidence"
            if reviewed
            else "release_rejected_design_evidence"
        ),
        "decision": envelope.decision,
        "review_id": envelope.review_id,
        "manifest_sha256": envelope.manifest_sha256,
        "release_readiness_sha256": envelope.release_readiness_sha256,
        "git_commit": envelope.git_commit,
        "git_tree": envelope.git_tree,
        "review_source_id": envelope.review_source_id,
        "reviewer_policy_id": envelope.reviewer_policy_id,
        "reviewer_policy_version": envelope.reviewer_policy_version,
        "reviewer_identity": envelope.reviewer_identity,
        "authenticator_algorithm": envelope.authenticator_algorithm,
        "selected_policy_sha256": selected_policy_sha256,
        "envelope_sha256": envelope.sha256(),
        "signing_payload_sha256": canonical_sha256(
            envelope.signing_payload()
        ),
        "observed_at": _timestamp(observed_at),
        "manifest_eligibility_verified": True,
        "authenticator_verified": True,
        "reviewed_release": reviewed,
        "persistence_implemented": False,
        "readiness_integration_implemented": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {
        **body,
        "verification_sha256": canonical_sha256(body),
    }
