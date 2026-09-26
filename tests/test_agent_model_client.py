"""Tests for the constrained local Trae proxy connector."""

from __future__ import annotations

import json

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_model_client


class Response:
    def __init__(
        self,
        payload,
        *,
        status=200,
        content_type="application/json",
        content_length=True,
    ):
        self.status = status
        self.raw = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        self.headers = {"content-type": content_type}
        if content_length:
            self.headers["content-length"] = str(len(self.raw))
        self.read_size = None

    def getheader(self, name):
        return self.headers.get(name.lower())

    def read(self, size):
        self.read_size = size
        return self.raw[:size]


class Connection:
    def __init__(self, response, observed):
        self.response = response
        self.observed = observed
        self.closed = False

    def request(self, method, path, *, body, headers):
        self.observed.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers,
            }
        )

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def factory_for(responses):
    observed = []
    connections = []
    timeouts = []

    def factory(host, port, timeout):
        response = responses[len(connections)]
        connection = Connection(response, observed)
        connections.append(connection)
        timeouts.append(timeout)
        assert host == "127.0.0.1"
        assert port == 8317
        return connection

    return factory, observed, connections, timeouts


def health():
    return {
        "ok": True,
        "proxy_version": "0.7",
        "proxy_source_sha256": agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        "traex": "traecli 0.205.1(internal edition)",
        "token": {"present": True, "user": "secret-not-public"},
        "upstream": "secret-not-public",
    }


def models(*ids):
    return {
        "object": "list",
        "data": [
            (
                dict(agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY)
                if model_id == agent_model_client.MODEL
                else {"id": model_id}
            )
            for model_id in ids
        ],
    }


def response(output):
    return {
        "id": "resp_123",
        "object": "response",
        "status": "completed",
        "model": agent_model_client.MODEL,
        "provider_metadata": {
            "model_family": agent_model_client.UPSTREAM_MODEL_FAMILY,
            "request_id": "upstream-123",
        },
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(output, separators=(",", ":")),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
    }


def tool_response(arguments):
    payload = response({})
    payload["output"] = [{
        "type": "function_call", "name": "submit_paper_trade",
        "call_id": "call_123", "arguments": json.dumps(arguments),
    }]
    return payload


def test_status_uses_only_loopback_allowlisted_routes_and_sanitizes_health():
    factory, observed, connections, timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL, "another-model")),
        ]
    )

    result = agent_model_client.status(connection_factory=factory)

    assert result == {
        "schema_version": 3,
        "transport": "trae_cli_proxy",
        "endpoint": "http://127.0.0.1:8317/v1/responses",
        "api": "openai_responses",
        "model": "GPT-5.6-Sol:max",
        "model_version": "unversioned-catalog-alias",
        "provider_model_revision": None,
        "provider_model_revision_available": False,
        "model_catalog_entry": agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY,
        "model_catalog_entry_sha256": (agent_model_client.MODEL_CATALOG_ENTRY_SHA256),
        "required_proxy_version": "0.7",
        "required_proxy_source_sha256": agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        "required_traecli_runtime": "traecli 0.205.1(internal edition)",
        "proxy_version": "0.7",
        "proxy_source_sha256": agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        "traecli_runtime": "traecli 0.205.1(internal edition)",
        "observed_model_catalog_entry_sha256": (agent_model_client.MODEL_CATALOG_ENTRY_SHA256),
        "instructions_sha256": canonical_sha256(agent_model_client.INSTRUCTIONS),
        "toolset_sha256": canonical_sha256([]),
        "tools": "none",
        "execution_authority": "none",
    }
    assert [item["path"] for item in observed] == ["/healthz", "/v1/models"]
    assert "token" not in result
    assert "upstream" not in result
    assert all(connection.closed for connection in connections)
    assert timeouts == [5.0, 5.0]


def test_generate_json_uses_no_tools_and_returns_strict_object():
    factory, observed, connections, timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(response({"decision": "no_action"})),
            Response(health()),
            Response(models(agent_model_client.MODEL)),
        ]
    )

    result = agent_model_client.generate_json(
        {"context": {"execution_authority": "none"}},
        connection_factory=factory,
    )

    assert result.output == {"decision": "no_action"}
    assert result.response_id == "resp_123"
    assert result.model == agent_model_client.MODEL
    assert result.model_version == agent_model_client.MODEL_VERSION
    assert result.proxy_version == "0.7"
    assert result.proxy_source_sha256 == agent_model_client.REQUIRED_PROXY_SOURCE_SHA256
    assert result.upstream_model_family == agent_model_client.UPSTREAM_MODEL_FAMILY
    assert result.upstream_request_id == "upstream-123"
    assert result.traecli_runtime == agent_model_client.REQUIRED_TRAECLI_RUNTIME
    assert result.model_catalog_entry_sha256 == agent_model_client.MODEL_CATALOG_ENTRY_SHA256
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }
    model_request = next(item for item in observed if item["path"] == "/v1/responses")
    request = json.loads(model_request["body"])
    assert request["model"] == "GPT-5.6-Sol:max"
    assert request["stream"] is False
    assert request["store"] is False
    assert request["tools"] == []
    assert request["tool_choice"] == "none"
    assert request["parallel_tool_calls"] is False
    assert result.request_sha256 == canonical_sha256(request)
    assert all(connection.closed for connection in connections)
    assert timeouts == [5.0, 5.0, 240.0, 5.0, 5.0]


def test_generate_veto_json_uses_distinct_fixed_prompt_and_no_tools():
    factory, observed, connections, timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(response({"decision": "allow"})),
            Response(health()),
            Response(models(agent_model_client.MODEL)),
        ]
    )

    result = agent_model_client.generate_veto_json(
        {"candidate": {"execution_authority": "none"}},
        connection_factory=factory,
    )

    request = json.loads(next(item for item in observed if item["path"] == "/v1/responses")["body"])
    assert result.output == {"decision": "allow"}
    assert request["instructions"] == agent_model_client.VETO_INSTRUCTIONS
    assert request["instructions"] != agent_model_client.INSTRUCTIONS
    assert request["tools"] == []
    assert request["tool_choice"] == "none"
    assert request["parallel_tool_calls"] is False
    assert result.request_sha256 == canonical_sha256(request)
    assert agent_model_client.identity(role="veto")["instructions_sha256"] == (
        canonical_sha256(agent_model_client.VETO_INSTRUCTIONS)
    )
    assert all(connection.closed for connection in connections)
    assert timeouts == [5.0, 5.0, 240.0, 5.0, 5.0]


def test_p15_scoring_uses_truthful_distinct_prompt_and_no_tools():
    factory, observed, connections, timeouts = factory_for([
        Response(health()), Response(models(agent_model_client.MODEL)),
        Response(response({"schema_version": 1, "assessments": []})),
        Response(health()), Response(models(agent_model_client.MODEL)),
    ])

    result = agent_model_client.generate_p15_scoring_json(
        {"policy_id": "p15-scoring-v1", "candidates": []},
        connection_factory=factory,
    )

    request = json.loads(
        next(item for item in observed if item["path"] == "/v1/responses")["body"]
    )
    assert result.output == {"schema_version": 1, "assessments": []}
    assert request["instructions"] == agent_model_client.P15_SCORING_INSTRUCTIONS
    assert "next session open" in request["instructions"]
    assert "20 basis points" in request["instructions"]
    assert "Roughly half" in request["instructions"]
    assert request["tools"] == [] and request["tool_choice"] == "none"
    assert agent_model_client.identity(role="p15_scoring")["instructions_sha256"] == (
        canonical_sha256(agent_model_client.P15_SCORING_INSTRUCTIONS)
    )
    assert all(connection.closed for connection in connections)
    assert timeouts == [5.0, 5.0, 240.0, 5.0, 5.0]


def test_p15_preopen_is_cancel_only_and_has_no_tools():
    output = {"schema_version": 1, "decisions": [
        {"intent_id": 1, "decision": "keep", "reason": "No adverse new fact.",
         "evidence_ids": ["a" * 64]},
    ]}
    factory, observed, connections, timeouts = factory_for([
        Response(health()), Response(models(agent_model_client.MODEL)),
        Response(response(output)), Response(health()),
        Response(models(agent_model_client.MODEL)),
    ])

    result = agent_model_client.generate_p15_preopen_json(
        {"policy_id": "p15-preopen-v1", "intents": []}, connection_factory=factory,
    )

    request = json.loads(
        next(item for item in observed if item["path"] == "/v1/responses")["body"]
    )
    assert result.output == output
    assert request["instructions"] == agent_model_client.P15_PREOPEN_INSTRUCTIONS
    assert "cancel-only" in request["instructions"]
    assert request["tools"] == [] and request["tool_choice"] == "none"
    assert agent_model_client.identity(role="p15_preopen")["instructions_sha256"] == (
        canonical_sha256(agent_model_client.P15_PREOPEN_INSTRUCTIONS)
    )
    assert all(connection.closed for connection in connections)
    assert timeouts == [5.0, 5.0, 240.0, 5.0, 5.0]


def test_generate_trade_tool_allows_exactly_one_bounded_function():
    arguments = {"ticker": "FAST", "side": "buy", "assessment_sha256": "a" * 64,
                 "horizon_sessions": 5, "thesis": "Momentum",
                 "invalidation": "Breakdown", "evidence_ids": ["b" * 64]}
    factory, observed, _connections, _timeouts = factory_for([
        Response(health()), Response(models(agent_model_client.MODEL)),
        Response(tool_response(arguments)), Response(health()),
        Response(models(agent_model_client.MODEL)),
    ])
    result = agent_model_client.generate_trade_tool(
        {"assessment": arguments}, connection_factory=factory
    )
    request = json.loads(
        next(item for item in observed if item["path"] == "/v1/responses")["body"]
    )
    assert result.output == {"name": "submit_paper_trade", "call_id": "call_123",
                             "arguments": arguments}
    assert request["tools"] == [agent_model_client.TRADE_TOOL]
    assert request["tool_choice"] == "required"
    assert request["parallel_tool_calls"] is False


def test_generation_rejects_catalog_drift_after_model_response():
    drifted = {
        **agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY,
        "description": "changed during generation",
    }
    factory, _observed, connections, _timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(response({"decision": "no_action"})),
            Response(health()),
            Response({"object": "list", "data": [drifted]}),
        ]
    )

    with pytest.raises(
        agent_model_client.ConnectorError,
        match="catalog entry has drifted",
    ):
        agent_model_client.generate_json({}, connection_factory=factory)

    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    ("provider_metadata", "detail"),
    [
        (None, "identity is unavailable"),
        ({"model_family": "different", "request_id": "upstream-123"}, "family"),
        (
            {"model_family": agent_model_client.UPSTREAM_MODEL_FAMILY, "request_id": ""},
            "request identity",
        ),
    ],
)
def test_generation_requires_bounded_upstream_identity(provider_metadata, detail):
    payload = response({"decision": "no_action"})
    if provider_metadata is None:
        payload.pop("provider_metadata")
    else:
        payload["provider_metadata"] = provider_metadata
    factory, _observed, connections, _timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(payload),
            Response(health()),
            Response(models(agent_model_client.MODEL)),
        ]
    )

    with pytest.raises(agent_model_client.ConnectorError, match=detail):
        agent_model_client.generate_json({}, connection_factory=factory)

    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    ("responses", "detail"),
    [
        ([Response({**health(), "ok": False})], "health check"),
        ([Response({**health(), "proxy_version": "0.5"})], "version"),
        ([Response({**health(), "traex": "traecli 0.205.0"})], "runtime version"),
        ([Response(health()), Response(models("another-model"))], "model is unavailable"),
        (
            [
                Response(health()),
                Response(
                    {
                        "object": "list",
                        "data": [
                            {
                                **agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY,
                                "config_name": "remapped-model",
                            }
                        ],
                    }
                ),
            ],
            "catalog entry has drifted",
        ),
        ([Response(health(), status=503)], "HTTP 503"),
        ([Response(health(), content_type="text/plain")], "application/json"),
        ([Response(b"{")], "invalid JSON"),
    ],
)
def test_status_fails_closed_on_unhealthy_or_malformed_proxy(responses, detail):
    factory, _observed, connections, _timeouts = factory_for(responses)

    with pytest.raises(agent_model_client.ConnectorError, match=detail):
        agent_model_client.status(connection_factory=factory)

    assert all(connection.closed for connection in connections)


def test_response_size_is_bounded_even_without_content_length():
    oversized = Response(
        b"{" + b"x" * agent_model_client.MAX_RESPONSE_BYTES + b"}",
        content_length=False,
    )
    factory, _observed, connections, _timeouts = factory_for([oversized])

    with pytest.raises(agent_model_client.ConnectorError, match="size limit"):
        agent_model_client.status(connection_factory=factory)

    assert oversized.read_size == agent_model_client.MAX_RESPONSE_BYTES + 1
    assert connections[0].closed is True


def test_generate_rejects_tool_calls_and_non_json_model_text():
    tool_response = response({"decision": "no_action"})
    tool_response["output"] = [
        {
            "type": "function_call",
            "name": "shell",
            "arguments": "{}",
        }
    ]
    factory, _observed, _connections, _timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(tool_response),
            Response(health()),
            Response(models(agent_model_client.MODEL)),
        ]
    )
    with pytest.raises(agent_model_client.ModelOutputError, match="disallowed tool") as error:
        agent_model_client.generate_json({}, connection_factory=factory)
    assert error.value.response_id == "resp_123"
    assert error.value.usage == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }
    assert len(error.value.response_sha256) == 64

    malformed = response({})
    malformed["output"][0]["content"][0]["text"] = "```json\n{}\n```"
    factory, _observed, _connections, _timeouts = factory_for(
        [
            Response(health()),
            Response(models(agent_model_client.MODEL)),
            Response(malformed),
            Response(health()),
            Response(models(agent_model_client.MODEL)),
        ]
    )
    with pytest.raises(agent_model_client.ModelOutputError, match="strict JSON object") as error:
        agent_model_client.generate_json({}, connection_factory=factory)
    assert error.value.response_id == "resp_123"
    assert error.value.request_sha256 is not None
    assert error.value.usage["total_tokens"] == 14


def test_generate_rejects_oversized_or_nonfinite_input_without_network():
    def no_network(*_args):
        raise AssertionError("invalid input must fail before network access")

    with pytest.raises(agent_model_client.ConnectorError, match="canonical JSON"):
        agent_model_client.generate_json({"value": float("nan")}, connection_factory=no_network)

    with pytest.raises(agent_model_client.ConnectorError, match="size limit"):
        agent_model_client.generate_json(
            {"value": "x" * agent_model_client.MAX_INPUT_BYTES},
            connection_factory=no_network,
        )
