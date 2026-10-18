#!/usr/bin/env python3
"""Run a registered job with common locks, timeouts, retries and bounded receipts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from engine.job_contract import JobContractError, JobSpec, LockSpec, load_registry
from engine.lib.settings import LOGS_DIR, REPO_ROOT

RECEIPT_SCHEMA_VERSION = 1
MAX_RECEIPT_BYTES = 1_048_576
TRANSIENT_SPEC_ENV = "ENGINE_JOB_TRANSIENT_SPEC_SHA256"
TRANSIENT_UNIT_ENV = "ENGINE_JOB_TRANSIENT_UNIT"
STATUS_EXIT = {
    "success": 0,
    "noop": 0,
    "degraded": 75,
    "superseded": 75,
    "retryable_failure": 1,
    "terminal_failure": 1,
    "interrupted": 130,
}


class JobRunError(RuntimeError):
    """The runner refused an unsafe or inconsistent invocation."""


class ChildLaunchError(JobRunError):
    def __init__(self, reason: str, pid: int | None = None, identity: str | None = None):
        super().__init__(reason)
        self.pid = pid
        self.identity = identity


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    receipts: tuple[Path, ...]
    final: Mapping[str, Any]


@dataclass(frozen=True)
class CatchUpPlan:
    execute: tuple[datetime, ...]
    skipped: tuple[datetime, ...]
    disposition: str


def require_runner_admission(spec: JobSpec) -> None:
    if not spec.runner_enabled:
        raise JobRunError(f"job is audit-only and not admitted to the runner: {spec.job_id}")
    if spec.schedules or spec.catch_up["mode"] != "none":
        raise JobRunError("scheduled/catch-up execution requires a later migration")
    if spec.runner_mode == "read_only" and (
        spec.authority != "data" or spec.parameters or spec.approval["kind"] != "read_only"
    ):
        raise JobRunError("read-only runner lacks its authority contract")
    if spec.runner_mode == "synthetic" and (
        spec.authority != "data" or spec.owner != "test" or spec.repository != "fixture"
        or spec.approval["kind"] != "synthetic_fixture"
    ):
        raise JobRunError("synthetic runner is not a test fixture")


def _current_systemd_unit(cgroup_text: str | None = None) -> str:
    if cgroup_text is None:
        try:
            cgroup_text = Path("/proc/self/cgroup").read_text()
        except OSError as exc:
            raise JobRunError("internal executor cgroup is unverifiable") from exc
    for line in cgroup_text.splitlines():
        path = line.rsplit(":", 1)[-1]
        for raw in reversed(path.split("/")):
            unit = raw.replace("\\x2d", "-")
            if unit.endswith(".service"):
                return unit
    raise JobRunError("internal executor has no systemd service cgroup")


def _systemctl_properties(unit: str) -> dict[str, str]:
    names = (
        "CPUQuotaPerSecUSec", "MemoryHigh", "MemoryMax", "TasksMax", "RuntimeMaxUSec",
        "KillMode", "Nice", "IOSchedulingClass",
    )
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit,
             *[item for name in names for item in ("--property", name)]],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise JobRunError("could not inspect transient systemd controls") from exc
    if result.returncode != 0:
        raise JobRunError("could not inspect transient systemd controls")
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if set(properties) != set(names):
        raise JobRunError("transient systemd controls are incomplete")
    return properties


def _systemd_seconds(value: str) -> float:
    units = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0}
    parts = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(us|ms|s|min|h)", value)
    if not parts:
        raise JobRunError(f"invalid systemd duration: {value}")
    return sum(float(number) * units[unit] for number, unit in parts)


def verify_transient_executor(
    spec: JobSpec,
    *,
    cgroup_text: str | None = None,
    properties: Mapping[str, str] | None = None,
) -> None:
    if os.environ.get(TRANSIENT_SPEC_ENV) != spec.spec_sha256:
        raise JobRunError("internal executor lacks the registered spec identity")
    if not os.environ.get("INVOCATION_ID"):
        raise JobRunError("internal executor is not a systemd invocation")
    unit = _current_systemd_unit(cgroup_text)
    if unit != os.environ.get(TRANSIENT_UNIT_ENV):
        raise JobRunError("internal executor unit identity does not match its cgroup")
    if not unit.startswith(f"trading-engine-job-{spec.job_id[:40]}-"):
        raise JobRunError("internal executor is outside the registered transient cgroup")
    controls = dict(properties) if properties is not None else _systemctl_properties(unit)
    resources = spec.resources
    expected_io = {"none": 0, "realtime": 1, "best-effort": 2, "idle": 3}
    mismatches = []
    try:
        if abs(_systemd_seconds(controls["CPUQuotaPerSecUSec"])
               - float(resources["cpu_quota_percent"]) / 100.0) > 1e-6:
            mismatches.append("CPUQuota")
        for field, prop in (("memory_high_bytes", "MemoryHigh"),
                            ("memory_max_bytes", "MemoryMax"), ("tasks_max", "TasksMax")):
            if int(controls[prop]) != int(resources[field]):
                mismatches.append(prop)
        if abs(_systemd_seconds(controls["RuntimeMaxUSec"])
               - float(spec.timeout["overall_seconds"])) > 1e-6:
            mismatches.append("RuntimeMaxSec")
        if controls["KillMode"] != "control-group":
            mismatches.append("KillMode")
        if int(controls["Nice"]) != int(resources["nice"]):
            mismatches.append("Nice")
        if int(controls["IOSchedulingClass"]) != expected_io[resources["io_scheduling_class"]]:
            mismatches.append("IOSchedulingClass")
    except (KeyError, TypeError, ValueError) as exc:
        raise JobRunError("transient systemd controls are incomplete") from exc
    if mismatches:
        raise JobRunError("transient systemd control mismatch: " + ", ".join(mismatches))


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JobRunError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise JobRunError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Create one JSON file atomically without replacing an existing receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise JobRunError("job receipt exceeds the size bound")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short receipt write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as exc:
        raise JobRunError(f"job receipt already exists: {path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace only a non-terminal running marker."""
    if not path.name.endswith(".running.json"):
        raise JobRunError("only running markers are mutable")
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise JobRunError("job running marker exceeds the size bound")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short running-marker write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_RECEIPT_BYTES:
            raise JobRunError(f"job receipt is too large: {path}")
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise JobRunError(f"malformed job receipt: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise JobRunError(f"malformed job receipt: {path}")
    return value


def _receipt_directory(
    logs_dir: Path, spec: JobSpec, scheduled_for: datetime, idempotency_key: str
) -> Path:
    slot = scheduled_for.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return logs_dir / "job-runs" / spec.job_id / slot / key_hash


def _job_receipts(logs_dir: Path, spec: JobSpec) -> list[tuple[Path, dict[str, Any]]]:
    root = logs_dir / "job-runs" / spec.job_id
    if not root.exists():
        return []
    rows = []
    for path in sorted(root.glob("**/*.json")):
        if path.name.endswith(".running.json"):
            continue
        rows.append((path, _read_json(path)))
    return rows


def _running_receipts(logs_dir: Path, spec: JobSpec) -> list[tuple[Path, dict[str, Any]]]:
    root = logs_dir / "job-runs" / spec.job_id
    if not root.exists():
        return []
    return [(path, _read_json(path)) for path in sorted(root.glob("**/*.running.json"))]


def _source_identity(repo_root: Path) -> str:
    """Return clean executable source identity or refuse ambiguous bytes."""
    try:
        revision = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise JobRunError("execution source identity is unavailable") from exc
    value = revision.stdout.strip()
    if revision.returncode != 0 or len(value) != 40 or not all(c in "0123456789abcdef" for c in value):
        raise JobRunError("execution source identity is unavailable")
    if status.returncode != 0:
        raise JobRunError("execution source cleanliness is unverifiable")
    if status.stdout.strip():
        raise JobRunError("execution source tree is dirty")
    return value


def _base_receipt(
    spec: JobSpec,
    *,
    scheduled_for: datetime,
    idempotency_key: str,
    operator_idempotency_key: str,
    scope_sha256: str,
    attempt: int,
    run_id: str,
    started: datetime,
    parameter_hash: str,
    source_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "run_id": run_id,
        "job_id": spec.job_id,
        "spec_version": spec.version,
        "spec_sha256": spec.spec_sha256,
        "idempotency_key": idempotency_key,
        "operator_idempotency_key": operator_idempotency_key,
        "idempotency_scope_sha256": scope_sha256,
        "scheduled_for": _iso(scheduled_for),
        "started_at": _iso(started),
        "attempt": attempt,
        "argv": list(spec.argv),
        "parameter_sha256": parameter_hash,
        "source_sha": source_sha,
    }


def _finish_receipt(
    base: Mapping[str, Any],
    *,
    ended: datetime,
    work_status: str,
    reason: str,
    process_exit: int | None,
    locks: Iterable[Mapping[str, Any]],
    child_pid: int | None = None,
    child_process_identity: str | None = None,
    termination: str | None = None,
    forwarded_signal: int | None = None,
    retry_disposition: str = "none",
    catch_up_disposition: str = "not-applicable",
    evidence: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        **base,
        "ended_at": _iso(ended),
        "work_status": work_status,
        "reason": reason,
        "process_exit": process_exit,
        "locks": list(locks),
        "child_pid": child_pid,
        "child_process_identity": child_process_identity,
        "systemd_invocation": os.environ.get("INVOCATION_ID"),
        "termination": termination,
        "forwarded_signal": forwarded_signal,
        "retry_disposition": retry_disposition,
        "catch_up_disposition": catch_up_disposition,
        "counters": {},
        "business_receipts": list(evidence),
    }


def _write_final(running: Path, final: Path, receipt: Mapping[str, Any]) -> None:
    _atomic_json(final, receipt)
    running.unlink(missing_ok=True)


def _lock_path(logs_dir: Path, group: str, name: str) -> Path:
    digest = hashlib.sha256(name.encode()).hexdigest()
    return logs_dir / "job-locks" / group / f"{digest}.lock"


@contextmanager
def _idempotency_lock(logs_dir: Path, key: str):
    path = _lock_path(logs_dir, "idempotency", key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise JobRunError("idempotency key already has a live run") from exc
        yield handle.fileno()


def _acquire_domain_locks(
    logs_dir: Path,
    locks: tuple[LockSpec, ...],
    *,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    deadline: float | None = None,
) -> tuple[ExitStack, list[dict[str, Any]], LockSpec | None, tuple[int, ...]]:
    stack = ExitStack()
    observations = []
    descriptors = []
    try:
        for lock in locks:
            path = _lock_path(logs_dir, "domains", lock.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open("a+"))
            descriptors.append(handle.fileno())
            flag = fcntl.LOCK_SH if lock.mode == "shared" else fcntl.LOCK_EX
            began = monotonic()
            allowed_wait = lock.wait_seconds
            if deadline is not None:
                allowed_wait = min(allowed_wait, max(0.0, deadline - began))
            acquired = False
            while True:
                try:
                    fcntl.flock(handle, flag | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    elapsed = monotonic() - began
                    if elapsed >= allowed_wait:
                        break
                    sleep(min(0.05, allowed_wait - elapsed))
            waited = max(0.0, monotonic() - began)
            observations.append(
                {"domain": lock.name, "mode": lock.mode, "wait_seconds": waited,
                 "acquired": acquired}
            )
            if not acquired:
                return stack, observations, lock, tuple()
        return stack, observations, None, tuple(descriptors)
    except BaseException:
        stack.close()
        raise


def _available_memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def resource_refusal(spec: JobSpec, root: Path) -> str | None:
    resources = spec.resources
    reserve = int(resources["min_free_bytes"]) + int(resources["scratch_bytes"]) + int(
        resources["output_bytes"]
    )
    if shutil.disk_usage(root).free < reserve:
        return "disk-reserve"
    required_memory = int(resources["minimum_available_memory_bytes"])
    available = _available_memory_bytes()
    if required_memory and (available is None or available < required_memory):
        return "memory-reserve"
    return None


def validate_parameters(spec: JobSpec, supplied: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(supplied) - set(spec.parameters)
    if unknown:
        raise JobRunError("unsupported job parameters: " + ", ".join(sorted(unknown)))
    clean: dict[str, Any] = {}
    for name, rule in spec.parameters.items():
        if name not in supplied:
            if rule.get("required", False):
                raise JobRunError(f"missing required job parameter: {name}")
            continue
        value = supplied[name]
        kind = rule["type"]
        try:
            if kind == "date":
                value = date.fromisoformat(str(value)).isoformat()
            elif kind == "integer":
                if isinstance(value, bool):
                    raise ValueError
                value = int(value)
            elif kind == "number":
                if isinstance(value, bool):
                    raise ValueError
                value = float(value)
            elif kind == "boolean":
                if not isinstance(value, bool):
                    raise ValueError
            elif kind == "string":
                value = str(value)
        except (TypeError, ValueError) as exc:
            raise JobRunError(f"invalid {kind} parameter: {name}") from exc
        clean[name] = value
    return clean


def validate_backfill_parameters(
    spec: JobSpec, from_date: str, through: str, reason: str
) -> dict[str, Any]:
    if spec.runner_mode != "synthetic" or spec.approval["kind"] != "synthetic_fixture":
        raise JobRunError("schema v1 backfill is limited to approved synthetic fixtures")
    parameters = validate_parameters(
        spec, {"from": from_date, "through": through, "reason": reason}
    )
    if parameters["from"] > parameters["through"]:
        raise JobRunError("backfill --from must not be after --through")
    if not str(parameters["reason"]).strip():
        raise JobRunError("backfill reason must not be empty")
    return parameters


def backfill_scheduled_for(parameters: Mapping[str, Any]) -> datetime:
    """Use the registered backfill start date as its stable one-off scope slot."""
    try:
        return datetime.fromisoformat(str(parameters["from"])).replace(tzinfo=UTC)
    except (KeyError, ValueError) as exc:
        raise JobRunError("backfill parameters have no valid start date") from exc


def child_argv(spec: JobSpec, repo_root: Path, parameters: Mapping[str, Any]) -> list[str]:
    argv = [
        value.replace("{repo}", str(repo_root)).replace("%h/trading-engine", str(repo_root))
        for value in spec.argv
    ]
    for name in sorted(parameters):
        rule = spec.parameters[name]
        value = parameters[name]
        if rule["type"] == "boolean":
            if value:
                argv.append(str(rule["option"]))
        else:
            argv.extend((str(rule["option"]), str(value)))
    return argv


def completion_probe_argv(
    spec: JobSpec, repo_root: Path, parameters: Mapping[str, Any]
) -> list[str] | None:
    probe = spec.completion_probe
    if probe["kind"] == "receipt":
        return None
    argv = []
    for registered in probe["argv"]:
        value = registered.replace("{repo}", str(repo_root)).replace(
            "%h/trading-engine", str(repo_root)
        )
        for name, parameter in parameters.items():
            value = value.replace(f"{{parameter:{name}}}", str(parameter))
        if "{parameter:" in value:
            raise JobRunError("completion probe references an unavailable parameter")
        argv.append(value)
    return argv


def _process_identity(pid: int) -> str | None:
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        suffix = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        start_ticks = suffix[19]
    except (OSError, IndexError):
        return None
    return f"{boot_id}:{start_ticks}"


def _wait_child(
    argv: list[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout_seconds: float,
    term_grace_seconds: float,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    pass_fds: tuple[int, ...] = (),
    on_started: Callable[[int, str], None] | None = None,
    on_releasing: Callable[[], None] | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[int | None, int, str | None, str | None, int | None]:
    gate_read = gate_write = None
    launch_argv = argv
    inherited = pass_fds
    if on_started is not None:
        gate_read, gate_write = os.pipe()
        launch_argv = [
            sys.executable, str(Path(__file__).resolve()), "_child", str(gate_read),
            "--", *argv,
        ]
        inherited = (*pass_fds, gate_read)
    launch_env = dict(env)
    if on_started is not None:
        launch_env["ENGINE_JOB_TASK_PYTHONPATH"] = launch_env.get("PYTHONPATH", "")
        launch_env["PYTHONPATH"] = os.pathsep.join(
            (str(Path(__file__).resolve().parents[1]), launch_env.get("PYTHONPATH", ""))
        )
    try:
        process = popen(
            launch_argv, cwd=cwd, env=launch_env, start_new_session=True,
            pass_fds=inherited,
        )
    except OSError as exc:
        for descriptor in (gate_read, gate_write):
            if descriptor is not None:
                os.close(descriptor)
        raise ChildLaunchError(f"child-popen-failed:{type(exc).__name__}") from exc
    if gate_read is not None:
        os.close(gate_read)
    process_identity = _process_identity(process.pid)
    if process_identity is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        if gate_write is not None:
            os.close(gate_write)
        raise ChildLaunchError("child-process-identity-unavailable", process.pid)
    if on_started is not None:
        try:
            on_started(process.pid, process_identity)
            if on_releasing is not None:
                on_releasing()
            os.write(gate_write, b"1")
        except BaseException as exc:
            os.close(gate_write)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise ChildLaunchError(
                "child-start-handshake-failed", process.pid, process_identity
            ) from exc
        os.close(gate_write)
    termination = None
    forwarded: int | None = None
    previous_handlers: dict[int, Any] = {}

    def forward(signum, _frame):
        nonlocal forwarded
        forwarded = signum
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
    try:
        try:
            code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            termination = "TERM"
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            grace = term_grace_seconds
            if deadline is not None:
                grace = min(grace, max(0.0, deadline - monotonic()))
            try:
                if grace <= 0:
                    raise subprocess.TimeoutExpired(argv, grace)
                code = process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                termination = "KILL"
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = process.wait()
        return code, process.pid, process_identity, termination, forwarded
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _status_for_exit(
    code: int | None,
    termination: str | None,
    retry_codes: set[int],
    forwarded_signal: int | None = None,
) -> tuple[str, str]:
    if forwarded_signal is not None:
        return "interrupted", f"wrapper-forwarded-signal-{forwarded_signal}"
    if termination is not None:
        return "retryable_failure", f"attempt-timeout-{termination.lower()}"
    if code == 0:
        return "success", "process-exit-0"
    if code == 75:
        return "degraded", "process-exit-75"
    if code is not None and code < 0 and -code == signal.SIGTERM:
        return "interrupted", "process-terminated"
    if code in retry_codes:
        return "retryable_failure", f"retryable-exit-{code}"
    return "terminal_failure", f"terminal-exit-{code}"


def _project(receipt: Mapping[str, Any], ops_dir: Path) -> None:
    from tools import ops_digest

    ops_digest.project_job_receipt(receipt, ops_dir)


def _invocation_keys(
    spec: JobSpec,
    scheduled_for: datetime,
    parameter_hash: str,
    explicit_key: str | None,
) -> tuple[str, str, str]:
    operator_key = explicit_key or spec.idempotency_template.format(
        job_id=spec.job_id, version=spec.version, scheduled_for=_iso(scheduled_for)
    )
    if (not operator_key or len(operator_key) > 400
            or any(value in operator_key for value in ("\0", "\n"))):
        raise JobRunError("invalid idempotency key")
    scope_sha256 = _hash_json(
        {
            "job_id": spec.job_id,
            "spec_version": spec.version,
            "spec_sha256": spec.spec_sha256,
            "scheduled_for": _iso(scheduled_for),
            "parameter_sha256": parameter_hash,
        }
    )
    canonical_key = f"{operator_key}:{scope_sha256}"
    return operator_key, canonical_key, scope_sha256


def _receipt_operator_key(receipt: Mapping[str, Any]) -> object:
    return receipt.get("operator_idempotency_key", receipt.get("idempotency_key"))


def execute_job(
    spec: JobSpec,
    *,
    scheduled_for: datetime,
    parameters: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
    repo_root: Path = REPO_ROOT,
    logs_dir: Path = LOGS_DIR,
    ops_dir: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    projector: Callable[[Mapping[str, Any], Path], None] = _project,
    executor_verified: bool = False,
    source_identity: Callable[[Path], str] = _source_identity,
) -> RunResult:
    """Execute one admitted one-off inside a verified transient resource boundary."""
    require_runner_admission(spec)
    if not executor_verified:
        raise JobRunError("direct execution lacks the registered transient resource boundary")
    if not spec.enabled:
        raise JobRunError(f"job is disabled: {spec.job_id}")
    scheduled_for = scheduled_for.astimezone(UTC)
    clean_parameters = validate_parameters(spec, parameters or {})
    parameter_hash = _hash_json(clean_parameters)
    operator_key, key, scope_sha256 = _invocation_keys(
        spec, scheduled_for, parameter_hash, idempotency_key
    )
    destination = _receipt_directory(logs_dir, spec, scheduled_for, key)
    ops_dir = ops_dir or logs_dir / "ops"
    receipt_paths: list[Path] = []
    source_sha = source_identity(repo_root)
    run_id = str(uuid.uuid4())

    def base_receipt(attempt: int, started: datetime) -> dict[str, Any]:
        return _base_receipt(
            spec, scheduled_for=scheduled_for, idempotency_key=key,
            operator_idempotency_key=operator_key, scope_sha256=scope_sha256,
            attempt=attempt, run_id=run_id, started=started,
            parameter_hash=parameter_hash, source_sha=source_sha,
        )

    def publish(receipt: Mapping[str, Any], final: Path, running: Path | None = None) -> None:
        if running is None:
            _atomic_json(final, receipt)
        else:
            _write_final(running, final, receipt)
        receipt_paths.append(final)
        try:
            projector(receipt, ops_dir)
        except Exception as exc:  # observability never changes the job result
            print(
                f"[run-job] receipt projection unavailable: {type(exc).__name__}",
                file=sys.stderr,
            )

    def finish(result: Mapping[str, Any]) -> RunResult:
        prune_receipts(
            logs_dir / "job-runs" / spec.job_id, spec.retention_days, now()
        )
        return RunResult(STATUS_EXIT[str(result["work_status"])], tuple(receipt_paths), result)

    lock_identity = f"{spec.job_id}:{operator_key}"
    with _idempotency_lock(logs_dir, lock_identity) as idempotency_fd:
        completed = _job_receipts(logs_dir, spec)
        running = _running_receipts(logs_dir, spec)
        same_operator = [
            (path, row) for path, row in completed + running
            if _receipt_operator_key(row) == operator_key
        ]
        mismatch = next(
            ((path, row) for path, row in same_operator
             if row.get("idempotency_scope_sha256") != scope_sha256),
            None,
        )
        if mismatch is not None:
            began = now()
            mismatch_attempt = max(
                (row.get("attempt", 0) for _path, row in completed + running
                 if row.get("idempotency_key") == key),
                default=0,
            ) + 1
            receipt = _finish_receipt(
                base_receipt(mismatch_attempt, began), ended=now(),
                work_status="terminal_failure",
                reason="idempotency-scope-mismatch", process_exit=None, locks=[],
                evidence=[str(mismatch[0])],
            )
            publish(receipt, destination / f"{mismatch_attempt}.json")
            return finish(receipt)
        attempts = [row.get("attempt", 0) for _path, row in completed + running
                    if row.get("idempotency_key") == key]
        for stale_path, stale in running:
            if stale.get("idempotency_key") != key:
                continue
            child_pid = stale.get("child_pid")
            child_identity = stale.get("child_process_identity")
            launch_state = stale.get("launch_state")
            has_identity = (
                not isinstance(child_pid, bool) and isinstance(child_pid, int)
                and isinstance(child_identity, str) and bool(child_identity)
            )
            if not has_identity and launch_state != "preparing":
                raise JobRunError("running attempt lacks a verifiable child identity")
            if has_identity and _process_identity(child_pid) == child_identity:
                raise JobRunError("prior child for idempotency key is still running")
            stale_reason = (
                "prelaunch-interrupted" if launch_state in {"preparing", "identity-published"}
                else "stale-interrupted-attempt"
            )
            final_path = stale_path.with_name(stale_path.name.replace(".running.json", ".json"))
            receipt = _finish_receipt(
                stale, ended=now(), work_status="interrupted", reason=stale_reason,
                process_exit=None, locks=stale.get("locks", []), retry_disposition="resume",
            )
            publish(receipt, final_path, stale_path)
            completed.append((final_path, receipt))
        prior_success = next(
            ((path, row) for path, row in reversed(completed)
             if row.get("idempotency_key") == key and row.get("work_status") in {"success", "noop"}),
            None,
        )
        next_attempt = max(attempts, default=0) + 1
        if prior_success:
            began = now()
            final = destination / f"{next_attempt}.json"
            receipt = _finish_receipt(
                base_receipt(next_attempt, began), ended=now(), work_status="noop",
                reason="completed-idempotency-key",
                process_exit=None, locks=[], evidence=[str(prior_success[0])],
            )
            publish(receipt, final)
            return finish(receipt)

        started_monotonic = monotonic()
        deadline_at = started_monotonic + min(
            float(spec.timeout["overall_seconds"]),
            float(spec.retry["deadline_seconds"]),
        )
        maximum = int(spec.retry["max_attempts"])
        retry_codes = set(spec.retry["exit_codes"])
        argv = child_argv(spec, repo_root, clean_parameters)
        probe_argv = completion_probe_argv(spec, repo_root, clean_parameters)
        final_receipt: Mapping[str, Any] = {}
        for retry_index in range(maximum):
            attempt = next_attempt + retry_index
            attempt_started = now()
            base = base_receipt(attempt, attempt_started)
            final_path = destination / f"{attempt}.json"
            if monotonic() >= deadline_at:
                receipt = _finish_receipt(
                    base, ended=now(), work_status="retryable_failure",
                    reason="overall-deadline-exhausted", process_exit=None, locks=[],
                    retry_disposition="exhausted",
                )
                publish(receipt, final_path)
                return finish(receipt)
            preflight = resource_refusal(spec, logs_dir)
            stack, lock_rows, refused, domain_fds = _acquire_domain_locks(
                logs_dir, spec.locks, monotonic=monotonic, sleep=sleep,
                deadline=deadline_at,
            )
            with stack:
                status: str
                reason: str
                process_exit: int | None = None
                child_pid: int | None = None
                child_identity: str | None = None
                termination: str | None = None
                forwarded: int | None = None
                if monotonic() >= deadline_at:
                    status = "retryable_failure"
                    reason = "overall-deadline-exhausted"
                elif preflight or refused:
                    status = refused.timeout_status if refused else "retryable_failure"
                    reason = (
                        f"lock-timeout:{refused.name}"
                        if refused else f"resource-refusal:{preflight}"
                    )
                else:
                    pass_fds = (idempotency_fd, *domain_fds)
                    common_env = {
                        **os.environ,
                        "PYTHONPATH": str(repo_root),
                        "ENGINE_JOB_RUN_ID": run_id,
                        "ENGINE_JOB_SCHEDULED_FOR": _iso(scheduled_for),
                        "ENGINE_JOB_IDEMPOTENCY_KEY": key,
                        "ENGINE_JOB_PARAMETERS_SHA256": parameter_hash,
                    }
                    if probe_argv is not None:
                        probe_remaining = deadline_at - monotonic()
                        if probe_remaining <= 0:
                            receipt = _finish_receipt(
                                base, ended=now(), work_status="retryable_failure",
                                reason="overall-deadline-exhausted", process_exit=None,
                                locks=lock_rows, retry_disposition="exhausted",
                            )
                            publish(receipt, final_path)
                            return finish(receipt)
                        try:
                            (probe_exit, probe_pid, probe_identity, probe_termination,
                             probe_forwarded) = _wait_child(
                                probe_argv, env=common_env, cwd=repo_root,
                                timeout_seconds=min(
                                    float(spec.completion_probe["timeout_seconds"]),
                                    probe_remaining,
                                ),
                                term_grace_seconds=float(spec.timeout["term_grace_seconds"]),
                                popen=popen, pass_fds=pass_fds, deadline=deadline_at,
                                monotonic=monotonic,
                            )
                        except ChildLaunchError as exc:
                            receipt = _finish_receipt(
                                base, ended=now(), work_status="terminal_failure",
                                reason=f"completion-probe-{exc}", process_exit=None,
                                locks=lock_rows, child_pid=exc.pid,
                                child_process_identity=exc.identity,
                            )
                            publish(receipt, final_path)
                            return finish(receipt)
                        if probe_termination is not None and monotonic() >= deadline_at:
                            receipt = _finish_receipt(
                                base, ended=now(), work_status="retryable_failure",
                                reason="overall-deadline-exhausted", process_exit=probe_exit,
                                locks=lock_rows, child_pid=probe_pid,
                                child_process_identity=probe_identity,
                                termination=probe_termination, retry_disposition="exhausted",
                            )
                            publish(receipt, final_path)
                            return finish(receipt)
                        if probe_exit == 0 and probe_termination is None and probe_forwarded is None:
                            receipt = _finish_receipt(
                                base, ended=now(), work_status="noop",
                                reason="task-completion-probe", process_exit=0,
                                locks=lock_rows, child_pid=probe_pid,
                                child_process_identity=probe_identity,
                                evidence=["registered-completion-probe"],
                            )
                            publish(receipt, final_path)
                            return finish(receipt)
                        if probe_exit != 1 or probe_termination is not None or probe_forwarded is not None:
                            receipt = _finish_receipt(
                                base, ended=now(), work_status="terminal_failure",
                                reason="completion-probe-failed", process_exit=probe_exit,
                                locks=lock_rows, child_pid=probe_pid,
                                child_process_identity=probe_identity,
                                termination=probe_termination, forwarded_signal=probe_forwarded,
                            )
                            publish(receipt, final_path)
                            return finish(receipt)
                    running_path = destination / f"{attempt}.running.json"
                    running_row = {
                        **base, "state": "running", "wrapper_pid": os.getpid(),
                        "locks": lock_rows, "launch_state": "preparing",
                    }
                    _atomic_json(running_path, running_row)

                    def child_started(
                        pid: int,
                        identity: str,
                        marker: Path = running_path,
                        row: dict[str, Any] = running_row,
                    ) -> None:
                        row.update(
                            {"child_pid": pid, "child_process_identity": identity,
                             "launch_state": "identity-published"}
                        )
                        _replace_json(marker, row)

                    def child_releasing(
                        marker: Path = running_path,
                        row: dict[str, Any] = running_row,
                    ) -> None:
                        row["launch_state"] = "released"
                        _replace_json(marker, row)

                    child_env = {
                        **common_env,
                        "ENGINE_JOB_RECEIPT_PATH": str(final_path),
                    }
                    remaining = deadline_at - monotonic()
                    if remaining <= 0:
                        receipt = _finish_receipt(
                            base, ended=now(), work_status="retryable_failure",
                            reason="overall-deadline-exhausted", process_exit=None,
                            locks=lock_rows, retry_disposition="exhausted",
                        )
                        publish(receipt, final_path, running_path)
                        return finish(receipt)
                    try:
                        (process_exit, child_pid, child_identity, termination,
                         forwarded) = _wait_child(
                            argv, env=child_env, cwd=repo_root,
                            timeout_seconds=max(
                                0.001, min(float(spec.timeout["attempt_seconds"]), remaining)
                            ),
                            term_grace_seconds=float(spec.timeout["term_grace_seconds"]),
                            popen=popen, pass_fds=pass_fds, on_started=child_started,
                            on_releasing=child_releasing, deadline=deadline_at,
                            monotonic=monotonic,
                        )
                    except ChildLaunchError as exc:
                        child_pid, child_identity = exc.pid, exc.identity
                        status, reason = "terminal_failure", str(exc)
                    else:
                        status, reason = _status_for_exit(
                            process_exit, termination, retry_codes, forwarded
                        )
            delay = (
                float(spec.retry["backoff_seconds"][retry_index])
                if retry_index + 1 < maximum else 0.0
            )
            elapsed = monotonic() - started_monotonic
            retry = (
                status == "retryable_failure"
                and retry_index + 1 < maximum
                and elapsed + delay < float(spec.retry["deadline_seconds"])
                and elapsed + delay < float(spec.timeout["overall_seconds"])
            )
            disposition = "retry" if retry else (
                "exhausted" if status == "retryable_failure" else "none"
            )
            receipt = _finish_receipt(
                base, ended=now(), work_status=status, reason=reason,
                process_exit=process_exit, locks=lock_rows, child_pid=child_pid,
                child_process_identity=child_identity, termination=termination,
                forwarded_signal=forwarded, retry_disposition=disposition,
            )
            running_path = destination / f"{attempt}.running.json"
            publish(receipt, final_path, running_path if running_path.exists() else None)
            final_receipt = receipt
            if not retry:
                break
            sleep(delay)
        return finish(final_receipt)


def plan_catch_up(spec: JobSpec, missed: Iterable[datetime], now: datetime) -> CatchUpPlan:
    slots = sorted({slot.astimezone(UTC) for slot in missed})
    policy = spec.catch_up
    age = timedelta(seconds=float(policy["max_age_seconds"]))
    eligible = [slot for slot in slots if slot <= now and now - slot <= age]
    mode = policy["mode"]
    if mode == "none":
        chosen: list[datetime] = []
    elif mode == "latest":
        chosen = eligible[-1:]
    else:
        chosen = eligible[-int(policy["max_count"]):]
    skipped = [slot for slot in slots if slot not in chosen]
    disposition = "none" if not chosen else ("latest" if mode == "latest" else "all_bounded")
    return CatchUpPlan(tuple(chosen), tuple(skipped), disposition)


def prune_receipts(root: Path, retention_days: int, now: datetime) -> int:
    cutoff = now.astimezone(UTC) - timedelta(days=retention_days)
    removed = 0
    if not root.exists():
        return removed
    for path in sorted(root.glob("*/*/*.json")):
        if path.name.endswith(".running.json"):
            continue
        try:
            ended = parse_timestamp(str(_read_json(path)["ended_at"]))
        except (JobRunError, KeyError):
            continue
        if ended < cutoff:
            path.unlink()
            removed += 1
    for directory in sorted((p for p in root.glob("*/*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
            directory.parent.rmdir()
        except OSError:
            pass
    return removed


def transient_properties(spec: JobSpec) -> list[str]:
    resources = spec.resources
    properties = [
        f"TimeoutStartSec={float(spec.timeout['overall_seconds']):g}s",
        f"RuntimeMaxSec={float(spec.timeout['overall_seconds']):g}s",
        "KillMode=control-group",
        f"Nice={int(resources['nice'])}",
        f"IOSchedulingClass={resources['io_scheduling_class']}",
    ]
    cpu_quota = float(resources["cpu_quota_percent"])
    if cpu_quota:
        properties.append(f"CPUQuota={cpu_quota:g}%")
    for field, name in (("memory_high_bytes", "MemoryHigh"),
                        ("memory_max_bytes", "MemoryMax"), ("tasks_max", "TasksMax")):
        value = resources[field]
        if value:
            properties.append(f"{name}={value}")
    return properties


def _transient_command(
    spec: JobSpec,
    *,
    repo_root: Path,
    logs_dir: Path,
    scheduled_for: datetime,
    idempotency_key: str | None,
    parameters: Mapping[str, Any],
) -> list[str]:
    require_runner_admission(spec)
    identity_source = idempotency_key or (
        f"{spec.job_id}:{spec.version}:{_iso(scheduled_for)}:{_hash_json(parameters)}"
    )
    identity = hashlib.sha256(identity_source.encode()).hexdigest()[:12]
    unit = f"trading-engine-job-{spec.job_id[:40]}-{identity}"
    command = [
        "systemd-run", "--user", "--wait", "--collect", "--quiet",
        f"--unit={unit}",
        f"--working-directory={repo_root}", f"--setenv=PYTHONPATH={repo_root}",
        f"--setenv={TRANSIENT_SPEC_ENV}={spec.spec_sha256}",
        f"--setenv={TRANSIENT_UNIT_ENV}={unit}.service",
    ]
    command.extend(f"--property={value}" for value in transient_properties(spec))
    command.extend(
        [
            sys.executable, "-m", "tools.run_job", "_execute", spec.job_id,
            "--repo-root", str(repo_root), "--logs-dir", str(logs_dir),
            "--scheduled-for", _iso(scheduled_for),
            "--parameters-json", json.dumps(parameters, sort_keys=True, separators=(",", ":")),
        ]
    )
    if idempotency_key is not None:
        command.extend(("--idempotency-key", idempotency_key))
    return command


def _backfill_command(
    spec: JobSpec,
    *,
    repo_root: Path,
    logs_dir: Path,
    scheduled_for: datetime,
    idempotency_key: str,
    parameters: Mapping[str, Any],
) -> list[str]:
    return _transient_command(
        spec, repo_root=repo_root, logs_dir=logs_dir, scheduled_for=scheduled_for,
        idempotency_key=idempotency_key, parameters=parameters,
    )


def backfill_plan(
    spec: JobSpec,
    *,
    scheduled_for: datetime,
    idempotency_key: str,
    parameters: Mapping[str, Any],
    logs_dir: Path,
) -> dict[str, Any]:
    parameter_hash = _hash_json(parameters)
    operator_key, canonical_key, scope_sha256 = _invocation_keys(
        spec, scheduled_for, parameter_hash, idempotency_key
    )
    existing = [
        {
            "attempt": row.get("attempt"),
            "status": row.get("work_status"),
            "scope_matches": row.get("idempotency_scope_sha256") == scope_sha256,
            "receipt": str(path),
        }
        for path, row in _job_receipts(logs_dir, spec)
        if _receipt_operator_key(row) == operator_key
    ]
    return {
        "action": "backfill-plan",
        "job_id": spec.job_id,
        "authority": spec.authority,
        "runner_mode": spec.runner_mode,
        "scheduled_for": _iso(scheduled_for),
        "idempotency_key": operator_key,
        "canonical_key_sha256": hashlib.sha256(canonical_key.encode()).hexdigest(),
        "scope_sha256": scope_sha256,
        "parameter_sha256": parameter_hash,
        "locks": [
            {"name": lock.name, "mode": lock.mode, "wait_seconds": lock.wait_seconds}
            for lock in spec.locks
        ],
        "resources": dict(spec.resources),
        "existing_completion_state": existing,
        "requires_apply": True,
    }


def _child_exec(start_fd: int, argv: list[str]) -> int:
    """Wait for the durable parent marker, then replace this launcher with the task."""
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        return 125
    try:
        admitted = os.read(start_fd, 1)
    finally:
        os.close(start_fd)
    if admitted != b"1":
        return 125
    environment = dict(os.environ)
    environment.pop("ENGINE_JOB_START_FD", None)
    task_pythonpath = environment.pop("ENGINE_JOB_TASK_PYTHONPATH", None)
    if task_pythonpath is not None:
        environment["PYTHONPATH"] = task_pythonpath
    try:
        os.execvpe(argv[0], argv, environment)
    except OSError as exc:
        print(f"run_job child exec failed: {type(exc).__name__}", file=sys.stderr)
        return 127


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("job_id")
    run.add_argument("--scheduled-for", required=True)
    run.add_argument("--idempotency-key")
    run.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    run.add_argument("--logs-dir", type=Path, default=LOGS_DIR)

    backfill = commands.add_parser("backfill")
    backfill.add_argument("job_id")
    backfill.add_argument("--from", dest="from_date", required=True)
    backfill.add_argument("--through", required=True)
    backfill.add_argument("--reason", required=True)
    backfill.add_argument("--idempotency-key", required=True)
    backfill.add_argument("--apply", action="store_true")
    backfill.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    backfill.add_argument("--logs-dir", type=Path, default=LOGS_DIR)

    execute = commands.add_parser("_execute", help=argparse.SUPPRESS)
    execute.add_argument("job_id")
    execute.add_argument("--scheduled-for", required=True)
    execute.add_argument("--idempotency-key")
    execute.add_argument("--parameters-json", default="{}")
    execute.add_argument("--repo-root", type=Path, required=True)
    execute.add_argument("--logs-dir", type=Path, required=True)
    child = commands.add_parser("_child", help=argparse.SUPPRESS)
    child.add_argument("start_fd", type=int)
    child.add_argument("argv", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "_child":
        return _child_exec(args.start_fd, args.argv)
    repo_root = args.repo_root.resolve()
    try:
        registry = load_registry(repo_root)
        spec = registry.get(args.job_id)
        require_runner_admission(spec)
        if args.command == "backfill":
            parameters = validate_backfill_parameters(
                spec, args.from_date, args.through, args.reason
            )
            scheduled_for = backfill_scheduled_for(parameters)
            plan = backfill_plan(
                spec, scheduled_for=scheduled_for, idempotency_key=args.idempotency_key,
                parameters=parameters, logs_dir=args.logs_dir.resolve(),
            )
            print(json.dumps(plan, sort_keys=True))
            if not args.apply:
                return 0
            command = _backfill_command(
                spec, repo_root=repo_root, logs_dir=args.logs_dir.resolve(),
                scheduled_for=scheduled_for, idempotency_key=args.idempotency_key,
                parameters=parameters,
            )
            result = subprocess.run(command, cwd=repo_root, env={**os.environ, "PYTHONPATH": str(repo_root)},
                                    check=False)
            return result.returncode
        if args.command == "run":
            scheduled_for = parse_timestamp(args.scheduled_for)
            command = _transient_command(
                spec, repo_root=repo_root, logs_dir=args.logs_dir.resolve(),
                scheduled_for=scheduled_for, idempotency_key=args.idempotency_key, parameters={},
            )
            result = subprocess.run(
                command, cwd=repo_root, env={**os.environ, "PYTHONPATH": str(repo_root)},
                check=False,
            )
            return result.returncode
        verify_transient_executor(spec)
        parameters = json.loads(args.parameters_json)
        if not isinstance(parameters, dict):
            raise JobRunError("parameters JSON must be an object")
        result = execute_job(
            spec, scheduled_for=parse_timestamp(args.scheduled_for), parameters=parameters,
            idempotency_key=args.idempotency_key, repo_root=repo_root,
            logs_dir=args.logs_dir.resolve(),
            executor_verified=True,
        )
        print(json.dumps(result.final, sort_keys=True))
        return result.exit_code
    except (JobContractError, JobRunError, json.JSONDecodeError) as exc:
        print(f"run_job: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
