"""server/run_p15_scoring.sh commits its post-scoring report re-render.

The scoring unit re-renders the league and the P15/agent-evaluation reports
after the nightly sync has already run, so the script must commit them itself
through engine/sync.py under its own driver name. The script is copied into a
throwaway fake repo with a stub `.venv/bin/python` that logs its argv.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "server/run_p15_scoring.sh"
SYNC = "-m engine.sync --driver run_p15_scoring"

FAKE_PY = r"""#!/usr/bin/env bash
echo "$*" >> "${FAKE_ARGV_LOG:?}"
case "$*" in
  *"engine.market_date"*) printf '2026-10-19\n'; exit 0 ;;
  *"server.agent_evaluation_reporting"*) exit "${FAKE_REPORT_STATUS:-0}" ;;
  *"engine.sync"*) exit "${FAKE_SYNC_STATUS:-0}" ;;
esac
exit 0
"""


def _run(tmp_path: Path, report_status: int = 0, sync_status: int = 0):
    fake = tmp_path / "repo"
    (fake / "server").mkdir(parents=True)
    (fake / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(REPO_ROOT / SCRIPT, fake / SCRIPT)
    python = fake / ".venv" / "bin" / "python"
    python.write_text(FAKE_PY)
    python.chmod(0o755)
    argv_log = tmp_path / "argv.log"
    env = {
        **os.environ,
        "FAKE_ARGV_LOG": str(argv_log),
        "FAKE_REPORT_STATUS": str(report_status),
        "FAKE_SYNC_STATUS": str(sync_status),
    }
    result = subprocess.run(
        ["bash", SCRIPT], cwd=fake, env=env, capture_output=True, text=True
    )
    argv = argv_log.read_text().splitlines() if argv_log.exists() else []
    return result.returncode, result.stdout + result.stderr, argv


def test_scoring_commits_reports_after_rendering_and_before_snapshot(tmp_path):
    rc, out, argv = _run(tmp_path)
    assert rc == 0, out
    assert [a.split()[1] for a in argv] == [
        "server.p15_scoring_runner",
        "engine.market_date",
        "sim.league",
        "farm.p15_event_runner",
        "server.agent_evaluation_reporting",
        "engine.sync",
        "tools.publish_snapshot",
    ]
    assert SYNC in argv


def test_validation_failure_still_commits_the_league_re_render(tmp_path):
    rc, out, argv = _run(tmp_path, report_status=75)
    assert rc == 75
    assert "restart suppressed" in out
    assert argv.index(SYNC) < argv.index("-m tools.publish_snapshot")


def test_reporting_error_commits_what_was_rendered_and_keeps_its_status(tmp_path):
    rc, _, argv = _run(tmp_path, report_status=1)
    assert rc == 1
    assert argv[-1] == SYNC
    assert "-m tools.publish_snapshot" not in argv


@pytest.mark.parametrize("report_status", [0, 75])
def test_sync_failure_never_changes_the_scoring_status(tmp_path, report_status):
    rc, out, argv = _run(tmp_path, report_status=report_status, sync_status=3)
    assert rc == report_status
    assert "WARN: sync failed (exit 3)" in out
    assert "-m tools.publish_snapshot" in argv
