"""Fail-closed control and entry point for supervised shadow generation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib.resources import advisory_file_lock, write_text_atomic
from engine.lib.settings import REPO_ROOT

from . import agent_context, agent_policy, agent_shadow_runner, agent_shadow_store
from .file_utils import read_bytes
from .json_utils import loads_object
from .status_validation import iso_timestamp

REGISTRATION_PATH = REPO_ROOT / "server" / "agent-shadow-registration.json"
CONTROL_PATH = REPO_ROOT / "store" / "agent-shadow-control.json"
CONTROL_LOCK_PATH = REPO_ROOT / "store" / "agent-shadow-control.json.lock"
MAX_CONTROL_BYTES = 4_096
MAX_FAILURE_REASON_CHARS = 512
SCHEDULE = {
    "systemd_timer": "trading-engine-agent-shadow.timer",
    "on_calendar": "Tue..Sat *-*-* 01:30:00 UTC",
    "persistent": True,
}
RETRY_POLICY = {
    "decision_regeneration": False,
    "service_restart_on_failure": True,
    "restart_delay_seconds": 300,
    "maximum_starts": 3,
    "interval_seconds": 1_800,
    "worker_timeout_seconds": 300,
}
CONTROL_FIELDS = frozenset(
    {"schema_version", "enabled", "registration_sha256", "reason", "updated_at"}
)


class ScheduleError(RuntimeError):
    """The supervised shadow schedule is not safe to run."""


def _read_object(path: Path, *, label: str, max_bytes: int) -> dict:
    try:
        return loads_object(
            read_bytes(
                path,
                max_bytes=max_bytes,
                label=label,
                allow_symlinked_parents=False,
            )
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ScheduleError(f"{label} is unavailable or invalid") from exc


def registration(path: Path = REGISTRATION_PATH) -> tuple[dict, str]:
    try:
        loaded = agent_policy.registry(path)
        policy = agent_policy.get(loaded["scheduled_policy_id"], path=path)
    except agent_policy.PolicyError as exc:
        raise ScheduleError(str(exc)) from exc
    value = {
        "schema_version": loaded["schema_version"],
        "policy_id": policy["id"],
        "mode": policy["mode"],
        "strategy_id": policy["strategy_id"],
        "ticker": loaded["scheduled_ticker"],
        "control_id": policy["control_id"],
        "execution_authority": "none",
    }
    return value, loaded["registry_sha256"]


def control_status(
    *,
    registration_path: Path = REGISTRATION_PATH,
    control_path: Path = CONTROL_PATH,
) -> dict:
    registered, registration_sha256 = registration(registration_path)
    control_updated_at = None
    try:
        control = _read_object(
            control_path,
            label="agent shadow control",
            max_bytes=MAX_CONTROL_BYTES,
        )
    except ScheduleError:
        return {
            "schema_version": 1,
            "enabled": False,
            "reason": "control_missing_or_invalid",
            "registration": registered,
            "registration_sha256": registration_sha256,
            "control_updated_at": None,
            "schedule": SCHEDULE,
            "retry_policy": RETRY_POLICY,
            "execution_authority": "none",
        }
    try:
        parsed_updated_at = iso_timestamp(control["updated_at"]).astimezone(timezone.utc)
        valid = (
            set(control) == CONTROL_FIELDS
            and control["schema_version"] == 1
            and type(control["enabled"]) is bool
            and isinstance(control["reason"], str)
            and bool(control["reason"].strip())
            and control["reason"] == control["reason"].strip()
            and len(control["reason"]) <= 256
            and control["reason"].isprintable()
            and control["registration_sha256"] == registration_sha256
            and parsed_updated_at <= datetime.now(timezone.utc)
        )
        if valid:
            control_updated_at = parsed_updated_at.isoformat().replace("+00:00", "Z")
    except (KeyError, TypeError, ValueError):
        valid = False
    return {
        "schema_version": 1,
        "enabled": bool(valid and control["enabled"]),
        "reason": control["reason"] if valid else "control_missing_or_invalid",
        "registration": registered,
        "registration_sha256": registration_sha256,
        "control_updated_at": control_updated_at,
        "schedule": SCHEDULE,
        "retry_policy": RETRY_POLICY,
        "execution_authority": "none",
    }


def set_control(
    enabled: bool,
    reason: str,
    *,
    registration_path: Path = REGISTRATION_PATH,
    control_path: Path = CONTROL_PATH,
    now: datetime | None = None,
) -> dict:
    if (
        type(enabled) is not bool
        or not isinstance(reason, str)
        or not reason.strip()
        or reason != reason.strip()
        or len(reason) > 256
        or not reason.isprintable()
    ):
        raise ScheduleError("agent shadow control reason is invalid")
    _registered, registration_sha256 = registration(registration_path)
    changed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    control = {
        "schema_version": 1,
        "enabled": enabled,
        "registration_sha256": registration_sha256,
        "reason": reason,
        "updated_at": changed_at.isoformat().replace("+00:00", "Z"),
    }
    lock_path = control_path.with_name(f"{control_path.name}.lock")
    with advisory_file_lock(lock_path):
        write_text_atomic(
            control_path,
            json.dumps(control, indent=2, sort_keys=True) + "\n",
        )
    return control_status(
        registration_path=registration_path,
        control_path=control_path,
    )


def run_scheduled(
    *,
    registration_path: Path = REGISTRATION_PATH,
    control_path: Path = CONTROL_PATH,
) -> dict:
    status = control_status(
        registration_path=registration_path,
        control_path=control_path,
    )
    if not status["enabled"]:
        return {
            "status": "disabled",
            "reason": status["reason"],
            "execution_authority": "none",
        }
    registered = status["registration"]
    return agent_shadow_runner.run(
        registered["strategy_id"],
        registered["ticker"],
        mode=registered["mode"],
        policy_id=registered["policy_id"],
        policy_path=registration_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("status")
    enable = commands.add_parser("enable")
    enable.add_argument("--reason", required=True)
    disable = commands.add_parser("disable")
    disable.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_scheduled()
        elif args.command == "status":
            result = control_status()
        else:
            result = set_control(args.command == "enable", args.reason)
    except (
        ScheduleError,
        agent_shadow_runner.ShadowRunError,
        agent_context.ContextError,
        agent_shadow_store.IdentifierSpaceExhausted,
        duckdb.Error,
        OSError,
    ) as exc:
        reason = str(exc).strip() or type(exc).__name__
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": reason[:MAX_FAILURE_REASON_CHARS],
                    "execution_authority": "none",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
