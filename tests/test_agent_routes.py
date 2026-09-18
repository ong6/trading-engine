"""HTTP adapters for bounded agent context and shadow proposals."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from server import agent_contract, main


def test_shadow_route_maps_proposal_error_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    monkeypatch.setattr(main, "write_con", lambda: con)
    monkeypatch.setattr(
        main.agent_proposals,
        "submit",
        lambda actual, body: (_ for _ in ()).throw(
            agent_contract.ProposalError(409, "duplicate proposal")
        ),
    )
    body = agent_contract.TradeProposalRequest(
        schema_version=2,
        proposal_id="proposal-1",
        idempotency_key="window-1",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        policy_registration_sha256="8" * 64,
        agent_id="agent-1",
        model="test-model",
        model_version="test-1",
        prompt_sha256="1" * 64,
        toolset_sha256="2" * 64,
        strategy_id="dual_momentum",
        strategy_config_sha256="3" * 64,
        agent_boundary_sha256="4" * 64,
        runtime_source_sha256="5" * 64,
        data_snapshot_sha256="6" * 64,
        context_sha256="7" * 64,
        ticker="SPY",
        side="buy",
        max_notional=1_000,
        stop=90,
        confidence=0.5,
        signal_at=datetime(2026, 9, 13, tzinfo=timezone.utc).isoformat(),
        expires_at=datetime(2026, 9, 14, tzinfo=timezone.utc).isoformat(),
        thesis="test",
        invalidation="test",
        evidence_ids=["evidence-1"],
    )

    with pytest.raises(HTTPException, match="duplicate proposal") as error:
        main.submit_shadow_agent_proposal(body)

    assert error.value.status_code == 409
    assert con.closed is True


def test_context_route_maps_context_error_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_context,
        "build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            main.agent_context.ContextError("not admitted")
        ),
    )

    with pytest.raises(HTTPException, match="not admitted") as error:
        main.paper_agent_context("unknown", "SPY")

    assert error.value.status_code == 422
    assert con.closed is True


def test_daily_price_observation_status_delegates_and_closes_connection(
    monkeypatch,
):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {
        "status": "capturing",
        "raw_retained": False,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_price_observations,
        "status",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_daily_price_observation_status() == payload
    assert con.closed is True


def test_daily_price_observation_status_maps_invalid_ledger(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(
        main.agent_price_observations,
        "status",
        lambda _con: (_ for _ in ()).throw(
            main.agent_price_observations.ObservationError("invalid ledger")
        ),
    )

    with pytest.raises(HTTPException, match="invalid ledger") as error:
        main.agent_daily_price_observation_status()

    assert error.value.status_code == 503


def test_corporate_action_observation_status_delegates_and_closes_connection(
    monkeypatch,
):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {
        "status": "capturing",
        "raw_retained": False,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_corporate_action_observations,
        "status",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_corporate_action_observation_status() == payload
    assert con.closed is True


def test_corporate_action_observation_status_maps_invalid_ledger(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(
        main.agent_corporate_action_observations,
        "status",
        lambda _con: (_ for _ in ()).throw(
            main.agent_corporate_action_observations.ObservationError(
                "invalid ledger"
            )
        ),
    )

    with pytest.raises(HTTPException, match="invalid ledger") as error:
        main.agent_corporate_action_observation_status()

    assert error.value.status_code == 503


def test_provider_response_status_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {
        "status": "capturing",
        "raw_response_bodies_retained": True,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_provider_responses,
        "status",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_provider_response_status() == payload
    assert con.closed is True


def test_provider_response_status_maps_invalid_receipt(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(
        main.agent_provider_responses,
        "status",
        lambda _con: (_ for _ in ()).throw(
            main.agent_provider_responses.ProviderResponseError("invalid receipt")
        ),
    )

    with pytest.raises(HTTPException, match="invalid receipt") as error:
        main.agent_provider_response_status()

    assert error.value.status_code == 503


def test_independent_price_evidence_status_delegates_and_closes_connection(
    monkeypatch,
):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {
        "status": "capturing",
        "raw_response_bodies_retained": True,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_independent_price_evidence,
        "status",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_independent_price_evidence_status() == payload
    assert con.closed is True


def test_independent_price_evidence_status_maps_invalid_ledger(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(
        main.agent_independent_price_evidence,
        "status",
        lambda _con: (_ for _ in ()).throw(
            main.agent_independent_price_evidence.IndependentPriceEvidenceError(
                "invalid independent evidence"
            )
        ),
    )

    with pytest.raises(HTTPException, match="invalid independent evidence") as error:
        main.agent_independent_price_evidence_status()

    assert error.value.status_code == 503


def test_proposal_ledger_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {"proposals": []}
    observed = []
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_proposal_read_models,
        "proposals",
        lambda actual, status: observed.append((actual, status)) or payload,
    )

    assert main.agent_proposal_ledger("shadow_rejected") == payload
    assert observed == [(con, "shadow_rejected")]
    assert con.closed is True


def test_proposal_ledger_route_schema_restricts_status_filter():
    parameter = main.app.openapi()["paths"]["/agent/proposals"]["get"]["parameters"][0]

    assert parameter["name"] == "status"
    assert set(parameter["schema"]["anyOf"][0]["enum"]) == {
        "shadow_accepted",
        "shadow_rejected",
    }


def test_agent_model_status_route_delegates_without_database(monkeypatch):
    payload = {"transport": "trae_cli_proxy", "execution_authority": "none"}
    monkeypatch.setattr(main.agent_model_client, "status", lambda: payload)
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("status must not open the database")),
    )

    assert main.agent_model_status() == payload


def test_agent_policy_evaluation_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {"policies": [], "execution_authority": "none"}
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_policy_read_models,
        "evaluation",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_policy_evaluation() == payload
    assert con.closed is True


def test_agent_attribution_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {"records": [], "execution_authority": "none"}
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_attribution_read_models,
        "attribution",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_decision_attribution() == payload
    assert con.closed is True


def test_agent_authority_readiness_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    release_status = {
        "status": "not_release_candidate",
        "reviewed_release": False,
    }
    payload = {
        "current_stage": "shadow",
        "automatic_paper_eligible": False,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_release_readiness,
        "inspect",
        lambda: release_status,
    )
    monkeypatch.setattr(
        main.agent_authority_read_models,
        "readiness",
        lambda actual, *, release_status: (
            payload
            if actual is con
            and release_status == {
                "status": "not_release_candidate",
                "reviewed_release": False,
            }
            else pytest.fail("wrong readiness inputs")
        ),
    )

    assert main.agent_authority_readiness() == payload
    assert con.closed is True


def test_agent_fault_drill_status_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {
        "status": "current_pass",
        "current": True,
        "execution_authority": "none",
    }
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_fault_drills,
        "status",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_fault_drill_status() == payload
    assert con.closed is True


def test_agent_fault_drill_status_maps_invalid_evidence(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(
        main.agent_fault_drills,
        "status",
        lambda _con: (_ for _ in ()).throw(
            main.agent_fault_drills.FaultDrillError("invalid drill evidence")
        ),
    )

    with pytest.raises(HTTPException, match="invalid drill evidence") as error:
        main.agent_fault_drill_status()

    assert error.value.status_code == 503


def test_shadow_attempt_ledger_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    payload = {"attempts": []}
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(
        main.agent_shadow_read_models,
        "attempts",
        lambda actual: payload if actual is con else pytest.fail("wrong connection"),
    )

    assert main.agent_shadow_attempt_ledger() == payload
    assert con.closed is True


def test_shadow_control_route_delegates_without_database(monkeypatch):
    payload = {
        "enabled": False,
        "execution_authority": "none",
        "registration_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        main.agent_shadow_schedule,
        "control_status",
        lambda: payload,
    )
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(
            AssertionError("control status must not open the database")
        ),
    )

    assert main.agent_shadow_control_status() == payload


def test_shadow_control_route_maps_registration_failure(monkeypatch):
    monkeypatch.setattr(
        main.agent_shadow_schedule,
        "control_status",
        lambda: (_ for _ in ()).throw(
            main.agent_shadow_schedule.ScheduleError("registration unavailable")
        ),
    )

    with pytest.raises(HTTPException, match="registration unavailable") as error:
        main.agent_shadow_control_status()

    assert error.value.status_code == 503


def test_agent_model_status_route_maps_connector_failure(monkeypatch):
    monkeypatch.setattr(
        main.agent_model_client,
        "status",
        lambda: (_ for _ in ()).throw(
            main.agent_model_client.ConnectorError("Trae proxy is unavailable")
        ),
    )

    with pytest.raises(HTTPException, match="Trae proxy is unavailable") as error:
        main.agent_model_status()

    assert error.value.status_code == 503
