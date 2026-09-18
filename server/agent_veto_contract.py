"""Closed model-output contract for a hybrid veto-only decision."""

from __future__ import annotations

import re

from .agent_contract import EVIDENCE_ID_MAX_CHARS, MAX_EVIDENCE_IDS
from .agent_decision_contract import NO_ACTION_REASON_MAX_CHARS

SCHEMA_VERSION = 1
FIELDS = frozenset(
    {
        "schema_version",
        "decision",
        "candidate_sha256",
        "reason",
        "evidence_ids",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class VetoDecisionError(ValueError):
    """The model returned an object outside the frozen veto-only contract."""


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise VetoDecisionError(f"{field} is invalid")
    return value


def normalize(
    body: object,
    *,
    expected_candidate_sha256: str,
    allowed_evidence_ids: frozenset[str],
) -> dict:
    """Accept only allow/veto over the exact deterministic candidate."""
    if not isinstance(body, dict):
        raise VetoDecisionError("hybrid veto decision must be an object")
    unknown = sorted(set(body) - FIELDS)
    missing = sorted(FIELDS - set(body))
    if unknown:
        raise VetoDecisionError(f"unknown veto field(s): {', '.join(unknown)}")
    if missing:
        raise VetoDecisionError(f"missing veto field(s): {', '.join(missing)}")
    if body.get("schema_version") != SCHEMA_VERSION or isinstance(
        body.get("schema_version"), bool
    ):
        raise VetoDecisionError(f"schema_version must be {SCHEMA_VERSION}")
    decision = body.get("decision")
    if decision not in {"allow", "veto"}:
        raise VetoDecisionError("decision must be allow or veto")
    candidate_sha256 = body.get("candidate_sha256")
    if (
        not isinstance(candidate_sha256, str)
        or _SHA256.fullmatch(candidate_sha256) is None
        or candidate_sha256 != expected_candidate_sha256
    ):
        raise VetoDecisionError("candidate_sha256 does not match the frozen candidate")
    evidence_ids = body.get("evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or len(evidence_ids) > MAX_EVIDENCE_IDS
    ):
        raise VetoDecisionError("evidence_ids must be a nonempty bounded array")
    normalized_evidence = []
    for evidence_id in evidence_ids:
        value = _text(evidence_id, "evidence_id", EVIDENCE_ID_MAX_CHARS)
        if value not in allowed_evidence_ids:
            raise VetoDecisionError(
                "evidence_ids contains a reference outside the context allowlist"
            )
        normalized_evidence.append(value)
    if len(set(normalized_evidence)) != len(normalized_evidence):
        raise VetoDecisionError("evidence_ids must not contain duplicates")
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "candidate_sha256": candidate_sha256,
        "reason": _text(body.get("reason"), "reason", NO_ACTION_REASON_MAX_CHARS),
        "evidence_ids": normalized_evidence,
    }


def output_schema() -> dict:
    """Return the fixed contract for future hybrid model requests."""
    return {
        "schema_version": SCHEMA_VERSION,
        "fields": {
            "schema_version": SCHEMA_VERSION,
            "decision": "allow or veto",
            "candidate_sha256": "exact supplied deterministic candidate SHA-256",
            "reason": "nonempty printable string",
            "evidence_ids": "nonempty unique subset of allowed_evidence_ids",
        },
        "additional_fields": False,
        "order_creation": False,
        "order_mutation": False,
        "sell_veto": False,
    }
