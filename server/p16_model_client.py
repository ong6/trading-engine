"""P16 tool-free inference under a registered observable model identity.

Raw requests and responses belong in the private research store. Public
projections use hashes and disclose that catalogue aliases are not immutable
provider revisions.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from server import agent_model_client as base
from server.json_utils import loads_object

PROMPT_PATH = REPO_ROOT / "server" / "p16-challenger-prompt-v2.txt"


class ResponseError(base.ConnectorError):
    """An unusable response whose exact private receipt can still be retained."""

    def __init__(self, reason: str, request: dict, response: dict):
        super().__init__(reason)
        self.request = request
        self.response = response
        self.request_sha256 = canonical_sha256(request)
        self.response_sha256 = canonical_sha256(response)


def prompt(path: Path = PROMPT_PATH) -> str:
    value = path.read_text()
    if not value.strip() or len(value.encode()) > 16_384:
        raise base.ConnectorError("P16 model instructions are invalid")
    return value


def _name(value: object) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > 128
        or not value.isprintable()
    ):
        raise base.ConnectorError("P16 model identifier is invalid")
    return value


def bind_contract(
    health: dict, catalog_entry: dict, *, upstream_model_family: str,
    instructions: str,
) -> dict:
    """Build a binding from observed proxy, catalogue, and provider facts."""
    if not isinstance(instructions, str) or not instructions.strip():
        raise base.ConnectorError("P16 model instructions are required")
    model = _name(catalog_entry.get("id"))
    body = {
        "schema_version": 1,
        "model": model,
        "catalog_entry": catalog_entry,
        "catalog_entry_sha256": canonical_sha256(catalog_entry),
        "upstream_model_family": _name(upstream_model_family),
        "proxy_version": base._proxy_version(health),
        "proxy_source_sha256": base._proxy_source_sha256(health),
        "runtime_sha256": canonical_sha256(base._traecli_runtime(health)),
        "prompt_sha256": canonical_sha256(instructions),
        "toolset_sha256": canonical_sha256([]),
        "identity_scope": "observable_catalog_alias",
        "provider_model_revision": None,
    }
    return {**body, "model_contract_sha256": canonical_sha256(body)}


def _verify(contract: dict, instructions: str) -> None:
    if not isinstance(instructions, str) or not instructions.strip():
        raise base.ConnectorError("P16 model instructions are required")
    body = {key: value for key, value in contract.items()
            if key != "model_contract_sha256"}
    try:
        valid = (
            canonical_sha256(body) == contract.get("model_contract_sha256")
            and contract["schema_version"] == 1
            and contract["model"] == contract["catalog_entry"].get("id")
            and canonical_sha256(contract["catalog_entry"])
            == contract["catalog_entry_sha256"]
            and contract["prompt_sha256"] == canonical_sha256(instructions)
            and contract["toolset_sha256"] == canonical_sha256([])
            and contract["identity_scope"] == "observable_catalog_alias"
            and contract["provider_model_revision"] is None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise base.ConnectorError("P16 registered model binding differs") from exc
    if not valid:
        raise base.ConnectorError("P16 registered model binding differs")
    _name(contract["model"])
    _name(contract["upstream_model_family"])


def request_payload(input_payload: dict, contract: dict, *, instructions: str) -> dict:
    _verify(contract, instructions)
    request = base._request_payload(input_payload, instructions)
    request["model"] = contract["model"]
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > base.MAX_INPUT_BYTES:
        raise base.ConnectorError("P16 model input exceeds the registered transport bound")
    return request


def _transport(contract: dict, request) -> dict:
    health = request(
        "GET", base.PROXY_HEALTH_PATH, None, timeout=base.STATUS_TIMEOUT_SECONDS)
    observed = {
        "proxy_version": base._proxy_version(health),
        "proxy_source_sha256": base._proxy_source_sha256(health),
        "runtime_sha256": canonical_sha256(base._traecli_runtime(health)),
    }
    catalog = request(
        "GET", base.PROXY_MODELS_PATH, None, timeout=base.STATUS_TIMEOUT_SECONDS)
    if catalog.get("object") != "list" or not isinstance(catalog.get("data"), list):
        raise base.ConnectorError("P16 model catalogue is unavailable")
    entries = catalog["data"]
    names = [_name(row.get("id")) for row in entries if isinstance(row, dict)]
    if len(names) != len(entries) or len(set(names)) != len(names):
        raise base.ConnectorError("P16 model catalogue is ambiguous")
    selected = next((row for row in entries if row["id"] == contract["model"]), None)
    if selected != contract["catalog_entry"] or any(
        observed[key] != contract[key] for key in observed
    ):
        raise base.ConnectorError("P16 observable model identity drifted")
    return observed


def _output(response: dict, contract: dict) -> tuple[dict, str]:
    if response.get("status") != "completed" or response.get("model") != contract["model"]:
        raise base.ConnectorError("P16 response model or completion identity differs")
    provider = response.get("provider_metadata")
    if (
        not isinstance(provider, dict)
        or set(provider) != {"model_family", "request_id"}
        or provider["model_family"] != contract["upstream_model_family"]
    ):
        raise base.ConnectorError("P16 provider family differs from registration")
    provider_request_id = _name(provider["request_id"])
    messages = []
    output = response.get("output")
    if not isinstance(output, list) or not output:
        raise base.ConnectorError("P16 response has no output")
    for item in output:
        if not isinstance(item, dict):
            raise base.ConnectorError("P16 response output is malformed")
        if item.get("type") == "reasoning":
            continue
        content = item.get("content")
        if (
            item.get("type") != "message" or item.get("role") != "assistant"
            or not isinstance(content, list) or len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "output_text"
            or not isinstance(content[0].get("text"), str)
        ):
            raise base.ConnectorError("P16 response contains tools or an invalid message")
        messages.append(content[0]["text"])
    if len(messages) != 1:
        raise base.ConnectorError("P16 response must contain one assistant message")
    return loads_object(messages[0]), provider_request_id


def generate(
    input_payload: dict, contract: dict, *, registered_model_contract_sha256: str,
    instructions: str | None = None, request=None,
) -> dict:
    """Call only the bound local proxy, without opening a database connection."""
    selected_prompt = prompt() if instructions is None else instructions
    if contract.get("model_contract_sha256") != registered_model_contract_sha256:
        raise base.ConnectorError("P16 model differs from the registered policy binding")
    transport_request = base._request if request is None else request
    payload = request_payload(input_payload, contract, instructions=selected_prompt)
    before = _transport(contract, transport_request)
    response = transport_request(
        "POST", base.PROXY_RESPONSES_PATH, payload,
        timeout=base.GENERATION_TIMEOUT_SECONDS,
    )
    try:
        after = _transport(contract, transport_request)
        if before != after:
            raise base.ConnectorError("P16 model transport changed during inference")
        response_id = _name(response.get("id"))
        usage = base._usage(response.get("usage"))
        output, provider_request_id = _output(response, contract)
    except (base.ConnectorError, TypeError, ValueError, KeyError) as exc:
        raise ResponseError(str(exc), payload, response) from exc
    return {
        "output": output, "request": payload, "response": response,
        "request_sha256": canonical_sha256(payload),
        "response_sha256": canonical_sha256(response),
        "model_contract_sha256": contract["model_contract_sha256"],
        "response_id": response_id, "provider_request_id": provider_request_id,
        "usage": usage, "identity_scope": "observable_catalog_alias",
        "execution_authority": "none",
    }
