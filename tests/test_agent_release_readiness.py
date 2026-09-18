"""Release readiness separates mechanical eligibility from explicit review."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_release_readiness
from tools import release_manifest

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
AUTHENTICATOR = b"external-release-review-authenticator"


def _manifest(*, eligible: bool = True) -> dict:
    groups = {
        name: {"sha256": "a" * 64, "file_count": 1, "files": {}}
        for name in (
            "agent_sources",
            "audit_sources",
            "broker_boundary_sources",
            "dependencies",
            "experiment_registrations",
            "prospective_evidence",
            "recovery_sources",
            "independent_risk_sources",
            "strategy_registrations",
            "execution_profiles",
            "schema_sources",
            "service_units",
            "schedule_sources",
        )
    }
    body = {
        "schema_version": release_manifest.SCHEMA_VERSION,
        "status": "release-candidate" if eligible else "non-releasable",
        "release_eligible": eligible,
        "identity_complete": True,
        "reasons": [] if eligible else ["dirty-working-tree"],
        "git": {
            "sha": "1" * 40,
            "tree": "2" * 40,
            "branch": "main",
            "dirty": not eligible,
            "changed_path_count": 0 if eligible else 1,
            "required_files_tracked": True,
            "untracked_required_files": [],
            "network_checked": False,
            "working_tree": {
                "sha256": "3" * 64,
                "file_count": 1,
                "missing_paths": [],
            },
        },
        "research_runtime": {"sha256": "4" * 64, "file_count": 1},
        "database_schema": {
            "status": "ok",
            "reason": None,
            "location": {
                "kind": "repository-relative",
                "path": "store/market.duckdb",
            },
            "sha256": "5" * 64,
            "table_count": 1,
            "view_count": 0,
            "index_count": 0,
        },
        **groups,
    }
    return {**body, "manifest_sha256": canonical_sha256(body)}


def _policy() -> agent_release_readiness.ReleaseReviewPolicy:
    return agent_release_readiness.ReleaseReviewPolicy(
        review_source_id="offline-release-review",
        reviewer_policy_id="release-reviewers",
        reviewer_policy_version="v1",
        authenticator_algorithm="external-test-algorithm",
        authorized_reviewer_identities=("operator-one",),
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        max_review_seconds=300,
    )


def _envelope(
    readiness: dict,
    **changes,
) -> agent_release_readiness.ReleaseReviewEnvelope:
    values = {
        "review_id": "release-review-1",
        "review_source_id": "offline-release-review",
        "reviewer_policy_id": "release-reviewers",
        "reviewer_policy_version": "v1",
        "reviewer_identity": "operator-one",
        "authenticator_algorithm": "external-test-algorithm",
        "decision": "approve_release",
        "manifest_sha256": readiness["manifest_sha256"],
        "release_readiness_sha256": readiness["release_readiness_sha256"],
        "git_commit": readiness["git_commit"],
        "git_tree": readiness["git_tree"],
        "issued_at": NOW + timedelta(seconds=1),
        "not_before": NOW + timedelta(seconds=1),
        "expires_at": NOW + timedelta(seconds=120),
        "authenticator_base64": base64.b64encode(AUTHENTICATOR).decode("ascii"),
    }
    values.update(changes)
    return agent_release_readiness.ReleaseReviewEnvelope(**values)


def _accept_expected(envelope):
    return lambda algorithm, reviewer, payload, authenticator: (
        algorithm == envelope.authenticator_algorithm
        and reviewer == envelope.reviewer_identity
        and payload == envelope.signing_bytes()
        and authenticator == AUTHENTICATOR
    )


def test_closed_policy_and_envelope_parsers_round_trip_without_trusting_them():
    policy = _policy()
    readiness = agent_release_readiness.summarize(_manifest())
    envelope = _envelope(readiness)

    assert (
        agent_release_readiness.policy_from_payload(
            deepcopy(policy.payload())
        )
        == policy
    )
    assert (
        agent_release_readiness.envelope_from_payload(
            deepcopy(envelope.payload())
        )
        == envelope
    )
    assert (
        agent_release_readiness.policy_from_json(
            json.dumps(policy.payload(), separators=(",", ":"))
        )
        == policy
    )
    assert (
        agent_release_readiness.envelope_from_json(
            json.dumps(envelope.payload(), separators=(",", ":")).encode()
        )
        == envelope
    )


@pytest.mark.parametrize(
    ("loader", "payload"),
    [
        (
            agent_release_readiness.policy_from_json,
            b'{"schema_version":1,"schema_version":1}',
        ),
        (
            agent_release_readiness.envelope_from_json,
            b'{"review_id":"one","review_id":"two"}',
        ),
        (agent_release_readiness.policy_from_json, b"[]"),
        (agent_release_readiness.envelope_from_json, b"null"),
        (agent_release_readiness.policy_from_json, b""),
        (agent_release_readiness.envelope_from_json, b"\xff"),
    ],
)
def test_json_parsers_reject_ambiguous_or_invalid_documents(loader, payload):
    with pytest.raises(agent_release_readiness.ReleaseReadinessError):
        loader(payload)


def test_eligible_manifest_still_requires_explicit_human_review():
    readiness = agent_release_readiness.summarize(_manifest())

    assert readiness["status"] == "eligible_awaiting_explicit_review"
    assert readiness["identity_complete"] is True
    assert readiness["release_eligible"] is True
    assert readiness["explicit_human_review_required"] is True
    assert readiness["review_evidence_status"] == "not_selected"
    assert readiness["release_review_verifier_implemented"] is True
    assert readiness["reviewed_release"] is False
    assert readiness["paper_order_route"] == "absent"
    assert readiness["execution_authority"] == "none"
    assert agent_release_readiness.verify_projection(readiness) == readiness


def test_dirty_manifest_is_sanitized_and_remains_blocked():
    readiness = agent_release_readiness.summarize(_manifest(eligible=False))

    assert readiness["status"] == "not_release_candidate"
    assert readiness["release_eligible"] is False
    assert readiness["manifest_reasons"] == ["dirty-working-tree"]
    assert readiness["working_tree_dirty"] is True
    assert readiness["changed_path_count"] == 1
    assert readiness["reviewed_release"] is False


def test_manifest_tampering_and_inspection_failure_fail_closed():
    manifest = _manifest()
    manifest["git"]["dirty"] = True
    with pytest.raises(
        agent_release_readiness.ReleaseReadinessError,
        match="identity",
    ):
        agent_release_readiness.summarize(manifest)

    result = agent_release_readiness.inspect(
        manifest_builder=lambda *_args: (_ for _ in ()).throw(OSError("private"))
    )
    assert result["status"] == "unavailable"
    assert result["manifest_reasons"] == ["release-manifest-inspection-failed"]
    assert result["reviewed_release"] is False
    assert result["execution_authority"] == "none"


def test_exact_authenticated_review_is_design_evidence_only():
    readiness = agent_release_readiness.summarize(_manifest())
    policy = _policy()
    envelope = _envelope(readiness)

    result = agent_release_readiness.verify_review(
        readiness,
        envelope,
        policy,
        trusted_release_readiness_sha256=readiness[
            "release_readiness_sha256"
        ],
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=_accept_expected(envelope),
        observed_at=NOW + timedelta(seconds=2),
    )

    assert result["status"] == "reviewed_release_design_evidence"
    assert result["reviewed_release"] is True
    assert result["manifest_eligibility_verified"] is True
    assert result["authenticator_verified"] is True
    assert result["persistence_implemented"] is False
    assert result["readiness_integration_implemented"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    body = {
        key: value for key, value in result.items() if key != "verification_sha256"
    }
    assert result["verification_sha256"] == canonical_sha256(body)


def test_ineligible_release_cannot_be_reviewed():
    readiness = agent_release_readiness.summarize(_manifest(eligible=False))
    policy = _policy()
    eligible = agent_release_readiness.summarize(_manifest())
    envelope = _envelope(eligible)

    with pytest.raises(
        agent_release_readiness.ReleaseReadinessError,
        match="not eligible",
    ):
        agent_release_readiness.verify_review(
            readiness,
            envelope,
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=_accept_expected(envelope),
            observed_at=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"git_commit": "9" * 40},
        {"git_tree": "8" * 40},
        {"manifest_sha256": "7" * 64},
        {"reviewer_identity": "operator-two"},
        {"expires_at": NOW + timedelta(seconds=302)},
    ],
)
def test_review_identity_scope_and_time_drift_fail_closed(change):
    readiness = agent_release_readiness.summarize(_manifest())
    policy = _policy()
    envelope = _envelope(readiness, **change)

    with pytest.raises(agent_release_readiness.ReleaseReadinessError):
        agent_release_readiness.verify_review(
            readiness,
            envelope,
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=_accept_expected(envelope),
            observed_at=NOW + timedelta(seconds=2),
        )


def test_rehashed_readiness_forgery_and_failed_authenticator_are_rejected():
    readiness = agent_release_readiness.summarize(_manifest())
    policy = _policy()
    envelope = _envelope(readiness)
    forged = deepcopy(readiness)
    forged["git_tree"] = "8" * 40
    forged_body = {
        key: value
        for key, value in forged.items()
        if key != "release_readiness_sha256"
    }
    forged["release_readiness_sha256"] = canonical_sha256(forged_body)

    with pytest.raises(
        agent_release_readiness.ReleaseReadinessError,
        match="not eligible",
    ):
        agent_release_readiness.verify_review(
            forged,
            envelope,
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=_accept_expected(envelope),
            observed_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(
        agent_release_readiness.ReleaseReadinessError,
        match="authentication failed",
    ):
        agent_release_readiness.verify_review(
            readiness,
            envelope,
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: False,
            observed_at=NOW + timedelta(seconds=2),
        )


def test_module_has_no_persistence_or_execution_surface():
    assert {
        "append",
        "persist",
        "record",
        "submit",
        "submit_order",
        "activate",
        "connect",
    }.isdisjoint(vars(agent_release_readiness))
