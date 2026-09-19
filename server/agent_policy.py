"""Frozen policy registrations for isolated agent-only and hybrid evidence."""

from __future__ import annotations

import math
import re
from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from sim.execution import PROFILES
from sim.strategies.configs import config_by_id

from .file_utils import read_bytes
from .json_utils import loads_object

REGISTRY_SCHEMA_VERSION = 2
REGISTRATION_PATH = REPO_ROOT / "server" / "agent-shadow-registration.json"
MAX_REGISTRATION_BYTES = 32_768
REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "scheduled_policy_id",
        "scheduled_ticker",
        "execution_authority",
        "policies",
    }
)
POLICY_FIELDS = frozenset(
    {
        "id",
        "mode",
        "authority_stage",
        "strategy_id",
        "strategy_config_sha256",
        "source_portfolio_id",
        "reserved_portfolio_id",
        "control_id",
        "execution_profile_id",
        "execution_profile_sha256",
        "cadence",
        "model_role",
        "model_failure_policy",
        "hybrid_behavior",
        "allowed_symbols",
        "capital_ceiling",
        "max_order_notional",
        "attribution",
        "generation_enabled",
        "execution_authority",
    }
)
ATTRIBUTION_FIELDS = frozenset({"strategy_control_id", "algorithm_control_id"})
EXPECTED_POLICY_IDS = frozenset(
    {
        "dual_momentum_agent_shadow_v1",
        "dual_momentum_hybrid_veto_shadow_v1",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PolicyError(ValueError):
    """A policy registry or its live source binding is invalid."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PolicyError(f"agent policy {field} is invalid")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PolicyError(f"agent policy {field} is invalid")
    return value


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PolicyError(f"agent policy {field} is invalid")
    return float(value)


def _validate_mode_and_authority(policy: dict) -> str:
    mode = policy["mode"]
    if mode not in {"agent_only", "hybrid"}:
        raise PolicyError("agent policy mode is invalid")
    if policy["authority_stage"] != "shadow_proposal_only":
        raise PolicyError("agent policy authority stage is invalid")
    if policy["execution_authority"] != "none":
        raise PolicyError("agent policy execution authority is invalid")
    return mode


def _validate_strategy_binding(policy: dict) -> str:
    strategy_id = _identifier(policy["strategy_id"], "strategy identity")
    try:
        strategy = config_by_id(strategy_id)
    except KeyError as exc:
        raise PolicyError("agent policy strategy is unavailable") from exc
    expected_config_sha256 = canonical_sha256(strategy)
    if _hash(policy["strategy_config_sha256"], "strategy config identity") != (
        expected_config_sha256
    ):
        raise PolicyError("agent policy strategy config does not match source")
    if policy["source_portfolio_id"] != strategy_id:
        raise PolicyError("agent policy source portfolio is invalid")
    if policy["cadence"] != strategy.get("cadence"):
        raise PolicyError("agent policy cadence does not match strategy")
    return strategy_id


def _validate_execution_profile(policy: dict) -> None:
    profile_id = _identifier(policy["execution_profile_id"], "execution profile")
    try:
        profile = PROFILES[profile_id]
    except KeyError as exc:
        raise PolicyError("agent policy execution profile is unavailable") from exc
    if _hash(policy["execution_profile_sha256"], "execution profile identity") != (
        canonical_sha256(profile.as_dict())
    ):
        raise PolicyError("agent policy execution profile does not match source")


def _validate_symbols(policy: dict) -> None:
    reserved_id = _identifier(policy["reserved_portfolio_id"], "portfolio reservation")
    if reserved_id == policy["source_portfolio_id"]:
        raise PolicyError("agent policy portfolio reservation is not isolated")
    _identifier(policy["control_id"], "control identity")
    symbols = policy["allowed_symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or len(symbols) > 16
        or symbols != sorted(set(symbols))
        or any(
            not isinstance(symbol, str)
            or not symbol
            or symbol != symbol.upper()
            or _IDENTIFIER.fullmatch(symbol) is None
            for symbol in symbols
        )
    ):
        raise PolicyError("agent policy allowed symbols are invalid")


def _validate_limits(policy: dict) -> None:
    capital_ceiling = _positive_number(policy["capital_ceiling"], "capital ceiling")
    max_order_notional = _positive_number(
        policy["max_order_notional"], "order-notional ceiling"
    )
    if max_order_notional > capital_ceiling:
        raise PolicyError("agent policy order-notional ceiling exceeds capital ceiling")
    if type(policy["generation_enabled"]) is not bool:
        raise PolicyError("agent policy generation flag is invalid")


def _validate_attribution(policy: dict, strategy_id: str) -> None:
    attribution = policy["attribution"]
    if not isinstance(attribution, dict) or set(attribution) != ATTRIBUTION_FIELDS:
        raise PolicyError("agent policy attribution is invalid")
    for field in ATTRIBUTION_FIELDS:
        _identifier(attribution[field], f"attribution {field}")
    if attribution["algorithm_control_id"] != strategy_id:
        raise PolicyError("agent policy algorithm control is invalid")
    try:
        config_by_id(attribution["strategy_control_id"])
    except KeyError as exc:
        raise PolicyError("agent policy strategy control is unavailable") from exc


def _validate_mode_contract(policy: dict, mode: str, policy_id: str) -> None:
    expected = {
        "agent_only": {
            "model_role": "independent_shadow_proposal",
            "model_failure_policy": "deterministic_no_action",
            "hybrid_behavior": "none",
            "generation_enabled": True,
        },
        "hybrid": {
            "model_role": "veto_only",
            "model_failure_policy": "unmodified_algorithm_signal",
            "hybrid_behavior": "veto_only",
            "generation_enabled": True,
        },
    }[mode]
    for field, value in expected.items():
        if policy[field] != value:
            raise PolicyError(f"agent policy {field} is invalid for {mode}")
    if policy_id not in EXPECTED_POLICY_IDS:
        raise PolicyError("agent policy identifier is outside the frozen set")


def _validate_policy(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != POLICY_FIELDS:
        raise PolicyError("agent policy shape is invalid")
    policy = dict(raw)
    policy_id = _identifier(policy["id"], "identifier")
    mode = _validate_mode_and_authority(policy)
    strategy_id = _validate_strategy_binding(policy)
    _validate_execution_profile(policy)
    _validate_symbols(policy)
    _validate_limits(policy)
    _validate_attribution(policy, strategy_id)
    _validate_mode_contract(policy, mode, policy_id)
    return policy


def registry(path: Path = REGISTRATION_PATH) -> dict:
    """Load and validate the complete frozen policy registry."""
    try:
        payload = loads_object(
            read_bytes(
                path,
                max_bytes=MAX_REGISTRATION_BYTES,
                label="agent policy registration",
                allow_symlinked_parents=False,
            )
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PolicyError("agent policy registry is unavailable or invalid") from exc
    if (
        set(payload) != REGISTRY_FIELDS
        or payload["schema_version"] != REGISTRY_SCHEMA_VERSION
        or isinstance(payload["schema_version"], bool)
        or payload["execution_authority"] != "none"
        or not isinstance(payload["policies"], list)
    ):
        raise PolicyError("agent policy registry shape is invalid")
    policies = [_validate_policy(item) for item in payload["policies"]]
    ids = [item["id"] for item in policies]
    if len(ids) != len(set(ids)) or set(ids) != EXPECTED_POLICY_IDS:
        raise PolicyError("agent policy registry does not contain the frozen policy set")
    reserved_ids = [item["reserved_portfolio_id"] for item in policies]
    control_ids = [item["control_id"] for item in policies]
    if len(set(reserved_ids)) != len(reserved_ids) or len(set(control_ids)) != len(
        control_ids
    ):
        raise PolicyError("agent policy isolation identifiers are duplicated")
    scheduled_policy_id = _identifier(
        payload["scheduled_policy_id"], "scheduled policy identity"
    )
    by_id = {item["id"]: item for item in policies}
    if (
        scheduled_policy_id not in by_id
        or by_id[scheduled_policy_id]["mode"] != "agent_only"
        or by_id[scheduled_policy_id]["generation_enabled"] is not True
    ):
        raise PolicyError("scheduled agent policy is invalid")
    ticker = payload["scheduled_ticker"]
    if ticker not in by_id[scheduled_policy_id]["allowed_symbols"]:
        raise PolicyError("scheduled agent ticker is not allowed by its policy")
    return {
        **payload,
        "policies": policies,
        "registry_sha256": canonical_sha256(payload),
    }


def get(policy_id: str, *, path: Path = REGISTRATION_PATH) -> dict:
    """Return one detached registration with its immutable registration hash."""
    _identifier(policy_id, "identifier")
    loaded = registry(path)
    for policy in loaded["policies"]:
        if policy["id"] == policy_id:
            return {
                **policy,
                "registration_sha256": canonical_sha256(policy),
                "registry_sha256": loaded["registry_sha256"],
            }
    raise PolicyError("agent policy is not registered")


def validate_live_registration(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    *,
    allow_reserved_portfolio: bool = False,
) -> None:
    """Bind a policy to the current baseline book without creating its reservation."""
    source = con.execute(
        "SELECT strategy, config, active, initial_cash, execution_profile "
        "FROM portfolios WHERE id = ?",
        [policy["source_portfolio_id"]],
    ).fetchone()
    if source is None or source[2] is not True:
        raise PolicyError("agent policy source portfolio is not active")
    try:
        source_config = loads_object(source[1])
    except (TypeError, ValueError) as exc:
        raise PolicyError("agent policy source portfolio config is invalid") from exc
    if (
        source[0] != config_by_id(policy["strategy_id"])["strategy"]
        or canonical_sha256(source_config) != policy["strategy_config_sha256"]
        or source[4] != policy["execution_profile_id"]
    ):
        raise PolicyError("agent policy source portfolio does not match registration")
    initial_cash = _positive_number(source[3], "source portfolio initial capital")
    if policy["capital_ceiling"] > initial_cash:
        raise PolicyError("agent policy capital ceiling exceeds source capital")
    if not allow_reserved_portfolio and con.execute(
        "SELECT 1 FROM portfolios WHERE id = ?",
        [policy["reserved_portfolio_id"]],
    ).fetchone():
        raise PolicyError("agent policy reserved portfolio already exists")
