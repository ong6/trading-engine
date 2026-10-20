"""Host and schedule contract: manifest, static rules, live probe and holder audit."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server import schedule_contract as sc
from tools import install_automation, schedule_contract_check

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = sc.load_manifest()
# Monday 2026-10-19, 12:40 UTC: 25 minutes before the P15 pre-open run (09:05 New York).
BEFORE_PREOPEN = datetime(2026, 10, 19, 12, 40, tzinfo=UTC)


def _installer_cron() -> dict[str, str]:
    monitor = install_automation.scheduler_monitor
    return {**monitor.expected_cron_entries(REPO_ROOT),
            **monitor.expected_auxiliary_cron_entries(REPO_ROOT)}


def _pairs(result: dict) -> set[tuple[str, str]]:
    return {(item["rule"], item["subject"]) for item in result["violations"]}


def test_contract_module_and_live_check_never_import_duckdb():
    code = ("import sys; import server.schedule_contract, tools.schedule_contract_check; "
            "print('duckdb' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                            text=True, timeout=60, check=True)
    assert result.stdout.strip() == "False"
    tree = ast.parse((REPO_ROOT / "server" / "schedule_contract.py").read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module and not node.level}
    assert imported <= set(sys.stdlib_module_names)


def test_checkout_satisfies_the_static_contract():
    result = sc.static_check(REPO_ROOT, MANIFEST, autostart=install_automation.AUTOSTART_UNITS,
                             expected_cron=_installer_cron())
    assert result["violations"] == []
    assert result["exceptions"] == []


def test_installer_sets_are_derived_from_the_manifest():
    assert install_automation.UNIT_SOURCES == sc.unit_sources(MANIFEST)
    assert install_automation.AUTOSTART_UNITS == sc.autostart_units(MANIFEST)
    assert install_automation.HELD_UNITS == {"massive-options-daily.timer"}
    assert "trading-engine-p16-challengers.timer" not in install_automation.AUTOSTART_UNITS


def _copy_units(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for source in sc.unit_sources(MANIFEST).values():
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / source, root / source)
    return root


def test_rehearsal_unit_that_stops_a_live_timer_is_a_static_violation(tmp_path):
    root = _copy_units(tmp_path)
    (root / "server" / "p22-rb-massive-options-daily.service").write_text(
        "[Unit]\nConflicts=trading-engine-ops-digest.timer\n[Service]\nType=oneshot\n"
        "ExecStartPre=/bin/systemctl --user stop trading-engine-p15-events.timer\n"
        "ExecStart=%h/engine-lanes/p22-ready/.venv/bin/python -m tools.free_massive_options\n")
    (root / "server" / "p22-rb-massive-options-daily.timer").write_text(
        "[Timer]\nOnCalendar=2099-01-01 00:00:00 UTC\nUnit=p22-rb-massive-options-daily.service\n")

    result = sc.static_check(root, MANIFEST)

    assert _pairs(result) == {
        ("unit-not-in-manifest", "p22-rb-massive-options-daily.service"),
        ("unit-not-in-manifest", "p22-rb-massive-options-daily.timer"),
        ("stops-live-unit", "p22-rb-massive-options-daily.service"),
        ("lane-path", "p22-rb-massive-options-daily.service"),
        ("unbounded", "p22-rb-massive-options-daily.service"),
    }
    stops = next(item for item in result["violations"] if item["rule"] == "stops-live-unit")
    assert stops["detail"]["stops"] == ["trading-engine-ops-digest.timer",
                                        "trading-engine-p15-events.timer"]


def test_held_timer_in_installer_autostart_is_a_static_violation():
    autostart = sc.autostart_units(MANIFEST) | {"massive-options-daily.timer"}

    result = sc.static_check(REPO_ROOT, MANIFEST, autostart=autostart)

    assert _pairs(result) == {("held-autostart", "massive-options-daily.timer")}


def test_unit_bounds_and_declarations_must_agree(tmp_path):
    root = _copy_units(tmp_path)
    service = root / "server" / "trading-engine-agent-shadow.service"
    service.write_text(service.read_text().replace("RuntimeMaxSec=5min\n", ""))
    timer = root / "server" / "trading-engine-ops-digest.timer"
    timer.write_text(timer.read_text().replace("*:08:00", "*:05:00"))
    settle = root / "server" / "trading-engine-accounts-settle.service"
    settle.write_text(settle.read_text().replace("TimeoutStartSec=30min", "TimeoutStartSec=2h"))
    (root / "server" / "trading-engine-p15-preopen.timer").unlink()

    assert _pairs(sc.static_check(root, MANIFEST)) == {
        ("unbounded", "trading-engine-agent-shadow.service"),
        ("timer-drift", "trading-engine-ops-digest.timer"),
        ("max-runtime-drift", "trading-engine-accounts-settle.service"),
        ("manifest-source-missing", "trading-engine-p15-preopen.timer"),
    }


def test_pinned_exception_moves_a_violation_aside_with_its_reason(tmp_path):
    root = _copy_units(tmp_path)
    service = root / "server" / "trading-engine-p15-scoring.service"
    service.write_text(service.read_text().replace("RuntimeMaxSec=9h\n", ""))
    manifest = json.loads(json.dumps(MANIFEST))
    entry = next(item for item in manifest["units"]
                 if item["unit"] == "trading-engine-p15-scoring.service")
    entry["pinned_exception"] = [{"rule": "unbounded", "reason": "registered file"}]

    result = sc.static_check(root, manifest)

    assert result["violations"] == []
    assert [(item["rule"], item["exception"]) for item in result["exceptions"]] == [
        ("unbounded", "registered file")]


@pytest.mark.parametrize("change, problem", [
    (lambda e: e.update(state="held", reason=""), "held or disabled without a reason"),
    (lambda e: e["store"].update(access="reader"), "store access does not match writes and reads"),
    (lambda e: e["store"].update(windows="sometimes"), "store windows"),
])
def test_manifest_entries_are_validated(change, problem):
    manifest = json.loads(json.dumps(MANIFEST))
    entry = next(item for item in manifest["units"]
                 if item["unit"] == "trading-engine-p15-preopen.service")
    change(entry)
    issues = [item for item in sc._schema_issues(manifest)
              if item["subject"] == "trading-engine-p15-preopen.service"]
    assert [item["detail"]["problem"] for item in issues] == [problem]


# --------------------------------------------------------------------------- live
class _Result:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _healthy_blocks(manifest: dict) -> dict[str, dict[str, str]]:
    blocks = {}
    for entry in manifest["units"]:
        name = entry["unit"]
        enabled = entry["state"] == "enabled"
        block = {"Id": name, "LoadState": "loaded", "ActiveState": "inactive",
                 "SubState": "dead", "UnitFileState": "static", "Type": "oneshot",
                 "TimeoutStartUSec": entry.get("max_runtime") or "infinity",
                 "RuntimeMaxUSec": "infinity", "Conflicts": "shutdown.target",
                 "ExecStart": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -m x }"}
        if name.endswith(".timer"):
            block.update(Triggers=entry["service"], UnitFileState="enabled" if enabled
                         else "disabled", ActiveState="active" if enabled else "inactive")
        elif entry.get("activation") == "boot":
            block.update(UnitFileState="enabled", ActiveState="active", SubState="running",
                         Type="simple")
        if name in {"store-sync.service", "te-autopush.service"}:
            block["TimeoutStartUSec"] = "5min"
        blocks[name] = block
    return blocks


def _runner(blocks: dict[str, dict[str, str]], crontab: str):
    def run(args):
        if args[:3] == ["systemctl", "--user", "list-units"]:
            return _Result("".join(f"{name} {b['LoadState']} {b['ActiveState']} "
                                   f"{b['SubState']} x\n" for name, b in blocks.items()))
        if args[:3] == ["systemctl", "--user", "list-unit-files"]:
            return _Result("".join(f"{name} {b['UnitFileState']}\n"
                                   for name, b in blocks.items()))
        if args[:3] == ["systemctl", "--user", "show"]:
            names = args[args.index("--") + 1:]
            return _Result("\n\n".join("\n".join(f"{key}={value}" for key, value in
                                                 blocks[name].items())
                                       for name in names if name in blocks) + "\n")
        if args == ["crontab", "-l"]:
            return _Result(crontab)
        raise AssertionError(args)
    return run


def _crontab(engine: Path, home: Path) -> str:
    return "".join(f"{entry['schedule']} {entry['match'].format(engine=engine, home=home)} "
                   f">> /tmp/x.log 2>&1\n# comment\n"
                   for entry in MANIFEST["cron"] if entry["state"] == "enabled")


def _live(tmp_path, blocks, crontab, *, now=BEFORE_PREOPEN, proc=None):
    proc = proc or tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    return sc.live_check(MANIFEST, run=_runner(blocks, crontab), proc_root=proc, now=now,
                         engine_root=tmp_path / "home" / "trading-engine",
                         home=tmp_path / "home")


def test_healthy_host_matches_the_manifest(tmp_path):
    home = tmp_path / "home"
    result = _live(tmp_path, _healthy_blocks(MANIFEST), _crontab(home / "trading-engine", home))
    assert result["errors"] == []
    assert result["violations"] == []


def test_live_unit_state_drift_failures_and_lane_units_are_violations(tmp_path):
    home = tmp_path / "home"
    blocks = _healthy_blocks(MANIFEST)
    blocks["trading-engine-p15-events.timer"]["UnitFileState"] = "disabled"
    blocks["massive-options-daily.timer"].update(UnitFileState="enabled", ActiveState="active")
    blocks["trading-engine-p15-preopen.service"]["ActiveState"] = "failed"
    blocks["trading-engine-ui.service"]["ActiveState"] = "inactive"
    blocks["te-autopush.service"]["TimeoutStartUSec"] = "infinity"
    blocks["massive-minute-capture.service"] = {
        "Id": "massive-minute-capture.service", "LoadState": "loaded", "ActiveState": "active",
        "SubState": "running", "UnitFileState": "static", "Type": "simple",
        "WorkingDirectory": "/srv/engine-lanes/minute", "ExecStart": "{ path=/bin/sh ; }"}
    blocks["p22-rb-trading-engine-api.service"] = {
        "Id": "p22-rb-trading-engine-api.service", "LoadState": "loaded",
        "ActiveState": "active", "SubState": "running", "UnitFileState": "static",
        "Conflicts": "trading-engine-api.service shutdown.target", "ExecStart": "{ }"}
    crontab = _crontab(home / "trading-engine", home).replace("30 22 * * 1-5", "30 23 * * 1-5")

    result = _live(tmp_path, blocks, crontab + "*/5 * * * * /opt/lane/run.sh\n")

    assert _pairs(result) == {
        ("not-enabled", "trading-engine-p15-events.timer"),
        ("held-enabled", "massive-options-daily.timer"),
        ("held-active", "massive-options-daily.timer"),
        ("failed", "trading-engine-p15-preopen.service"),
        ("not-active", "trading-engine-ui.service"),
        ("unbounded", "te-autopush.service"),
        ("off-manifest-unit", "massive-minute-capture.service"),
        ("lane-path", "massive-minute-capture.service"),
        ("off-manifest-unit", "p22-rb-trading-engine-api.service"),
        ("stops-live-unit", "p22-rb-trading-engine-api.service"),
        ("missing-cron", "cron:run_daily"),
        ("off-manifest-cron", "cron:30 23 * * 1-5 run_daily.sh"),
        ("off-manifest-cron", "cron:*/5 * * * * run.sh"),
    }


def test_probe_failure_is_reported_as_an_error(tmp_path):
    def run(args):
        return None if args[:3] == ["systemctl", "--user", "list-units"] else _Result("")

    result = sc.live_check(MANIFEST, run=run, proc_root=tmp_path, now=BEFORE_PREOPEN,
                           engine_root=tmp_path, home=tmp_path)
    assert result["errors"] == ["systemctl --user list-units failed"]


def _process(proc: Path, pid: int, *, cmdline: str, cgroup: str, ppid: int = 1,
             fds: dict[int, tuple[Path, str]] | None = None) -> None:
    root = proc / str(pid)
    (root / "fd").mkdir(parents=True)
    (root / "fdinfo").mkdir()
    (root / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode() + b"\0")
    (root / "cgroup").write_text(cgroup + "\n")
    (root / "stat").write_text(f"{pid} (python3) S {ppid} 0 0\n")
    for fd, (target, flags) in (fds or {}).items():
        (root / "fd" / str(fd)).symlink_to(target)
        (root / "fdinfo" / str(fd)).write_text(f"pos:\t0\nflags:\t{flags}\nmnt_id:\t1\n")


def _user_unit(unit: str) -> str:
    return f"1:name=systemd:/user.slice/user-1001.slice/user@1001.service/{unit}"


def _holders_fixture(tmp_path: Path) -> Path:
    engine = tmp_path / "home" / "trading-engine"
    market = engine / "store" / "market.duckdb"
    proc = tmp_path / "proc"
    rdwr, rdonly = "0100002", "0100000"
    _process(proc, 4242, cmdline="uv run pytest -q", cgroup="0::/user.slice/session-c9.scope",
             fds={7: (market, rdwr), 8: (Path(f"{market}.wal"), rdwr)})
    _process(proc, 501, cmdline="uvicorn server.main:app", cgroup=_user_unit(
        "trading-engine-api.service"), fds={9: (market, rdwr)})
    _process(proc, 502, cmdline="python -m server.p15_preopen --run",
             cgroup=_user_unit("trading-engine-p15-preopen.service"), fds={5: (market, rdwr)})
    _process(proc, 503, cmdline="python verify.py", cgroup=_user_unit("x.scope"),
             fds={5: (engine / "store" / "snapshots" / "market-latest.duckdb", rdonly)})
    _process(proc, 600, cmdline=f"/bin/bash {engine}/engine/run_daily.sh",
             cgroup="0::/user.slice/session-c1.scope")
    _process(proc, 601, cmdline="python -m engine.collect", ppid=600,
             cgroup="0::/user.slice/session-c1.scope", fds={4: (market, rdwr)})
    return proc


def test_foreign_pid_holding_the_market_store_before_preopen_is_a_violation(tmp_path):
    proc = _holders_fixture(tmp_path)

    holders = sc.scan_holders(proc, tmp_path / "home" / "trading-engine",
                              MANIFEST["audited_databases"])
    assert [(h["pid"], h["database"], h["mode"]) for h in holders["holders"]] == [
        (501, "store/market.duckdb", "write"), (502, "store/market.duckdb", "write"),
        (601, "store/market.duckdb", "write"), (4242, "store/market.duckdb", "write")]

    found = sc.holder_violations(MANIFEST, holders["holders"], now=BEFORE_PREOPEN,
                                 engine_root=tmp_path / "home" / "trading-engine",
                                 home=tmp_path / "home")

    assert [(item["rule"], item["subject"]) for item in found] == [
        ("holder-outside-window", "trading-engine-p15-preopen.service"),
        ("holder-outside-window", "cron:run_daily"),
        ("foreign-holder", "pid 4242"),
    ]
    foreign = found[-1]["detail"]
    assert foreign["pid"] == 4242 and foreign["cmdline"] == "uv run pytest -q"
    assert foreign["cgroup"] == "0::/user.slice/session-c9.scope"


def test_declared_holders_inside_their_windows_are_clean(tmp_path):
    proc = _holders_fixture(tmp_path)
    shutil.rmtree(proc / "4242")
    engine, home = tmp_path / "home" / "trading-engine", tmp_path / "home"
    holders = sc.scan_holders(proc, engine, MANIFEST["audited_databases"])["holders"]
    preopen = [h for h in holders if h["pid"] in {501, 502}]
    nightly = [h for h in holders if h["pid"] in {501, 601}]

    at_preopen = datetime(2026, 10, 19, 13, 20, tzinfo=UTC)
    after_nightly_start = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
    assert sc.holder_violations(MANIFEST, preopen, now=at_preopen, engine_root=engine,
                                home=home) == []
    assert sc.holder_violations(MANIFEST, nightly, now=after_nightly_start, engine_root=engine,
                                home=home) == []


def test_reader_holding_a_store_for_write_is_an_undeclared_writer():
    holder = {"pid": 7, "database": "store/market.duckdb", "mode": "write", "cmdline": "backup",
              "cgroup": "", "unit": "trading-data-backup.service", "ancestors": []}
    found = sc.holder_violations(MANIFEST, [holder], now=datetime(2026, 10, 20, 4, 40, tzinfo=UTC),
                                 engine_root=Path("/e"), home=Path("/h"))
    assert [(item["rule"], item["subject"]) for item in found] == [
        ("undeclared-writer", "trading-data-backup.service")]


def test_windows_follow_the_timer_zone_and_runtime():
    units = {entry["unit"]: entry for entry in MANIFEST["units"]}
    preopen = units["trading-engine-p15-preopen.service"]
    # 09:05 New York is 13:05 UTC in October; 20 min runtime plus 5 min slack.
    assert not sc.in_window(preopen, units, datetime(2026, 10, 19, 13, 4, tzinfo=UTC))
    assert sc.in_window(preopen, units, datetime(2026, 10, 19, 13, 30, tzinfo=UTC))
    assert not sc.in_window(preopen, units, datetime(2026, 10, 19, 13, 31, tzinfo=UTC))
    # 09:05 New York is 14:05 UTC after the November clock change.
    assert sc.in_window(preopen, units, datetime(2026, 11, 2, 14, 10, tzinfo=UTC))
    assert sc.span_seconds("1h 30min") == 5400 and sc.span_seconds("infinity") is None
    assert sc.span_seconds("0") is None and sc.span_seconds("9 h") == 32400


def test_cli_exit_codes(monkeypatch, capsys):
    assert schedule_contract_check.main(["--static"]) == 0
    assert capsys.readouterr().out.startswith("schedule contract: ok (static)")
    for status, code in (("violations", 2), ("error", 3)):
        monkeypatch.setattr(sc, "check", lambda status=status, **_: {
            "status": status, "modes": ["live"], "violations": [], "exceptions": [],
            "errors": []})
        assert schedule_contract_check.main(["--live", "--json"]) == code
        assert json.loads(capsys.readouterr().out)["status"] == status


def test_public_status_is_bounded_path_free_and_ages(tmp_path):
    path = tmp_path / "schedule-contract.json"
    assert sc.public_status(path)["status"] == "absent"
    violations = [{"rule": "foreign-holder", "subject": "pid 4242", "detail": {"cmdline": "x"}},
                  *({"rule": "failed", "subject": f"u{n}.service", "detail": {}}
                    for n in range(25)),
                  {"rule": "lane-path", "subject": "/srv/engine-lanes/x", "detail": {}}]
    path.write_text(json.dumps({"status": "violations",
                                "checked_at": "2026-10-20T07:08:00+00:00",
                                "violations": violations}))
    now = datetime(2026, 10, 20, 7, 20, tzinfo=UTC)

    public = sc.public_status(path, now=now)

    assert public["status"] == "violations" and public["age_minutes"] == 12
    assert public["violation_count"] == 27 and public["truncated"] is True
    assert public["violations"][0] == {"rule": "foreign-holder", "subject": "pid 4242"}
    assert len(public["violations"]) == sc.PUBLIC_VIOLATION_LIMIT
    assert sc.public_status(path, now=datetime(2026, 10, 20, 9, 40, tzinfo=UTC))["status"] == "stale"
    path.write_text(json.dumps({"status": "ok", "checked_at": "2026-10-20T07:08:00+00:00",
                                "violations": [{"rule": "invented", "subject": "x"}]}))
    assert sc.public_status(path, now=now) == sc.invalid_status()
    path.write_text(json.dumps({"status": "ok", "checked_at": "2026-10-20T07:08:00+00:00",
                                "violations": [violations[-1]]}))
    assert sc.public_status(path, now=now)["violations"] == [
        {"rule": "lane-path", "subject": "redacted"}]
