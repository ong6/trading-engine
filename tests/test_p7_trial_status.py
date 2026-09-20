"""P7 manifest and status are hash-bound, bounded, and non-authorizing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from engine.lib.provenance import canonical_sha256
from server import main, p7_trial_status


def _authority(*, data_status: str = "blocked", drills_status: str = "pass") -> dict:
    policies = []
    for policy_id in (
        "dual_momentum_agent_shadow_v1",
        "dual_momentum_hybrid_veto_shadow_v1",
    ):
        policies.append(
            {
                "policy_id": policy_id,
                "automatic_paper": {
                    "gates": [
                        {"name": "point_in_time_data", "status": data_status},
                        {
                            "name": "fault_injection_and_restart_evidence",
                            "status": drills_status,
                        },
                    ]
                },
            }
        )
    return {
        "policies": policies,
        "broker_route": "absent",
        "live_trading": "disabled",
        "execution_authority": "none",
    }


def test_registration_is_exactly_hash_bound_and_preregistered_inactive():
    manifest = p7_trial_status.registration()

    assert manifest["schema_version"] == 1
    assert manifest["registration_status"] == "preregistered_inactive"
    assert [arm["arm_id"] for arm in manifest["arms"]] == list(p7_trial_status.ARM_IDS)
    assert manifest["capital"]["owner_envelope_value"] == 10_000
    assert manifest["capital"]["usd_opening_balance"] is None
    assert manifest["cohort"]["activation_market_date"] is None
    assert manifest["cohort"]["cohort_id"] is None
    assert manifest["execution_authority"] == "none"
    assert manifest["live_trading"] == "disabled"


def test_registration_rejects_nested_policy_or_manifest_tampering(tmp_path: Path):
    payload = json.loads(p7_trial_status.REGISTRATION_PATH.read_text())
    payload["arms"][0]["behavior"] = "changed"
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(p7_trial_status.TrialStatusError, match="arm contract"):
        p7_trial_status.registration(path)

    payload = json.loads(p7_trial_status.REGISTRATION_PATH.read_text())
    payload["capital"]["fx_observation_sha256"] = "f" * 64
    path.write_text(json.dumps(payload))
    with pytest.raises(p7_trial_status.TrialStatusError, match="FX boundary"):
        p7_trial_status.registration(path)

    payload = json.loads(p7_trial_status.REGISTRATION_PATH.read_text())
    payload["runtime_evidence"]["dry_run_window_sha256"] = "f" * 64
    path.write_text(json.dumps(payload))
    with pytest.raises(p7_trial_status.TrialStatusError, match="manifest hash"):
        p7_trial_status.registration(path)


def test_current_status_reports_every_activation_blocker_without_writes(con, monkeypatch):
    monkeypatch.setattr(
        p7_trial_status.agent_authority_read_models,
        "readiness",
        lambda actual: _authority() if actual is con else pytest.fail("wrong connection"),
    )
    monkeypatch.setattr(
        p7_trial_status.agent_model_client,
        "status",
        lambda: p7_trial_status.agent_model_client.identity(),
    )
    before = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in (
            "portfolios",
            "sim_orders",
            "sim_fills",
            "sim_positions",
            "sim_equity",
        )
    }

    status = p7_trial_status.project(con)

    assert status["status"] == "blocked"
    assert status["cohort_id"] is None
    assert status["activation_permitted"] is False
    assert status["execution_authority"] == "none"
    assert status["broker_route"] == "absent"
    assert status["live_trading"] == "disabled"
    assert status["blockers"] == [
        "trial_policy_implementations",
        "shared_data_admission",
        "independent_fx_boundary",
        "three_isolated_books",
        "simulator_only_orchestrator",
        "complete_dry_run_window",
        "fault_drills_current",
        "trial_scheduler_current",
        "backup_restore_rehearsal",
        "validation_evidence",
        "future_activation_date",
        "immutable_cohort_identity",
    ]
    assert status["blocker_count"] == len(status["blockers"])
    gates = {gate["name"]: gate for gate in status["gates"]}
    assert gates["manifest_dependencies_current"]["status"] == "pass"
    assert gates["fault_drills_current"]["status"] == "blocked"
    assert gates["fault_drills_current"]["evidence"]["p7_trial_drills_implemented"] is False
    assert gates["shared_data_admission"]["evidence"]["content_fingerprint_verified"] is False
    assert gates["observable_model_identity"]["status"] == "pass"
    assert gates["observable_model_identity"]["evidence"]["response_binding_required"] is True
    assert gates["prohibited_routes_absent"]["status"] == "pass"
    assert gates["three_isolated_books"]["evidence"] == {
        "matching_inactive_name_count": 0,
        "required_book_count": 3,
        "portfolio_bindings_complete": False,
        "attribution_table_count": 0,
        "required_attribution_table_count": 2,
        "exact_attribution_balance_date_config_verified": False,
        "semantic_verifier_available": False,
        "verification_status": "unverified",
        "legacy_p5_initializer_usable_for_p7": False,
    }
    assert (
        gates["trial_policy_implementations"]["evidence"]["legacy_p5_initializer_usable_for_p7"]
        is False
    )
    assert (
        gates["trial_policy_implementations"]["evidence"][
            "legacy_receipt_consumer_attribution_usable_for_p7"
        ]
        is False
    )
    assert len(status["gates"]) == len(p7_trial_status.REQUIREMENTS)
    assert status["status_sha256"] == canonical_sha256(
        {key: value for key, value in status.items() if key != "status_sha256"}
    )
    after = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() for table in before
    }
    assert after == before


def test_forged_hashes_and_dummy_books_leave_every_unverified_gate_blocked(
    con, tmp_path: Path, monkeypatch
):
    payload = json.loads(p7_trial_status.REGISTRATION_PATH.read_text())
    for index, arm in enumerate(payload["arms"]):
        arm["implementation_binding"] = {
            "policy_registration_sha256": f"{index + 1}" * 64,
            "portfolio_id": f"p7-book-{index}",
            "runtime_source_sha256": f"{index + 4}" * 64,
        }
        arm["policy_sha256"] = canonical_sha256(
            {key: value for key, value in arm.items() if key != "policy_sha256"}
        )
        con.execute(
            "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
            "VALUES (?, ?, 'none', '{}', DATE '2026-09-20', FALSE, 1)",
            [f"p7-book-{index}", f"book {index}"],
        )
    con.execute("CREATE TABLE agent_paper_book_attribution (id INTEGER)")
    con.execute("CREATE TABLE agent_paper_order_attribution (id INTEGER)")
    payload["capital"].update(
        {
            "fx_observation_sha256": "a" * 64,
            "fx_observed_at": "2026-09-20T00:00:00Z",
            "usd_opening_balance": 7777.0,
        }
    )
    payload["cohort"]["activation_market_date"] = "2026-10-01"
    payload["cohort"]["cohort_id"] = "forged-cohort"
    for field in payload["runtime_evidence"]:
        payload["runtime_evidence"][field] = "b" * 64
    payload["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        p7_trial_status.agent_authority_read_models,
        "readiness",
        lambda _con: _authority(data_status="pass", drills_status="pass"),
    )
    monkeypatch.setattr(p7_trial_status.agent_model_client, "MODEL_VERSION", "stable-1")
    original_identity = p7_trial_status.agent_model_client.identity
    monkeypatch.setattr(
        p7_trial_status.agent_model_client,
        "identity",
        lambda *args, **kwargs: {
            **original_identity(*args, **kwargs),
            "provider_model_revision_available": True,
            "provider_model_revision": "stable-1",
        },
    )
    monkeypatch.setattr(
        p7_trial_status.agent_model_client,
        "status",
        lambda: p7_trial_status.agent_model_client.identity(),
    )

    status = p7_trial_status.project(con, registration_path=path)

    assert status["activation_permitted"] is False
    assert status["execution_authority"] == "none"
    gates = {gate["name"]: gate for gate in status["gates"]}
    for name in (
        "trial_policy_implementations",
        "shared_data_admission",
        "independent_fx_boundary",
        "three_isolated_books",
        "simulator_only_orchestrator",
        "complete_dry_run_window",
        "fault_drills_current",
        "trial_scheduler_current",
        "backup_restore_rehearsal",
        "validation_evidence",
        "future_activation_date",
        "immutable_cohort_identity",
    ):
        assert gates[name]["status"] == "blocked"
        assert gates[name]["evidence"]["verification_status"] == "unverified"
    assert gates["three_isolated_books"]["evidence"]["matching_inactive_name_count"] == 3
    assert (
        gates["three_isolated_books"]["evidence"]["exact_attribution_balance_date_config_verified"]
        is False
    )


def test_read_only_route_delegates_closes_and_maps_invalid_evidence(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {"status": "blocked", "activation_permitted": False}
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.p7_trial_status,
        "project",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.paper_trial_status() == payload
    assert con.closed is True

    con = Connection()
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.p7_trial_status,
        "project",
        lambda _con: (_ for _ in ()).throw(p7_trial_status.TrialStatusError("invalid manifest")),
    )
    with pytest.raises(HTTPException, match="paper trial status unavailable") as error:
        main.paper_trial_status()
    assert error.value.status_code == 503
    assert con.closed is True
