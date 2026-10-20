"""Read-only host probes used by scheduler continuity monitoring."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .host_command import bounded_printable_line, run_bounded

CRON_SERVICE_UNITS = ("cron", "crond")
PUBLIC_TIMEZONE_MAX_CHARS = 255
CRON_SERVICE_LOAD_STATES = frozenset(
    {"bad-setting", "error", "loaded", "masked", "merged", "not-found", "stub"}
)
CRON_SERVICE_STATES = frozenset(
    {
        "active",
        "activating",
        "deactivating",
        "failed",
        "inactive",
        "maintenance",
        "refreshing",
        "reloading",
    }
)
CRON_SERVICE_ENABLEMENT_STATES = frozenset(
    {
        "disabled",
        "enabled",
        "enabled-runtime",
        "generated",
        "indirect",
        "linked",
        "linked-runtime",
        "masked",
        "masked-runtime",
        "static",
        "transient",
    }
)
_ZERO_EXIT_ENABLEMENT_STATES = frozenset(
    {"enabled", "enabled-runtime", "generated", "indirect", "static", "transient"}
)


def _exact_output_line(result, *, max_chars: int) -> str | None:
    """Accept one canonical stdout line only when no diagnostic was emitted."""
    if result.stderr or not result.stdout.endswith("\n") or result.stdout.count("\n") != 1:
        return None
    value = result.stdout[:-1]
    return value if bounded_printable_line(value, max_chars=max_chars) == value else None


def _service_observation(result) -> tuple[str, str] | None:
    """Decode one atomic systemd load/active-state observation."""
    if result.returncode != 0 or result.stderr or not result.stdout.endswith("\n"):
        return None
    properties = {}
    for line in result.stdout.splitlines():
        name, separator, value = line.partition("=")
        if (
            not separator
            or name not in {"LoadState", "ActiveState"}
            or name in properties
            or bounded_printable_line(value, max_chars=PUBLIC_TIMEZONE_MAX_CHARS) != value
        ):
            return None
        properties[name] = value
    if set(properties) != {"LoadState", "ActiveState"}:
        return None
    load_state = properties["LoadState"]
    active_state = properties["ActiveState"]
    if load_state not in CRON_SERVICE_LOAD_STATES or active_state not in CRON_SERVICE_STATES:
        return None
    if load_state == "not-found" and active_state != "inactive":
        return None
    return load_state, active_state


def _is_absent_crontab(result) -> bool:
    if result.returncode != 1 or result.stdout:
        return False
    message = bounded_printable_line(result.stderr, max_chars=PUBLIC_TIMEZONE_MAX_CHARS)
    return bool(message and message.startswith("no crontab for "))


def read_user_crontab() -> tuple[str | None, str | None]:
    """Return the installed user crontab or a stable fail-closed reason."""
    result = run_bounded(["crontab", "-l"])
    if result is None:
        return None, "crontab-unreadable"
    if result.returncode == 0 and not result.stderr:
        return result.stdout, None
    if _is_absent_crontab(result):
        return "", None
    return None, "crontab-unreadable"


def cron_service() -> tuple[str, str | None]:
    """Find the host's cron service and report its observed active state."""
    observed: list[tuple[str, str]] = []
    for unit in CRON_SERVICE_UNITS:
        result = run_bounded(
            [
                "systemctl",
                "show",
                unit,
                "--property=LoadState",
                "--property=ActiveState",
            ]
        )
        if result is None:
            if observed:
                continue
            return "unknown", None
        observation = _service_observation(result)
        if observation is None:
            if observed:
                continue
            return "unknown", None
        load_state, state = observation
        if load_state == "not-found":
            continue
        if state == "active":
            return state, unit
        observed.append((state, unit))
    return observed[0] if observed else ("unknown", None)


def system_timezone() -> str:
    """Read the system timezone without changing host configuration."""
    result = run_bounded(["timedatectl", "show", "--property=Timezone", "--value"])
    if result is None or result.returncode != 0:
        return "unknown"
    timezone_name = _exact_output_line(result, max_chars=PUBLIC_TIMEZONE_MAX_CHARS)
    return timezone_name if timezone_name is not None else "unknown"


def service_enabled(unit: str | None) -> str:
    """Read whether the selected cron service is enabled for boot."""
    if unit is None:
        return "unknown"
    result = run_bounded(["systemctl", "is-enabled", unit])
    if result is None:
        return "unknown"
    state = _exact_output_line(result, max_chars=PUBLIC_TIMEZONE_MAX_CHARS)
    if state not in CRON_SERVICE_ENABLEMENT_STATES:
        return "unknown"
    expected_zero = state in _ZERO_EXIT_ENABLEMENT_STATES
    return state if (result.returncode == 0) == expected_zero else "unknown"


USER_UNIT_NAME_RE = re.compile(r"[A-Za-z0-9:_.@\\-]{1,255}\.[a-z]+")
BACKUP_STATE_MAX_BYTES = 65_536
BACKUP_STATE_STATUSES = frozenset({"ok", "retry", "failed"})


def user_unit_enablement(units: tuple[str, ...]) -> dict[str, str] | None:
    """Read the boot enablement of named user units in one query, or None."""
    if not units:
        return {}
    result = run_bounded(
        ["systemctl", "--user", "show", "--property=Id", "--property=UnitFileState", "--", *units]
    )
    if result is None or result.returncode != 0 or result.stderr:
        return None
    states: dict[str, str] = {}
    for block in result.stdout.strip("\n").split("\n\n"):
        properties = dict(line.partition("=")[::2] for line in block.splitlines())
        unit = properties.get("Id")
        if unit not in units or unit in states or set(properties) != {"Id", "UnitFileState"}:
            return None
        state = properties["UnitFileState"] or "not-found"
        states[unit] = (
            state if state in CRON_SERVICE_ENABLEMENT_STATES | {"not-found"} else "unknown"
        )
    return states if set(states) == set(units) else None


def failed_user_units() -> tuple[str, ...] | None:
    """List this user's units in the failed state, or None when unreadable."""
    result = run_bounded(
        ["systemctl", "--user", "list-units", "--state=failed", "--all", "--plain",
         "--no-legend", "--full"]
    )
    if result is None or result.returncode != 0 or result.stderr:
        return None
    units = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        unit = line.split()[0]
        if not USER_UNIT_NAME_RE.fullmatch(unit):
            return None
        units.add(unit)
    return tuple(sorted(units))


def _utc_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def backup_state(path: Path) -> tuple[str, str | None]:
    """Return the backup script's last recorded status and when it was written."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(BACKUP_STATE_MAX_BYTES + 1)
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "unknown", None
    if len(raw) > BACKUP_STATE_MAX_BYTES:
        return "unknown", None
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return "unknown", None
    if not isinstance(state, dict) or state.get("status") not in BACKUP_STATE_STATUSES:
        return "unknown", None
    return state["status"], _utc_timestamp(state.get("at"))


def last_backup_commit(repository: Path) -> str | None:
    """Return the commit time of the newest backup commit in the data repository."""
    result = run_bounded(
        ["git", "-C", str(repository), "log", "-1", "--format=%cI", "--grep=^backup "]
    )
    if result is None or result.returncode != 0 or result.stderr:
        return None
    return _utc_timestamp(result.stdout.strip())
