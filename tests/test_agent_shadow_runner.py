"""The manual shadow runner is durable, idempotent, and non-executing."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    agent_policy,
    agent_shadow_runner,
    agent_shadow_schedule,
    agent_shadow_store,
)
from sim import calendar as sim_calendar
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


@contextmanager
def no_lock(_path):
    yield


@contextmanager
def borrowed_connection(factory):
    yield factory()


def connector_result(model_input, output):
    request = (
        agent_model_client.veto_request_payload(model_input)
        if model_input["requested_mode"] == "hybrid"
        else agent_model_client.request_payload(model_input)
    )
    return agent_model_client.ConnectorResult(
        output=output,
        response_id="resp-test",
        model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION,
        proxy_version=agent_model_client.REQUIRED_PROXY_VERSION,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        model_catalog_entry_sha256=(
            agent_model_client.MODEL_CATALOG_ENTRY_SHA256
        ),
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )


@pytest.fixture
def runner(con, monkeypatch):
    fixed_etf_market(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    return {
        "connection_factory": lambda: con,
        "now": NOW,
    }


def test_no_action_is_persisted_and_replayed_without_second_model_call(con, runner):
    calls = []

    def generate(model_input):
        calls.append(model_input)
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "The bounded facts do not support action.",
            },
        )

    first = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        **runner,
    )
    second = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        **runner,
    )

    assert first["status"] == "no_action"
    assert first["replayed"] is False
    assert second == {**first, "replayed": True}
    assert len(calls) == 1
    assert calls[0]["execution_authority"] == "none"
    assert calls[0]["requested_mode"] == "agent_only"
    assert calls[0]["model_role"] == "independent_shadow_proposal"
    assert calls[0]["context"]["mode"] == "shadow"
    assert con.execute("SELECT COUNT(*) FROM agent_shadow_attempts").fetchone() == (1,)
    assert con.execute(
        "SELECT event_type FROM agent_shadow_events ORDER BY id"
    ).fetchall() == [("started",), ("model_response",), ("no_action",)]
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_proposals'"
    ).fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM agent_daily_price_observations"
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT COUNT(*) FROM agent_corporate_action_observations"
    ).fetchone() == (0,)
    stored_context = con.execute(
        "SELECT context_payload FROM agent_shadow_attempts"
    ).fetchone()[0]
    assert '"policy":"append_only_normalized_observation"' in stored_context
    assert '"raw_retained":false' in stored_context


def test_scheduled_no_action_uses_runner_replay_without_order_mutation(
    con, runner, tmp_path, monkeypatch
):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    registration.write_text(agent_policy.REGISTRATION_PATH.read_text())
    agent_shadow_schedule.set_control(
        True,
        "test scheduled shadow observation",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )
    model_calls = 0

    def generate(model_input):
        nonlocal model_calls
        model_calls += 1
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "The bounded facts do not support action.",
            },
        )

    direct_run = agent_shadow_runner.run
    monkeypatch.setattr(
        agent_shadow_schedule.agent_shadow_runner,
        "run",
        lambda strategy, ticker, **kwargs: direct_run(
            strategy,
            ticker,
            generate=generate,
            **runner,
            **kwargs,
        ),
    )

    first = agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=control,
    )
    second = agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=control,
    )

    assert first["status"] == "no_action"
    assert second == {**first, "replayed": True}
    assert model_calls == 1
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_proposals'"
    ).fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_valid_proposal_uses_server_ids_and_existing_shadow_admission(con, runner):
    complete_dual_momentum_history(con)

    def generate(model_input):
        context = model_input["context"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "proposal",
                "side": "buy",
                "max_notional": 1_000,
                "stop": 90,
                "confidence": 0.6,
                "thesis": "A bounded counterfactual proposal.",
                "invalidation": "Invalidate when the frozen context expires.",
                "evidence_ids": [context["context_sha256"]],
            },
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        **runner,
    )

    assert result["status"] == "shadow_accepted"
    assert result["execution_authority"] == "none"
    assert result["proposal_result"]["execution_authority"] == "none"
    stored = con.execute(
        "SELECT proposal_id, idempotency_key, mode, status FROM agent_proposals"
    ).fetchone()
    assert stored[0].startswith("agent-shadow-proposal:")
    assert stored[1] == result["decision_window"]
    assert stored[2:] == ("agent_only", "shadow_accepted")
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_malformed_output_and_transport_failure_consume_the_window(con, runner):
    calls = 0

    def malformed(model_input):
        nonlocal calls
        calls += 1
        return connector_result(
            model_input,
            {"schema_version": 1, "decision": "proposal", "side": "buy"},
        )

    first = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=malformed,
        **runner,
    )
    replay = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=malformed,
        **runner,
    )

    assert first["status"] == "malformed_output"
    assert replay == {**first, "replayed": True}
    assert calls == 1
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    con.execute("DELETE FROM agent_shadow_events")
    con.execute("DELETE FROM agent_shadow_attempts")

    def failed(_model_input):
        raise agent_model_client.ConnectorError("Trae proxy is unavailable")

    failure = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=failed,
        **runner,
    )
    assert failure["status"] == "transport_failure"
    assert failure["reason"] == "Trae proxy is unavailable"
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_connector_model_output_error_is_audited_as_malformed(con, runner):
    def malformed_text(model_input):
        raise agent_model_client.ModelOutputError(
            "model output is not one strict JSON object",
            response_id="resp-malformed",
            request_sha256=canonical_sha256(
                agent_model_client.request_payload(model_input)
            ),
            response_sha256="b" * 64,
            usage={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=malformed_text,
        **runner,
    )

    assert result["status"] == "malformed_output"
    payload = agent_shadow_store.events(con, result["attempt_id"])[1][2]
    assert '"response_id":"resp-malformed"' in payload
    assert '"response_sha256":"' + "b" * 64 + '"' in payload
    assert '"total_tokens":15' in payload
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_started_attempt_without_response_becomes_uncertain_without_retry(con, runner):
    with pytest.raises(BaseException, match="simulated process death"):
        agent_shadow_runner.run(
            "dual_momentum",
            "SPY",
            mode="agent_only",
            generate=lambda _input: (_ for _ in ()).throw(
                BaseException("simulated process death")
            ),
            **runner,
        )

    calls = 0

    def must_not_generate(_model_input):
        nonlocal calls
        calls += 1
        raise AssertionError("uncertain attempt must not retry")

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )
    replay = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )

    assert result["status"] == "uncertain"
    assert replay == {**result, "replayed": True}
    assert calls == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_unfinished_prior_market_date_is_resolved_before_new_window(con, runner):
    with pytest.raises(BaseException, match="simulated process death"):
        agent_shadow_runner.run(
            "dual_momentum",
            "SPY",
            mode="agent_only",
            generate=lambda _input: (_ for _ in ()).throw(
                BaseException("simulated process death")
            ),
            **runner,
        )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('SPY', DATE '2026-09-14', 101, 102, 100, 101, 1000000, "
        "'yfinance', TIMESTAMP '2026-09-15 00:00:00')"
    )
    calls = 0

    def must_not_generate(_model_input):
        nonlocal calls
        calls += 1
        raise AssertionError("prior unfinished attempt must be resolved first")

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )

    assert result["status"] == "uncertain"
    assert calls == 0
    assert con.execute("SELECT COUNT(*) FROM agent_shadow_attempts").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_recorded_response_is_completed_after_restart_without_model_retry(
    con, runner, monkeypatch
):
    original_complete = agent_shadow_runner._complete_response

    def crash_after_response(*_args, **_kwargs):
        raise BaseException("simulated post-response process death")

    monkeypatch.setattr(agent_shadow_runner, "_complete_response", crash_after_response)

    def generate(model_input):
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "No sufficient evidence.",
            },
        )

    with pytest.raises(BaseException, match="post-response process death"):
        agent_shadow_runner.run(
            "dual_momentum",
            "SPY",
            mode="agent_only",
            generate=generate,
            **runner,
        )

    monkeypatch.setattr(agent_shadow_runner, "_complete_response", original_complete)
    calls = 0

    def must_not_generate(_model_input):
        nonlocal calls
        calls += 1
        raise AssertionError("a recorded response must be resumed, not regenerated")

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )

    assert result["status"] == "no_action"
    assert result["replayed"] is False
    assert calls == 0
    assert con.execute(
        "SELECT event_type FROM agent_shadow_events ORDER BY id"
    ).fetchall() == [("started",), ("model_response",), ("no_action",)]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_inference_runs_without_an_open_database_connection(con, monkeypatch):
    fixed_etf_market(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", no_lock)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    open_connections = 0

    @contextmanager
    def observed_connection(factory):
        nonlocal open_connections
        open_connections += 1
        try:
            yield factory()
        finally:
            open_connections -= 1

    monkeypatch.setattr(agent_shadow_runner, "_connection", observed_connection)

    def generate(model_input):
        assert open_connections == 0
        return connector_result(
            model_input,
            {"schema_version": 1, "decision": "no_action", "reason": "No action."},
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        now=NOW,
        generate=generate,
        connection_factory=lambda: con,
    )

    assert result["status"] == "no_action"
    assert open_connections == 0


def _hybrid_context(monkeypatch, *, orders):
    original = agent_shadow_runner.agent_context.build

    def build(con, strategy_id, ticker, **kwargs):
        payload = original(con, strategy_id, ticker, **kwargs)
        candidate = payload["algorithm_candidate"]
        body = {
            **candidate,
            "status": "materialized",
            "cadence_admitted": True,
            "orders": orders,
            "order_count": len(orders),
            "buy_order_count": sum(order["side"] == "buy" for order in orders),
            "sell_order_count": sum(order["side"] == "sell" for order in orders),
        }
        body.pop("candidate_sha256", None)
        candidate = {**body, "candidate_sha256": canonical_sha256(body)}
        context_body = {
            **payload,
            "algorithm_candidate": candidate,
        }
        context_body.pop("context_sha256")
        return {
            **context_body,
            "context_sha256": canonical_sha256(context_body),
        }

    monkeypatch.setattr(agent_shadow_runner.agent_context, "build", build)


def test_hybrid_allow_is_attributed_without_proposal_or_order(con, runner, monkeypatch):
    order = {
        "sequence": 1,
        "portfolio_id": "dual_momentum",
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": 1000.0,
        "veto_eligible": True,
    }
    _hybrid_context(monkeypatch, orders=[order])

    def generate(model_input):
        candidate = model_input["context"]["algorithm_candidate"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "allow",
                "candidate_sha256": candidate["candidate_sha256"],
                "reason": "No bounded evidence justifies a veto.",
                "evidence_ids": [candidate["candidate_sha256"]],
            },
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=generate,
        **runner,
    )

    assert result["status"] == "hybrid_allow"
    assert result["proposal_result"]["policy_effect"] == "unmodified_algorithm_signal"
    assert result["proposal_result"]["effective_order_count"] == 1
    assert result["proposal_result"]["vetoed_order_count"] == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_proposals'"
    ).fetchone() == (0,)

    replay = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _input: pytest.fail("completed hybrid window must replay"),
        **runner,
    )
    assert replay == {**result, "replayed": True}


def test_hybrid_veto_removes_only_buy_from_counterfactual(con, runner, monkeypatch):
    buy = {
        "sequence": 1,
        "portfolio_id": "dual_momentum",
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": 1000.0,
        "veto_eligible": True,
    }
    sell = {
        **buy,
        "sequence": 2,
        "ticker": "EFA",
        "side": "sell",
        "veto_eligible": False,
    }
    _hybrid_context(monkeypatch, orders=[buy, sell])

    def generate(model_input):
        candidate = model_input["context"]["algorithm_candidate"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "veto",
                "candidate_sha256": candidate["candidate_sha256"],
                "reason": "The buy is invalidated by bounded evidence.",
                "evidence_ids": [candidate["candidate_sha256"]],
            },
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=generate,
        **runner,
    )

    assert result["status"] == "hybrid_veto"
    assert result["proposal_result"]["policy_effect"] == "veto_buy_candidates"
    assert result["proposal_result"]["candidate_order_count"] == 2
    assert result["proposal_result"]["effective_order_count"] == 1
    assert result["proposal_result"]["vetoed_order_count"] == 1
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_hybrid_transport_failure_uses_registered_fallback(con, runner, monkeypatch):
    order = {
        "sequence": 1,
        "portfolio_id": "dual_momentum",
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": 1000.0,
        "veto_eligible": True,
    }
    _hybrid_context(monkeypatch, orders=[order])

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _input: (_ for _ in ()).throw(
            agent_model_client.ConnectorError("Trae proxy is unavailable")
        ),
        **runner,
    )

    assert result["status"] == "hybrid_fallback_allow"
    assert result["proposal_result"]["policy_effect"] == "unmodified_algorithm_signal"
    assert result["proposal_result"]["effective_order_count"] == 1
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_hybrid_candidate_hash_mismatch_uses_registered_fallback(
    con, runner, monkeypatch
):
    order = {
        "sequence": 1,
        "portfolio_id": "dual_momentum",
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": 1000.0,
        "veto_eligible": True,
    }
    _hybrid_context(monkeypatch, orders=[order])

    def generate(model_input):
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "veto",
                "candidate_sha256": "f" * 64,
                "reason": "Attempted stale-candidate veto.",
                "evidence_ids": [
                    model_input["context"]["algorithm_candidate"]["candidate_sha256"]
                ],
            },
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=generate,
        **runner,
    )

    assert result["status"] == "hybrid_fallback_allow"
    assert "candidate_sha256 does not match" in result["reason"]
    assert result["proposal_result"]["effective_order_count"] == 1
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_interrupted_hybrid_request_falls_back_without_regeneration(
    con, runner, monkeypatch
):
    order = {
        "sequence": 1,
        "portfolio_id": "dual_momentum",
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": 1000.0,
        "veto_eligible": True,
    }
    _hybrid_context(monkeypatch, orders=[order])

    with pytest.raises(BaseException, match="simulated process death"):
        agent_shadow_runner.run(
            "dual_momentum",
            "SPY",
            mode="hybrid",
            policy_id="dual_momentum_hybrid_veto_shadow_v1",
            generate=lambda _input: (_ for _ in ()).throw(
                BaseException("simulated process death")
            ),
            **runner,
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _input: pytest.fail("interrupted hybrid request must not retry"),
        **runner,
    )

    assert result["status"] == "hybrid_fallback_allow"
    assert result["proposal_result"]["policy_effect"] == "unmodified_algorithm_signal"
    assert result["proposal_result"]["effective_order_count"] == 1
    assert con.execute(
        "SELECT event_type FROM agent_shadow_events ORDER BY id"
    ).fetchall() == [("started",), ("hybrid_fallback_allow",)]


def test_hybrid_without_buy_candidate_skips_model(con, runner):
    calls = 0

    def must_not_generate(_model_input):
        nonlocal calls
        calls += 1

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=must_not_generate,
        **runner,
    )

    assert result["status"] == "hybrid_no_veto_candidate"
    assert result["proposal_result"]["effective_order_count"] == 0
    assert calls == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_non_signal_date_is_recorded_without_context_or_model_request(
    con, runner, monkeypatch
):
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", sim_calendar.is_month_signal)
    calls = 0

    def must_not_generate(_model_input):
        nonlocal calls
        calls += 1
        raise AssertionError("cadence admission must precede model generation")

    first = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )
    replay = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=must_not_generate,
        **runner,
    )

    assert first["status"] == "cadence_no_action"
    assert first["reason"] == "market date is not a registered strategy signal date"
    assert replay == {**first, "replayed": True}
    assert calls == 0
    row = con.execute(
        "SELECT policy_id, context_payload, model_input, model_request, "
        "request_sha256 FROM agent_shadow_attempts"
    ).fetchone()
    assert row == ("dual_momentum_agent_shadow_v1", None, None, None, None)
    assert con.execute(
        "SELECT event_type FROM agent_shadow_events"
    ).fetchall() == [("cadence_no_action",)]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_shadow_schema_adds_nullable_policy_identity_without_rewriting_legacy(con):
    con.execute(
        "CREATE TABLE agent_shadow_attempts ("
        "id BIGINT PRIMARY KEY, decision_window VARCHAR UNIQUE, mode VARCHAR)"
    )
    con.execute(
        "INSERT INTO agent_shadow_attempts VALUES "
        "(1, 'agent-shadow-v1:legacy', 'agent_only')"
    )

    agent_shadow_store.init_schema(con)

    assert con.execute(
        "SELECT id, decision_window, mode, policy_id, "
        "policy_registration_sha256 FROM agent_shadow_attempts"
    ).fetchall() == [
        (1, "agent-shadow-v1:legacy", "agent_only", None, None)
    ]


def test_shadow_store_records_exact_request_and_usage(con, runner):
    def generate(model_input):
        return connector_result(
            model_input,
            {"schema_version": 1, "decision": "no_action", "reason": "No action."},
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        **runner,
    )
    row = agent_shadow_store.find_window(con, result["decision_window"])
    assert row is not None
    assert canonical_sha256(agent_model_client.request_payload(
        agent_shadow_runner._model_input(
            agent_shadow_runner.agent_context.build(con, "dual_momentum", "SPY"),
            "agent_only",
        )
    )) == row[11]
    response_payload = agent_shadow_store.events(con, result["attempt_id"])[1][2]
    assert '"total_tokens":120' in response_payload
