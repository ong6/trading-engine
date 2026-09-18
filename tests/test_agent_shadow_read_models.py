"""Bounded shadow-attempt projections expose metadata, not retained content."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from server import agent_shadow_read_models, agent_shadow_store

NOW = datetime(2026, 9, 13, 12, 0)


def _insert_attempt(con, attempt_id: int, *, terminal: str | None = "no_action"):
    agent_shadow_store.init_schema(con)
    con.execute(
        "INSERT INTO agent_shadow_attempts ("
        "id, decision_window, schema_version, mode, agent_id, strategy_id, "
        "ticker, market_date, context_sha256, context_payload, model_input, "
        "model_request, request_sha256, model, model_version, prompt_sha256, "
        "toolset_sha256, required_proxy_version, execution_authority, started_at"
        ") VALUES (?, ?, 1, 'agent_only', 'paper-research-agent', "
        "'dual_momentum', 'SPY', DATE '2026-09-11', ?, ?, ?, ?, ?, "
        "'GPT-5.6-Sol:max', 'unversioned-catalog-alias', ?, ?, '0.7', 'none', ?)",
        [
            attempt_id,
            f"agent-shadow-v1:{attempt_id:064x}",
            "a" * 64,
            '{"private_context":"hidden"}',
            '{"private_prompt":"hidden"}',
            '{"private_request":"hidden"}',
            "b" * 64,
            "c" * 64,
            "d" * 64,
            NOW,
        ],
    )
    con.execute(
        "INSERT INTO agent_shadow_events VALUES (?, ?, 'started', ?, ?)",
        [
            attempt_id * 10,
            attempt_id,
            json.dumps({"request_sha256": "b" * 64, "execution_authority": "none"}),
            NOW,
        ],
    )
    if terminal == "no_action":
        con.execute(
            "INSERT INTO agent_shadow_events VALUES (?, ?, 'model_response', ?, ?)",
            [
                attempt_id * 10 + 1,
                attempt_id,
                json.dumps(
                    {
                        "response_id": f"resp-{attempt_id}",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "total_tokens": 12,
                        },
                    }
                ),
                NOW,
            ],
        )
        con.execute(
            "INSERT INTO agent_shadow_events VALUES (?, ?, 'no_action', ?, ?)",
            [
                attempt_id * 10 + 2,
                attempt_id,
                json.dumps(
                    {
                        "decision": {"reason": "private detailed output"},
                        "result": {
                            "status": "no_action",
                            "reason": "No sufficient edge.",
                            "proposal_result": None,
                        },
                    }
                ),
                NOW,
            ],
        )


def test_missing_tables_return_closed_empty_projection(con):
    assert agent_shadow_read_models.attempts(con) == {
        "execution_authority": "none",
        "invocation": {
            "manual": True,
            "systemd_timer": "trading-engine-agent-shadow.timer",
        },
        "retry_policy": {
            "decision_regeneration": False,
            "completed_window_replay": True,
            "recorded_response_resume": True,
            "unrecorded_response_outcome": "uncertain",
        },
        "limit": 100,
        "matching_count": 0,
        "truncated": False,
        "attempts": [],
    }


def test_projection_exposes_bounded_metadata_not_retained_content(con):
    _insert_attempt(con, 1)

    payload = agent_shadow_read_models.attempts(con)

    assert payload["matching_count"] == 1
    assert payload["truncated"] is False
    assert payload["attempts"] == [
        {
            "id": 1,
            "decision_window": f"agent-shadow-v1:{1:064x}",
            "mode": "agent_only",
            "policy_id": "legacy_unregistered",
            "policy_registration_sha256": None,
            "strategy_id": "dual_momentum",
            "ticker": "SPY",
            "market_date": datetime(2026, 9, 11).date(),
            "context_sha256": "a" * 64,
            "model": "GPT-5.6-Sol:max",
            "model_version": "unversioned-catalog-alias",
            "request_sha256": "b" * 64,
            "started_at": NOW,
            "status": "no_action",
            "completed_at": NOW,
            "response_id": "resp-1",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            },
            "reason": "No sufficient edge.",
            "proposal_record_id": None,
            "proposal_status": None,
        }
    ]
    serialized = json.dumps(payload, default=str)
    for private in ("private_context", "private_prompt", "private_request", "private detailed"):
        assert private not in serialized


def test_projection_orders_bounds_and_marks_in_progress(con, monkeypatch):
    monkeypatch.setattr(agent_shadow_read_models, "ATTEMPTS_LIMIT", 2)
    _insert_attempt(con, 1)
    _insert_attempt(con, 2, terminal=None)
    _insert_attempt(con, 3)

    payload = agent_shadow_read_models.attempts(con)

    assert payload["matching_count"] == 3
    assert payload["truncated"] is True
    assert [item["id"] for item in payload["attempts"]] == [3, 2]
    assert payload["attempts"][1]["status"] == "in_progress"
    assert payload["attempts"][1]["completed_at"] is None


@pytest.mark.parametrize(
    ("column", "value", "detail"),
    [
        ("mode", "invalid", "registration"),
        ("decision_window", "bad window", "decision window"),
        ("context_sha256", "bad", "context identity"),
        ("model", "", "model"),
        ("request_sha256", "bad", "request identity"),
    ],
)
def test_projection_fails_closed_on_malformed_attempt(con, column, value, detail):
    _insert_attempt(con, 1)
    con.execute(f"UPDATE agent_shadow_attempts SET {column} = ?", [value])

    with pytest.raises(ValueError, match=detail):
        agent_shadow_read_models.attempts(con)


def test_projection_rejects_inconsistent_usage(con):
    _insert_attempt(con, 1)
    con.execute(
        "UPDATE agent_shadow_events SET payload = ? "
        "WHERE attempt_id = 1 AND event_type = 'model_response'",
        [
            json.dumps(
                {
                    "response_id": "resp-1",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 99,
                    },
                }
            )
        ],
    )

    with pytest.raises(ValueError, match="inconsistent"):
        agent_shadow_read_models.attempts(con)


def test_projection_reports_metadata_from_malformed_model_response(con):
    _insert_attempt(con, 1, terminal=None)
    con.execute(
        "INSERT INTO agent_shadow_events VALUES (11, 1, 'malformed_output', ?, ?)",
        [
            json.dumps(
                {
                    "response_id": "resp-malformed",
                    "response_sha256": "e" * 64,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    },
                    "result": {
                        "status": "malformed_output",
                        "reason": "model output is not one strict JSON object",
                        "proposal_result": None,
                    },
                }
            ),
            NOW,
        ],
    )

    attempt = agent_shadow_read_models.attempts(con)["attempts"][0]

    assert attempt["status"] == "malformed_output"
    assert attempt["response_id"] == "resp-malformed"
    assert attempt["usage"]["total_tokens"] == 11
