#!/usr/bin/env python3
"""GET-only preflight of the local Trae model gateway against the engine's client pins.

Reads ``/healthz`` and ``/v1/models`` from the loopback proxy (never ``/maintain`` or any
POST) and the installed CLI's ``--version`` line, then checks:

- the proxy is healthy and reports the pinned proxy version and source hash;
- the runtime the proxy cached at its start is a reviewed build;
- the configured model's catalog entry matches the pinned entry;
- the token has at least two hours left, the last relogin did not fail, and the model
  catalog was refreshed within 48 hours;
- the installed runtime, which a proxy restart would report, is also a reviewed build
  (``restart_runtime``), so drift between the startup and installed builds is visible
  before a restart makes every model call fail closed.

``python -m tools.model_gateway_check`` prints a JSON report and exits 1 when any check
fails. The hourly ops digest embeds the same report; there is no separate schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from engine.lib.provenance import canonical_sha256
from server import agent_model_client as client

# The proxy renews below 36 h every 30 min. Two hours leave several maintenance
# attempts and time to intervene; a failed renewal warns immediately at any age.
MIN_TOKEN_HOURS = 2.0
MAX_CATALOG_AGE_S = 48 * 3600
VERSION_TIMEOUT_S = 20.0
RUNTIME_BINARIES = ("traex", "traecli", "trae-cli")
# "fail": model calls fail closed now. "warn": they will after a restart, expiry or refresh.
SEVERITY = {
    "proxy_reachable": "fail", "proxy_healthy": "fail", "proxy_version": "fail",
    "proxy_source_sha256": "fail", "startup_runtime": "fail", "model_catalog_entry": "fail",
    "token_hours_left": "warn", "relogin_last_ok": "warn", "catalog_age": "warn",
    "restart_runtime": "warn",
}

Fetch = Callable[[str], dict]
Runner = Callable[[list[str], float], str | None]


def _fetch(path: str) -> dict:
    return client._request("GET", path, None, timeout=client.STATUS_TIMEOUT_SECONDS)


def _run(args: list[str], timeout: float) -> str | None:
    try:
        done = subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def runtime_binary(run: Runner = _run) -> str | None:
    """Prefer the proxy unit's effective pin, then use the local proxy-style resolution."""
    try:
        environment = run(
            ["systemctl", "--user", "show", "trae-proxy.service", "-p", "Environment"],
            VERSION_TIMEOUT_S,
        )
        values = dict(item.split("=", 1) for item in shlex.split(
            (environment or "").removeprefix("Environment=").strip()) if "=" in item)
    except (OSError, subprocess.SubprocessError, ValueError):
        values = {}
    pinned = values.get("TRAEX_BIN")
    if pinned and os.access(pinned, os.X_OK):
        return pinned
    configured = os.environ.get("TRAEX_BIN")
    if configured and os.access(configured, os.X_OK):
        return configured
    for name in RUNTIME_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    fallback = Path.home() / ".local" / "bin" / "traex"
    return str(fallback) if os.access(fallback, os.X_OK) else None


def installed_runtime(run: Runner = _run, binary: str | None = None) -> str | None:
    """The first ``--version`` line, exactly as a restarted proxy would cache it."""
    binary = binary or runtime_binary(run)
    if binary is None:
        return None
    output = run([binary, "--version"], VERSION_TIMEOUT_S)
    lines = (output or "").strip().splitlines()
    return lines[0] if lines else None


def _runtime_label(value: object) -> str | None:
    """Semantic version of a reviewed runtime, else a hash; never the raw vendor string."""
    if not isinstance(value, str):
        return None
    digest = canonical_sha256(value)
    version = next((key for key, pin in client.REVIEWED_TRAECLI_RUNTIMES.items()
                    if pin == digest), None)
    return version or f"unreviewed:{digest[:12]}"


def _check(name: str, passed: bool, observed: object, expected: object) -> dict:
    return {"name": name, "ok": bool(passed), "severity": SEVERITY[name],
            "observed": observed, "expected": expected}


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def evaluate(health: dict | None, catalog: dict | None, installed: str | None, *,
             error: str | None = None, simulate_restart: bool = True) -> dict:
    """Compare one ``/healthz`` and ``/v1/models`` reading with the client pins.

    ``restart_simulation`` re-evaluates the same reading as if the proxy had restarted and
    cached the installed runtime instead of its startup one.
    """
    if health is None:
        checks = [_check("proxy_reachable", False, error, "GET /healthz returns JSON")]
        return _report(checks, None, _runtime_label(installed))
    pins = {"reviewed_traecli_runtime_sha256": client.REVIEWED_TRAECLI_RUNTIME_SHA256}
    startup = health.get("traex")
    token = health.get("token") if isinstance(health.get("token"), dict) else {}
    relogin = health.get("relogin") if isinstance(health.get("relogin"), dict) else {}
    catalog_state = health.get("catalog") if isinstance(health.get("catalog"), dict) else {}
    hours_left = _number(token.get("hours_left"))
    catalog_age = _number(catalog_state.get("age_s"))
    try:
        entry_ok, entry = True, canonical_sha256(client._selected_catalog_entry(catalog))
    except (client.ConnectorError, AttributeError, TypeError) as exc:
        entry_ok, entry = False, str(exc) if catalog is not None else error
    checks = [
        _check("proxy_healthy", health.get("ok") is True and token.get("present") is True,
               {"ok": health.get("ok"), "token_present": token.get("present")},
               {"ok": True, "token_present": True}),
        _check("proxy_version", health.get("proxy_version") == client.REQUIRED_PROXY_VERSION,
               health.get("proxy_version"), client.REQUIRED_PROXY_VERSION),
        _check("proxy_source_sha256",
               health.get("proxy_source_sha256") == client.REQUIRED_PROXY_SOURCE_SHA256,
               health.get("proxy_source_sha256"), client.REQUIRED_PROXY_SOURCE_SHA256),
        _check("startup_runtime", client.traecli_runtime_matches(pins, startup),
               _runtime_label(startup), sorted(client.REVIEWED_TRAECLI_RUNTIMES)),
        _check("model_catalog_entry", entry_ok and entry == client.MODEL_CATALOG_ENTRY_SHA256,
               entry, client.MODEL_CATALOG_ENTRY_SHA256),
        _check("token_hours_left", hours_left is not None and hours_left >= MIN_TOKEN_HOURS,
               hours_left, f">= {MIN_TOKEN_HOURS:g}"),
        _check("relogin_last_ok", relogin.get("last_ok") is not False,
               relogin.get("last_ok"), "true or not yet attempted"),
        _check("catalog_age", catalog_age is not None and catalog_age <= MAX_CATALOG_AGE_S,
               catalog_age, f"<= {MAX_CATALOG_AGE_S} s"),
        _check("restart_runtime", client.traecli_runtime_matches(pins, installed),
               _runtime_label(installed), sorted(client.REVIEWED_TRAECLI_RUNTIMES)),
    ]
    report = _report(checks, _runtime_label(startup), _runtime_label(installed))
    if simulate_restart:
        restarted = evaluate({**health, "traex": installed}, catalog, installed,
                             error=error, simulate_restart=False)
        report["restart_simulation"] = {
            "startup_runtime": _runtime_label(installed), "status": restarted["status"],
            "failed": restarted["failed"],
        }
    return report


def _report(checks: list[dict], startup: str | None, installed: str | None) -> dict:
    failed = [item for item in checks if not item["ok"]]
    status = ("fail" if any(item["severity"] == "fail" for item in failed)
              else "warn" if failed else "ok")
    return {
        "schema_version": 1, "status": status, "ok": not failed,
        "failed": [item["name"] for item in failed],
        "runtime": {"startup": startup, "installed": installed,
                    "drift": startup is not None and installed is not None
                    and startup != installed},
        "checks": checks,
    }


def check(fetch: Fetch = _fetch, run: Runner = _run, binary: str | None = None) -> dict:
    """Read the gateway (GET only) and the installed runtime, then evaluate."""
    installed = installed_runtime(run, binary)
    try:
        health = fetch(client.PROXY_HEALTH_PATH)
    except client.ConnectorError as exc:
        return evaluate(None, None, installed, error=str(exc))
    try:
        catalog, error = fetch(client.PROXY_MODELS_PATH), None
    except client.ConnectorError as exc:
        catalog, error = None, str(exc)
    return evaluate(health, catalog, installed, error=error)


def summary_lines(report: dict) -> list[str]:
    """Markdown lines for the ops digest."""
    runtime = report.get("runtime") or {}
    drift = " (drift)" if runtime.get("drift") else ""
    restart = report.get("restart_simulation") or {}
    lines = [f"Gateway {report['status'].upper()}: startup runtime "
             f"{runtime.get('startup') or 'unknown'}, installed "
             f"{runtime.get('installed') or 'unknown'}{drift}; after a restart "
             f"{str(restart.get('status', 'unknown')).upper()}."]
    for item in report["checks"]:
        if not item["ok"]:
            lines.append(f"- [{item['severity']}] {item['name']}: observed "
                         f"`{item['observed']}`, expected `{item['expected']}`")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--binary", help="CLI to read --version from (default: resolved)")
    args = parser.parse_args(argv)
    report = check(binary=args.binary)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
