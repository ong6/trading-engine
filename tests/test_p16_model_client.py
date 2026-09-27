from copy import deepcopy

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_model_client as base
from server import p16_model_client as client


def _health():
    return {
        "ok": True, "proxy_version": base.REQUIRED_PROXY_VERSION,
        "proxy_source_sha256": base.REQUIRED_PROXY_SOURCE_SHA256,
        "traex": base.REQUIRED_TRAECLI_RUNTIME, "token": {"present": True},
    }


def _entry():
    return {
        "id": "fixture-model:max", "object": "model", "owned_by": "fixture",
        "routing_key": "fixture-max",
    }


def _contract(**kwargs):
    return client.bind_contract(
        _health(), _entry(), upstream_model_family="fixture-family",
        instructions=kwargs.pop("instructions", client.prompt()), **kwargs,
    )


def _response():
    return {
        "id": "response-1", "status": "completed", "model": _entry()["id"],
        "provider_metadata": {
            "model_family": "fixture-family", "request_id": "upstream-1",
        },
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        "output": [{"type": "message", "role": "assistant", "content": [{
            "type": "output_text", "text": '{"schema_version":1,"assessments":[]}',
        }]}],
    }


def _transport(
    response=None, *, changed_catalog=False, duplicate_catalog=False,
    changed_health=False,
):
    calls = []

    def request(method, path, body, **_kwargs):
        calls.append((method, path, body))
        if path == base.PROXY_RESPONSES_PATH:
            return deepcopy(_response() if response is None else response)
        if path == base.PROXY_HEALTH_PATH:
            health = _health()
            if changed_health and len(calls) > 3:
                health["proxy_source_sha256"] = "0" * 64
            return health
        entry = _entry()
        if changed_catalog and len(calls) > 3:
            entry["routing_key"] = "changed-route"
        return {"object": "list", "data": [entry, entry] if duplicate_catalog else [entry]}

    return request, calls


def _generate(request, contract=None, **kwargs):
    binding = _contract() if contract is None else contract
    return client.generate(
        {"candidates": []}, binding,
        registered_model_contract_sha256=binding["model_contract_sha256"],
        request=request, **kwargs,
    )


def test_alternate_model_request_and_receipt_are_bound_without_changing_p15():
    original = base.identity(role="p15_scoring")
    request, calls = _transport()
    result = _generate(request)
    assert base.identity(role="p15_scoring") == original
    assert len(calls) == 5 and calls[2][:2] == ("POST", base.PROXY_RESPONSES_PATH)
    payload = calls[2][2]
    assert payload["model"] == _entry()["id"]
    assert payload["instructions"] == client.prompt()
    assert payload["tools"] == [] and payload["tool_choice"] == "none"
    assert payload["parallel_tool_calls"] is False and payload["store"] is False
    assert result["request_sha256"] == canonical_sha256(payload)
    assert result["response_sha256"] == canonical_sha256(result["response"])
    assert result["provider_request_id"] == "upstream-1"
    assert result["usage"]["total_tokens"] == 30
    assert result["identity_scope"] == "observable_catalog_alias"
    assert result["execution_authority"] == "none"


def test_custom_lab_prompt_requires_its_own_frozen_binding():
    instructions = "Return one JSON object containing the supplied diagnostic answers."
    binding = _contract(instructions=instructions)
    request, _ = _transport()
    with pytest.raises(base.ConnectorError, match="binding differs"):
        _generate(request, binding)
    result = _generate(request, binding, instructions=instructions)
    assert result["request"]["instructions"] == instructions


def test_a_rehashed_binding_cannot_replace_registered_binding():
    original = _contract()
    changed = deepcopy(original)
    changed["upstream_model_family"] = "other-family"
    changed["model_contract_sha256"] = canonical_sha256({
        key: value for key, value in changed.items() if key != "model_contract_sha256"
    })
    request, calls = _transport()
    with pytest.raises(base.ConnectorError, match="registered policy binding"):
        client.generate(
            {}, changed,
            registered_model_contract_sha256=original["model_contract_sha256"],
            request=request,
        )
    assert calls == []


@pytest.mark.parametrize(
    "change", ["model", "provider", "tool", "duplicate_json", "multiple_messages", "usage"],
)
def test_invalid_responses_keep_exact_private_receipt(change):
    response = _response()
    if change == "model":
        response["model"] = "other-model"
    elif change == "provider":
        response["provider_metadata"]["model_family"] = "other-family"
    elif change == "tool":
        response["output"].append({
            "type": "function_call", "name": "submit_order", "arguments": "{}",
        })
    elif change == "duplicate_json":
        response["output"][0]["content"][0]["text"] = \
            '{"schema_version":1,"schema_version":2}'
    elif change == "multiple_messages":
        response["output"].append(deepcopy(response["output"][0]))
    else:
        response["usage"]["input_tokens"] = -1
    request, _ = _transport(response)
    with pytest.raises(client.ResponseError) as caught:
        _generate(request)
    assert caught.value.response == response
    assert caught.value.response_sha256 == canonical_sha256(response)
    assert caught.value.request["tools"] == []


@pytest.mark.parametrize("options", [
    {"changed_catalog": True}, {"changed_health": True},
])
def test_identity_drift_during_generation_invalidates_and_retains_response(options):
    request, _ = _transport(**options)
    with pytest.raises(client.ResponseError) as caught:
        _generate(request)
    assert caught.value.response == _response()


def test_ambiguous_catalogue_fails_before_model_inference():
    request, calls = _transport(duplicate_catalog=True)
    with pytest.raises(base.ConnectorError, match="ambiguous"):
        _generate(request)
    assert len(calls) == 2 and all(method == "GET" for method, _, _ in calls)


def test_contract_exposes_runtime_hash_and_rejects_empty_instructions():
    binding = _contract()
    assert binding["runtime_sha256"] == canonical_sha256(base.REQUIRED_TRAECLI_RUNTIME)
    assert "traex" not in binding and "traecli_runtime" not in binding
    assert binding["provider_model_revision"] is None
    with pytest.raises(base.ConnectorError, match="instructions"):
        client.bind_contract(
            _health(), _entry(), upstream_model_family="fixture-family", instructions="",
        )
