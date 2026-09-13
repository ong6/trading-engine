"""Read-only audit of the engine's cron installation and launch prerequisites."""

from __future__ import annotations

import os
import shlex
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from engine.lib.settings import REPO_ROOT

from . import friday_postflight, scheduler_host
from .driver_monitor import DRIVER_SCHEDULES
from .host_command import command_budget

PUBLIC_INVALID_REASONS = frozenset({"crontab-unreadable", "projection-error"})
PUBLIC_STATUSES = frozenset({"inactive", "invalid", "misconfigured", "ok", "unknown"})


@dataclass(frozen=True)
class _SchedulerObservation:
    crontab_text: str | None
    crontab_error: str | None
    service_state: str
    service_unit: str | None
    service_enabled: str
    timezone_name: str
    unexecutable_drivers: tuple[str, ...]
    unlaunchable_auxiliary_entries: tuple[str, ...]
    unsafe_log_targets: tuple[str, ...]
    log_directory_writable: bool
    launch_identities: tuple[tuple[str, tuple | None], ...]


def _stable_metadata(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _node_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _open_flags(*, directory: bool) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("no-follow traversal is unavailable")
    flags = getattr(os, "O_PATH", os.O_RDONLY) | getattr(os, "O_CLOEXEC", 0) | nofollow
    if directory:
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if directory_flag is None:
            raise OSError("directory traversal is unavailable")
        flags |= directory_flag
    elif not hasattr(os, "O_PATH"):
        flags |= getattr(os, "O_NONBLOCK", 0)
    return flags


@contextmanager
def _directory_chain(anchor: Path, parts: tuple[str, ...]):
    flags = _open_flags(directory=True)
    with ExitStack() as stack:
        current = os.open(anchor, flags)
        stack.callback(os.close, current)
        identities = [_stable_metadata(os.fstat(current))]
        for part in parts:
            child = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, child)
            current = child
            identities.append(_stable_metadata(os.fstat(current)))
        yield current, tuple(identities)


def _valid_relative_path(relative: Path) -> bool:
    return bool(relative.parts) and not relative.is_absolute() and all(
        part not in {"", ".", ".."} for part in relative.parts
    )


def _inspect_stable_in_tree(
    repo_root: Path,
    relative: Path,
    access_mode: int,
    *,
    stable_metadata: bool = True,
) -> tuple[os.stat_result | None, bool] | None:
    """Inspect one present or absent node through matching no-follow traversals."""
    if not _valid_relative_path(relative):
        return None
    parts = relative.parts
    try:
        with _directory_chain(repo_root, parts[:-1]) as (parent_fd, parent_chain):
            try:
                descriptor = os.open(
                    parts[-1], _open_flags(directory=False), dir_fd=parent_fd
                )
            except FileNotFoundError:
                descriptor = -1
            if descriptor < 0:
                with _directory_chain(repo_root, parts[:-1]) as (visible_parent_fd, visible_chain):
                    try:
                        os.stat(parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        return (None, True) if parent_chain == visible_chain else None
                return None
            try:
                before = os.fstat(descriptor)
                accessible = os.access(f"/proc/self/fd/{descriptor}", access_mode)
                anchored = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                with _directory_chain(repo_root, parts[:-1]) as (visible_parent_fd, visible_chain):
                    visible = os.stat(
                        parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False
                    )
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
    except OSError:
        return None
    identity = _stable_metadata if stable_metadata else _node_identity
    identities = {identity(value) for value in (before, after, anchored, visible)}
    if parent_chain != visible_chain or len(identities) != 1:
        return None
    return after, accessible


def _is_in_tree_accessible_file(repo_root: Path, relative: Path, mode: int) -> bool:
    """Require a stable regular launch file with no symlinked checkout component."""
    inspected = _inspect_stable_in_tree(repo_root, relative, mode)
    return bool(
        inspected is not None
        and inspected[0] is not None
        and stat.S_ISREG(inspected[0].st_mode)
        and inspected[1]
    )


def _in_tree_accessible_file_observation(
    repo_root: Path, relative: Path, mode: int
) -> tuple[bool, tuple | None]:
    inspected = _inspect_stable_in_tree(repo_root, relative, mode)
    ready = bool(
        inspected is not None
        and inspected[0] is not None
        and stat.S_ISREG(inspected[0].st_mode)
        and inspected[1]
    )
    identity = _stable_metadata(inspected[0]) if ready else None
    return ready, identity


def _is_in_tree_writable_directory(repo_root: Path, relative: Path) -> bool:
    inspected = _inspect_stable_in_tree(repo_root, relative, os.W_OK | os.X_OK)
    return bool(
        inspected is not None
        and inspected[0] is not None
        and stat.S_ISDIR(inspected[0].st_mode)
        and inspected[1]
    )


def _in_tree_writable_directory_observation(
    repo_root: Path, relative: Path
) -> tuple[bool, tuple | None]:
    inspected = _inspect_stable_in_tree(repo_root, relative, os.W_OK | os.X_OK)
    ready = bool(
        inspected is not None
        and inspected[0] is not None
        and stat.S_ISDIR(inspected[0].st_mode)
        and inspected[1]
    )
    identity = _stable_metadata(inspected[0]) if ready else None
    return ready, identity


def _cron_weekdays(weekdays: tuple[int, ...]) -> str:
    """Render Python weekdays as the compact cron field used by this project."""
    cron_days = tuple((weekday + 1) % 7 for weekday in weekdays)
    if len(cron_days) > 1 and cron_days == tuple(range(cron_days[0], cron_days[-1] + 1)):
        return f"{cron_days[0]}-{cron_days[-1]}"
    return ",".join(str(day) for day in cron_days)


def expected_cron_entries(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return the exact unattended driver lines expected in the user crontab."""
    return {
        name: " ".join(
            (
                str(minute),
                str(hour),
                "*",
                "*",
                _cron_weekdays(weekdays),
                str(repo_root / "engine" / f"{name}.sh"),
                ">>",
                str(repo_root / "logs" / log),
                "2>&1",
            )
        )
        for _key, name, log, _lock, weekdays, hour, minute, _grace, _first in DRIVER_SCHEDULES
    }


def expected_auxiliary_cron_entries(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return exact evidence-only schedules kept outside production drivers."""
    schedule = friday_postflight.SCHEDULE_TIME
    weekday = _cron_weekdays((friday_postflight.SCHEDULE_WEEKDAY,))
    return {
        "friday_postflight": " ".join(
            (
                str(schedule.minute),
                str(schedule.hour),
                "*",
                "*",
                weekday,
                "cd",
                str(repo_root),
                "&&",
                ".venv/bin/python",
                "-m",
                "tools.verify_friday_postflight",
                "--publish",
                ">",
                str(repo_root / "logs" / "friday-postflight.log"),
                "2>&1",
            )
        )
    }


def managed_log_targets(repo_root: Path = REPO_ROOT) -> dict[str, Path]:
    """Return every file that a managed cron entry redirects output into."""
    targets = {
        name: repo_root / "logs" / log
        for _key, name, log, _lock, _weekdays, _hour, _minute, _grace, _first in DRIVER_SCHEDULES
    }
    targets["friday_postflight"] = repo_root / "logs" / "friday-postflight.log"
    return targets


def _log_target_observations(
    repo_root: Path,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple | None], ...]]:
    """Classify log targets and retain identity without treating appends as changes."""
    log_directory = _inspect_stable_in_tree(repo_root, Path("logs"), os.F_OK)
    if (
        log_directory is None
        or log_directory[0] is None
        or not stat.S_ISDIR(log_directory[0].st_mode)
    ):
        return (), ()
    observations = []
    unsafe = []
    for name, path in managed_log_targets(repo_root).items():
        inspected = _inspect_stable_in_tree(
            repo_root,
            path.relative_to(repo_root),
            os.F_OK,
            stable_metadata=False,
        )
        safe = bool(
            inspected is not None
            and (inspected[0] is None or stat.S_ISREG(inspected[0].st_mode))
        )
        if not safe:
            unsafe.append(name)
        identity = None if inspected is None else (
            ("absent",) if inspected[0] is None else _node_identity(inspected[0])
        )
        observations.append((name, identity))
    return tuple(sorted(unsafe)), tuple(sorted(observations))


def unsafe_log_targets(repo_root: Path = REPO_ROOT) -> tuple[str, ...]:
    """List cron log targets that are neither stably absent nor stable regular files."""
    return _log_target_observations(repo_root)[0]


def _shell_tokens(line: str) -> tuple[str, ...]:
    """Return words from the command portion cron passes to the POSIX shell."""
    command_end = len(line)
    escaped = False
    for index, character in enumerate(line):
        if character == "%" and not escaped:
            command_end = index
            break
        if character == "\\":
            escaped = not escaped
        else:
            escaped = False
    lexer = shlex.shlex(line[:command_end], posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return tuple(lexer)
    except ValueError:
        return ()


def _is_postflight_invocation(tokens: tuple[str, ...]) -> bool:
    return "tools.verify_friday_postflight" in tokens or any(
        token.endswith("/tools/verify_friday_postflight.py")
        or token == "tools/verify_friday_postflight.py"
        for token in tokens
    )


def _active_cron_lines(crontab_text: str) -> list[str]:
    return [
        " ".join(line.split())
        for line in crontab_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _schedule_matches(active_lines: list[str], repo_root: Path) -> dict:
    expected = expected_cron_entries(repo_root)
    auxiliary = expected_auxiliary_cron_entries(repo_root)
    tokenized = [_shell_tokens(line) for line in active_lines]
    exact = {name: active_lines.count(line) for name, line in expected.items()}
    auxiliary_exact = {name: active_lines.count(line) for name, line in auxiliary.items()}
    invocation_counts = {
        name: sum(
            str(repo_root / "engine" / f"{name}.sh") in tokens for tokens in tokenized
        )
        for name in expected
    }
    auxiliary_invocations = {
        name: sum(_is_postflight_invocation(tokens) for tokens in tokenized) for name in auxiliary
    }
    return {
        "expected_entries": len(expected),
        "matched_entries": sum(count == 1 for count in exact.values()),
        "missing_drivers": sorted(name for name, count in exact.items() if count == 0),
        "duplicate_drivers": sorted(name for name, count in invocation_counts.items() if count > 1),
        "auxiliary_expected_entries": len(auxiliary),
        "auxiliary_matched_entries": sum(count == 1 for count in auxiliary_exact.values()),
        "missing_auxiliary_entries": sorted(
            name for name, count in auxiliary_exact.items() if count == 0
        ),
        "duplicate_auxiliary_entries": sorted(
            name for name, count in auxiliary_invocations.items() if count > 1
        ),
    }


def _scheduler_state(
    service_state: str,
    service_enabled: str,
    timezone_ok: bool,
    schedule: dict,
    launch_ready: bool,
) -> str:
    schedule_ready = not any(
        schedule[field]
        for field in (
            "missing_drivers",
            "duplicate_drivers",
            "missing_auxiliary_entries",
            "duplicate_auxiliary_entries",
        )
    )
    if (
        service_state == "active"
        and service_enabled == "enabled"
        and timezone_ok
        and schedule_ready
        and launch_ready
    ):
        return "ok"
    if service_state == "unknown" or (service_state == "active" and service_enabled == "unknown"):
        return "unknown"
    if service_state != "active":
        return "inactive"
    return "misconfigured"


def evaluate_scheduler(
    crontab_text: str,
    service_state: str,
    *,
    service_unit: str | None = None,
    service_enabled: str = "enabled",
    timezone_name: str = "UTC",
    unexecutable_drivers: tuple[str, ...] = (),
    unlaunchable_auxiliary_entries: tuple[str, ...] = (),
    unsafe_log_targets: tuple[str, ...] = (),
    log_directory_writable: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Validate the exact driver schedules without changing scheduler state."""
    schedule = _schedule_matches(_active_cron_lines(crontab_text), repo_root)
    timezone_ok = timezone_name in {"UTC", "Etc/UTC"}
    launch_ready = (
        not unexecutable_drivers
        and not unlaunchable_auxiliary_entries
        and not unsafe_log_targets
        and log_directory_writable
    )
    return {
        "status": _scheduler_state(
            service_state, service_enabled, timezone_ok, schedule, launch_ready
        ),
        "cron_service": service_state,
        "cron_service_unit": service_unit,
        "cron_service_enabled": service_enabled,
        "timezone": timezone_name,
        "expected_timezone": "UTC",
        "timezone_ok": timezone_ok,
        **schedule,
        "unlaunchable_auxiliary_entries": sorted(unlaunchable_auxiliary_entries),
        "unexecutable_drivers": sorted(unexecutable_drivers),
        "unsafe_log_targets": sorted(unsafe_log_targets),
        "log_directory_writable": log_directory_writable,
    }


def invalid_status(
    reason: str,
    *,
    cron_service: str = "unknown",
    cron_service_unit: str | None = None,
    cron_service_enabled: str = "unknown",
    timezone_name: str = "unknown",
    unexecutable_drivers: tuple[str, ...] = (),
    unlaunchable_auxiliary_entries: tuple[str, ...] = (),
    unsafe_log_targets: tuple[str, ...] = (),
    log_directory_writable: bool = False,
) -> dict:
    """Return the complete fail-closed scheduler schema for unavailable probes."""
    if reason not in PUBLIC_INVALID_REASONS:
        raise ValueError(f"unknown scheduler invalid reason: {reason}")
    return {
        "status": "invalid",
        "reason": reason,
        "cron_service": cron_service,
        "cron_service_unit": cron_service_unit,
        "cron_service_enabled": cron_service_enabled,
        "timezone": timezone_name,
        "expected_timezone": "UTC",
        "timezone_ok": timezone_name in {"UTC", "Etc/UTC"},
        "expected_entries": len(DRIVER_SCHEDULES),
        "matched_entries": 0,
        "missing_drivers": [],
        "duplicate_drivers": [],
        "auxiliary_expected_entries": len(expected_auxiliary_cron_entries()),
        "auxiliary_matched_entries": 0,
        "missing_auxiliary_entries": [],
        "duplicate_auxiliary_entries": [],
        "unlaunchable_auxiliary_entries": sorted(unlaunchable_auxiliary_entries),
        "unexecutable_drivers": sorted(unexecutable_drivers),
        "unsafe_log_targets": sorted(unsafe_log_targets),
        "log_directory_writable": log_directory_writable,
    }


def _launch_prerequisites(
    repo_root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool, tuple]:
    driver_observations = tuple(
        (
            name,
            *_in_tree_accessible_file_observation(
                repo_root, Path("engine") / f"{name}.sh", os.X_OK
            ),
        )
        for _key, name, _log, _lock, _weekdays, _hour, _minute, _grace, _first in DRIVER_SCHEDULES
    )
    unexecutable_drivers = tuple(
        name for name, ready, _identity in driver_observations if not ready
    )
    postflight_python = repo_root / ".venv" / "bin" / "python"
    try:
        python_metadata = postflight_python.stat()
        python_ready = stat.S_ISREG(python_metadata.st_mode) and os.access(
            postflight_python, os.X_OK
        )
        python_identity = _stable_metadata(python_metadata) if python_ready else None
    except OSError:
        python_ready = False
        python_identity = None
    module_ready, module_identity = _in_tree_accessible_file_observation(
        repo_root, Path("tools/verify_friday_postflight.py"), os.R_OK
    )
    unlaunchable_auxiliary_entries = (
        ()
        if python_ready and module_ready
        else ("friday_postflight",)
    )
    log_directory_writable, log_directory_identity = (
        _in_tree_writable_directory_observation(repo_root, Path("logs"))
    )
    unsafe_logs, log_target_identities = _log_target_observations(repo_root)
    identities = (
        *((f"driver:{name}", identity) for name, _ready, identity in driver_observations),
        ("postflight-python", python_identity),
        ("postflight-module", module_identity),
        ("log-directory", log_directory_identity),
        *((f"log-target:{name}", identity) for name, identity in log_target_identities),
    )
    return (
        unexecutable_drivers,
        unlaunchable_auxiliary_entries,
        unsafe_logs,
        log_directory_writable,
        identities,
    )


def _observation(repo_root: Path) -> _SchedulerObservation:
    crontab_text, error = scheduler_host.read_user_crontab()
    service_state, service_unit = scheduler_host.cron_service()
    service_enabled = scheduler_host.service_enabled(service_unit)
    timezone_name = scheduler_host.system_timezone()
    (
        unexecutable_drivers,
        unlaunchable_auxiliary_entries,
        unsafe_logs,
        log_directory_writable,
        launch_identities,
    ) = _launch_prerequisites(repo_root)
    return _SchedulerObservation(
        crontab_text=crontab_text,
        crontab_error=error,
        service_state=service_state,
        service_unit=service_unit,
        service_enabled=service_enabled,
        timezone_name=timezone_name,
        unexecutable_drivers=unexecutable_drivers,
        unlaunchable_auxiliary_entries=unlaunchable_auxiliary_entries,
        unsafe_log_targets=unsafe_logs,
        log_directory_writable=log_directory_writable,
        launch_identities=launch_identities,
    )


def _project_observation(observation: _SchedulerObservation, repo_root: Path) -> dict:
    if observation.crontab_error is not None or observation.crontab_text is None:
        return invalid_status(
            observation.crontab_error or "crontab-unreadable",
            cron_service=observation.service_state,
            cron_service_unit=observation.service_unit,
            cron_service_enabled=observation.service_enabled,
            timezone_name=observation.timezone_name,
            unexecutable_drivers=observation.unexecutable_drivers,
            unlaunchable_auxiliary_entries=observation.unlaunchable_auxiliary_entries,
            unsafe_log_targets=observation.unsafe_log_targets,
            log_directory_writable=observation.log_directory_writable,
        )
    return evaluate_scheduler(
        observation.crontab_text,
        observation.service_state,
        service_unit=observation.service_unit,
        service_enabled=observation.service_enabled,
        timezone_name=observation.timezone_name,
        unexecutable_drivers=observation.unexecutable_drivers,
        unlaunchable_auxiliary_entries=observation.unlaunchable_auxiliary_entries,
        unsafe_log_targets=observation.unsafe_log_targets,
        log_directory_writable=observation.log_directory_writable,
        repo_root=repo_root,
    )


def _status(repo_root: Path) -> dict:
    observation = _observation(repo_root)
    if _observation(repo_root) != observation:
        return invalid_status("projection-error")
    return _project_observation(observation, repo_root)


def status(*, repo_root: Path = REPO_ROOT) -> dict:
    """Audit the scheduler within one shared host-command budget."""
    with command_budget():
        return _status(repo_root)
