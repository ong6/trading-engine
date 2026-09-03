"""engine/run_*.sh drivers on the shared engine/lib/driver.sh preamble.

Each driver is copied into a throwaway fake repo (so REPO_ROOT resolves there)
with a stub `.venv/bin/python` that logs its argv, and run for real. Checks
the contract the cron logs depend on: lock-file name and refusal, log path,
header/footer markers, the stage breadcrumb, exit-code propagation, and the
warn-and-continue vs fatal semantics of each stage.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVERS = sorted(p.name for p in (REPO_ROOT / "engine").glob("run_*.sh"))

FAKE_PY = r"""#!/usr/bin/env bash
echo "[fakepy] argv: $*"
echo "$*" >> "${FAKE_ARGV_LOG:?}"
case "$*" in
  *"farm.sweep.sweep --grid list"*) printf '[diag] skipped cell\ngrid_a extra\ngrid_b\n' ;;
esac
if [ -n "${FAKE_FAIL_MATCH:-}" ] && [[ "$*" == *"${FAKE_FAIL_MATCH}"* ]]; then
  echo "[fakepy] simulated failure" >&2; exit 3
fi
exit 0
"""

# driver -> (lock file, log prefix, stage file or None)
SPEC = {
    "run_daily.sh": (".nightly.lock", "run", ".last_stage"),
    "run_weekend_sweeps.sh": (".sweeps.lock", "sweeps", ".last_stage_sweeps"),
    "run_weekly_walkforward.sh": (".walkforward.lock", "walkforward", ".last_stage_walkforward"),
    "run_weekly_verify.sh": (".verify.lock", "verify-full", None),
    "run_weekly_liquid.sh": (".liquid.lock", "liquid", None),
}


@pytest.fixture
def fake_repo(tmp_path):
    fake = tmp_path / "repo"
    (fake / "engine" / "lib").mkdir(parents=True)
    (fake / ".venv" / "bin").mkdir(parents=True)
    for d in DRIVERS:
        shutil.copy(REPO_ROOT / "engine" / d, fake / "engine" / d)
    shutil.copy(REPO_ROOT / "engine" / "lib" / "driver.sh", fake / "engine" / "lib" / "driver.sh")
    py = fake / ".venv" / "bin" / "python"
    py.write_text(FAKE_PY)
    py.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(fake)], check=True)
    return fake


def run_driver(fake: Path, name: str, fail_match: str = "") -> tuple[int, str, list[str]]:
    argv_log = fake / "argv.log"
    argv_log.write_text("")
    env = dict(os.environ, FAKE_ARGV_LOG=str(argv_log), FAKE_FAIL_MATCH=fail_match)
    env.pop("PYTHONUNBUFFERED", None)
    cp = subprocess.run(["bash", str(fake / "engine" / name)], cwd=str(fake), env=env,
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr, argv_log.read_text().splitlines()


def test_all_drivers_and_preamble_parse():
    for f in [*(REPO_ROOT / "engine" / d for d in DRIVERS), REPO_ROOT / "engine/lib/driver.sh"]:
        subprocess.run(["bash", "-n", str(f)], check=True)


def test_every_driver_sources_the_shared_preamble():
    assert set(DRIVERS) == set(SPEC)
    for d in DRIVERS:
        text = (REPO_ROOT / "engine" / d).read_text()
        assert 'source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"' in text, d
        assert "driver_main body" in text, d
        assert "flock -n 9" not in text, f"{d} still carries its own lock preamble"


@pytest.mark.parametrize("name", DRIVERS)
def test_happy_path_markers_log_lock_exit(fake_repo, name):
    lock, prefix, stage_file = SPEC[name]
    rc, out, argv = run_driver(fake_repo, name)
    assert rc == 0, out
    stem = name[:-3]
    assert out.splitlines()[0].startswith(f"=== {stem} ")
    assert out.splitlines()[-1].startswith("=== done ")
    assert (fake_repo / lock).exists()
    logs = list((fake_repo / "logs").glob(f"{prefix}-*.log"))
    assert len(logs) == 1 and logs[0].read_text() == out
    assert argv, "the stub python was never invoked"
    if stage_file:
        assert (fake_repo / "logs" / stage_file).exists()
    else:
        assert not list((fake_repo / "logs").glob(".last_stage*"))


@pytest.mark.parametrize("name", DRIVERS)
def test_lock_held_refuses_with_exit_1(fake_repo, name):
    lock, prefix, _ = SPEC[name]
    fd = os.open(str(fake_repo / lock), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        rc, out, argv = run_driver(fake_repo, name)
    finally:
        os.close(fd)
    assert rc == 1
    assert out.startswith("ERROR: another ") and "(lock held)" in out
    assert argv == []
    assert not list((fake_repo / "logs").glob("*.log")) if (fake_repo / "logs").exists() else True


def test_daily_fatal_stage_propagates_exit_and_breadcrumb(fake_repo):
    rc, out, argv = run_driver(fake_repo, "run_daily.sh", fail_match="engine.collect")
    assert rc == 3
    assert "TODO: run_daily failed" in out and "(stage=collect exit 3)" in out
    assert (fake_repo / "logs" / ".last_stage").read_text().strip() == "collect"
    assert argv == ["-m engine.universe", "-m engine.collect"], "no stage may run after a fatal one"
    log = next((fake_repo / "logs").glob("run-*.log")).read_text()
    assert log.rstrip().endswith(out.rstrip().splitlines()[-1])  # breadcrumb reaches the log


def test_daily_warn_stages_continue(fake_repo):
    rc, out, argv = run_driver(fake_repo, "run_daily.sh", fail_match="engine.universe")
    assert rc == 0
    assert "WARN: universe refresh failed" in out
    assert "-m engine.collect" in argv


def test_daily_farm_section_never_fails_the_nightly(fake_repo):
    rc, out, argv = run_driver(fake_repo, "run_daily.sh", fail_match="queue_runner --run")
    assert rc == 0
    assert "WARN: farm section had failures (enqueue-nightly=0 run=3)" in out
    assert "-m engine.queue_runner --enqueue-nightly" in argv
    assert "-m engine.queue_runner --run --jobs 8" in argv


def test_daily_stage_order(fake_repo):
    _, _, argv = run_driver(fake_repo, "run_daily.sh")
    mods = [a.split()[1] for a in argv]
    assert mods == ["engine.universe", "engine.collect", "engine.screen", "engine.actions",
                    "engine.actions", "sim.league", "farm.experiment_runner", "engine.sync",
                    "engine.verify_prices", "engine.queue_runner", "engine.queue_runner"]


def test_sweeps_enqueues_each_grid_then_drains(fake_repo):
    rc, out, argv = run_driver(fake_repo, "run_weekend_sweeps.sh")
    assert rc == 0
    assert "grids: grid_a grid_b" in out
    assert '-m engine.queue_runner --enqueue sweep --priority 900 --mem-mb 4500 --params {"grid": "grid_a"}' in argv
    assert '-m engine.queue_runner --enqueue sweep --priority 900 --mem-mb 4500 --params {"grid": "grid_b"}' in argv
    assert argv[-1] == "-m engine.sync"


def test_sweeps_drain_failure_breadcrumb(fake_repo):
    rc, out, _ = run_driver(fake_repo, "run_weekend_sweeps.sh", fail_match="queue_runner --run")
    assert rc == 3 and "(stage=drain exit 3)" in out


def test_walkforward_enqueue_failure_breadcrumb(fake_repo):
    rc, out, argv = run_driver(fake_repo, "run_weekly_walkforward.sh",
                               fail_match="farm.walkforward.grid")
    assert rc == 3 and "TODO: run_weekly_walkforward failed" in out
    assert "(stage=enqueue exit 3)" in out
    assert argv == ["-m farm.walkforward.grid --enqueue"]


def test_verify_is_fail_soft(fake_repo):
    rc, out, _ = run_driver(fake_repo, "run_weekly_verify.sh", fail_match="verify_prices")
    assert rc == 0 and "WARN: verification exited non-zero" in out


def test_liquid_is_fatal_without_stage(fake_repo):
    rc, out, _ = run_driver(fake_repo, "run_weekly_liquid.sh", fail_match="engine.collect")
    assert rc == 3
    assert "TODO: run_weekly_liquid failed" in out and "(exit 3)" in out and "stage=" not in out


def test_appended_logs_vs_truncated_nightly(fake_repo):
    for _ in range(2):
        run_driver(fake_repo, "run_weekly_liquid.sh")
        run_driver(fake_repo, "run_daily.sh")
    liquid = next((fake_repo / "logs").glob("liquid-*.log")).read_text()
    daily = next((fake_repo / "logs").glob("run-*.log")).read_text()
    assert liquid.count("=== run_weekly_liquid ") == 2   # tee -a
    assert daily.count("=== run_daily ") == 1            # tee (truncate)
