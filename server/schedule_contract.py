"""Host and schedule contract: what may run on the engine host, and which live store it may hold.

``server/schedule-contract.json`` lists every user unit, timer and cron line on the host,
including ones other repositories install, with its state (enabled, held or disabled, with a
reason), its declared store access and the windows in which it may hold a live database. Two
checks read it:

- ``static_check`` compares the manifest with this checkout's unit files: every timer-driven
  unit is bounded, no unit runs from a lane worktree, no unit stops or conflicts with a live
  unit, the installer's autostart set is the manifest's, and every unit file is declared.
- ``live_check`` compares it with the host, read-only: ``systemctl --user show`` and
  ``list-*``, ``crontab -l`` and a ``/proc/*/fd`` scan. The scan only reads links, so it never
  opens a database file, and any process holding ``store/market.duckdb`` or
  ``store/pit/*.duckdb`` that is not a declared unit or cron job inside its window is reported
  with its pid, command line and cgroup.

Standard library only (``tests/test_schedule_contract.py`` checks that DuckDB is never imported):
the live probe runs inside the hourly ops digest and must never take a store handle itself.
"""

from __future__ import annotations

import fnmatch
import json
import math
import os
import re
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

MANIFEST_PATH = Path(__file__).resolve().with_name("schedule-contract.json")
# Optional host-local overlay for units another project installs on this host. It may only
# add external units; it never redeclares or silences a unit of this repository.
OVERLAY_PATH = Path.home() / ".config" / "trading-engine" / "schedule-contract.local.json"
OVERLAY_MAX_BYTES = 65_536
OVERLAY_KEYS = frozenset({"unit", "owner", "reason", "state", "activation", "timer", "service",
                          "calendar", "max_runtime", "window_minutes", "store", "acknowledge"})
# Rules an overlay entry may acknowledge for its own unit: where another project runs from
# and how long it may run are that project's decision. Store holders are never acknowledged.
OVERLAY_ACKNOWLEDGEABLE = frozenset({"lane-path", "unbounded"})
STATES = frozenset({"enabled", "held", "disabled"})
ACCESS = frozenset({"writer", "reader", "none"})
ACTIVATIONS = frozenset({"boot", "timer", "manual", "slice"})
WINDOW_SLACK_MINUTES = 5
RESULT_STALE_AFTER_MINUTES = 150
PUBLIC_VIOLATION_LIMIT = 20
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_ANCESTORS = 32
STATIC_RULES = frozenset({
    "manifest-invalid", "unit-not-in-manifest", "manifest-source-missing", "unbounded",
    "max-runtime-drift", "lane-path", "stops-live-unit", "held-autostart", "autostart-drift",
    "timer-drift", "state-drift", "cron-drift",
})
LIVE_RULES = frozenset({
    "not-installed", "not-enabled", "not-active", "held-enabled", "held-active", "failed",
    "off-manifest-unit", "off-manifest-cron", "missing-cron", "duplicate-cron", "held-cron",
    "lane-path", "unbounded", "max-runtime-drift", "stops-live-unit", "foreign-holder",
    "held-holder", "undeclared-holder", "undeclared-writer", "holder-outside-window",
})
PUBLIC_STATUSES = frozenset({"ok", "violations", "error", "stale", "absent", "invalid"})
UNIT_SUFFIXES = (".service", ".timer", ".slice", ".socket", ".path", ".target")
EXEC_KEYS = ("ExecStartPre", "ExecStart", "ExecStartPost", "ExecStop", "ExecStopPost",
             "ExecReload", "WorkingDirectory")
STOP_VERBS = frozenset({"stop", "kill", "disable", "mask", "isolate", "restart", "try-restart",
                        "reload-or-restart", "freeze"})
SHOW_PROPERTIES = ("Id", "LoadState", "ActiveState", "SubState", "UnitFileState", "Type",
                   "ConditionResult", "Result",
                   "TimeoutStartUSec", "RuntimeMaxUSec", "Conflicts", "Triggers", *EXEC_KEYS)
_SPAN_UNITS = {"": 1.0, "us": 1e-6, "usec": 1e-6, "ms": 1e-3, "msec": 1e-3, "s": 1.0,
               "sec": 1.0, "m": 60.0, "min": 60.0, "h": 3600.0, "hr": 3600.0, "d": 86400.0,
               "w": 604800.0}
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str] | None"]
Matcher = Callable[[datetime], bool]


# --------------------------------------------------------------------------- manifest
def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text())


def _units(manifest: dict) -> dict[str, dict]:
    return {entry["unit"]: entry for entry in manifest["units"]}


def _installable(entry: dict) -> bool:
    return entry["unit"].endswith(".timer") or entry.get("activation") == "boot"


def unit_sources(manifest: dict | None = None) -> dict[str, Path]:
    """Repository unit files the installer copies into the user unit directory."""
    manifest = manifest or load_manifest()
    return {entry["unit"]: Path(entry["source"]) for entry in manifest["units"]
            if entry["origin"] == "repo"}


def autostart_units(manifest: dict | None = None) -> frozenset[str]:
    """Repository units the installer enables and starts: enabled timers and boot services."""
    manifest = manifest or load_manifest()
    return frozenset(entry["unit"] for entry in manifest["units"] if entry["origin"] == "repo"
                     and entry["state"] == "enabled" and _installable(entry))


def completing_units(manifest: dict | None = None) -> frozenset[str]:
    """Finite boot units: done (start condition unmet) or between runs counts as running."""
    manifest = manifest or load_manifest()
    return frozenset(entry["unit"] for entry in manifest["units"] if entry.get("completes"))


def held_units(manifest: dict | None = None) -> frozenset[str]:
    """Repository units installed but left alone until the blocker in their reason is fixed."""
    manifest = manifest or load_manifest()
    return frozenset(entry["unit"] for entry in manifest["units"] if entry["origin"] == "repo"
                     and entry["state"] == "held" and _installable(entry))


def _violation(rule: str, subject: str, **detail) -> dict:
    return {"rule": rule, "subject": subject, "detail": detail}


def _schema_issues(manifest: dict) -> list[dict]:
    issues = []
    units = _units(manifest)
    cron_names = [entry.get("name") for entry in manifest.get("cron", [])]
    if len(units) != len(manifest["units"]) or len(set(cron_names)) != len(cron_names):
        issues.append(_violation("manifest-invalid", "manifest", problem="duplicate entry"))
    for entry in [*manifest["units"], *manifest.get("cron", [])]:
        name = entry.get("unit") or entry.get("name") or "?"
        problems = []
        if entry.get("state") not in STATES:
            problems.append("state")
        if entry.get("state") in {"held", "disabled"} and not entry.get("reason"):
            problems.append("held or disabled without a reason")
        if entry.get("origin") not in {"repo", "external"}:
            problems.append("origin")
        if "unit" in entry and entry["origin"] == "repo" and Path(
                entry.get("source", "")).name != name:
            problems.append("source")
        if "unit" in entry and not name.endswith(".timer") and entry.get(
                "activation") not in ACTIVATIONS:
            problems.append("activation")
        if name.endswith(".timer"):
            service = units.get(entry.get("service", ""))
            if service is None or service.get("timer") != name:
                problems.append("timer and service do not name each other")
            else:
                try:
                    _ = [calendar_matcher(spec) for spec in entry.get("calendar", [])]
                except (ValueError, KeyError):
                    problems.append("calendar")
        elif entry.get("activation") == "timer" and entry.get("timer") not in units:
            problems.append("timer")
        if "completes" in entry and (
                entry["completes"] is not True or entry.get("activation") != "boot"
                or not all(isinstance(entry.get(key), str) and entry[key]
                           for key in ("completion_marker", "completion_manifest"))):
            problems.append("completes")
        if "max_runtime" in entry and entry["max_runtime"] is not None and span_seconds(
                entry["max_runtime"]) is None:
            problems.append("max_runtime")
        store = entry.get("store")
        if not name.endswith(".timer"):
            problems += _store_problems(entry, store, units)
        if problems:
            issues.append(_violation("manifest-invalid", name, problem=", ".join(problems)))
    return issues


def _store_problems(entry: dict, store: dict | None, units: dict[str, dict]) -> list[str]:
    if not isinstance(store, dict) or store.get("access") not in ACCESS:
        return ["store"]
    writes, reads = store.get("writes", []), store.get("reads", [])
    expected = "writer" if writes else "reader" if reads else "none"
    if store["access"] != expected:
        return ["store access does not match writes and reads"]
    if expected == "none":
        return []
    windows = store.get("windows")
    if windows == "always":
        return []
    if windows != "schedule" or span_seconds(entry.get("max_runtime") or "") is None:
        return ["store windows"]
    if _schedule_matcher(entry, units) is None:
        return ["schedule window without a calendar or cron schedule"]
    return []


# --------------------------------------------------------------------------- local overlay
def _overlay_text(path: Path) -> str | None:
    """The overlay's text, None when absent; refuses links, other owners and open modes."""
    try:
        # O_NONBLOCK: a FIFO or device in its place must not block the hourly check.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"unreadable or a symbolic link ({exc.strerror})") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        if info.st_uid != os.getuid():
            raise ValueError("not owned by this user")
        if info.st_mode & 0o077:
            raise ValueError(f"mode {stat.S_IMODE(info.st_mode):o} is not owner-only")
        raw = handle.read(OVERLAY_MAX_BYTES + 1)
    if len(raw) > OVERLAY_MAX_BYTES:
        raise ValueError("larger than 64 KiB")
    return raw.decode("utf-8")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate key {sorted(k for k in keys if keys.count(k) > 1)[0]!r}")
    return dict(pairs)


def _overlay_entry(item: object, reserved: set[str]) -> dict:
    if not isinstance(item, dict) or not set(item) <= OVERLAY_KEYS:
        raise ValueError("an entry is not an object of known keys")
    name = item.get("unit")
    if not isinstance(name, str) or "/" in name or not name.endswith(UNIT_SUFFIXES):
        raise ValueError(f"invalid unit name {name!r}")
    if name in reserved or re.match(r"trading-engine[-@.]", name):
        raise ValueError(f"{name} belongs to this repository's manifest")
    # An overlay unit never holds a store: a declared store would excuse a foreign holder.
    if name.endswith(".timer") and "store" in item:
        raise ValueError(f"{name}: a timer declares no store")
    if not name.endswith(".timer") and item.get("store") != {"access": "none"}:
        raise ValueError(f'{name}: an overlay unit must declare store {{"access": "none"}}')
    for key in ("owner", "reason"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f"{name} needs a non-empty {key}")
    acknowledge = item.get("acknowledge", [])
    if not isinstance(acknowledge, list) or not set(acknowledge) <= OVERLAY_ACKNOWLEDGEABLE:
        raise ValueError(f"{name} may acknowledge only {sorted(OVERLAY_ACKNOWLEDGEABLE)}")
    entry = {key: value for key, value in item.items()
             if key not in {"owner", "acknowledge"}}
    entry.update(origin="external", managed_by=item["owner"], local_overlay=True)
    reason = f"host-local unit of {item['owner']}: {item['reason']}"
    entry["pinned_exception"] = [{"rule": rule, "reason": reason} for rule in acknowledge]
    return entry


def apply_overlay(manifest: dict, path: Path | None, repo_units: set[str] = frozenset()
                  ) -> tuple[dict, dict]:
    """Merge the optional local overlay into a copy of the manifest, with a status report.

    An invalid overlay is ignored as a whole and reported, never half-applied.
    """
    report = {"path": str(path) if path else None, "status": "absent", "units": [],
              "error": None}
    if path is None:
        return manifest, report
    try:
        text = _overlay_text(path)
        if text is None:
            return manifest, report
        document = json.loads(text, object_pairs_hook=_unique_keys)
        if (not isinstance(document, dict) or set(document) != {"version", "units"}
                or document["version"] != 1 or not isinstance(document["units"], list)):
            raise ValueError('expected {"version": 1, "units": [...]}')
        reserved = set(_units(manifest)) | set(repo_units)
        entries = [_overlay_entry(item, reserved) for item in document["units"]]
        merged = {**manifest, "units": [*manifest["units"], *entries]}
        names = {entry["unit"] for entry in entries}
        issues = [item for item in _schema_issues(merged) if item["subject"] in names
                  or item["subject"] == "manifest"]
        if issues:
            raise ValueError("; ".join(f"{item['subject']}: {item['detail']['problem']}"
                                       for item in issues))
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError,
            RecursionError, MemoryError) as exc:
        error = str(exc) if not isinstance(exc, RecursionError) else "nested too deeply"
        return manifest, {**report, "status": "invalid", "error": error[:300]}
    return merged, {**report, "status": "loaded", "units": [
        {"unit": entry["unit"], "owner": entry["managed_by"], "reason": entry["reason"],
         "acknowledged": sorted(rule["rule"] for rule in entry["pinned_exception"])}
        for entry in entries]}


# --------------------------------------------------------------------------- time
def span_seconds(text: str) -> float | None:
    """Seconds in a systemd time span; None for infinity, zero or an unparsable value."""
    text = str(text).strip().lower()
    if not text or text == "infinity":
        return None
    total = 0.0
    position = 0
    for match in re.finditer(r"\s*(\d+(?:\.\d+)?)\s*([a-z]*)", text):
        if match.start() != position or match.group(2) not in _SPAN_UNITS:
            return None
        total += float(match.group(1)) * _SPAN_UNITS[match.group(2)]
        position = match.end()
    return total if position == len(text) and total > 0 else None


def _field(text: str, low: int, high: int, names: tuple[str, ...] = (),
           separator: str = "..") -> frozenset[int] | None:
    if text == "*":
        return None

    def value(token: str) -> int:
        key = token.lower()[:3]
        number = names.index(key) if key in names else int(token)
        if not low <= number <= high:
            raise ValueError(f"out of range: {token}")
        return number

    allowed: set[int] = set()
    for item in text.split(","):
        part, _, step = item.partition("/")
        bounds = [low, high] if part == "*" else [value(b) for b in part.split(separator)]
        last = high if step and len(bounds) == 1 else bounds[-1]
        allowed.update(range(bounds[0], last + 1, int(step or 1)))
    return frozenset(allowed)


def _allows(allowed: frozenset[int] | None, value: int) -> bool:
    return allowed is None or value in allowed


def calendar_matcher(spec: str) -> Matcher:
    """Match whole minutes against an ``OnCalendar`` spec: ``[DOW] Y-M-D H:M[:S] [TZ]``."""
    tokens = spec.split()
    zone = UTC
    if len(tokens) > 1 and ":" not in tokens[-1] and "-" not in tokens[-1]:
        name = tokens.pop()
        zone = UTC if name == "UTC" else ZoneInfo(name)
    weekdays = None
    if len(tokens) == 3:
        weekdays = _field(tokens.pop(0), 0, 6, _WEEKDAYS)
    if len(tokens) != 2 or "-" not in tokens[0] or ":" not in tokens[1]:
        raise ValueError(f"unsupported calendar {spec!r}")
    year, month, day = (_field(text, low, high) for text, low, high in zip(
        tokens[0].split("-"), (1970, 1, 1), (2199, 12, 31), strict=True))
    clock = tokens[1].split(":")
    if len(clock) not in (2, 3) or (len(clock) == 3 and clock[2] not in {"0", "00"}):
        raise ValueError(f"unsupported calendar {spec!r}")
    hour, minute = _field(clock[0], 0, 23), _field(clock[1], 0, 59)

    def matcher(moment: datetime) -> bool:
        local = moment.astimezone(zone)
        return (_allows(weekdays, local.weekday()) and _allows(year, local.year)
                and _allows(month, local.month) and _allows(day, local.day)
                and _allows(hour, local.hour) and _allows(minute, local.minute))
    return matcher


def cron_matcher(schedule: str) -> Matcher | None:
    """Match whole minutes against a five-field cron schedule in UTC; None for ``@reboot``."""
    if schedule == "@reboot":
        return None
    fields = schedule.split()
    if len(fields) != 5:
        raise ValueError(f"unsupported cron schedule {schedule!r}")
    minute, hour = _field(fields[0], 0, 59, separator="-"), _field(fields[1], 0, 23, separator="-")
    day, month = _field(fields[2], 1, 31, separator="-"), _field(fields[3], 1, 12, separator="-")
    cron_days = _field(fields[4], 0, 7, separator="-")
    weekdays = None if cron_days is None else frozenset((d + 6) % 7 for d in cron_days)

    def matcher(moment: datetime) -> bool:
        local = moment.astimezone(UTC)
        if not (_allows(minute, local.minute) and _allows(hour, local.hour)
                and _allows(month, local.month)):
            return False
        on_day, on_weekday = _allows(day, local.day), _allows(weekdays, local.weekday())
        if day is not None and weekdays is not None:
            return on_day or on_weekday
        return on_day and on_weekday
    return matcher


def _schedule_matcher(entry: dict, units: dict[str, dict]) -> Matcher | None:
    if "schedule" in entry:
        return cron_matcher(entry["schedule"])
    timer = units.get(entry.get("timer", ""))
    specs = timer.get("calendar", []) if timer else []
    if not specs:
        return None
    matchers = [calendar_matcher(spec) for spec in specs]
    return lambda moment: any(matcher(moment) for matcher in matchers)


def in_window(entry: dict, units: dict[str, dict], now: datetime) -> bool:
    """Whether ``now`` lies in one of the entry's declared store windows."""
    windows = entry.get("store", {}).get("windows")
    if windows == "always":
        return True
    matcher = _schedule_matcher(entry, units)
    if windows != "schedule" or matcher is None:
        return False
    span = entry.get("window_minutes") or math.ceil(
        span_seconds(entry["max_runtime"]) / 60) + WINDOW_SLACK_MINUTES
    minute = now.astimezone(UTC).replace(second=0, microsecond=0)
    return any(matcher(minute - timedelta(minutes=back)) for back in range(span + 1))


# --------------------------------------------------------------------------- unit files
def parse_unit(text: str) -> dict[str, list[str]]:
    """Directive values of a unit file, in order, across all sections."""
    directives: dict[str, list[str]] = {}
    for raw in text.replace("\\\n", " ").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        directives.setdefault(key.strip(), []).append(value.strip())
    return directives


def _last(directives: dict[str, list[str]], key: str) -> str | None:
    values = directives.get(key)
    return values[-1] if values else None


def unit_bound_seconds(directives: dict[str, list[str]]) -> float | None:
    """The wall-clock bound systemd enforces on one run, or None when unbounded.

    Type=oneshot is bounded by TimeoutStartSec; every other type only by RuntimeMaxSec
    (systemd 241 stops applying TimeoutStartSec to Type=exec once execve succeeds).
    """
    if (_last(directives, "Type") or "simple") == "oneshot":
        value = _last(directives, "TimeoutStartSec") or _last(directives, "TimeoutSec")
    else:
        value = _last(directives, "RuntimeMaxSec")
    return None if value is None else span_seconds(value)


def _lane_paths(values: list[str], markers: list[str]) -> list[str]:
    return [value[:300] for value in values if any(marker in value for marker in markers)]


def _stops(directives: dict[str, list[str]], protected: set[str]) -> list[str]:
    """Live units this unit conflicts with or stops through systemctl."""
    hits = {name for value in directives.get("Conflicts", []) for name in value.split()
            if name in protected}
    for key in EXEC_KEYS[:-1]:
        for value in directives.get(key, []):
            words = [word.strip("'\";{}") for word in re.split(r"[\s;]+", value)]
            if not any(word.endswith("systemctl") for word in words):
                continue
            if not STOP_VERBS & set(words):
                continue
            hits.update(unit for unit in protected for word in words
                        if word and (word == unit or (any(c in word for c in "*?[")
                                                      and fnmatch.fnmatchcase(unit, word))))
    return sorted(hits)


def _protected(units: dict[str, dict], own: str) -> set[str]:
    return {name for name, entry in units.items() if entry["state"] == "enabled" and name != own}


def _apply_exceptions(units: dict[str, dict], violations: list[dict]) -> tuple[list, list]:
    kept, excepted = [], []
    for item in violations:
        entry = units.get(item["subject"], {})
        reason = next((rule["reason"] for rule in entry.get("pinned_exception", [])
                       if rule.get("rule") == item["rule"]), None)
        if reason:
            excepted.append({**item, "exception": reason})
        else:
            kept.append(item)
    return kept, excepted


def _bounded_boot(entry: dict | None) -> bool:
    """A boot service that declares a runtime bound must enforce it like a timer's service."""
    return bool(entry and entry.get("activation") == "boot" and entry.get("max_runtime"))


def _repo_unit_files(repo_root: Path) -> dict[str, str]:
    files = {}
    for folder in ("server", "ui"):
        directory = repo_root / folder
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.name.endswith(UNIT_SUFFIXES):
                    files[f"{folder}/{path.name}"] = path.read_text()
    return files


def static_check(
    repo_root: Path, manifest: dict | None = None, *,
    autostart: frozenset[str] | None = None, expected_cron: dict[str, str] | None = None,
) -> dict:
    """Check the manifest against this checkout's unit files (and the installer, if given)."""
    manifest = manifest or load_manifest()
    units = _units(manifest)
    violations = _schema_issues(manifest)
    markers = manifest["lane_path_markers"]
    files = _repo_unit_files(repo_root)
    declared = {entry["source"]: name for name, entry in units.items() if entry["origin"] == "repo"}
    for source, name in sorted(declared.items()):
        if not (repo_root / source).is_file():
            violations.append(_violation("manifest-source-missing", name, source=source))
    parsed = {Path(source).name: parse_unit(text) for source, text in files.items()}
    triggered = {}
    for source in files:
        name = Path(source).name
        if source not in declared:
            violations.append(_violation("unit-not-in-manifest", name, source=source))
        if name.endswith(".timer"):
            triggered[_last(parsed[name], "Unit") or name.removesuffix(".timer") + ".service"] = name
    for name, directives in sorted(parsed.items()):
        entry = units.get(name)
        lane = _lane_paths([v for key in EXEC_KEYS for v in directives.get(key, [])], markers)
        if lane:
            violations.append(_violation("lane-path", name, paths=lane))
        stopped = _stops(directives, _protected(units, name))
        if stopped:
            violations.append(_violation("stops-live-unit", name, stops=stopped))
        if name.endswith(".timer") and entry is not None:
            target = _last(directives, "Unit") or name.removesuffix(".timer") + ".service"
            calendar = directives.get("OnCalendar", [])
            if target != entry.get("service") or calendar != entry.get("calendar", []):
                violations.append(_violation("timer-drift", name, unit=target, calendar=calendar))
        if name in triggered or _bounded_boot(entry):
            bound = unit_bound_seconds(directives)
            declared_max = span_seconds((entry or {}).get("max_runtime") or "")
            if bound is None:
                violations.append(_violation("unbounded", name, type=_last(directives, "Type")))
            elif entry is not None and declared_max != bound:
                violations.append(_violation("max-runtime-drift", name, unit_seconds=bound,
                                             declared_seconds=declared_max))
    for name, entry in sorted(units.items()):
        timer = units.get(entry.get("timer", ""))
        if timer is not None and timer["state"] != entry["state"]:
            violations.append(_violation("state-drift", name, timer_state=timer["state"],
                                         state=entry["state"]))
    if autostart is not None:
        expected = autostart_units(manifest)
        held = {name for name, entry in units.items() if entry["state"] != "enabled"}
        for name in sorted(autostart - expected):
            rule = "held-autostart" if name in held else "autostart-drift"
            violations.append(_violation(rule, name, state=units.get(name, {}).get("state")))
        for name in sorted(expected - autostart):
            violations.append(_violation("autostart-drift", name, missing_from_installer=True))
    if expected_cron is not None:
        violations += _cron_drift(manifest, expected_cron, repo_root)
    kept, excepted = _apply_exceptions(units, violations)
    return {"violations": kept, "exceptions": excepted, "errors": [],
            "counts": {"unit_files": len(files), "manifest_units": len(units)}}


def _cron_drift(manifest: dict, expected_cron: dict[str, str], repo_root: Path) -> list[dict]:
    entries = {entry["name"]: entry for entry in manifest.get("cron", [])
               if entry["origin"] == "repo"}
    drift = []
    for name in sorted(set(entries) | set(expected_cron)):
        entry, line = entries.get(name), expected_cron.get(name)
        if entry is None or line is None:
            drift.append(_violation("cron-drift", f"cron:{name}", declared=entry is not None,
                                    managed=line is not None))
            continue
        match = entry["match"].format(engine=repo_root, home=repo_root.parent)
        if " ".join(line.split()[:5]) != entry["schedule"] or match not in line:
            drift.append(_violation("cron-drift", f"cron:{name}", schedule=entry["schedule"]))
    return drift


# --------------------------------------------------------------------------- live probe
def _run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None


def _show_blocks(text: str) -> dict[str, dict[str, list[str]]]:
    blocks: dict[str, dict[str, list[str]]] = {}
    for chunk in text.split("\n\n"):
        properties: dict[str, list[str]] = {}
        for line in chunk.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                properties.setdefault(key, []).append(value)
        if properties.get("Id"):
            blocks[properties["Id"][0]] = properties
    return blocks


def _prop(block: dict[str, list[str]], key: str) -> str:
    values = block.get(key) or [""]
    return values[0]


def _listed_units(text: str) -> dict[str, str]:
    listed = {}
    for line in text.splitlines():
        parts = line.replace("●", " ").split()
        if parts and parts[0].endswith(UNIT_SUFFIXES):
            listed[parts[0]] = parts[1] if len(parts) > 1 else ""
    return listed


def _live_bound(block: dict[str, list[str]]) -> float | None:
    if _prop(block, "Type") == "oneshot":
        return span_seconds(_prop(block, "TimeoutStartUSec"))
    return span_seconds(_prop(block, "RuntimeMaxUSec"))


COMPLETION_MAX_BYTES = 4 * 1024 * 1024


def _json_file(path: Path) -> dict | None:
    text = _read(path, COMPLETION_MAX_BYTES + 1)
    if text is None or len(text) > COMPLETION_MAX_BYTES:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def completion_recorded(entry: dict, engine_root: Path) -> bool:
    """The unit's completion marker exists and names the manifest it was run for."""
    marker = _json_file(engine_root / entry["completion_marker"])
    manifest = _json_file(engine_root / entry["completion_manifest"])
    identity = None if manifest is None else manifest.get("manifest_sha256")
    return (marker is not None and isinstance(identity, str) and bool(identity)
            and marker.get("manifest_sha256") == identity)


def completed_or_resuming(entry: dict, block: dict[str, list[str]], engine_root: Path) -> bool:
    """A finite boot unit (``completes``) between runs: waiting to restart, or done.

    Waiting counts only after a successful run (``Result=success``; a paused exit 75 is a
    success through ``SuccessExitStatus``): a crash or a runtime-bound kill waiting to restart
    is still a failure. Done means its start condition failed and its completion marker
    names the current manifest, so a unit that was never started is not done. A unit
    merely stopped is still ``not-active``.
    """
    if not entry.get("completes"):
        return False
    active = _prop(block, "ActiveState")
    if active == "activating" and _prop(block, "SubState") == "auto-restart":
        return _prop(block, "Result") == "success"
    return (active == "inactive" and _prop(block, "ConditionResult") == "no"
            and completion_recorded(entry, engine_root))


def _host_unit(manifest: dict, name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, item["pattern"]) for item in manifest["host_units"])


def _unit_violations(manifest: dict, blocks: dict[str, dict[str, list[str]]],
                     engine_root: Path) -> list[dict]:
    units = _units(manifest)
    markers = manifest["lane_path_markers"]
    violations = []
    for name, entry in sorted(units.items()):
        block = blocks.get(name)
        if block is None or entry.get("activation") in {"manual", "slice"}:
            continue
        load, active = _prop(block, "LoadState"), _prop(block, "ActiveState")
        file_state = _prop(block, "UnitFileState")
        running = active in {"active", "activating", "reloading"}
        if entry["state"] != "enabled":
            if _installable(entry) and file_state == "enabled":
                violations.append(_violation("held-enabled", name, unit_file_state=file_state))
            if running:
                violations.append(_violation("held-active", name, active_state=active))
        elif _installable(entry):
            if load == "not-found":
                violations.append(_violation("not-installed", name))
            elif file_state != "enabled":
                violations.append(_violation("not-enabled", name, unit_file_state=file_state))
            elif active != "active" and not completed_or_resuming(entry, block, engine_root):
                violations.append(_violation("not-active", name, active_state=active))
    triggered = {target for block in blocks.values() if _prop(block, "Id").endswith(".timer")
                 for value in block.get("Triggers", []) for target in value.split()}
    for name, block in sorted(blocks.items()):
        if _host_unit(manifest, name):
            continue
        entry = units.get(name)
        active = _prop(block, "ActiveState")
        if active == "failed":
            violations.append(_violation("failed", name, sub_state=_prop(block, "SubState")))
        if entry is None and _prop(block, "LoadState") != "not-found" and (
                active in {"active", "activating", "reloading"}
                or _prop(block, "UnitFileState") in {"enabled", "enabled-runtime", "linked"}):
            violations.append(_violation("off-manifest-unit", name, active_state=active,
                                         unit_file_state=_prop(block, "UnitFileState")))
        if _prop(block, "LoadState") == "not-found":
            continue
        lane = _lane_paths([v for key in EXEC_KEYS for v in block.get(key, [])], markers)
        if lane:
            violations.append(_violation("lane-path", name, paths=lane))
        stopped = _stops(block, _protected(units, name))
        if stopped:
            violations.append(_violation("stops-live-unit", name, stops=stopped))
        if name in triggered or _bounded_boot(entry):
            bound = _live_bound(block)
            declared = span_seconds((entry or {}).get("max_runtime") or "")
            if bound is None:
                violations.append(_violation("unbounded", name, type=_prop(block, "Type")))
            elif declared is not None and bound > declared:
                violations.append(_violation("max-runtime-drift", name, unit_seconds=bound,
                                             declared_seconds=declared))
    return violations


def _root_forms(path: Path) -> list[str]:
    return sorted({str(path), os.path.realpath(path)}, key=len, reverse=True)


def _cron_matches(entry: dict, text: str, engine_root: Path, home: Path) -> bool:
    return any(entry["match"].format(engine=engine, home=house) in text
               for engine in _root_forms(engine_root) for house in _root_forms(home))


def _cron_violations(manifest: dict, crontab: str, engine_root: Path, home: Path) -> list[dict]:
    lines = []
    for raw in crontab.splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
            continue
        fields = line.split()
        schedule = fields[0] if line.startswith("@") else " ".join(fields[:5])
        command = fields[1:] if line.startswith("@") else fields[5:]
        lines.append((schedule, " ".join(command)))
    counts = dict.fromkeys((entry["name"] for entry in manifest.get("cron", [])), 0)
    violations = []
    for schedule, command in lines:
        owners = [entry for entry in manifest.get("cron", []) if entry["schedule"] == schedule
                  and _cron_matches(entry, command, engine_root, home)]
        for entry in owners:
            counts[entry["name"]] += 1
        if not owners:
            program = Path(command.split()[0]).name if command else "?"
            violations.append(_violation("off-manifest-cron", f"cron:{schedule} {program}",
                                         line=f"{schedule} {command}"))
    for entry in manifest.get("cron", []):
        name, count = entry["name"], counts[entry["name"]]
        if entry["state"] == "enabled" and count == 0:
            violations.append(_violation("missing-cron", f"cron:{name}"))
        elif entry["state"] == "enabled" and count > 1:
            violations.append(_violation("duplicate-cron", f"cron:{name}", count=count))
        elif entry["state"] != "enabled" and count:
            violations.append(_violation("held-cron", f"cron:{name}", count=count))
    return violations


def _read(path: Path, limit: int = 65_536) -> str | None:
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _audited(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern)
               and relative.count("/") == pattern.count("/") for pattern in patterns)


def scan_holders(proc_root: Path, engine_root: Path, patterns: list[str]) -> dict:
    """Processes with a descriptor on an audited live database, found by reading fd links."""
    roots = [form.rstrip("/") + "/" for form in _root_forms(engine_root)]
    holders: dict[tuple[int, str], str] = {}
    scanned = unreadable = 0
    try:
        pids = [name for name in os.listdir(proc_root) if name.isdigit()]
    except OSError:
        return {"holders": [], "scanned": 0, "unreadable": 0, "error": "proc unreadable"}
    for pid in pids:
        try:
            descriptors = os.listdir(proc_root / pid / "fd")
        except OSError:
            unreadable += 1
            continue
        scanned += 1
        for fd in descriptors:
            try:
                target = os.readlink(proc_root / pid / "fd" / fd)
            except OSError:
                continue
            target = target.removesuffix(" (deleted)").removesuffix(".wal")
            if not target.endswith(".duckdb"):
                continue
            relative = next((target[len(root):] for root in roots if target.startswith(root)),
                            None)
            if relative is None or not _audited(relative, patterns):
                continue
            mode = "unknown"
            info = _read(proc_root / pid / "fdinfo" / fd) or ""
            flags = re.search(r"^flags:\s*([0-7]+)", info, re.MULTILINE)
            if flags:
                mode = "write" if int(flags.group(1), 8) & 3 else "read"
            key = (int(pid), relative)
            if holders.get(key) != "write":
                holders[key] = mode
    return {"holders": [_process(proc_root, pid, database, mode)
                        for (pid, database), mode in sorted(holders.items())],
            "scanned": scanned, "unreadable": unreadable, "error": None}


def _cmdline(proc_root: Path, pid: int) -> str:
    raw = _read(proc_root / str(pid) / "cmdline") or ""
    return " ".join(part for part in raw.split("\0") if part)[:400]


def _parent(proc_root: Path, pid: int) -> int | None:
    stat_text = _read(proc_root / str(pid) / "stat") or ""
    fields = stat_text.rpartition(")")[2].split()
    return int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None


def _cgroup_unit(cgroup: str) -> str | None:
    for line in cgroup.splitlines():
        parts = line.split(":", 2)[-1].split("/")
        if any(part.startswith("user@") for part in parts):
            units = [part for part in parts if part.endswith((".service", ".scope"))
                     and not part.startswith("user@")]
            if units:
                return units[-1]
    return None


def _process(proc_root: Path, pid: int, database: str, mode: str) -> dict:
    cgroup = (_read(proc_root / str(pid) / "cgroup") or "").strip()
    ancestors, current = [], _parent(proc_root, pid)
    while current and current > 1 and len(ancestors) < MAX_ANCESTORS:
        ancestors.append(_cmdline(proc_root, current))
        current = _parent(proc_root, current)
    return {"pid": pid, "database": database, "mode": mode, "cmdline": _cmdline(proc_root, pid),
            "cgroup": cgroup.splitlines()[-1] if cgroup else "", "unit": _cgroup_unit(cgroup),
            "ancestors": ancestors}


def holder_violations(manifest: dict, holders: list[dict], *, now: datetime,
                      engine_root: Path, home: Path) -> list[dict]:
    """Every holder that is not a declared, enabled unit or cron job inside its window."""
    units = _units(manifest)
    violations = []
    for holder in holders:
        entry = units.get(holder["unit"] or "")
        subject = holder["unit"] if entry else None
        if entry is None and holder["unit"] is None:
            for text in [holder["cmdline"], *holder["ancestors"]]:
                entry = next((item for item in manifest.get("cron", [])
                              if _cron_matches(item, text, engine_root, home)), None)
                if entry:
                    subject = f"cron:{entry['name']}"
                    break
        detail = {key: holder[key] for key in ("pid", "database", "mode", "cmdline", "cgroup")}
        store = (entry or {}).get("store", {})
        if entry is None:
            rule, subject = "foreign-holder", holder["unit"] or f"pid {holder['pid']}"
        elif entry["state"] != "enabled":
            rule = "held-holder"
        elif holder["database"] not in [*store.get("writes", []), *store.get("reads", [])]:
            rule = "undeclared-holder"
        elif holder["mode"] == "write" and holder["database"] not in store.get("writes", []):
            rule = "undeclared-writer"
        elif not in_window(entry, units, now):
            rule = "holder-outside-window"
        else:
            continue
        violations.append(_violation(rule, subject, **detail))
    return violations


def live_check(
    manifest: dict | None = None, *, run: Runner = _run, proc_root: Path = Path("/proc"),
    now: datetime | None = None, engine_root: Path | None = None, home: Path | None = None,
) -> dict:
    """Compare the manifest with the host's user units, crontab and live-store holders."""
    manifest = manifest or load_manifest()
    now = now or datetime.now(UTC)
    home = home or Path.home()
    engine_root = engine_root or home / "trading-engine"
    errors: list[str] = []

    def output(args: list[str], *, absent_ok: bool = False) -> str | None:
        result = run(args)
        if result is not None and result.returncode == 0:
            return result.stdout
        if absent_ok and result is not None and "no crontab" in result.stderr.lower():
            return ""
        errors.append(f"{' '.join(args[:3])} failed")
        return None

    listed = output(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend",
                     "--full", "--no-pager", "--type=service,timer"])
    files = output(["systemctl", "--user", "list-unit-files", "--no-legend", "--no-pager",
                    "--type=service,timer"])
    violations: list[dict] = []
    names = sorted(set(_listed_units(listed or "")) | set(_listed_units(files or ""))
                   | set(_units(manifest)))
    blocks: dict[str, dict[str, list[str]]] = {}
    if listed is not None and files is not None:
        args = ["systemctl", "--user", "show", "--no-pager"]
        for prop in SHOW_PROPERTIES:
            args += ["-p", prop]
        shown = output([*args, "--", *names])
        if shown is not None:
            blocks = _show_blocks(shown)
            violations += _unit_violations(manifest, blocks, engine_root)
    crontab = output(["crontab", "-l"], absent_ok=True)
    if crontab is not None:
        violations += _cron_violations(manifest, crontab, engine_root, home)
    scan = scan_holders(proc_root, engine_root, manifest["audited_databases"])
    if scan["error"]:
        errors.append(scan["error"])
    violations += holder_violations(manifest, scan["holders"], now=now,
                                    engine_root=engine_root, home=home)
    kept, excepted = _apply_exceptions(_units(manifest), violations)
    return {"violations": kept, "exceptions": excepted, "errors": errors,
            "counts": {"units": len(blocks), "processes_scanned": scan["scanned"],
                       "processes_unreadable": scan["unreadable"],
                       "holders": len(scan["holders"])}}


# --------------------------------------------------------------------------- results
def check(*, static: bool, live: bool, repo_root: Path, manifest_path: Path = MANIFEST_PATH,
          now: datetime | None = None, autostart: frozenset[str] | None = None,
          expected_cron: dict[str, str] | None = None,
          overlay_path: Path | None = OVERLAY_PATH, **live_args) -> dict:
    """Run the requested checks and fold them into one result with an exit status.

    The live check also reads the optional host-local overlay (``overlay_path``); the static
    check never does, so the checkout alone decides what this repository declares.
    """
    now = now or datetime.now(UTC)
    result = {"checked_at": now.astimezone(UTC).isoformat(timespec="seconds"),
              "modes": [mode for mode, wanted in (("static", static), ("live", live)) if wanted],
              "violations": [], "exceptions": [], "errors": [], "counts": {}}
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        return {**result, "status": "error", "errors": [f"manifest unreadable: {exc}"]}
    parts = []
    try:
        if static:
            parts.append(static_check(repo_root, manifest, autostart=autostart,
                                      expected_cron=expected_cron))
        if live:
            repo_units = {Path(source).name for source in _repo_unit_files(repo_root)}
            local, overlay = apply_overlay(manifest, overlay_path, repo_units)
            result["overlay"] = overlay
            if overlay["status"] == "invalid":
                result["errors"].append(f"local overlay invalid: {overlay['error']}")
            parts.append(live_check(local, now=now, **live_args))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return {**result, "status": "error", "errors": [f"manifest malformed: {exc!r}"]}
    for part in parts:
        for key in ("violations", "exceptions", "errors"):
            result[key] += part[key]
        result["counts"].update(part["counts"])
    result["status"] = ("error" if result["errors"] else
                        "violations" if result["violations"] else "ok")
    return result


def exit_code(result: dict) -> int:
    return {"ok": 0, "violations": 2}.get(result["status"], 3)


def _public_subject(value: object) -> str:
    text = str(value)
    return text if len(text) <= 255 and text.isprintable() and "/" not in text else "redacted"


def public_status(path: Path, *, now: datetime | None = None) -> dict:
    """Project the newest digest result for ``/meta``: rules and subjects only, no paths."""
    now = now or datetime.now(UTC)
    base = {"status": "absent", "checked_at": None, "age_minutes": None,
            "stale_after_minutes": RESULT_STALE_AFTER_MINUTES, "violation_count": 0,
            "violations": [], "truncated": False}
    try:
        result = json.loads(path.read_text())
    except FileNotFoundError:
        return base
    except (OSError, ValueError):
        return {**base, "status": "invalid"}
    try:
        checked = datetime.fromisoformat(result["checked_at"]).astimezone(UTC)
        violations = [{"rule": item["rule"], "subject": _public_subject(item["subject"])}
                      for item in result["violations"]]
        status = result["status"]
        if status not in {"ok", "violations", "error"} or not all(
                item["rule"] in STATIC_RULES | LIVE_RULES for item in violations):
            raise ValueError("unknown status or rule")
    except (KeyError, TypeError, ValueError):
        return {**base, "status": "invalid"}
    age = max(0, int((now - checked).total_seconds() // 60))
    return {
        "status": "stale" if age > RESULT_STALE_AFTER_MINUTES else status,
        "checked_at": checked.isoformat(timespec="seconds"),
        "age_minutes": age,
        "stale_after_minutes": RESULT_STALE_AFTER_MINUTES,
        "violation_count": len(violations),
        "violations": violations[:PUBLIC_VIOLATION_LIMIT],
        "truncated": len(violations) > PUBLIC_VIOLATION_LIMIT,
    }


def invalid_status() -> dict:
    return {"status": "invalid", "checked_at": None, "age_minutes": None,
            "stale_after_minutes": RESULT_STALE_AFTER_MINUTES, "violation_count": 0,
            "violations": [], "truncated": False}
