"""Versioned job registrations and audit-only legacy schedule rendering.

The registry is deliberately not an executor.  Revision 1 compares its rendered cron and
systemd sources with the legacy configuration while those sources remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from engine.lib.settings import REPO_ROOT

SCHEMA_VERSION = 1
DEFAULT_MANIFEST = Path("ops/jobs.toml")
MANIFEST_ENV = "ENGINE_JOB_MANIFESTS"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
_LOCK_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{1,127}$")
_WORK_STATUSES = frozenset(
    {
        "success",
        "noop",
        "degraded",
        "retryable_failure",
        "terminal_failure",
        "interrupted",
        "superseded",
    }
)
_SHELL_TOKENS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "2>&1"})


class JobContractError(ValueError):
    """A manifest does not satisfy the public job contract."""


@dataclass(frozen=True)
class LockSpec:
    name: str
    mode: str
    wait_seconds: float
    timeout_status: str


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    owner: str
    repository: str
    version: int
    argv: tuple[str, ...]
    parameters: Mapping[str, Mapping[str, Any]]
    authority: str
    enabled: bool
    runner_enabled: bool
    runner_mode: str
    schedules: tuple[str, ...]
    calendar: str
    locks: tuple[LockSpec, ...]
    idempotency_template: str
    completion_probe: Mapping[str, Any]
    approval: Mapping[str, Any]
    retention_days: int
    timeout: Mapping[str, Any]
    retry: Mapping[str, Any]
    alert: Mapping[str, Any]
    catch_up: Mapping[str, Any]
    resources: Mapping[str, Any]
    legacy: Mapping[str, Any]
    raw: Mapping[str, Any]
    spec_sha256: str
    manifest: Path

    @property
    def service_unit(self) -> str | None:
        service = self.legacy.get("service", {})
        value = service.get("unit") if isinstance(service, Mapping) else None
        return str(value) if value else None

    @property
    def timer_unit(self) -> str | None:
        timer = self.legacy.get("timer", {})
        value = timer.get("unit") if isinstance(timer, Mapping) else None
        return str(value) if value else None


@dataclass(frozen=True)
class JobRegistry:
    jobs: tuple[JobSpec, ...]
    manifests: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_id", MappingProxyType({j.job_id: j for j in self.jobs}))

    def get(self, job_id: str) -> JobSpec:
        try:
            return self._by_id[job_id]
        except KeyError as exc:
            raise JobContractError(f"unknown job id: {job_id}") from exc

    @property
    def by_id(self) -> Mapping[str, JobSpec]:
        return self._by_id


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {key: value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise JobContractError(f"{label} must be a table")
    return value


def _positive_number(value: Any, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobContractError(f"{label} must be numeric")
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise JobContractError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}")
    return float(value)


def _validate_argv(argv: Any, label: str) -> tuple[str, ...]:
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise JobContractError(f"{label} must be a non-empty argv array")
    values = tuple(argv)
    if Path(values[0]).name in {"sh", "bash", "zsh"} or "-c" in values[:3]:
        raise JobContractError(f"{label} may not invoke a command shell")
    for value in values:
        if any(mark in value for mark in ("\0", "\n", "`", "$(")) or value in _SHELL_TOKENS:
            raise JobContractError(f"{label} contains unsafe shell syntax")
    return values


def _validate_calendar(value: str, label: str) -> None:
    if not value or " " not in value:
        raise JobContractError(f"{label} is not a systemd calendar expression")
    zone = value.rsplit(" ", 1)[-1]
    if zone != "UTC" and "/" not in zone:
        raise JobContractError(f"{label} must name an explicit timezone")


def _validate_parameters(value: Any, label: str) -> Mapping[str, Mapping[str, Any]]:
    table = _mapping(value, label)
    result: dict[str, Mapping[str, Any]] = {}
    for name, raw in table.items():
        if not _ID_RE.fullmatch(name):
            raise JobContractError(f"{label} has invalid parameter {name!r}")
        item = _mapping(raw, f"{label}.{name}")
        if item.get("type") not in {"string", "date", "integer", "number", "boolean"}:
            raise JobContractError(f"{label}.{name} has unsupported type")
        option = item.get("option")
        if not isinstance(option, str) or not option.startswith("--"):
            raise JobContractError(f"{label}.{name} needs a long option")
        result[name] = MappingProxyType(dict(item))
    return MappingProxyType(result)


def _validate_job(raw: Mapping[str, Any], manifest: Path, retention_limit: int) -> JobSpec:
    job_id = raw.get("job_id")
    if not isinstance(job_id, str) or not _ID_RE.fullmatch(job_id):
        raise JobContractError(f"{manifest}: invalid job_id {job_id!r}")
    label = f"{manifest}:{job_id}"
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise JobContractError(f"{label}: version must be a positive integer")
    argv = _validate_argv(raw.get("argv"), f"{label}.argv")
    schedules_raw = raw.get("schedules", [])
    if not isinstance(schedules_raw, list) or not all(isinstance(v, str) for v in schedules_raw):
        raise JobContractError(f"{label}.schedules must be an array")
    schedules = tuple(schedules_raw)
    for index, value in enumerate(schedules):
        _validate_calendar(value, f"{label}.schedules[{index}]")
    calendar = raw.get("calendar")
    if calendar not in {"always", "UTC-weekday", "XNYS"}:
        raise JobContractError(f"{label}: unsupported calendar")

    lock_rows = raw.get("locks", [])
    if not isinstance(lock_rows, list):
        raise JobContractError(f"{label}.locks must be an array")
    locks = []
    for index, item_raw in enumerate(lock_rows):
        item = _mapping(item_raw, f"{label}.locks[{index}]")
        name = item.get("name")
        if isinstance(name, str):
            name = name.replace("{job_id}", job_id)
        if not isinstance(name, str) or not _LOCK_RE.fullmatch(name):
            raise JobContractError(f"{label}: invalid lock domain")
        mode = item.get("mode")
        if mode not in {"shared", "exclusive"}:
            raise JobContractError(f"{label}:{name}: invalid lock mode")
        wait = _positive_number(item.get("wait_seconds"), f"{label}:{name}.wait_seconds",
                                allow_zero=True)
        outcome = item.get("timeout_status")
        if outcome not in {"retryable_failure", "terminal_failure", "superseded"}:
            raise JobContractError(f"{label}:{name}: invalid timeout status")
        locks.append(LockSpec(name, mode, wait, outcome))
    if [item.name for item in locks] != sorted(item.name for item in locks):
        raise JobContractError(f"{label}: lock domains must be ordered by name")
    if f"job:{job_id}" not in {item.name for item in locks}:
        raise JobContractError(f"{label}: missing job lock")

    idempotency = _mapping(raw.get("idempotency"), f"{label}.idempotency")
    template = idempotency.get("template")
    if not isinstance(template, str) or "{job_id}" not in template or "{version}" not in template:
        raise JobContractError(f"{label}: incomplete idempotency template")
    completion_probe = _mapping(
        idempotency.get("completion_probe"), f"{label}.idempotency.completion_probe"
    )
    if completion_probe.get("kind") not in {"receipt", "command"}:
        raise JobContractError(f"{label}: invalid completion probe")
    if completion_probe["kind"] == "command":
        _validate_argv(completion_probe.get("argv"), f"{label}.idempotency.completion_probe.argv")
        _positive_number(
            completion_probe.get("timeout_seconds"),
            f"{label}.idempotency.completion_probe.timeout_seconds",
        )
    run_record = _mapping(raw.get("run_record"), f"{label}.run_record")
    retention = run_record.get("retention_days")
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= retention_limit:
        raise JobContractError(f"{label}: run receipt retention must be bounded")

    timeout = _mapping(raw.get("timeout"), f"{label}.timeout")
    attempt_seconds = _positive_number(timeout.get("attempt_seconds"),
                                       f"{label}.timeout.attempt_seconds")
    _positive_number(timeout.get("term_grace_seconds"), f"{label}.timeout.term_grace_seconds")
    overall_seconds = _positive_number(timeout.get("overall_seconds"),
                                       f"{label}.timeout.overall_seconds")
    if overall_seconds < attempt_seconds:
        raise JobContractError(f"{label}: overall timeout is shorter than one attempt")

    retry = _mapping(raw.get("retry"), f"{label}.retry")
    maximum = retry.get("max_attempts")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 10:
        raise JobContractError(f"{label}: retry attempts must be bounded")
    exits = retry.get("exit_codes", [])
    backoff = retry.get("backoff_seconds", [])
    if not isinstance(exits, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in exits):
        raise JobContractError(f"{label}: invalid retry exit codes")
    if not isinstance(backoff, list) or len(backoff) != maximum - 1:
        raise JobContractError(f"{label}: retry backoff must cover every additional attempt")
    for value in backoff:
        _positive_number(value, f"{label}.retry.backoff_seconds", allow_zero=True)
    deadline = _positive_number(retry.get("deadline_seconds"), f"{label}.retry.deadline_seconds")
    if deadline > overall_seconds:
        raise JobContractError(f"{label}: retry deadline exceeds overall timeout")

    alert = _mapping(raw.get("alert"), f"{label}.alert")
    if alert.get("severity") not in {"ignore", "WARN", "FAIL"}:
        raise JobContractError(f"{label}: invalid alert severity")
    alert_grace = _positive_number(
        alert.get("grace_seconds"), f"{label}.alert.grace_seconds", allow_zero=True
    )
    if alert_grace > retention * 86400:
        raise JobContractError(f"{label}: alert grace exceeds receipt retention")
    catch_up = _mapping(raw.get("catch_up"), f"{label}.catch_up")
    mode = catch_up.get("mode")
    count = catch_up.get("max_count")
    age = catch_up.get("max_age_seconds")
    if mode not in {"none", "latest", "all_bounded"} or isinstance(count, bool) or not isinstance(count, int):
        raise JobContractError(f"{label}: invalid catch-up policy")
    _positive_number(age, f"{label}.catch_up.max_age_seconds", allow_zero=True)
    if (mode == "none" and (count or age)) or (mode == "latest" and count != 1) or (
        mode == "all_bounded" and count < 1
    ):
        raise JobContractError(f"{label}: catch-up bounds do not match mode")

    resources = _mapping(raw.get("resources"), f"{label}.resources")
    for field in (
        "memory_high_bytes", "memory_max_bytes", "minimum_available_memory_bytes",
        "scratch_bytes", "output_bytes", "min_free_bytes", "tasks_max",
    ):
        value = resources.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise JobContractError(f"{label}.resources.{field} must be a nonnegative integer")
    cpu_quota = _positive_number(
        resources.get("cpu_quota_percent"), f"{label}.resources.cpu_quota_percent",
        allow_zero=True,
    )
    if cpu_quota > 10_000:
        raise JobContractError(f"{label}.resources.cpu_quota_percent exceeds 10000")
    nice = resources.get("nice")
    if isinstance(nice, bool) or not isinstance(nice, int) or not -20 <= nice <= 19:
        raise JobContractError(f"{label}.resources.nice must be an integer from -20 through 19")
    if resources.get("io_scheduling_class") not in {"none", "realtime", "best-effort", "idle"}:
        raise JobContractError(f"{label}.resources.io_scheduling_class is invalid")
    memory_high = resources["memory_high_bytes"]
    memory_max = resources["memory_max_bytes"]
    if memory_high and memory_max and memory_high > memory_max:
        raise JobContractError(f"{label}: memory_high_bytes exceeds memory_max_bytes")
    owner = raw.get("owner")
    repository = raw.get("repository")
    authority = raw.get("authority")
    if not all(isinstance(value, str) and value for value in (owner, repository)):
        raise JobContractError(f"{label}: owner and repository are required")
    if authority not in {"data", "shadow", "paper"}:
        raise JobContractError(f"{label}: invalid authority")
    parameters = _validate_parameters(raw.get("parameters", {}), f"{label}.parameters")
    approval = _mapping(raw.get("approval"), f"{label}.approval")
    if approval.get("kind") not in {"none", "read_only", "synthetic_fixture"}:
        raise JobContractError(f"{label}: invalid approval contract")
    if (resources.get("memory_max_bytes") == 0 or resources.get("cpu_quota_percent") == 0
            or resources.get("tasks_max") == 0):
        reason = resources.get("unlimited_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise JobContractError(f"{label}: unlimited resources need a reason")

    runner_enabled = raw.get("runner_enabled")
    runner_mode = raw.get("runner_mode")
    if not isinstance(runner_enabled, bool):
        raise JobContractError(f"{label}: runner_enabled must be boolean")
    if runner_enabled:
        if runner_mode not in {"read_only", "synthetic"}:
            raise JobContractError(f"{label}: admitted runner needs a bounded runner_mode")
        if runner_mode == "synthetic" and completion_probe["kind"] != "command":
            raise JobContractError(f"{label}: mutable synthetic runner needs a task-side probe")
        if any(
            resources[field] <= 0
            for field in ("cpu_quota_percent", "memory_high_bytes", "memory_max_bytes", "tasks_max")
        ):
            raise JobContractError(f"{label}: admitted runner needs explicit resource limits")
        if runner_mode == "read_only" and (
            authority != "data" or parameters or approval["kind"] != "read_only"
        ):
            raise JobContractError(f"{label}: read-only runner lacks its authority contract")
        if runner_mode == "synthetic" and (
            authority != "data" or owner != "test" or repository != "fixture"
            or approval["kind"] != "synthetic_fixture"
        ):
            raise JobContractError(f"{label}: synthetic runner is not a test fixture")
        if schedules or catch_up["mode"] != "none":
            raise JobContractError(
                f"{label}: scheduled/catch-up runner execution requires a later migration"
            )
    elif runner_mode != "blocked":
        raise JobContractError(f"{label}: blocked runner must use runner_mode=blocked")

    legacy = _mapping(raw.get("legacy", {}), f"{label}.legacy")
    service = legacy.get("service")
    timer = legacy.get("timer")
    cron = legacy.get("cron")
    if sum(value is not None for value in (timer, cron)) > 1:
        raise JobContractError(f"{label}: job cannot have both legacy timer and cron")
    if timer is not None:
        if service is None:
            raise JobContractError(f"{label}: timer needs a service")
        timer_table = _mapping(timer, f"{label}.legacy.timer")
        if tuple(timer_table.get("on_calendar", [])) != schedules:
            raise JobContractError(f"{label}: timer calendars differ from registration")
        service_table = _mapping(service, f"{label}.legacy.service")
        commands = service_table.get("exec_start", [])
        primary = service_table.get("primary_index", 0)
        if not isinstance(commands, list) or not isinstance(primary, int) or not 0 <= primary < len(commands):
            raise JobContractError(f"{label}: invalid legacy ExecStart list")
        command = _mapping(commands[primary], f"{label}.legacy.service.exec_start")
        if _validate_argv(command.get("argv"), f"{label}.legacy.service.exec_start") != argv:
            raise JobContractError(f"{label}: primary legacy command differs from argv")
    elif cron is not None:
        cron_table = _mapping(cron, f"{label}.legacy.cron")
        fields = cron_table.get("fields")
        if not isinstance(fields, str) or len(fields.split()) != 5:
            raise JobContractError(f"{label}: invalid legacy cron fields")
    elif schedules:
        raise JobContractError(f"{label}: scheduled job has no audit source")

    if not isinstance(raw.get("enabled"), bool):
        raise JobContractError(f"{label}: enabled must be boolean")
    frozen_raw = MappingProxyType(dict(raw))
    return JobSpec(
        job_id=job_id, owner=owner, repository=repository, version=version, argv=argv,
        parameters=parameters, authority=authority, enabled=raw["enabled"],
        runner_enabled=runner_enabled, runner_mode=runner_mode, schedules=schedules,
        calendar=calendar, locks=tuple(locks), idempotency_template=template,
        completion_probe=MappingProxyType(dict(completion_probe)),
        approval=MappingProxyType(dict(approval)),
        retention_days=retention, timeout=MappingProxyType(dict(timeout)),
        retry=MappingProxyType(dict(retry)), alert=MappingProxyType(dict(alert)),
        catch_up=MappingProxyType(dict(catch_up)), resources=MappingProxyType(dict(resources)),
        legacy=MappingProxyType(dict(legacy)), raw=frozen_raw, spec_sha256=_canonical_hash(raw),
        manifest=manifest,
    )


def manifest_paths(repo_root: Path = REPO_ROOT, environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Return the public manifest plus explicitly configured host-private manifests."""
    environ = os.environ if environ is None else environ
    paths = [repo_root / DEFAULT_MANIFEST]
    configured = environ.get(MANIFEST_ENV, "")
    paths.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    return tuple(paths)


def load_registry(
    repo_root: Path = REPO_ROOT,
    *,
    paths: Iterable[Path] | None = None,
    environ: Mapping[str, str] | None = None,
) -> JobRegistry:
    """Load, merge and validate manifests without opening runtime stores."""
    selected = tuple(Path(path) for path in (paths or manifest_paths(repo_root, environ)))
    jobs: list[JobSpec] = []
    seen: set[str] = set()
    for path in selected:
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise JobContractError(f"cannot read job manifest {path}: {exc}") from exc
        if document.get("schema_version") != SCHEMA_VERSION:
            raise JobContractError(f"{path}: unsupported schema version")
        retention_limit = document.get("maximum_receipt_retention_days")
        if retention_limit != 180:
            raise JobContractError(f"{path}: receipt retention limit must be 180 days")
        defaults = _mapping(document.get("defaults", {}), f"{path}.defaults")
        rows = document.get("jobs")
        if not isinstance(rows, list) or not rows:
            raise JobContractError(f"{path}: jobs must be a non-empty array")
        for row in rows:
            merged = _deep_merge(defaults, _mapping(row, f"{path}.jobs"))
            spec = _validate_job(merged, path, retention_limit)
            if spec.job_id in seen:
                raise JobContractError(f"duplicate job id: {spec.job_id}")
            seen.add(spec.job_id)
            jobs.append(spec)
    return JobRegistry(tuple(jobs), selected)


def _command_line(command: Mapping[str, Any]) -> str:
    argv = _validate_argv(command.get("argv"), "legacy command")
    return ("-" if command.get("ignore_failure", False) else "") + " ".join(argv)


def render_service(spec: JobSpec) -> str:
    service = _mapping(spec.legacy.get("service"), f"{spec.job_id}.legacy.service")
    lines = ["[Unit]", f"Description={service['description']}"]
    for key in ("after", "wants"):
        values = service.get(key, [])
        if values:
            lines.append(f"{key.title()}=" + " ".join(values))
    if service.get("start_limit_interval"):
        lines.append(f"StartLimitIntervalSec={service['start_limit_interval']}")
    if service.get("start_limit_burst"):
        lines.append(f"StartLimitBurst={service['start_limit_burst']}")
    lines += ["", "[Service]", f"Type={service.get('type', 'oneshot')}",
              f"WorkingDirectory={service.get('working_directory', '%h/trading-engine')}"]
    lines.extend(service.get("comments", []))
    lines.extend(f"ExecStart={_command_line(command)}" for command in service["exec_start"])
    lines.extend(f"ExecStartPost={_command_line(command)}"
                 for command in service.get("exec_start_post", []))
    lines.extend(f"Environment={value}" for value in service.get("environment", []))
    ordered = (
        ("nice", "Nice"), ("io_scheduling_class", "IOSchedulingClass"),
        ("timeout_start", "TimeoutStartSec"), ("standard_output", "StandardOutput"),
        ("standard_error", "StandardError"), ("private_tmp", "PrivateTmp"),
        ("protect_system", "ProtectSystem"),
        ("protect_control_groups", "ProtectControlGroups"), ("umask", "UMask"),
        ("restart", "Restart"), ("restart_prevent_exit_status", "RestartPreventExitStatus"),
        ("restart_sec", "RestartSec"),
    )
    for key, rendered in ordered:
        if key in service:
            value = service[key]
            if isinstance(value, bool):
                value = str(value).lower()
            lines.append(f"{rendered}={value}")
    return "\n".join(lines) + "\n"


def render_timer(spec: JobSpec) -> str:
    timer = _mapping(spec.legacy.get("timer"), f"{spec.job_id}.legacy.timer")
    lines = ["[Unit]", f"Description={timer['description']}", "", "[Timer]"]
    lines.extend(f"OnCalendar={value}" for value in timer["on_calendar"])
    for key, rendered in (
        ("persistent", "Persistent"), ("accuracy_sec", "AccuracySec"),
        ("randomized_delay_sec", "RandomizedDelaySec"), ("service_unit", "Unit"),
    ):
        if key in timer:
            value = timer[key]
            if isinstance(value, bool):
                value = str(value).lower()
            lines.append(f"{rendered}={value}")
    lines += ["", "[Install]", "WantedBy=timers.target"]
    return "\n".join(lines) + "\n"


def render_units(registry: JobRegistry) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for spec in registry.jobs:
        if spec.service_unit:
            rendered[spec.service_unit] = render_service(spec)
        if spec.timer_unit:
            rendered[spec.timer_unit] = render_timer(spec)
    return rendered


def _expand_repo(argv: Iterable[str], repo_root: Path) -> tuple[str, ...]:
    return tuple(value.replace("{repo}", str(repo_root)) for value in argv)


def render_cron_entries(registry: JobRegistry, repo_root: Path) -> dict[str, str]:
    rendered = {}
    for spec in registry.jobs:
        cron = spec.legacy.get("cron")
        if not isinstance(cron, Mapping):
            continue
        argv = " ".join(_expand_repo(spec.argv, repo_root))
        if cron.get("working_directory"):
            argv = f"cd {repo_root} && {argv}"
        redirect = ">>" if cron.get("append", False) else ">"
        log = str(repo_root / str(cron["log"]))
        rendered[str(cron.get("name", spec.job_id))] = (
            f"{cron['fields']} {argv} {redirect} {log} 2>&1"
        )
    return rendered


def audit_sources(repo_root: Path = REPO_ROOT, registry: JobRegistry | None = None) -> dict[str, Any]:
    registry = registry or load_registry(repo_root)
    differences = []
    rendered = render_units(registry)
    for unit, expected in sorted(rendered.items()):
        source = repo_root / "server" / unit
        try:
            actual = source.read_text()
        except OSError:
            differences.append(f"missing-source:{unit}")
            continue
        if actual != expected:
            differences.append(f"source-mismatch:{unit}")
    return {
        "status": "ok" if not differences else "mismatch",
        "schema_version": SCHEMA_VERSION,
        "manifests": [str(path) for path in registry.manifests],
        "jobs": len(registry.jobs),
        "scheduled_jobs": sum(bool(job.schedules) for job in registry.jobs),
        "rendered_units": len(rendered),
        "differences": differences,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit",))
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        result = audit_sources(args.repo_root.resolve())
    except JobContractError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
