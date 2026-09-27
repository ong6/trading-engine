"""Frozen, tool-free W3 filing model transport."""
from __future__ import annotations

import hashlib
import inspect
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine import p16_filing_parser
from engine.lib.provenance import canonical_sha256
from server import agent_model_client as base

POLICY_ID = "p16-filings-v1"
ROLE = "p16_filing"
PROMPT_VERSION = "p16-filing-prompt-v1"
VALIDATOR_VERSION = "p16-filing-validator-v1"
PROMPT_PATH = Path(__file__).with_name(f"{PROMPT_VERSION}.txt")
PROMPT_BYTES = PROMPT_PATH.read_bytes()
PROMPT = PROMPT_BYTES.decode("utf-8")
MAX_OUTPUT_TOKENS = 3_000
GENERATION_TIMEOUT_SECONDS = 120.0
OUTPUT_FIELDS = (
    "ticker", "p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10",
    "action", "thesis", "invalidation", "evidence_ids", "event_kind",
    "guidance_change", "headline_surprise", "one_off_items", "tone",
)
OUTPUT_SCHEMA = {
    "schema_version": 1, "envelope": ("schema_version", "assessments"),
    "assessment": OUTPUT_FIELDS, "assessment_count": 1,
    "action": ("ignore", "watch", "buy_candidate", "exit"),
    "event_kind": tuple(p16_filing_parser.EVENTS.values()),
    "guidance_change": ("raised", "maintained", "lowered", "withdrawn", "none"),
    "headline_surprise": ("beat", "inline", "miss", "unknown"),
    "numeric_bounds": {"p_outperform_5": (0, 1), "expected_excess_bp": (-10_000, 10_000),
                       "tone": (-1, 1)},
    "text": {"thesis_words": (1, 60), "invalidation_chars": (1, 1_000)},
    "evidence_ids": {"minimum": 1, "unique": True, "source": "input_allowlist"},
    "one_off_items": {"maximum": 8,
                      "fields": ("description", "amount", "currency", "evidence_id"),
                      "description_chars": (1, 160), "amount": "finite_or_null",
                      "currency": "uppercase_iso3_or_null", "evidence": "input_allowlist"},
    "conditions": {"exit": "held_only", "nonpositive_h5": ("ignore", "exit_if_held"),
                   "surprise": "comparable_consensus_or_cited_company_statement"},
    "unknown_fields": "reject",
}
INPUT_FIELDS = {
    "schema_version", "policy_id", "call_id", "model_identity", "accession", "cik",
    "issuer_id", "security_id", "ticker", "information_cutoff_at", "current_decision_time",
    "expected_entry_rule", "source_bundle_sha256", "evidence", "allowed_evidence_ids",
    "allowed_event_kinds", "text_completeness", "previous_guidance", "consensus",
    "comparable_consensus", "company_consensus_statement", "company_consensus_evidence_ids",
    "company_consensus_context", "held", "tradeable", "reason", "underlying_p15_gates",
    "prior_market_context",
}
EVIDENCE_FIELDS = {
    "evidence_id", "text", "source_sha256", "filename", "parser_version",
    "normalized_sha256", "start", "end", "published_at", "available_at", "ingested_at",
}
ENTRY_RULE = "next_session_open_after_response_new_york_date"
ISO_CURRENCIES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD
BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD
EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD
IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD
MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR
PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD
SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW
UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF XPD XPF XPT XSU XTS
XUA XXX YER ZAR ZMW ZWG
""".split())

@dataclass(frozen=True, slots=True)
class FilingConnectorResult(base.ConnectorResult):
    """Model result extended with the exact successful proxy response bytes hash."""
    raw_response_sha256: str
def _validator_sha256() -> str:
    source = inspect.getsource(validate_input) + inspect.getsource(validate_output)
    return hashlib.sha256(source.encode()).hexdigest()

def identity() -> dict:
    """Return the static, registration-ready W3 model boundary identity."""
    return {
        "policy_id": POLICY_ID,
        "role": ROLE,
        "prompt_version": PROMPT_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "validator_sha256": _validator_sha256(),
        "prompt_bytes_sha256": hashlib.sha256(PROMPT_BYTES).hexdigest(),
        "instructions_sha256": canonical_sha256(PROMPT),
        "output_schema_sha256": canonical_sha256(OUTPUT_SCHEMA),
        "parser_version": p16_filing_parser.PARSER_VERSION,
        "model": base.MODEL,
        "model_version": base.MODEL_VERSION,
        "upstream_model_family": base.UPSTREAM_MODEL_FAMILY,
        "model_catalog_entry_sha256": base.MODEL_CATALOG_ENTRY_SHA256,
        "required_proxy_version": base.REQUIRED_PROXY_VERSION,
        "required_proxy_source_sha256": base.REQUIRED_PROXY_SOURCE_SHA256,
        "required_traecli_runtime": base.REQUIRED_TRAECLI_RUNTIME,
        "toolset_sha256": canonical_sha256([]),
        "tools": "none",
        "execution_authority": "none",
    }

def request_payload(input_payload: dict) -> dict:
    """Build the exact bounded request sent to the local proxy."""
    validate_input(input_payload)
    request = base._request_payload(input_payload, PROMPT)
    request["max_output_tokens"] = MAX_OUTPUT_TOKENS
    return request

def _utc(value, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise base.ConnectorError(f"filing {field} is invalid") from exc
    if parsed.utcoffset() is None:
        raise base.ConnectorError(f"filing {field} requires a timezone")
    return parsed.astimezone(timezone.utc)

def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)

def _string_list(value, *, allow_empty: bool = False) -> bool:
    return (isinstance(value, list) and (allow_empty or bool(value))
            and all(isinstance(item, str) and bool(item) for item in value)
            and len(value) == len(set(value)))

def validate_input(value: object) -> dict:
    """Validate the exact W3 envelope before any transport call."""
    if not isinstance(value, dict) or set(value) != INPUT_FIELDS:
        raise base.ConnectorError("filing input envelope is invalid")
    if (value["schema_version"] != 1 or value["policy_id"] != POLICY_ID
            or value["model_identity"] != identity() or value["expected_entry_rule"] != ENTRY_RULE
            or value["tradeable"] is not False or value["reason"] != "shadow_only"
            or not isinstance(value["held"], bool)):
        raise base.ConnectorError("filing input policy identity is invalid")
    try:
        cik = p16_filing_parser.cik_id(value["cik"])
    except (TypeError, ValueError) as exc:
        raise base.ConnectorError("filing input source identity is invalid") from exc
    if (not isinstance(value["accession"], str)
            or re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", value["accession"]) is None
            or cik != value["cik"]
            or any(not isinstance(value[field], str) or not value[field]
                   for field in ("call_id", "issuer_id", "security_id", "ticker"))
            or not isinstance(value["source_bundle_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["source_bundle_sha256"]) is None):
        raise base.ConnectorError("filing input source identity is invalid")
    cutoff = _utc(value["information_cutoff_at"], "information cutoff")
    if _utc(value["current_decision_time"], "decision time") != cutoff:
        raise base.ConnectorError("filing decision time differs from its cutoff")
    evidence, allowed = value["evidence"], value["allowed_evidence_ids"]
    if not isinstance(evidence, list) or not evidence or not _string_list(allowed):
        raise base.ConnectorError("filing evidence is invalid")
    evidence_ids, text_size = set(), 0
    for item in evidence:
        if not isinstance(item, dict) or set(item) != EVIDENCE_FIELDS:
            raise base.ConnectorError("filing evidence is invalid")
        evidence_id, text = item["evidence_id"], item["text"]
        if (not isinstance(evidence_id, str) or re.fullmatch(r"[0-9a-f]{64}", evidence_id) is None
                or evidence_id in evidence_ids or not isinstance(text, str)
                or any(not isinstance(item[field], str)
                       or re.fullmatch(r"[0-9a-f]{64}", item[field]) is None
                       for field in ("source_sha256", "normalized_sha256"))
                or item["parser_version"] != p16_filing_parser.PARSER_VERSION
                or any(isinstance(item[field], bool) or not isinstance(item[field], int)
                       for field in ("start", "end"))
                or not 0 <= item["start"] <= item["end"]):
            raise base.ConnectorError("filing evidence is invalid")
        evidence_ids.add(evidence_id)
        text_size += len(text)
        published, available, ingested = (
            _utc(item[field], field) for field in ("published_at", "available_at", "ingested_at")
        )
        if not published <= available <= ingested <= cutoff:
            raise base.ConnectorError("filing evidence is after the cutoff")
    if text_size > 40_000 or not set(allowed) <= evidence_ids:
        raise base.ConnectorError("filing evidence exceeds its bound or allowlist")
    kinds = value["allowed_event_kinds"]
    if (not _string_list(kinds)
            or not set(kinds) <= set(p16_filing_parser.EVENTS.values())):
        raise base.ConnectorError("filing event kinds are invalid")
    company_ids = value["company_consensus_evidence_ids"]
    consensus = value["consensus"]
    consensus_ids = consensus.get("evidence_ids", []) if isinstance(consensus, dict) else []
    consensus_valid = (isinstance(consensus, dict)
                       and {"metric", "period", "basis", "evidence_ids"} <= set(consensus)
                       and _string_list(consensus_ids)
                       and set(consensus_ids) <= set(allowed))
    company_context = value["company_consensus_context"]
    if (not _string_list(company_ids, allow_empty=True) or not set(company_ids) <= set(allowed)
            or value["company_consensus_statement"] is not bool(company_ids)
            or not isinstance(value["comparable_consensus"], bool)
            or value["comparable_consensus"] != consensus_valid
            or (value["company_consensus_statement"] and (
                not isinstance(company_context, dict)
                or set(company_context) != {"metric", "period", "basis"}))
            or (not value["company_consensus_statement"] and company_context is not None)
            or (value["previous_guidance"] is not None
                and not isinstance(value["previous_guidance"], (dict, list)))
            or not isinstance(value["text_completeness"], dict)
            or value["text_completeness"].get("status") not in {"full", "primary_only", "truncated"}
            or not isinstance(value["underlying_p15_gates"], list)
            or not isinstance(value["prior_market_context"], dict)):
        raise base.ConnectorError("filing comparison context is invalid")
    forbidden = {"label", "outcome", "realized_return", "forward_return", "post_decision_return"}
    if forbidden & set(_keys(value)):
        raise base.ConnectorError("filing input contains post-decision data")
    return value

def _number(value, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise base.ModelOutputError("filing numeric output is invalid")
    if not low <= value <= high:
        raise base.ModelOutputError("filing numeric output is outside bounds")
    return float(value)

def validate_output(output: object, input_payload: dict) -> dict:
    """Reject any assessment outside the exact W3 schema and evidence boundary."""
    validate_input(input_payload)
    if (not isinstance(output, dict) or set(output) != {"schema_version", "assessments"}
            or output.get("schema_version") != 1 or not isinstance(output["assessments"], list)
            or len(output["assessments"]) != 1):
        raise base.ModelOutputError("filing output envelope is invalid")
    item = output["assessments"][0]
    if not isinstance(item, dict) or set(item) != set(OUTPUT_FIELDS) or item["ticker"] != input_payload["ticker"]:
        raise base.ModelOutputError("filing assessment shape is invalid")
    probability = _number(item["p_outperform_5"], 0, 1)
    excess5 = _number(item["expected_excess_bp_5"], -10_000, 10_000)
    excess10 = _number(item["expected_excess_bp_10"], -10_000, 10_000)
    tone = _number(item["tone"], -1, 1)
    action = item["action"]
    if (action not in OUTPUT_SCHEMA["action"] or (action == "exit" and not input_payload["held"])
            or (excess5 <= 0 and action not in {"ignore", "exit"})):
        raise base.ModelOutputError("filing action is invalid")
    if (not isinstance(item["thesis"], str) or not item["thesis"].strip()
            or len(item["thesis"].split()) > 60 or not isinstance(item["invalidation"], str)
            or not item["invalidation"].strip() or len(item["invalidation"]) > 1_000):
        raise base.ModelOutputError("filing assessment text is invalid")
    evidence_ids, allowed = item["evidence_ids"], set(input_payload["allowed_evidence_ids"])
    if not _string_list(evidence_ids) or not set(evidence_ids) <= allowed:
        raise base.ModelOutputError("filing output evidence is invalid")
    if (item["event_kind"] not in input_payload["allowed_event_kinds"]
            or item["guidance_change"] not in OUTPUT_SCHEMA["guidance_change"]
            or item["headline_surprise"] not in OUTPUT_SCHEMA["headline_surprise"]):
        raise base.ModelOutputError("filing output category is invalid")
    if item["headline_surprise"] != "unknown":
        company_route = (input_payload["company_consensus_statement"]
                         and bool(set(evidence_ids) & set(input_payload["company_consensus_evidence_ids"])))
        if not input_payload["comparable_consensus"] and not company_route:
            raise base.ModelOutputError("filing surprise evidence is unavailable")
    one_offs = item["one_off_items"]
    if not isinstance(one_offs, list) or len(one_offs) > 8:
        raise base.ModelOutputError("filing one-off items are invalid")
    for one_off in one_offs:
        if (not isinstance(one_off, dict)
                or set(one_off) != {"description", "amount", "currency", "evidence_id"}
                or not isinstance(one_off["description"], str) or not one_off["description"].strip()
                or len(one_off["description"]) > 160
                or not isinstance(one_off["evidence_id"], str)
                or one_off["evidence_id"] not in allowed
                or (one_off["currency"] is not None
                    and (not isinstance(one_off["currency"], str)
                         or one_off["currency"] not in ISO_CURRENCIES))):
            raise base.ModelOutputError("filing one-off item is invalid")
        if one_off["amount"] is not None:
            _number(one_off["amount"], -math.inf, math.inf)
    normalized = {**item, "p_outperform_5": probability,
                  "expected_excess_bp_5": excess5, "expected_excess_bp_10": excess10,
                  "tone": tone}
    return {"schema_version": 1, "assessments": [normalized]}

class _CapturedResponse:
    def __init__(self, response, hashes: list[str]):
        self.response, self.hashes = response, hashes
    def __getattr__(self, name):
        return getattr(self.response, name)
    def read(self, size):
        raw = self.response.read(size)
        self.hashes.append(hashlib.sha256(raw).hexdigest())
        return raw
class _DeadlineConnection:
    def __init__(self, connection, remaining: float, hashes: list[str] | None = None):
        self.connection = connection
        self.hashes = [] if hashes is None else hashes
        self.capture = False
        self.timer = threading.Timer(remaining, connection.close)
        self.timer.daemon = True
        self.timer.start()
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def request(self, method, path, **kwargs):
        self.capture = path == base.PROXY_RESPONSES_PATH
        return self.connection.request(method, path, **kwargs)
    def getresponse(self):
        response = self.connection.getresponse()
        return _CapturedResponse(response, self.hashes) if self.capture else response
    def close(self):
        self.timer.cancel()
        self.connection.close()
def generate_json(input_payload: dict, *, connection_factory=base._connection) -> FilingConnectorResult:
    """Generate one filing assessment with a 120-second connection ceiling."""
    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    response_hashes: list[str] = []
    def bounded_factory(host: str, port: int, timeout: float):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise base.ConnectorError("filing generation deadline exceeded")
        connection = connection_factory(host, port, min(timeout, remaining))
        return _DeadlineConnection(connection, remaining, response_hashes)
    try:
        result = base._generate_json(
            input_payload, payload_builder=request_payload, connection_factory=bounded_factory,
        )
    except base.ConnectorError as exc:
        exc.raw_response_sha256 = response_hashes[-1] if response_hashes else None
        raise
    if time.monotonic() > deadline:
        raise base.ConnectorError("filing generation deadline exceeded")
    if len(response_hashes) != 1:
        raise base.ConnectorError("filing response provenance is unavailable")
    try:
        output = validate_output(result.output, input_payload)
    except base.ModelOutputError as exc:
        exc.response_id, exc.request_sha256 = result.response_id, result.request_sha256
        exc.response_sha256, exc.raw_response_sha256 = None, response_hashes[0]
        exc.usage = result.usage
        raise
    return FilingConnectorResult(
        **{field: getattr(result, field) for field in result.__dataclass_fields__ if field != "output"},
        output=output, raw_response_sha256=response_hashes[0],
    )
