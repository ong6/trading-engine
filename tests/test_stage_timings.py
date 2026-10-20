from __future__ import annotations

import json

import pytest

from tools import stage_timings


def _record(run_id: str, stage: str, seconds: float, ended: str, *, driver="daily", exit=0):
    return {
        "driver": driver,
        "run_id": run_id,
        "stage": stage,
        "started": ended,
        "ended": ended,
        "seconds": seconds,
        "exit": exit,
    }


def test_summarize_uses_last_n_runs_per_driver():
    records = [
        _record("old", "collect", 100, "2026-10-01T00:00:00Z"),
        _record("new-1", "collect", 1, "2026-10-02T00:00:00Z"),
        _record("new-1", "screen", 2, "2026-10-02T00:00:01Z"),
        _record("new-2", "collect", 3, "2026-10-03T00:00:00Z", exit=1),
    ]

    assert stage_timings.summarize(records, runs=2) == [
        {
            "driver": "daily", "stage": "collect", "runs": 2,
            "median_seconds": 2.0, "p90_seconds": 3.0, "failures": 1,
        },
        {
            "driver": "daily", "stage": "screen", "runs": 1,
            "median_seconds": 2.0, "p90_seconds": 2.0, "failures": 0,
        },
    ]


def test_load_timings_ignores_malformed_lines(tmp_path):
    path = tmp_path / "timings.jsonl"
    valid = _record("run", "collect", 1.25, "2026-10-02T00:00:00Z")
    path.write_text("not-json\n" + json.dumps(valid) + "\n{}\n")
    assert stage_timings.load_timings(path) == [valid]
    assert stage_timings.load_timings(tmp_path / "missing") == []


def test_summarize_rejects_nonpositive_run_count():
    with pytest.raises(ValueError, match="runs must be positive"):
        stage_timings.summarize([], runs=0)


def test_stage_counters_distinguish_unknown_zero_and_failed_work(monkeypatch, tmp_path):
    path = tmp_path / 'flow.jsonl'
    monkeypatch.setenv('TRADING_ENGINE_STAGE_METRICS', str(path))
    assert all(v is None for v in stage_timings.flow_totals(path).values())
    stage_timings.record_flow(input_rows=0, output_rows=0, input_bytes=0)
    stage_timings.record_flow(input_rows=10, output_rows=4, input_bytes=256,
                              writer_hold_seconds=.02, lock_wait_seconds=5)
    stage_timings.flow_totals(path)
    path.write_text(path.read_text() + 'bad-json\n')
    assert stage_timings.flow_totals(path) == {
        'input_rows':10, 'output_rows':4, 'input_bytes':256, 'output_bytes':None,
        'writer_hold_seconds':.02, 'lock_wait_seconds':5,
    }


def test_driver_records_counters_and_preserves_subprocess_failure(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    fake = tmp_path / 'repo'
    (fake/'engine/lib').mkdir(parents=True)
    (fake/'.venv/bin').mkdir(parents=True)
    shutil.copy(root/'engine/lib/driver.sh', fake/'engine/lib/driver.sh')
    (fake/'.venv/bin/python').symlink_to(sys.executable)
    script = fake/'engine/test.sh'
    script.write_text('''#!/bin/bash
set -euo pipefail
DRIVER_NAME=test
DRIVER_LOCK=.test.lock
DRIVER_LOG_PREFIX=test
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"
body() {
  stage no-op
  "${PY}" -c 'from tools.stage_timings import record_flow; record_flow(input_rows=0,output_rows=0)'
  stage failed-work
  "${PY}" -c 'from tools.stage_timings import record_flow; record_flow(input_rows=3,output_rows=1,input_bytes=32); raise SystemExit(7)'
  stage unreachable
}
driver_main body
''')
    import os
    env={**os.environ,'PYTHONPATH':str(root)}
    result=subprocess.run(['bash',str(script)],env=env,capture_output=True)
    assert result.returncode==7
    rows=stage_timings.load_timings(fake/'logs/stage-timings.jsonl')
    assert [(r['stage'],r['exit'],r['input_rows'],r['output_rows']) for r in rows]==[
        ('no-op',0,0,0),('failed-work',7,3,1)]
    assert rows[0]['input_bytes'] is None
    assert rows[1]['input_bytes']==32
    assert not list((fake/'logs').glob('.stage-flow.*'))


def test_writer_lease_reports_retry_wait_and_hold(monkeypatch, tmp_path):
    from pathlib import Path

    from engine.lib import db
    path=tmp_path/'metrics'
    monkeypatch.setenv('TRADING_ENGINE_STAGE_METRICS',str(path))
    original=db.connect
    def connect(*args,**kwargs):
        db.log.info('[db] store locked (attempt 1/2) — retrying in 5s')
        return original(*args,**kwargs)
    monkeypatch.setattr(db,'connect',connect)
    with stage_timings.writer_connection(':memory:') as con:
        con.execute('SELECT 1')
    result=stage_timings.flow_totals(Path(path))
    assert result['lock_wait_seconds']==db._LOCK_RETRY_S
    assert result['writer_hold_seconds']>0


def test_history_shell_reuses_publisher_age_budget_and_propagates_failure(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    fake=tmp_path/'repo'
    (fake/'server').mkdir(parents=True)
    (fake/'.venv/bin').mkdir(parents=True)
    shutil.copy(root/'server/run_tradingview_history_archive.sh',fake/'server/run_tradingview_history_archive.sh')
    py=fake/'.venv/bin/python'
    py.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$ARGV_LOG"
if [[ "$*" == *tools.publish_snapshot* ]]; then exit "${PUBLISH_EXIT:-0}"; fi
''')
    py.chmod(0o755)
    log=fake/'argv'
    env={**os.environ,'ARGV_LOG':str(log),'PUBLISH_EXIT':'7'}
    run=subprocess.run(['bash',str(fake/'server/run_tradingview_history_archive.sh')],env=env)
    assert run.returncode==7
    assert log.read_text().splitlines()[-1]=='-m tools.publish_snapshot --min-age-minutes 1440'
