"""Source-aware deployment of the two long-running application services.

API sources are conservatively all Python in the five importable packages (main
imports farm and tools too), plus dependency declarations. UI sources are its
whole tree apart from generated output and installed dependencies. Unit-file
reconciliation remains the installer's responsibility.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from engine.lib.resources import write_text_atomic

API = "trading-engine-api.service"
UI = "trading-engine-ui.service"
SOURCE_SETS = {
    API: tuple(f":(glob){package}/**/*.py" for package in ("server", "engine", "sim", "farm", "tools"))
    + ("pyproject.toml", "uv.lock", "engine/requirements.txt"),
    UI: (":(glob)ui/**",)
    + tuple(f":(exclude,glob)ui/**/{directory}/**" for directory in
            (".next", "node_modules", "out", "build", "coverage", ".turbo"))
    + (":(exclude,glob)ui/**/*.tsbuildinfo", ":(exclude)ui/next-env.d.ts"),
}
HEALTH_URLS = {
    API: ("http://127.0.0.1:8000/health", "http://127.0.0.1:8000/meta"),
    UI: ("http://127.0.0.1:3000/",),
}
HEALTH_WAIT = {API: 90, UI: 600}


def run(args: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    # systemd renders wall timestamps in the client's timezone. Fix both locale
    # and timezone so the fallback is independent of the calling shell's TZ.
    return subprocess.run(args, capture_output=True, text=True, check=False,
                          timeout=timeout, env={**os.environ, "LC_ALL": "C", "TZ": "UTC"})


def git(repo_root: Path, *args: str, runner=None) -> str:
    result = (runner or run)(["git", "-C", str(repo_root), *args])
    if result.returncode:
        raise RuntimeError(f"service source comparison failed: {result.stderr.strip()}")
    return result.stdout.strip()


def service_state(unit: str, *, runner=None, timeout: float = 30) -> dict:
    try:
        result = (runner or run)([
            "systemctl", "--user", "show", unit,
            "-p", "ActiveState", "-p", "ActiveEnterTimestamp", "-p", "InvocationID",
        ], timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode:
        return {}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _timestamp(value: str) -> float | None:
    if not value.endswith(" UTC"):
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S UTC", "%a %Y-%m-%d %H:%M:%S.%f UTC"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC).timestamp()
        except ValueError:
            pass
    return None


def state_path(home: Path, unit: str) -> Path:
    return home / ".local/state/trading-engine" / f"{unit}.json"


def _record(home: Path, repo_root: Path, unit: str, invocation: str) -> dict:
    try:
        record = json.loads(state_path(home, unit).read_text())
        if (isinstance(record, dict) and invocation
                and record.get("invocation_id") == invocation
                and record.get("repo_root") == str(repo_root)):
            return record
    except (OSError, ValueError):
        pass
    return {}


def plan(repo_root: Path, home: Path, *, runner=None, clock=None) -> dict[str, dict]:
    """Read-only restart decisions, keyed by service; never query or mutate stores."""
    head = git(repo_root, "rev-parse", "HEAD", runner=runner)
    now = (clock or time.time)()
    decisions = {}
    for unit, paths in SOURCE_SETS.items():
        current = service_state(unit, runner=runner)
        invocation = current.get("InvocationID", "")
        record = _record(home, repo_root, unit, invocation)
        old = record.get("commit")
        decision = {
            "restart": False, "reason": "source-unchanged", "from_commit": old,
            "to_commit": head, "invocation_id": invocation,
            "active_enter_timestamp": current.get("ActiveEnterTimestamp"),
        }
        if current.get("ActiveState") == "inactive":
            decision["reason"] = "service-inactive-needs-start"
        elif old:
            try:
                # Resolve only a commit object, never let state be interpreted as
                # git options or a revision expression in the diff.
                base = git(repo_root, "rev-parse", "--verify", f"{old}^{{commit}}", runner=runner)
                names = git(repo_root, "diff", "--name-only", "--no-renames", base, head,
                            "--", *paths, runner=runner).splitlines()
                decision.update(restart=bool(names), changed_files=names,
                                reason="source-changed" if names else "source-unchanged")
            except RuntimeError:
                decision.update(restart=True, reason="recorded-commit-unavailable")
        else:
            last = git(repo_root, "log", "-1", "--format=%H %ct", head, "--", *paths, runner=runner)
            started = _timestamp(current.get("ActiveEnterTimestamp", ""))
            try:
                last_commit, changed_at = last.split()
                changed_at = int(changed_at)
            except ValueError:
                last_commit, changed_at = None, None
            decision.update(from_commit=None, last_source_commit=last_commit,
                            last_source_commit_time=changed_at)
            known = (current.get("ActiveState") == "active" and started is not None
                     and changed_at is not None and changed_at < started <= now)
            decision.update(restart=not known,
                            reason="timestamp-source-unchanged" if known else "timestamp-source-changed-or-unknown")
        decisions[unit] = decision
    return decisions


def http_status(url: str, *, timeout: float) -> int:
    # All readiness requests stay on loopback, independent of proxy environment.
    with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
        return response.status


def verify_health(unit: str, previous_invocation: str, *, restarted: bool,
                  runner=None, probe=None, clock=None, sleep=None, wait: float | None = None) -> dict:
    """Bounded readiness polling; a restart must have replaced the old process."""
    clock, sleep, probe = clock or time.monotonic, sleep or time.sleep, probe or http_status
    wait = HEALTH_WAIT[unit] if wait is None else wait
    deadline = clock() + wait
    evidence = {}
    while clock() < deadline:
        current = service_state(unit, runner=runner, timeout=min(5, max(0.01, deadline - clock())))
        invocation = current.get("InvocationID", "")
        evidence = {"active_state": current.get("ActiveState", "unknown"),
                    "invocation_id": invocation, "http": {}}
        if (current.get("ActiveState") == "active" and invocation
                and (not restarted or invocation != previous_invocation)):
            for url in HEALTH_URLS[unit]:
                remaining = deadline - clock()
                if remaining <= 0:
                    evidence["http"][url] = "deadline reached"
                    break
                try:
                    evidence["http"][url] = probe(url, timeout=min(5, remaining))
                except (OSError, URLError, ValueError) as exc:
                    evidence["http"][url] = str(exc)
            if (len(evidence["http"]) == len(HEALTH_URLS[unit])
                    and all(code == 200 for code in evidence["http"].values())):
                return {"status": "ok", **evidence}
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(2, remaining))
    return {"status": "error", "wait_seconds": wait, **evidence}


def record_running(repo_root: Path, home: Path, unit: str, decision: dict,
                   *, invocation: str, runner=None) -> None:
    """Save only a verified invocation against the exact checkout that was applied."""
    if git(repo_root, "rev-parse", "HEAD", runner=runner) != decision["to_commit"]:
        raise RuntimeError("service checkout changed during apply")
    current = service_state(unit, runner=runner)
    if not invocation or current.get("ActiveState") != "active" or current.get("InvocationID") != invocation:
        raise RuntimeError(f"service invocation changed during apply: {unit}")
    write_text_atomic(state_path(home, unit), json.dumps({
        "commit": decision["to_commit"], "repo_root": str(repo_root),
        "invocation_id": invocation, "active_enter_timestamp": current.get("ActiveEnterTimestamp"),
    }, indent=2, sort_keys=True) + "\n")
