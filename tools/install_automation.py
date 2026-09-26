#!/usr/bin/env python3
"""Audit or install this checkout's unattended cron and user-service configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

from engine.lib.settings import REPO_ROOT
from server import scheduler_monitor

BEGIN_MARKER = "# BEGIN trading-engine managed automation"
END_MARKER = "# END trading-engine managed automation"
UNIT_SOURCES = {
    "trading-engine-api.service": Path("server/trading-engine-api.service"),
    "trading-engine-ui.service": Path("ui/trading-engine-ui.service"),
    "trading-engine-agent-shadow.service": Path(
        "server/trading-engine-agent-shadow.service"
    ),
    "trading-engine-agent-shadow.timer": Path(
        "server/trading-engine-agent-shadow.timer"
    ),
    "trading-engine-agent-data-capture.service": Path(
        "server/trading-engine-agent-data-capture.service"
    ),
    "trading-engine-agent-data-capture.timer": Path(
        "server/trading-engine-agent-data-capture.timer"
    ),
    "trading-engine-daily-opportunity.service": Path(
        "server/trading-engine-daily-opportunity.service"
    ),
    "trading-engine-daily-opportunity.timer": Path(
        "server/trading-engine-daily-opportunity.timer"
    ),
    "trading-engine-hourly-opportunity.service": Path(
        "server/trading-engine-hourly-opportunity.service"
    ),
    "trading-engine-hourly-opportunity.timer": Path(
        "server/trading-engine-hourly-opportunity.timer"
    ),
    "trading-engine-four-hour-opportunity.service": Path(
        "server/trading-engine-four-hour-opportunity.service"
    ),
    "trading-engine-four-hour-opportunity.timer": Path(
        "server/trading-engine-four-hour-opportunity.timer"
    ),
    "trading-engine-tradingview-history.service": Path(
        "server/trading-engine-tradingview-history.service"
    ),
    "trading-engine-tradingview-history.timer": Path(
        "server/trading-engine-tradingview-history.timer"
    ),
    "trading-engine-p15-scoring.service": Path(
        "server/trading-engine-p15-scoring.service"
    ),
    "trading-engine-p15-scoring.timer": Path(
        "server/trading-engine-p15-scoring.timer"
    ),
    "trading-engine-p15-preopen.service": Path(
        "server/trading-engine-p15-preopen.service"
    ),
    "trading-engine-p15-preopen.timer": Path(
        "server/trading-engine-p15-preopen.timer"
    ),
    "trading-engine-p15-events.service": Path(
        "server/trading-engine-p15-events.service"
    ),
    "trading-engine-p15-events.timer": Path(
        "server/trading-engine-p15-events.timer"
    ),
}
AUTOSTART_UNITS = frozenset(
    {
        "trading-engine-agent-data-capture.timer",
        "trading-engine-agent-shadow.timer",
        "trading-engine-daily-opportunity.timer",
        "trading-engine-hourly-opportunity.timer",
        "trading-engine-four-hour-opportunity.timer",
        "trading-engine-tradingview-history.timer",
        "trading-engine-api.service",
        "trading-engine-ui.service",
    }
)
MAX_AUTOMATION_SOURCE_BYTES = 1_048_576


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_relative_access(
    parent_fd: int,
    leaf: str,
    relative: Path,
    *,
    label: str,
    access_mode: int | None,
    access_label: str | None,
) -> None:
    """Check requested access through the parent descriptor used for opening."""
    if access_mode is None:
        return
    if os.access(leaf, access_mode, dir_fd=parent_fd, follow_symlinks=False):
        return
    requirement = access_label or "accessible"
    raise RuntimeError(f"{label} is not {requirement}: {relative.as_posix()}")


@contextmanager
def _directory_chain(anchor: Path, parts: tuple[str, ...], *, create: bool = False):
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise RuntimeError("secure service unit traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with ExitStack() as stack:
        current = os.open(anchor, flags)
        stack.callback(os.close, current)
        identities = [_stat_identity(os.fstat(current))]
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, child)
            current = child
            identities.append(_stat_identity(os.fstat(current)))
        yield current, tuple(identities)


def _read_stable_regular_file(
    anchor: Path,
    relative: Path,
    *,
    label: str,
    access_mode: int | None = None,
    access_label: str | None = None,
) -> bytes:
    """Read one bounded regular file through a stable no-follow path."""
    parts = relative.parts
    if not parts or relative.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"invalid {label}: {relative.as_posix()}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError("secure service unit traversal is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    try:
        with _directory_chain(anchor, parts[:-1]) as (parent_fd, parent_chain):
            descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeError(f"{label} is not regular: {relative.as_posix()}")
                _require_relative_access(
                    parent_fd,
                    parts[-1],
                    relative,
                    label=label,
                    access_mode=access_mode,
                    access_label=access_label,
                )
                chunks = []
                remaining = MAX_AUTOMATION_SOURCE_BYTES + 1
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                after = os.fstat(descriptor)
                anchored = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            finally:
                os.close(descriptor)
            with _directory_chain(anchor, parts[:-1]) as (
                visible_parent_fd,
                visible_parent_chain,
            ):
                visible = os.stat(
                    parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False
                )
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"{label} is unsafe: {relative.as_posix()}") from exc
    if len(content) > MAX_AUTOMATION_SOURCE_BYTES:
        raise RuntimeError(f"{label} is too large: {relative.as_posix()}")
    if (
        parent_chain != visible_parent_chain
        or not stat.S_ISREG(after.st_mode)
        or not stat.S_ISREG(anchored.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or before.st_mode != after.st_mode
        or after.st_mode != anchored.st_mode
        or anchored.st_mode != visible.st_mode
        or _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(anchored)
        or _stat_identity(anchored) != _stat_identity(visible)
        or len(content) != before.st_size
    ):
        raise RuntimeError(f"{label} changed: {relative.as_posix()}")
    return content


def _read_unit_source(repo_root: Path, relative: Path) -> bytes:
    """Read one bounded unit through a stable no-follow checkout path."""
    return _read_stable_regular_file(repo_root, relative, label="service unit source")


def _read_installed_unit(home: Path, unit: str) -> bytes:
    """Read one installed unit through a stable no-follow home-relative path."""
    return _read_stable_regular_file(
        home, Path(".config/systemd/user") / unit, label="installed service unit"
    )


def _read_installed_unit_at(directory_fd: int, unit: str) -> bytes:
    """Read one installed unit through an already anchored directory."""
    if Path(unit).name != unit:
        raise RuntimeError(f"invalid installed service unit: {unit}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError("secure service unit traversal is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    try:
        descriptor = os.open(unit, flags, dir_fd=directory_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeError(f"installed service unit is not regular: {unit}")
            chunks = []
            remaining = MAX_AUTOMATION_SOURCE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            visible = os.stat(unit, dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.close(descriptor)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"installed service unit is unsafe: {unit}") from exc
    if len(content) > MAX_AUTOMATION_SOURCE_BYTES:
        raise RuntimeError(f"installed service unit is too large: {unit}")
    if (
        not stat.S_ISREG(after.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(visible)
        or len(content) != before.st_size
    ):
        raise RuntimeError(f"installed service unit changed: {unit}")
    return content


@contextmanager
def _open_unit_directory(home: Path):
    """Open/create the user unit directory without following path symlinks."""
    relative = Path(".config/systemd/user")
    stack = ExitStack()
    try:
        _creation_fd, _creation_identity = stack.enter_context(
            _directory_chain(home, relative.parts, create=True)
        )
        descriptor, identity = stack.enter_context(
            _directory_chain(home, relative.parts)
        )
        if tuple(item[:2] for item in identity) != tuple(
            item[:2] for item in _creation_identity
        ):
            raise RuntimeError("service unit directory changed after replan")
        opened = descriptor, identity
    except (OSError, RuntimeError) as exc:
        stack.close()
        raise RuntimeError("service unit directory changed after replan") from exc
    try:
        yield opened
    finally:
        stack.close()


def _unit_directory_unchanged(
    home: Path, initial: tuple[tuple[int, int, int, int, int], ...]
) -> bool:
    try:
        with _directory_chain(home, Path(".config/systemd/user").parts) as (
            _descriptor,
            visible,
        ):
            return (
                visible[:-1] == initial[:-1]
                and visible[-1][:2] == initial[-1][:2]
            )
    except (OSError, RuntimeError):
        return False


def _install_unit_snapshot(directory_fd: int, unit: str, content: bytes) -> None:
    """Atomically install one private snapshot relative to an opened directory."""
    if Path(unit).name != unit:
        raise RuntimeError(f"invalid service unit name: {unit}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError("secure service unit installation is unavailable")
    temporary = f".{unit}.{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | nofollow
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short service unit write")
            view = view[written:]
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary,
            unit,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except OSError as exc:
        raise RuntimeError(f"could not install service unit: {unit}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _is_regular_file(path: Path, *, anchor: Path | None = None) -> bool:
    if anchor is not None:
        try:
            relative = path.relative_to(anchor)
        except ValueError:
            return False
        current = anchor
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return False
    return path.is_file() and not path.is_symlink()


def _is_in_tree_directory(repo_root: Path, relative: Path) -> bool:
    current = repo_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return False
    return current.is_dir()


def _has_symlinked_parent(path: Path, anchor: Path) -> bool:
    try:
        relative = path.relative_to(anchor)
    except ValueError:
        return True
    current = anchor
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _validate_launch_file(
    repo_root: Path, relative: Path, *, access_mode: int, access_label: str
) -> str | None:
    path = repo_root / relative
    if not _is_regular_file(path, anchor=repo_root):
        return f"not-regular:{relative.as_posix()}"
    if not os.access(path, access_mode):
        return f"not-{access_label}:{relative.as_posix()}"
    return None


def _run(
    args: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _read_crontab() -> str:
    result = _run(["crontab", "-l"])
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and "no crontab" in result.stderr.lower():
        return ""
    raise RuntimeError("installed user crontab is unreadable")


def _service_state(action: str, unit: str) -> str:
    """Return one systemd unit state without changing the user manager."""
    try:
        result = _run(["systemctl", "--user", action, unit])
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    state = result.stdout.strip()
    return state if state else "unknown"


def _linger_state() -> str:
    """Return whether this user's service manager survives logout."""
    try:
        result = _run(
            ["loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value"]
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    state = result.stdout.strip().lower()
    return state if result.returncode == 0 and state in {"yes", "no"} else "unknown"


def _host_continuity(repo_root: Path) -> dict:
    """Return non-mutating host prerequisites outside this user's managed files."""
    cron_service, cron_unit = scheduler_monitor.scheduler_host.cron_service()
    cron_enabled = scheduler_monitor.scheduler_host.service_enabled(cron_unit)
    timezone = scheduler_monitor.scheduler_host.system_timezone()
    logs = repo_root / "logs"
    return {
        "cron_service": cron_service,
        "cron_service_unit": cron_unit,
        "cron_service_enabled": cron_enabled,
        "timezone": timezone,
        "timezone_ok": timezone in {"UTC", "Etc/UTC"},
        "log_directory_writable": _is_in_tree_directory(repo_root, Path("logs"))
        and os.access(logs, os.W_OK),
        "unsafe_log_targets": list(scheduler_monitor.unsafe_log_targets(repo_root)),
    }


def _host_errors(host: dict) -> list[str]:
    errors = []
    if host["cron_service"] != "active":
        errors.append(f"cron-service-not-active:{host['cron_service']}")
    if host["cron_service_enabled"] != "enabled":
        errors.append(f"cron-service-not-enabled:{host['cron_service_enabled']}")
    if not host["timezone_ok"]:
        errors.append(f"timezone-not-utc:{host['timezone']}")
    if not host["log_directory_writable"]:
        errors.append("log-directory-not-writable")
    for name in host["unsafe_log_targets"]:
        errors.append(f"unsafe-log-target:{name}")
    return errors


def managed_entries(repo_root: Path) -> tuple[str, ...]:
    production = scheduler_monitor.expected_cron_entries(repo_root)
    auxiliary = scheduler_monitor.expected_auxiliary_cron_entries(repo_root)
    return tuple((*production.values(), *auxiliary.values()))


def managed_block(repo_root: Path) -> tuple[str, ...]:
    return (
        BEGIN_MARKER,
        "# Generated by: python -m tools.install_automation --apply",
        "# Production drivers (five) plus one evidence-only Saturday postflight.",
        *managed_entries(repo_root),
        END_MARKER,
    )


def _is_legacy_entry(line: str, repo_root: Path) -> bool:
    if not line.strip() or line.lstrip().startswith("#"):
        return False
    normalized = " ".join(line.split())
    if normalized in managed_entries(repo_root):
        return True
    tokens = normalized.split()
    driver_paths = {
        str(repo_root / "engine" / f"{name}.sh")
        for name in scheduler_monitor.expected_cron_entries(repo_root)
    }
    if driver_paths.intersection(tokens):
        return True
    return (
        str(repo_root) in tokens and "tools.verify_friday_postflight" in tokens
    ) or any(
        token == str(repo_root / "tools" / "verify_friday_postflight.py")
        for token in tokens
    )


def render_crontab(current: str, repo_root: Path) -> str:
    """Replace only this checkout's managed/legacy entries and preserve all others."""
    retained: list[str] = []
    inside = False
    saw_block = False
    for line in current.splitlines():
        if line == BEGIN_MARKER:
            if inside or saw_block:
                raise ValueError("duplicate or nested trading-engine cron block")
            inside = True
            saw_block = True
            continue
        if line == END_MARKER:
            if not inside:
                raise ValueError("unmatched trading-engine cron end marker")
            inside = False
            continue
        if not inside and not _is_legacy_entry(line, repo_root):
            retained.append(line)
    if inside:
        raise ValueError("unterminated trading-engine cron block")
    while retained and not retained[-1].strip():
        retained.pop()
    if retained:
        retained.append("")
    retained.extend(managed_block(repo_root))
    return "\n".join(retained) + "\n"


def _validate_checkout(repo_root: Path, home: Path) -> list[str]:
    errors: list[str] = []
    if any(character.isspace() for character in str(repo_root)):
        errors.append("repo-root-not-cron-safe")
    service_checkout = home / "trading-engine"
    if not service_checkout.exists() or service_checkout.resolve() != repo_root:
        errors.append("service-working-directory-mismatch")
    for relative in UNIT_SOURCES.values():
        if not _is_regular_file(repo_root / relative, anchor=repo_root):
            errors.append(f"not-regular:{relative.as_posix()}")
    unit_dir = home / ".config" / "systemd" / "user"
    if _has_symlinked_parent(unit_dir / "placeholder.service", home):
        errors.append("installed-unit-directory-has-symlink")
    for name in scheduler_monitor.expected_cron_entries(repo_root):
        error = _validate_launch_file(
            repo_root,
            Path("engine") / f"{name}.sh",
            access_mode=os.X_OK,
            access_label="executable",
        )
        if error:
            errors.append(error)
    python = repo_root / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        errors.append("not-executable:.venv/bin/python")
    error = _validate_launch_file(
        repo_root,
        Path("tools/verify_friday_postflight.py"),
        access_mode=os.R_OK,
        access_label="readable",
    )
    if error:
        errors.append(error)
    return errors


def _launch_source_paths(repo_root: Path) -> dict[str, Path]:
    """Return every repository file invoked directly by managed cron entries."""
    drivers = {
        name: Path("engine") / f"{name}.sh"
        for name in scheduler_monitor.expected_cron_entries(repo_root)
    }
    return {**drivers, "friday_postflight": Path("tools/verify_friday_postflight.py")}


def _launch_sources(repo_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Describe stable launch bytes while retaining existing validation labels."""
    sources = {}
    errors = []
    for name, relative in _launch_source_paths(repo_root).items():
        access_mode = os.R_OK if name == "friday_postflight" else os.X_OK
        access_label = "readable" if name == "friday_postflight" else "executable"
        try:
            content = _read_stable_regular_file(
                repo_root,
                relative,
                label="automation launch source",
                access_mode=access_mode,
                access_label=access_label,
            )
        except RuntimeError:
            content = None
            errors.append(f"unsafe-launch-source:{relative.as_posix()}")
        sources[name] = {
            "source": relative.as_posix(),
            "source_sha256": (
                hashlib.sha256(content).hexdigest() if content is not None else None
            ),
        }
    return sources, errors


def _installed_units(
    repo_root: Path, home: Path, *, source_errors: list[str] | None = None
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for unit, relative in UNIT_SOURCES.items():
        installed = Path(".config/systemd/user") / unit
        try:
            source_bytes = _read_unit_source(repo_root, relative)
        except RuntimeError:
            source_bytes = None
            if source_errors is not None:
                source_errors.append(f"unsafe-service-unit-source:{relative.as_posix()}")
        try:
            installed_bytes = _read_installed_unit(home, unit)
        except RuntimeError:
            installed_bytes = None
        result[unit] = {
            "source": relative.as_posix(),
            "source_sha256": (
                hashlib.sha256(source_bytes).hexdigest()
                if source_bytes is not None
                else None
            ),
            "installed": installed.as_posix(),
            "matches": source_bytes is not None and source_bytes == installed_bytes,
            "enabled": _service_state("is-enabled", unit),
            "active": _service_state("is-active", unit),
        }
    return result


def plan(repo_root: Path = REPO_ROOT, home: Path | None = None) -> tuple[dict, str]:
    repo_root = repo_root.resolve()
    home = (home or Path.home()).resolve()
    errors = _validate_checkout(repo_root, home)
    launch_sources, launch_errors = _launch_sources(repo_root)
    errors.extend(launch_errors)
    host = _host_continuity(repo_root)
    errors.extend(_host_errors(host))
    try:
        current_crontab = _read_crontab()
        desired_crontab = render_crontab(current_crontab, repo_root)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        errors.append(str(exc))
        current_crontab = ""
        desired_crontab = ""
    units = _installed_units(repo_root, home, source_errors=errors)
    linger = _linger_state()
    changes = {
        "crontab": bool(desired_crontab) and desired_crontab != current_crontab,
        "service_units": sorted(unit for unit, state in units.items() if not state["matches"]),
        "enable_units": sorted(
            unit
            for unit, state in units.items()
            if unit in AUTOSTART_UNITS and state["enabled"] != "enabled"
        ),
        "start_units": sorted(
            unit
            for unit, state in units.items()
            if unit in AUTOSTART_UNITS and state["active"] != "active"
        ),
        "enable_linger": linger != "yes",
    }
    summary = {
        "status": "invalid" if errors else ("changes-required" if any(changes.values()) else "ok"),
        "applied": False,
        "repo_root": str(repo_root),
        "errors": errors,
        "changes": changes,
        "service_units": units,
        "launch_sources": launch_sources,
        "linger": linger,
        "host": host,
        "managed_cron_entries": len(managed_entries(repo_root)),
    }
    return summary, desired_crontab


def _checked(args: list[str], *, input_text: str | None = None) -> None:
    result = _run(args, input_text=input_text)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{args[0]} failed: {detail}")


def _verify_applied(repo_root: Path, home: Path, units: list[str]) -> tuple[dict, dict, str]:
    installed = _installed_units(repo_root, home)
    mismatched = sorted(unit for unit, state in installed.items() if not state["matches"])
    if mismatched:
        raise RuntimeError(f"installed service units do not match: {', '.join(mismatched)}")
    current_crontab = _read_crontab()
    if render_crontab(current_crontab, repo_root) != current_crontab:
        raise RuntimeError("installed crontab does not match the managed configuration")
    _checked(["systemctl", "--user", "is-enabled", *units])
    _checked(["systemctl", "--user", "is-active", *units])
    installed = _installed_units(repo_root, home)
    checked_units = set(units)
    disabled = sorted(
        unit
        for unit, state in installed.items()
        if unit in checked_units and state["enabled"] != "enabled"
    )
    inactive = sorted(
        unit
        for unit, state in installed.items()
        if unit in checked_units and state["active"] != "active"
    )
    if disabled:
        raise RuntimeError(f"installed service units are not enabled: {', '.join(disabled)}")
    if inactive:
        raise RuntimeError(f"installed service units are not active: {', '.join(inactive)}")
    linger = _linger_state()
    if linger != "yes":
        raise RuntimeError(f"user lingering is not enabled: {linger}")
    scheduler = scheduler_monitor.status(repo_root=repo_root)
    if scheduler["status"] != "ok":
        raise RuntimeError(f"post-install scheduler verification failed: {scheduler['status']}")
    return scheduler, installed, linger


def _snapshot_unit_sources(repo_root: Path, summary: dict) -> dict[str, bytes]:
    """Revalidate and freeze every service-unit source accepted by re-plan."""
    snapshots = {}
    for unit, relative in UNIT_SOURCES.items():
        content = _read_unit_source(repo_root, relative)
        expected_sha256 = summary["service_units"][unit]["source_sha256"]
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError(f"service unit source changed after replan: {unit}")
        snapshots[unit] = content
    return snapshots


def _changed_unit_snapshots(
    unit_dir_fd: int, source_snapshots: dict[str, bytes]
) -> dict[str, bytes]:
    """Select units whose latest installed bytes differ from pinned sources."""
    changed = {}
    for unit, content in source_snapshots.items():
        try:
            installed = _read_installed_unit_at(unit_dir_fd, unit)
        except RuntimeError:
            installed = None
        if installed != content:
            changed[unit] = content
    return changed


def _verify_launch_sources(repo_root: Path, summary: dict) -> None:
    """Require every cron launch source to retain the bytes accepted by re-plan."""
    for name, relative in _launch_source_paths(repo_root).items():
        access_mode = os.R_OK if name == "friday_postflight" else os.X_OK
        access_label = "readable" if name == "friday_postflight" else "executable"
        try:
            content = _read_stable_regular_file(
                repo_root,
                relative,
                label="automation launch source",
                access_mode=access_mode,
                access_label=access_label,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"launch source changed after replan: {relative.as_posix()}"
            ) from exc
        expected_sha256 = summary["launch_sources"][name]["source_sha256"]
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError(f"launch source changed after replan: {relative.as_posix()}")


def _reconcile_units(home: Path, source_snapshots: dict[str, bytes]) -> list[str]:
    """Compare and publish units through one retained destination descriptor."""
    with _open_unit_directory(home) as (unit_dir_fd, unit_dir_identity):
        changed = _changed_unit_snapshots(unit_dir_fd, source_snapshots)
        for unit, content in changed.items():
            _install_unit_snapshot(unit_dir_fd, unit, content)
        if not _unit_directory_unchanged(home, unit_dir_identity):
            raise RuntimeError("service unit directory changed after replan")
    return sorted(changed)


def _refresh_and_install_crontab(repo_root: Path) -> bool:
    """Merge managed entries into the latest readable crontab before replacement."""
    current = _read_crontab()
    desired = render_crontab(current, repo_root)
    if desired == current:
        return False
    _checked(["crontab", "-"], input_text=desired)
    return True


def _current_service_changes(units: list[str]) -> tuple[list[str], list[str]]:
    """Return units that need enabling or starting at the mutation boundary."""
    enabled = {unit: _service_state("is-enabled", unit) for unit in units}
    active = {unit: _service_state("is-active", unit) for unit in units}
    return (
        sorted(unit for unit, state in enabled.items() if state != "enabled"),
        sorted(unit for unit, state in active.items() if state != "active"),
    )


def apply(summary: dict, _desired_crontab: str, repo_root: Path, home: Path) -> dict:
    """Apply a validated plan; caller must have explicitly requested mutation."""
    # The caller may have displayed an earlier dry-run. Re-read every source and
    # host prerequisite immediately before mutation so that stale plan data cannot
    # authorize writes or discard a newer unrelated crontab entry.
    summary, _desired_crontab = plan(repo_root, home)
    if summary["errors"]:
        raise RuntimeError("refusing invalid automation plan")
    _verify_launch_sources(repo_root, summary)
    source_snapshots = _snapshot_unit_sources(repo_root, summary)
    changed_units = _reconcile_units(home, source_snapshots)
    summary["changes"]["service_units"] = changed_units
    if _refresh_and_install_crontab(repo_root):
        summary["changes"]["crontab"] = True
    if _linger_state() != "yes":
        _checked(["loginctl", "enable-linger", str(os.getuid())])
        summary["changes"]["enable_linger"] = True
    units = sorted(AUTOSTART_UNITS)
    enable_units, start_units = _current_service_changes(units)
    summary["changes"]["enable_units"] = enable_units
    summary["changes"]["start_units"] = start_units
    if changed_units:
        _checked(["systemctl", "--user", "daemon-reload"])
    if enable_units:
        _checked(["systemctl", "--user", "enable", *enable_units])
    changed = set(changed_units) & AUTOSTART_UNITS
    if changed:
        _checked(["systemctl", "--user", "restart", *sorted(changed)])
    inactive_unchanged = sorted(set(start_units) - changed)
    if inactive_unchanged:
        _checked(["systemctl", "--user", "start", *inactive_unchanged])
    scheduler, installed, linger = _verify_applied(repo_root, home, units)
    return {
        **summary,
        "status": "ok",
        "applied": True,
        "service_units": installed,
        "linger": linger,
        "scheduler": scheduler,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--apply", action="store_true", help="install the reported changes")
    args = parser.parse_args(argv)

    summary, desired_crontab = plan(args.repo_root, args.home)
    if args.apply and not summary["errors"]:
        try:
            summary = apply(
                summary, desired_crontab, args.repo_root.resolve(), args.home.resolve()
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            summary = {**summary, "status": "failed", "errors": [*summary["errors"], str(exc)]}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
