"""Recover a cron driver that has stalled past its declared run time.

The five cron drivers (`engine/run_*.sh`) hold an advisory lock for their whole run and have no
supervisor. On 2026-11-13 the nightly hung inside one DuckDB statement and held its lock and the
store for five days; every later nightly aborted and the timers that need the store failed.

`trading-engine-driver-watchdog.timer` runs this every ten minutes. For each enabled driver in
the schedule contract it finds the driver script's own process (an open descriptor on the
driver lock and the script path on its command line) and the processes descended from it. Other
processes that merely have the lock open, such as services waiting for it or the API probing
it, are never part of a run and are never signalled. A run is a candidate when it has outlived
its contract `max_runtime` and used under `STALL_CPU_SHARE` of one CPU over a sampling interval,
or has outlived `HARD_LIMIT_FACTOR` times that runtime; it is recovered only when two consecutive
passes find the same run a candidate. Recovery records the run's Python stacks, terminates the
run, clears failed units this repository installs and, for the nightly, owes one transient
`trading-engine-nightly-catch-up.service` that later passes start once the lock is free, inside
a window that ends before the pre-open, and then runs the P15 scoring unit again so the P15
window steps its books to the same session. It never opens a database. Every decision is one JSON
line in `logs/driver-watchdog.jsonl`, which the hourly digest reads (`"status": "failed"` is a
FAIL), written before the action it describes.

Create `<engine>/.driver-watchdog.disabled` to pause it during maintenance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.lib import resources
from server import schedule_contract

STALL_CPU_SHARE = 0.02
HARD_LIMIT_FACTOR = 2.0
SAMPLE_SECONDS = 60.0
CONFIRM_WITHIN = timedelta(minutes=30)
TERM_GRACE_SECONDS = 30.0
STACK_BUDGET_SECONDS = 120.0
CATCH_UP_DRIVER = "run_daily"
CATCH_UP_UNIT = "trading-engine-nightly-catch-up.service"  # transient, via systemd-run
CATCH_UP_ATTEMPTS = 3
# The P15 window steps the P15 books only once the league has stepped the session, so a
# finished catch-up starts the scoring unit again; it refuses on its own after 12:00 UTC.
P15_SCORING_UNIT = "trading-engine-p15-scoring.service"
# A catch-up nightly usually takes under two hours. Starting by 12:00 UTC and bounding the run
# at 13:45 UTC keeps the store free for the 14:05 UTC pre-open. Tuesday to Friday only:
# weekend mornings belong to the weekly drivers, and Monday has no missed weekday nightly.
CATCH_UP_HOURS_UTC = range(0, 12)
CATCH_UP_WEEKDAYS = {1, 2, 3, 4}
CATCH_UP_END_UTC = (13, 45)
CLK_TCK = os.sysconf("SC_CLK_TCK")


def _stat(proc: Path, pid: int) -> list[str] | None:
    try:
        text = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    return text.rpartition(")")[2].split()


def _alive(proc: Path, pid: int) -> bool:
    fields = _stat(proc, pid)
    return bool(fields) and fields[0] != "Z"


def _cmdline(proc: Path, pid: int) -> str:
    try:
        raw = (proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return " ".join(part for part in raw.decode("utf-8", "replace").split("\0") if part)


def _pids(proc: Path) -> list[int]:
    return [int(name) for name in os.listdir(proc) if name.isdigit()]


def _boot_time(proc: Path) -> float:
    for line in (proc / "stat").read_text().splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    raise RuntimeError("btime missing from /proc/stat")


def _forms(path: Path) -> set[str]:
    return {str(path), os.path.realpath(path)}


def lock_holders(proc: Path, lock: Path) -> list[int]:
    """Processes with an open descriptor on ``lock`` (holders and waiters alike)."""
    forms = _forms(lock)
    holders = []
    for pid in _pids(proc):
        try:
            descriptors = os.listdir(proc / str(pid) / "fd")
        except OSError:
            continue
        for fd in descriptors:
            try:
                if os.readlink(proc / str(pid) / "fd" / fd) in forms:
                    holders.append(pid)
                    break
            except OSError:
                continue
    return holders


def lock_is_held(proc: Path, lock: Path) -> bool:
    """Whether any process holds (not merely waits for) a lock on ``lock``'s inode."""
    try:
        info = os.stat(lock)
        text = (proc / "locks").read_text()
    except OSError:
        return False
    device = f"{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino}"
    for line in text.splitlines():
        fields = line.split()
        if "->" not in fields and device in fields:
            return True
    return False


def descendants(proc: Path, root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid in _pids(proc):
        fields = _stat(proc, pid)
        if fields:
            children.setdefault(int(fields[1]), []).append(pid)
    found, stack = set(), [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def run_members(proc: Path, root: int, script_forms: set[str]) -> set[int]:
    """The driver process, its descendants and a launching shell that names the script."""
    members = {root} | descendants(proc, root)
    fields = _stat(proc, root)
    parent = int(fields[1]) if fields else 0
    argv = _cmdline(proc, parent).split()
    if (parent > 1 and argv and Path(argv[0]).name in {"sh", "bash", "dash"}
            and "-c" in argv[1:3] and any(form in " ".join(argv) for form in script_forms)):
        members.add(parent)  # cron's `/bin/sh -c <script> >> log`
    return {pid for pid in members if _alive(proc, pid)}


def _ticks(proc: Path, pids: set[int]) -> dict[int, int]:
    """User and system ticks of each pid, its own and its reaped children's."""
    ticks = {}
    for pid in pids:
        fields = _stat(proc, pid)
        if fields:
            ticks[pid] = sum(int(value) for value in fields[11:15])
    return ticks


def drivers(manifest: dict, engine: Path) -> list[dict]:
    """Enabled cron drivers with their lock file and runtime limit in seconds."""
    found = []
    for entry in manifest.get("cron", []):
        match = re.fullmatch(r"\{engine\}/(engine/run_\w+\.sh)", entry.get("match", ""))
        limit = schedule_contract.span_seconds(entry.get("max_runtime") or "")
        if entry.get("state") != "enabled" or not match or not limit:
            continue
        script = engine / match.group(1)
        lock = re.search(r"^DRIVER_LOCK=(\S+)$", script.read_text(), re.MULTILINE)
        if lock:
            found.append({"name": entry["name"], "script": script,
                          "lock": engine / lock.group(1), "limit": limit})
    return found


def _stacks(proc: Path, pids: list[int], path: Path) -> str | None:
    lines = [f"{pid} {_cmdline(proc, pid)}" for pid in pids]
    spy = shutil.which("py-spy")
    uvx = Path.home() / ".local/bin/uvx"
    command = [spy] if spy else [str(uvx), "py-spy"] if uvx.exists() else None
    deadline = time.monotonic() + STACK_BUDGET_SECONDS
    for pid in pids:
        if command is None or "python" not in _cmdline(proc, pid):
            continue
        left = deadline - time.monotonic()
        if left <= 1:
            lines += ["", f"== py-spy dump {pid} skipped: stack budget spent"]
            continue
        try:
            result = subprocess.run([*command, "dump", "--pid", str(pid)], capture_output=True,
                                    text=True, timeout=left, check=False)
            lines += ["", f"== py-spy dump {pid}", result.stdout.strip() or result.stderr.strip()]
        except (OSError, subprocess.TimeoutExpired) as exc:
            lines += ["", f"== py-spy dump {pid} unavailable: {exc}"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        resources.write_text_atomic(path, "\n".join(lines) + "\n")
    except OSError:
        return None
    return str(path)


def session_holders(proc: Path, session: int, lock: Path) -> set[int]:
    """Processes of the run's session that still have the lock open (orphans included)."""
    return {pid for pid in lock_holders(proc, lock)
            if (fields := _stat(proc, pid)) and int(fields[3]) == session and fields[0] != "Z"}


def _terminate(proc: Path, root: int, script_forms: set[str], members: set[int],
               session: int, lock: Path, sleep=time.sleep) -> list[int]:
    """SIGTERM the run, then SIGKILL what remains of it; return the survivors."""
    def current() -> set[int]:
        alive = {pid for pid in members if _alive(proc, pid)}
        if _alive(proc, root):
            alive |= run_members(proc, root, script_forms)
        return alive | session_holders(proc, session, lock)

    def send(pids: set[int], sig: int) -> None:
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    send(current(), signal.SIGTERM)
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline and current():
        sleep(1)
    if left := current():
        send(left, signal.SIGKILL)
        sleep(2)
    return sorted(current())


def _systemctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                              timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def reset_failed_units(manifest: dict) -> list[str]:
    """Clear the failed state of this repository's units, which mostly failed on the held store."""
    listed = _systemctl("list-units", "--state=failed", "--plain", "--no-legend", "--no-pager")
    ours = {entry["unit"] for entry in manifest.get("units", []) if entry.get("origin") == "repo"}
    failed = [line.split()[0] for line in (listed.stdout if listed else "").splitlines()
              if line.split() and line.split()[0] in ours]
    if failed:
        _systemctl("reset-failed", *failed)
    return failed


def _load_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, state: dict) -> None:
    resources.write_text_atomic(path, json.dumps(state, sort_keys=True))


def _start_catch_up(engine: Path, now: datetime) -> bool:
    end = now.replace(hour=CATCH_UP_END_UTC[0], minute=CATCH_UP_END_UTC[1], second=0,
                      microsecond=0)
    runtime = int((end - now).total_seconds())
    _systemctl("reset-failed", CATCH_UP_UNIT)  # a leftover failed unit would block the name
    log = engine / "logs/cron.log"
    command = ["systemd-run", "--user", f"--unit={CATCH_UP_UNIT}",
               f"--property=WorkingDirectory={engine}", f"--property=RuntimeMaxSec={runtime}s",
               f"--property=StandardOutput=append:{log}",
               f"--property=StandardError=append:{log}",
               "--setenv=PYTHONUNBUFFERED=1", str(engine / "engine/run_daily.sh")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def advance_catch_up(engine: Path, now: datetime, state: dict, locks_held: Callable[[], bool],
                     emit: Callable[[dict], None]) -> None:
    """Drive an owed catch-up nightly one step: start it, watch it, retry or give up."""
    owed = state.get("catch_up")
    if not isinstance(owed, dict):
        return
    today = now.date().isoformat()
    if owed.get("day") != today:
        state.pop("catch_up")  # the window has passed; tonight's scheduled nightly runs
        if owed.get("status") in {"owed", "started"}:
            emit({"at": now.isoformat(), "driver": CATCH_UP_DRIVER, "status": "failed",
                  "action": "catch-up-expired", "day": owed.get("day")})
        return
    if owed.get("status") == "started":
        shown = _systemctl("show", CATCH_UP_UNIT, "-p", "ActiveState", "-p", "Result")
        values = dict(line.split("=", 1) for line in (shown.stdout if shown else "").splitlines()
                      if "=" in line)
        if "ActiveState" not in values or values["ActiveState"] in {
                "active", "activating", "deactivating", "reloading"}:
            return  # still running, or systemd could not be read: decide next pass
        if values.get("ActiveState") == "failed" or values.get("Result", "success") != "success":
            _systemctl("reset-failed", CATCH_UP_UNIT)
            owed["status"] = "owed"
            emit({"at": now.isoformat(), "driver": CATCH_UP_DRIVER, "status": "failed",
                  "action": "catch-up-failed", "attempts": owed.get("attempts", 0)})
        else:
            owed["status"] = "done"
            _systemctl("reset-failed", P15_SCORING_UNIT)
            started = _systemctl("start", "--no-block", P15_SCORING_UNIT)
            emit({"at": now.isoformat(), "driver": CATCH_UP_DRIVER, "status": "ok",
                  "action": "catch-up-finished",
                  "p15_scoring_started": bool(started and started.returncode == 0)})
            return
    if owed.get("status") != "owed":
        return
    if owed.get("attempts", 0) >= CATCH_UP_ATTEMPTS:
        owed["status"] = "gave-up"
        emit({"at": now.isoformat(), "driver": CATCH_UP_DRIVER, "status": "failed",
              "action": "catch-up-gave-up", "attempts": owed["attempts"]})
        return
    if now.weekday() not in CATCH_UP_WEEKDAYS or now.hour not in CATCH_UP_HOURS_UTC:
        return
    if locks_held():
        return
    owed["attempts"] = owed.get("attempts", 0) + 1
    started = _start_catch_up(engine, now)
    owed["status"] = "started" if started else "owed"
    emit({"at": now.isoformat(), "driver": CATCH_UP_DRIVER,
          "status": "degraded" if started else "failed",
          "action": "catch-up-started" if started else "catch-up-start-failed",
          "attempts": owed["attempts"]})


def check(engine: Path, *, proc: Path = Path("/proc"), now: datetime | None = None,
          sample_seconds: float = SAMPLE_SECONDS, sleep=time.sleep, act: bool = True,
          emit: Callable[[dict], None] | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    receipts: list[dict] = []

    def record(receipt: dict) -> None:
        receipts.append(receipt)
        if emit is not None:
            emit(receipt)

    manifest = schedule_contract.load_manifest()
    boot = _boot_time(proc)
    me = {os.getpid(), os.getpgid(0)}
    state_path = engine / "logs/.driver-watchdog-state.json"
    state = _load_state(state_path)
    stalls = state.setdefault("stall", {})
    found = drivers(manifest, engine)
    for driver in found:
        forms = _forms(driver["script"])
        roots = [pid for pid in lock_holders(proc, driver["lock"])
                 if pid not in me and any(form in _cmdline(proc, pid) for form in forms)]
        roots = [pid for pid in roots if _alive(proc, pid)]
        if not roots:  # idle, or a deploy or tool holds the lock: never a run to touch
            stalls.pop(driver["name"], None)
            continue
        root = min(roots, key=lambda pid: int((_stat(proc, pid) or [0] * 22)[19]))
        fields = _stat(proc, root)
        if fields is None:
            continue
        age = now.timestamp() - (boot + int(fields[19]) / CLK_TCK)
        if age <= driver["limit"]:
            stalls.pop(driver["name"], None)
            continue
        before = _ticks(proc, run_members(proc, root, forms))
        started = time.monotonic()
        sleep(sample_seconds)
        elapsed = max(time.monotonic() - started, 1e-9)
        members = run_members(proc, root, forms)
        after = _ticks(proc, members)
        share = sum(max(0, ticks - before.get(pid, 0)) for pid, ticks in after.items())
        share = share / CLK_TCK / elapsed
        receipt = {"at": now.isoformat(), "driver": driver["name"], "root": root,
                   "age_seconds": round(age), "max_runtime_seconds": driver["limit"],
                   "cpu_share": round(share, 4), "pids": sorted(members)}
        stalled = share < STALL_CPU_SHARE
        over = age > HARD_LIMIT_FACTOR * driver["limit"]
        if not stalled and not over:
            stalls.pop(driver["name"], None)
            record({**receipt, "status": "degraded", "action": "none",
                    "reason": "overdue but still working"})
            continue
        reason = "stalled" if stalled else "over hard limit"
        if not act:
            record({**receipt, "status": "failed", "action": "dry-run", "reason": reason})
            continue
        identity = {"root": root, "start": int(fields[19])}
        previous = stalls.get(driver["name"]) or {}
        seen = previous.get("seen")
        try:
            recent = isinstance(seen, str) and now - datetime.fromisoformat(seen) <= CONFIRM_WITHIN
        except (TypeError, ValueError):
            recent = False
        confirmed = {k: previous.get(k) for k in identity} == identity and recent
        if not confirmed:
            stalls[driver["name"]] = {**identity, "seen": now.isoformat()}
            record({**receipt, "status": "degraded", "action": "watching",
                    "reason": f"{reason}; confirming on the next pass"})
            continue
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        receipt["stacks"] = _stacks(proc, sorted(members), engine / "logs/driver-watchdog"
                                    / f"{stamp}-{driver['name']}.txt")
        record({**receipt, "status": "failed", "action": "terminating", "reason": reason})
        survivors = _terminate(proc, root, forms, members, int(fields[3]), driver["lock"],
                               sleep=sleep)
        stalls.pop(driver["name"], None)
        if driver["name"] == CATCH_UP_DRIVER:
            today = now.date().isoformat()
            prior = state.get("catch_up") if isinstance(state.get("catch_up"), dict) else {}
            attempts = prior.get("attempts", 0) if prior.get("day") == today else 0
            state["catch_up"] = {"day": today, "status": "owed", "attempts": attempts}
            _save_state(state_path, state)
        cleared = reset_failed_units(manifest)
        record({"at": now.isoformat(), "driver": driver["name"], "root": root,
                "status": "failed", "action": "terminated", "survivors": survivors,
                "reset_failed": cleared,
                "lock_still_held": lock_is_held(proc, driver["lock"])})

    if act:
        locks = [driver["lock"] for driver in found]
        advance_catch_up(engine, now, state,
                         lambda: any(lock_is_held(proc, lock) for lock in locks), record)
        _save_state(state_path, state)
    return receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine-root", type=Path, default=Path.home() / "trading-engine")
    parser.add_argument("--dry-run", action="store_true", help="report without acting")
    args = parser.parse_args(argv)
    engine = args.engine_root
    if (engine / ".driver-watchdog.disabled").exists():
        print(json.dumps({"status": "disabled"}))
        return 0
    log = engine / "logs/driver-watchdog.jsonl"

    def emit(receipt: dict) -> None:
        if not args.dry_run:
            with log.open("a") as handle:
                handle.write(json.dumps(receipt, sort_keys=True) + "\n")

    receipts = check(engine, act=not args.dry_run, emit=emit)
    print(json.dumps({"status": "ok", "receipts": receipts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
