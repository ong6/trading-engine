"""Recover a cron driver that has stalled past its declared run time.

The five cron drivers (`engine/run_*.sh`) hold an advisory lock for their whole run and have no
supervisor. On 2026-11-13 the nightly hung inside one DuckDB statement and held its lock and the
store for five days; every later nightly aborted and the timers that need the store failed.

`trading-engine-driver-watchdog.timer` runs this every ten minutes. For each enabled driver in
the schedule contract it finds the processes holding the driver's lock through /proc. A run is
recovered when it has outlived its contract `max_runtime` and its process group used under
`STALL_CPU_SHARE` of one CPU over a sampling interval, or when it has outlived
`HARD_LIMIT_FACTOR` times that runtime whatever it is doing. Recovery records the stacks of the
group's Python processes, terminates the group, clears failed engine units and, for the nightly,
starts the transient `trading-engine-nightly-catch-up.service` once per day when it can finish before the
pre-open. It never opens a database. Every decision is one JSON line in
`logs/driver-watchdog.jsonl`, which the hourly digest reads (`"status": "failed"` is a FAIL).

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
from datetime import UTC, datetime
from pathlib import Path

from server import schedule_contract

STALL_CPU_SHARE = 0.02
HARD_LIMIT_FACTOR = 2.0
SAMPLE_SECONDS = 60.0
TERM_GRACE_SECONDS = 30.0
STACK_TIMEOUT_SECONDS = 90
CATCH_UP_DRIVER = "run_daily"
CATCH_UP_UNIT = "trading-engine-nightly-catch-up.service"  # transient, via systemd-run
# A catch-up nightly takes one to two hours; starting by 12:00 UTC ends it before the
# 14:05 UTC pre-open. Tuesday to Friday only: Saturday and Sunday mornings belong to the
# weekly drivers, and Monday has no missed weekday nightly before it.
CATCH_UP_HOURS_UTC = range(0, 12)
CATCH_UP_WEEKDAYS = {1, 2, 3, 4}
CLK_TCK = os.sysconf("SC_CLK_TCK")


def _stat(proc: Path, pid: int) -> list[str] | None:
    try:
        text = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    return text.rpartition(")")[2].split()


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


def lock_holders(proc: Path, lock: Path) -> list[int]:
    """Processes with an open descriptor on ``lock``."""
    forms = {str(lock), os.path.realpath(lock)}
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


def group_members(proc: Path, pgid: int) -> list[int]:
    return [pid for pid in _pids(proc) if (fields := _stat(proc, pid)) and int(fields[2]) == pgid]


def cpu_ticks(proc: Path, pids: list[int]) -> int:
    """User and system ticks of ``pids`` and their reaped children."""
    total = 0
    for pid in pids:
        fields = _stat(proc, pid)
        if fields:
            total += sum(int(value) for value in fields[11:15])
    return total


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
            found.append({"name": entry["name"], "script": str(script),
                          "lock": engine / lock.group(1), "limit": limit})
    return found


def _stacks(proc: Path, pids: list[int], path: Path) -> str | None:
    lines = [f"{pid} {_cmdline(proc, pid)}" for pid in pids]
    spy = shutil.which("py-spy")
    uvx = Path.home() / ".local/bin/uvx"
    command = [spy] if spy else [str(uvx), "py-spy"] if uvx.exists() else None
    for pid in pids:
        if command is None or "python" not in _cmdline(proc, pid):
            continue
        try:
            result = subprocess.run([*command, "dump", "--pid", str(pid)], capture_output=True,
                                    text=True, timeout=STACK_TIMEOUT_SECONDS, check=False)
            lines += ["", f"== py-spy dump {pid}", result.stdout.strip() or result.stderr.strip()]
        except (OSError, subprocess.TimeoutExpired) as exc:
            lines += ["", f"== py-spy dump {pid} unavailable: {exc}"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
    except OSError:
        return None
    return str(path)


def _alive(proc: Path, pid: int) -> bool:
    fields = _stat(proc, pid)
    return bool(fields) and fields[0] != "Z"


def _terminate(proc: Path, pgid: int, pids: list[int], sleep=time.sleep) -> list[int]:
    """SIGTERM the group and stray holders, then SIGKILL what remains; return survivors."""
    def send(sig):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    send(signal.SIGTERM)
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline and any(_alive(proc, pid) for pid in pids):
        sleep(1)
    if any(_alive(proc, pid) for pid in pids):
        send(signal.SIGKILL)
        sleep(2)
    return [pid for pid in pids if _alive(proc, pid)]


def _systemctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                              timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def reset_failed_units(manifest: dict) -> list[str]:
    """Clear the failed state of declared units, which mostly failed on the held store."""
    listed = _systemctl("list-units", "--state=failed", "--plain", "--no-legend", "--no-pager")
    declared = {entry["unit"] for entry in manifest.get("units", [])}
    failed = [line.split()[0] for line in (listed.stdout if listed else "").splitlines()
              if line.split() and line.split()[0] in declared]
    if failed:
        _systemctl("reset-failed", *failed)
    return failed


def _state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def catch_up(engine: Path, now: datetime, state_path: Path, others_running: bool) -> str:
    """Start one catch-up nightly per UTC day inside the safe window; return the outcome."""
    if now.weekday() not in CATCH_UP_WEEKDAYS or now.hour not in CATCH_UP_HOURS_UTC:
        return "outside-window"
    if others_running:
        return "another-driver-running"
    state = _state(state_path)
    today = now.date().isoformat()
    if state.get("catch_up_day") == today:
        return "already-ran-today"
    log = engine / "logs/cron.log"
    command = ["systemd-run", "--user", f"--unit={CATCH_UP_UNIT}", "--collect",
               f"--property=WorkingDirectory={engine}", "--property=RuntimeMaxSec=6h",
               f"--property=StandardOutput=append:{log}",
               f"--property=StandardError=append:{log}",
               "--setenv=PYTHONUNBUFFERED=1", str(engine / "engine/run_daily.sh")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                check=False)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode != 0:
        return "start-failed"
    state["catch_up_day"] = today
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    tmp.replace(state_path)
    return "started"


def check(engine: Path, *, proc: Path = Path("/proc"), now: datetime | None = None,
          sample_seconds: float = SAMPLE_SECONDS, sleep=time.sleep, act: bool = True) -> list[dict]:
    now = now or datetime.now(UTC)
    manifest = schedule_contract.load_manifest()
    boot = _boot_time(proc)
    me = {os.getpid(), os.getpgid(0)}
    receipts = []
    found = drivers(manifest, engine)
    held = {driver["name"]: lock_holders(proc, driver["lock"]) for driver in found}
    for driver in found:
        holders = [pid for pid in held[driver["name"]] if pid not in me]
        roots = [pid for pid in holders if driver["script"] in _cmdline(proc, pid)]
        if not roots:
            continue  # idle, or a deploy holds the lock: never touch a non-driver holder
        root = min(roots, key=lambda pid: int((_stat(proc, pid) or [0] * 22)[19]))
        fields = _stat(proc, root)
        if fields is None:
            continue
        age = now.timestamp() - (boot + int(fields[19]) / CLK_TCK)
        if age <= driver["limit"]:
            continue
        pgid = int(fields[2])
        if pgid in me:
            continue
        members = sorted(set(group_members(proc, pgid)) | set(holders))
        before, started = cpu_ticks(proc, members), time.monotonic()
        sleep(sample_seconds)
        elapsed = max(time.monotonic() - started, 1e-9)
        share = (cpu_ticks(proc, members) - before) / CLK_TCK / elapsed
        receipt = {"at": now.isoformat(), "driver": driver["name"], "age_seconds": round(age),
                   "max_runtime_seconds": driver["limit"], "cpu_share": round(share, 4),
                   "pids": members}
        stalled = share < STALL_CPU_SHARE
        if not stalled and age <= HARD_LIMIT_FACTOR * driver["limit"]:
            receipts.append({**receipt, "status": "degraded", "action": "none",
                             "reason": "overdue but still working"})
            continue
        receipt["reason"] = "stalled" if stalled else "over hard limit"
        if not act:
            receipts.append({**receipt, "status": "failed", "action": "dry-run"})
            continue
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        receipt["stacks"] = _stacks(proc, members, engine / "logs/driver-watchdog"
                                    / f"{stamp}-{driver['name']}.txt")
        receipt["survivors"] = _terminate(proc, pgid, members, sleep=sleep)
        receipt["reset_failed"] = reset_failed_units(manifest)
        if driver["name"] == CATCH_UP_DRIVER:
            others = any(held[name] for name in held if name != driver["name"])
            receipt["catch_up"] = catch_up(engine, now, engine / "logs/.driver-watchdog-state.json",
                                           others)
        receipts.append({**receipt, "status": "failed", "action": "terminated"})
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
    receipts = check(engine, act=not args.dry_run)
    if receipts and not args.dry_run:
        with (engine / "logs/driver-watchdog.jsonl").open("a") as handle:
            for receipt in receipts:
                handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    print(json.dumps({"status": "ok", "receipts": receipts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
