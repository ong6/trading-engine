"""Deterministic, shadow-only recomputation and risk checks for proposal claims."""

from __future__ import annotations

import math
import re
import statistics
from datetime import date

import duckdb

from engine.lib.provenance import canonical_sha256
from sim.execution import PROFILES

VALIDATION_SCHEMA_VERSION = 1
GATE_NAMES = (
    "execution_authority",
    "policy_identity",
    "instrument_eligibility",
    "feature_availability",
    "signal_price",
    "notional_ceiling",
    "capital_concentration",
    "stop_geometry",
    "sell_inventory",
    "liquidity_participation",
)
LIQUIDITY_BARS = 60
VALIDATION_SCOPE = "deterministic_shadow_recomputation_and_risk"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "scope",
        "execution_authority",
        "policy_id",
        "policy_registration_sha256",
        "context_sha256",
        "recomputed_claim",
        "recomputed_claim_sha256",
        "gates",
        "failed_gates",
        "validation_sha256",
    }
)


class ValidationError(ValueError):
    """Server state cannot support deterministic proposal validation."""


def verify(evidence: object) -> dict:
    """Validate stored evidence and its canonical identities without recomputing it."""
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS:
        raise ValidationError("agent proposal validation evidence shape is invalid")
    if (
        evidence["schema_version"] != VALIDATION_SCHEMA_VERSION
        or isinstance(evidence["schema_version"], bool)
        or evidence["status"] not in {"pass", "fail"}
        or evidence["scope"] != VALIDATION_SCOPE
        or evidence["execution_authority"] != "none"
        or not isinstance(evidence["policy_id"], str)
        or not evidence["policy_id"]
    ):
        raise ValidationError("agent proposal validation evidence is invalid")
    for field in (
        "policy_registration_sha256",
        "context_sha256",
        "recomputed_claim_sha256",
        "validation_sha256",
    ):
        if (
            not isinstance(evidence[field], str)
            or _SHA256.fullmatch(evidence[field]) is None
        ):
            raise ValidationError("agent proposal validation identity is invalid")
    claim = evidence["recomputed_claim"]
    if (
        not isinstance(claim, dict)
        or canonical_sha256(claim) != evidence["recomputed_claim_sha256"]
    ):
        raise ValidationError("agent proposal recomputed claim is invalid")
    gates = evidence["gates"]
    if (
        not isinstance(gates, list)
        or len(gates) != len(GATE_NAMES)
        or tuple(gate.get("name") for gate in gates if isinstance(gate, dict))
        != GATE_NAMES
        or any(
            set(gate) != {"name", "status", "detail"}
            or gate["status"] not in {"pass", "fail"}
            or not isinstance(gate["detail"], str)
            or not gate["detail"]
            or len(gate["detail"]) > 512
            or not gate["detail"].isprintable()
            for gate in gates
        )
    ):
        raise ValidationError("agent proposal validation gates are invalid")
    failed = [gate["name"] for gate in gates if gate["status"] == "fail"]
    if evidence["failed_gates"] != failed or evidence["status"] != (
        "fail" if failed else "pass"
    ):
        raise ValidationError("agent proposal validation outcome is inconsistent")
    body = {
        key: value for key, value in evidence.items() if key != "validation_sha256"
    }
    if canonical_sha256(body) != evidence["validation_sha256"]:
        raise ValidationError("agent proposal validation hash does not match evidence")
    return evidence


def verify_binding(
    evidence: object,
    *,
    validation_sha256: object,
    policy_id: object,
    policy_registration_sha256: object,
    context_sha256: object,
    proposal_status: object,
    reasons: object,
) -> dict:
    """Verify stored evidence and bind it to the surrounding proposal row."""
    verified = verify(evidence)
    expected_status = (
        "shadow_accepted" if verified["status"] == "pass" else "shadow_rejected"
    )
    if (
        verified["validation_sha256"] != validation_sha256
        or verified["policy_id"] != policy_id
        or verified["policy_registration_sha256"] != policy_registration_sha256
        or verified["context_sha256"] != context_sha256
        or proposal_status != expected_status
        or reasons != verified["failed_gates"]
    ):
        raise ValidationError("agent proposal validation evidence binding is invalid")
    return verified


def _gate(name: str, status: str, detail: str) -> dict:
    if name not in GATE_NAMES or status not in {"pass", "fail"}:
        raise ValidationError("agent proposal validation gate is invalid")
    return {"name": name, "status": status, "detail": detail}


def _finite(value: object, field: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        raise ValidationError(f"agent proposal {field} is invalid")
    return float(value)


def _liquidity(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
    notional: float,
    maximum_participation: float,
) -> tuple[dict, dict]:
    values = con.execute(
        "SELECT close * volume FROM prices "
        "WHERE ticker = ? AND date <= ? AND close > 0 AND volume > 0 "
        "ORDER BY date DESC LIMIT ?",
        [ticker, market_date, LIQUIDITY_BARS],
    ).fetchall()
    observations = [
        _finite(row[0], "liquidity observation", positive=True) for row in values
    ]
    median_dollar_volume = (
        statistics.median(observations) if len(observations) == LIQUIDITY_BARS else None
    )
    participation = (
        None if median_dollar_volume is None else notional / median_dollar_volume
    )
    passed = (
        participation is not None
        and math.isfinite(participation)
        and participation <= maximum_participation
    )
    detail = (
        f"{len(observations)} of {LIQUIDITY_BARS} required liquidity observations"
        if participation is None
        else f"participation {participation:.6f} vs cap {maximum_participation:.6f}"
    )
    return (
        _gate("liquidity_participation", "pass" if passed else "fail", detail),
        {
            "lookback_sessions": LIQUIDITY_BARS,
            "observed_sessions": len(observations),
            "median_dollar_volume": median_dollar_volume,
            "participation": participation,
            "maximum_participation": maximum_participation,
        },
    )


def evaluate(
    con: duckdb.DuckDBPyConnection,
    proposal: dict,
    context: dict,
) -> dict:
    """Recompute a proposal's bounded shadow quantity and risk evidence."""
    policy = context["policy"]
    instrument = context["instrument"]
    market_date = date.fromisoformat(context["market_date"])
    close = _finite(instrument["close"], "signal close", positive=True)
    notional = _finite(proposal["max_notional"], "notional", positive=True)
    quantity = notional / close
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValidationError("agent proposal recomputed quantity is invalid")

    profile_id = policy["execution_profile_id"]
    try:
        profile = PROFILES[profile_id]
    except KeyError as exc:
        raise ValidationError("agent proposal execution profile is unavailable") from exc
    feature = next(
        (
            item
            for item in context["decision_features"]["assets"]
            if item["ticker"] == proposal["ticker"]
        ),
        None,
    )
    all_features_complete = (
        context["decision_features"]["complete_tickers"]
        == context["decision_features"]["required_tickers"]
    )
    stop = proposal["stop"]
    stop_valid = stop is None or (
        proposal["side"] == "buy" and _finite(stop, "stop", positive=True) < close
    )
    position = con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [policy["reserved_portfolio_id"], proposal["ticker"]],
    ).fetchone()
    held_quantity = 0.0 if position is None else _finite(
        position[0], "reserved inventory", positive=True
    )
    sell_valid = proposal["side"] == "buy" or held_quantity >= quantity
    liquidity_gate, liquidity = _liquidity(
        con,
        proposal["ticker"],
        market_date,
        notional,
        profile.max_participation,
    )
    capital_ceiling = _finite(policy["capital_ceiling"], "capital ceiling", positive=True)
    max_order_notional = _finite(
        policy["max_order_notional"],
        "order-notional ceiling",
        positive=True,
    )

    gates = [
        _gate(
            "execution_authority",
            "pass" if policy["execution_authority"] == "none" else "fail",
            "shadow validation has no execution authority",
        ),
        _gate(
            "policy_identity",
            "pass"
            if proposal["policy_id"] == policy["id"]
            and proposal["policy_registration_sha256"]
            == policy["registration_sha256"]
            else "fail",
            "proposal policy identity matches the server context",
        ),
        _gate(
            "instrument_eligibility",
            "pass"
            if instrument["active"]
            and instrument["liquid"]
            and instrument["etf"]
            and instrument["quarantine"] is None
            else "fail",
            "instrument must be active, liquid, ETF, and not quarantined",
        ),
        _gate(
            "feature_availability",
            "pass" if feature is not None and all_features_complete else "fail",
            (
                "all registered-universe decision features are complete"
                if all_features_complete
                else "registered-universe decision features are incomplete"
            ),
        ),
        _gate(
            "signal_price",
            "pass" if instrument["quote_date"] == context["market_date"] else "fail",
            f"signal close {close:.8g} at {instrument['quote_date']}",
        ),
        _gate(
            "notional_ceiling",
            "pass" if notional <= max_order_notional else "fail",
            f"notional {notional:.8g} vs policy ceiling {max_order_notional:.8g}",
        ),
        _gate(
            "capital_concentration",
            "pass" if notional <= capital_ceiling else "fail",
            f"notional {notional:.8g} vs capital ceiling {capital_ceiling:.8g}",
        ),
        _gate(
            "stop_geometry",
            "pass" if stop_valid else "fail",
            (
                "stop not required by the registered strategy"
                if stop is None
                else f"buy stop {stop:.8g} vs signal close {close:.8g}"
            ),
        ),
        _gate(
            "sell_inventory",
            "pass" if sell_valid else "fail",
            (
                "buy proposal does not require inventory"
                if proposal["side"] == "buy"
                else f"sell quantity {quantity:.8g} vs held {held_quantity:.8g}"
            ),
        ),
        liquidity_gate,
    ]
    if tuple(gate["name"] for gate in gates) != GATE_NAMES:
        raise ValidationError("agent proposal validation gate contract changed")
    passed = all(gate["status"] == "pass" for gate in gates)
    recomputed_claim = {
        "ticker": proposal["ticker"],
        "side": proposal["side"],
        "signal_date": context["market_date"],
        "signal_close": close,
        "maximum_notional": notional,
        "quantity_at_signal_close": quantity,
        "stop": stop,
        "reserved_portfolio_id": policy["reserved_portfolio_id"],
        "held_quantity": held_quantity,
        "execution_profile_id": profile_id,
        "execution_profile_sha256": policy["execution_profile_sha256"],
        "liquidity": liquidity,
    }
    body = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "scope": VALIDATION_SCOPE,
        "execution_authority": "none",
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "context_sha256": context["context_sha256"],
        "recomputed_claim": recomputed_claim,
        "recomputed_claim_sha256": canonical_sha256(recomputed_claim),
        "gates": gates,
        "failed_gates": [
            gate["name"] for gate in gates if gate["status"] == "fail"
        ],
    }
    return verify({**body, "validation_sha256": canonical_sha256(body)})
