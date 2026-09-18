"""Release-review observations are durable, exact, and non-authorizing."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_release_readiness, agent_release_review_store
from tests.test_agent_release_readiness import (
    NOW,
    _accept_expected,
    _envelope,
    _manifest,
    _policy,
)
from tests.test_release_manifest import _repository


def _builder(manifest):
    return lambda _repo_root, _database, **_kwargs: deepcopy(manifest)


def _record(
    con,
    manifest,
    policy,
    envelope,
    *,
    observed_at=NOW + timedelta(seconds=2),
    recorded_at=NOW + timedelta(seconds=3),
    verifier=None,
):
    agent_release_review_store.init_schema(con)
    readiness = agent_release_readiness.summarize(manifest)
    return agent_release_review_store.record_authenticated_review(
        con,
        envelope,
        policy,
        trusted_release_readiness_sha256=readiness[
            "release_readiness_sha256"
        ],
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=verifier or _accept_expected(envelope),
        observed_at=observed_at,
        recorded_at=recorded_at,
        manifest_builder=_builder(manifest),
    )


def test_authenticated_release_review_is_hash_chained_and_non_authorizing(con):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    policy = _policy()
    envelope = _envelope(readiness)

    result = _record(con, manifest, policy, envelope)

    assert result["status"] == (
        "authenticated_release_review_observed_non_authorizing"
    )
    assert result["observation_sequence"] == 1
    assert result["review_id"] == envelope.review_id
    assert result["manifest_sha256"] == readiness["manifest_sha256"]
    assert result["release_readiness_sha256"] == (
        readiness["release_readiness_sha256"]
    )
    assert result["prior_observation_sha256"] is None
    assert result["authenticated_evidence_replay_protection"] is True
    assert result["production_readiness_integration_implemented"] is False
    assert result["reviewed_release_gate_passed"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    assert result["observation_sha256"] == canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key != "observation_sha256"
        }
    )
    assert agent_release_review_store.status(con) == {
        "schema_version": 1,
        "status": "initialized",
        "observation_count": 1,
        "approve_observation_count": 1,
        "reject_observation_count": 0,
        "latest_recorded_at": "2026-09-17T12:00:03Z",
        "latest_observation_sha256": result["observation_sha256"],
        "authenticated_evidence_replay_protection_implemented": True,
        "production_readiness_integration_implemented": False,
        "trust_source_loader_implemented": False,
        "reviewed_release_gate_passed": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def test_complete_history_requires_exact_independently_trusted_count_and_head(con):
    empty = agent_release_review_store.verify_complete_history(
        con,
        trusted_observation_count=0,
        trusted_latest_observation_sha256=None,
    )
    assert empty["status"] == "complete_history_verified_non_authorizing"
    assert empty["trusted_observation_count"] == 0
    assert empty["trusted_latest_observation_sha256"] is None
    assert empty["independent_head_required"] is True
    assert empty["review_selection_implemented"] is False
    assert empty["reviewed_release_gate_passed"] is False
    assert empty["submission_authority"] == "none"

    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    event = _record(con, manifest, _policy(), _envelope(readiness))
    result = agent_release_review_store.verify_complete_history(
        con,
        trusted_observation_count=1,
        trusted_latest_observation_sha256=event["observation_sha256"],
    )

    assert result["trusted_observation_count"] == 1
    assert result["trusted_latest_observation_sha256"] == event[
        "observation_sha256"
    ]
    assert result["approve_observation_count"] == 1
    assert result["reject_observation_count"] == 0
    assert result["history_evidence_sha256"] == canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key != "history_evidence_sha256"
        }
    )
    assert result["reviewed_release_gate_passed"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"


def test_truncated_or_wrong_release_review_history_cannot_match_trusted_head(con):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    event = _record(con, manifest, _policy(), _envelope(readiness))

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="trusted head",
    ):
        agent_release_review_store.verify_complete_history(
            con,
            trusted_observation_count=2,
            trusted_latest_observation_sha256="f" * 64,
        )

    con.execute(f"DELETE FROM {agent_release_review_store.TABLE}")
    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="trusted head",
    ):
        agent_release_review_store.verify_complete_history(
            con,
            trusted_observation_count=1,
            trusted_latest_observation_sha256=event["observation_sha256"],
        )


@pytest.mark.parametrize(
    ("trusted_count", "trusted_head", "detail"),
    [
        (True, None, "count is invalid"),
        (-1, None, "count is invalid"),
        (0, "f" * 64, "count and head are inconsistent"),
        (1, None, "identity is invalid"),
    ],
)
def test_trusted_release_review_head_shape_fails_closed(
    con,
    trusted_count,
    trusted_head,
    detail,
):
    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match=detail,
    ):
        agent_release_review_store.verify_complete_history(
            con,
            trusted_observation_count=trusted_count,
            trusted_latest_observation_sha256=trusted_head,
        )


def test_release_review_history_change_during_verification_fails_closed(
    con,
    monkeypatch,
):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    event = _record(con, manifest, _policy(), _envelope(readiness))
    captured = agent_release_review_store._capture_rows(con)
    values = iter((captured, ("present", ())))
    monkeypatch.setattr(
        agent_release_review_store,
        "_capture_rows",
        lambda *_args: next(values),
    )

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="changed during verification",
    ):
        agent_release_review_store.verify_complete_history(
            con,
            trusted_observation_count=1,
            trusted_latest_observation_sha256=event["observation_sha256"],
        )


def test_release_review_schema_appearance_during_verification_fails_closed(
    con,
    monkeypatch,
):
    values = iter((("missing", ()), ("present", ())))
    monkeypatch.setattr(
        agent_release_review_store,
        "_capture_rows",
        lambda *_args: next(values),
    )

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="changed during verification",
    ):
        agent_release_review_store.verify_complete_history(
            con,
            trusted_observation_count=0,
            trusted_latest_observation_sha256=None,
        )


def test_exact_replay_is_idempotent_without_reauthentication(con):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    policy = _policy()
    envelope = _envelope(readiness)
    first = _record(con, manifest, policy, envelope)

    replay = _record(
        con,
        manifest,
        policy,
        envelope,
        observed_at=NOW + timedelta(minutes=10),
        recorded_at=NOW + timedelta(minutes=10),
        verifier=lambda *_args: pytest.fail(
            "exact retained replay must not re-authenticate"
        ),
    )

    assert replay == first
    assert con.execute(
        f"SELECT COUNT(*) FROM {agent_release_review_store.TABLE}"
    ).fetchone() == (1,)


def test_conflicting_review_identity_reuse_fails_closed(con):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    policy = _policy()
    envelope = _envelope(readiness)
    _record(con, manifest, policy, envelope)
    conflicting = _envelope(
        readiness,
        review_id="release-review-2",
        decision="reject_release",
    )

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="conflicts with retained evidence",
    ):
        _record(con, manifest, policy, conflicting)

    assert con.execute(
        f"SELECT review_id, decision FROM {agent_release_review_store.TABLE}"
    ).fetchall() == [("release-review-1", "approve_release")]


def test_current_release_drift_fails_before_authentication_or_schema(con):
    original = _manifest()
    readiness = agent_release_readiness.summarize(original)
    policy = _policy()
    calls = []
    changed = _manifest()
    changed["git"]["tree"] = "9" * 40
    changed_body = {
        key: value for key, value in changed.items() if key != "manifest_sha256"
    }
    changed["manifest_sha256"] = canonical_sha256(changed_body)

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="does not match trusted",
    ):
        agent_release_review_store.record_authenticated_review(
            con,
            _envelope(readiness),
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: calls.append(_args) or True,
            observed_at=NOW + timedelta(seconds=2),
            recorded_at=NOW + timedelta(seconds=3),
            manifest_builder=_builder(changed),
        )

    assert calls == []
    assert agent_release_review_store.TABLE not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }


def test_missing_ledger_fails_before_authentication(con):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    policy = _policy()
    calls = []

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="not initialized",
    ):
        agent_release_review_store.record_authenticated_review(
            con,
            _envelope(readiness),
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: calls.append(_args) or True,
            observed_at=NOW + timedelta(seconds=2),
            recorded_at=NOW + timedelta(seconds=3),
            manifest_builder=_builder(manifest),
        )

    assert calls == []
    assert agent_release_review_store.TABLE not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }


def test_file_backed_record_reuses_locked_database_connection(tmp_path):
    repo_root = _repository(tmp_path)
    database = repo_root / "store" / "market.duckdb"
    connection = duckdb.connect(str(database))
    try:
        agent_release_review_store.init_schema(connection)
        readiness = agent_release_readiness.inspect(
            repo_root=repo_root,
            database=database,
            database_connection=connection,
        )
        policy = _policy()
        envelope = _envelope(readiness)

        result = agent_release_review_store.record_authenticated_review(
            connection,
            envelope,
            policy,
            trusted_release_readiness_sha256=readiness[
                "release_readiness_sha256"
            ],
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=_accept_expected(envelope),
            observed_at=NOW + timedelta(seconds=2),
            recorded_at=NOW + timedelta(seconds=3),
            repo_root=repo_root,
            database=database,
        )
    finally:
        connection.close()

    assert readiness["status"] == "eligible_awaiting_explicit_review"
    assert result["observation_sequence"] == 1
    assert result["reviewed_release_gate_passed"] is False


@pytest.mark.parametrize(
    ("query", "value"),
    [
        (
            "UPDATE agent_release_review_observations "
            "SET envelope_payload = ?",
            '{"tampered":true}',
        ),
        (
            "UPDATE agent_release_review_observations "
            "SET prior_observation_sha256 = ?",
            "f" * 64,
        ),
        (
            "UPDATE agent_release_review_observations "
            "SET observation_sha256 = ?",
            "f" * 64,
        ),
    ],
)
def test_retained_payload_or_chain_tampering_fails_closed(con, query, value):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    _record(con, manifest, _policy(), _envelope(readiness))
    con.execute(query, [value])

    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="stored",
    ):
        agent_release_review_store.status(con)


def test_recording_failure_rolls_back_new_ledger(con, monkeypatch):
    manifest = _manifest()
    readiness = agent_release_readiness.summarize(manifest)
    agent_release_review_store.init_schema(con)
    original = agent_release_review_store._verified_events
    calls = 0

    def fail_post_write(actual):
        nonlocal calls
        calls += 1
        events = original(actual)
        if calls == 2:
            raise agent_release_review_store.ReleaseReviewStoreError(
                "forced post-write verification failure"
            )
        return events

    monkeypatch.setattr(
        agent_release_review_store,
        "_verified_events",
        fail_post_write,
    )
    with pytest.raises(
        agent_release_review_store.ReleaseReviewStoreError,
        match="forced post-write",
    ):
        _record(con, manifest, _policy(), _envelope(readiness))

    assert con.execute(
        f"SELECT COUNT(*) FROM {agent_release_review_store.TABLE}"
    ).fetchone() == (0,)


def test_release_review_store_has_no_route_adapter_or_authority_surface():
    assert {
        "activate",
        "approve",
        "issue_lease",
        "route",
        "submit",
        "submit_order",
    }.isdisjoint(vars(agent_release_review_store))
