"""Producers read the primary, never a published generation (storage review, finding 1).

A generation lags the primary by up to its publication cadence. The nightly's market-date
step, the queue's parallel children, forward reviews and P15 scoring decide from what was
just written, so a read-only open of the store must see the primary.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from test_publish_snapshot import _repo

from engine import queue_runner
from engine.lib import db as engine_db
from engine.lib import settings
from tools import backup_database, publish_snapshot


def test_nightly_market_date_sees_the_session_written_after_the_last_publication(tmp_path):
    root, source = _repo(tmp_path)
    writer = engine_db.connect(source, wait_s=0)
    writer.execute("INSERT INTO universe (ticker, active, liquid) VALUES ('SPY', TRUE, TRUE)")
    writer.execute("UPDATE prices SET open=1, high=2, low=0.5, close=1.5, volume=100")
    writer.close()
    publish_snapshot.publish_snapshot(root, source)
    writer = engine_db.connect(source, wait_s=0)  # the nightly collect writes the next session
    writer.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,first_fetched_at) "
        "VALUES ('SPY','2026-10-02',1,2,0.5,1.5,100,'2026-10-02')"
    )
    for relative in backup_database._operational_files("2026-10-02"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"path": relative}) + "\n")
    assert str(engine_db.latest_operational_market_date(writer)) == "2026-10-02"
    writer.close()

    result = subprocess.run(
        [sys.executable, "-m", "engine.market_date"],
        env=dict(os.environ, TRADING_ENGINE_DB=str(source)),
        capture_output=True, text=True, check=False,
    )

    assert (result.returncode, result.stdout.strip()) == (0, "2026-10-02"), result.stderr


def test_queue_child_sees_a_job_enqueued_after_the_last_publication(
    tmp_path, monkeypatch, capsys,
):
    root, source = _repo(tmp_path)
    monkeypatch.setattr(settings, "DEFAULT_DB", source)
    monkeypatch.setattr(queue_runner.db, "DEFAULT_DB", source)
    monkeypatch.setattr(queue_runner.rsc, "apply_niceness", lambda: None)
    publish_snapshot.publish_snapshot(root, source)
    writer = engine_db.connect(source, wait_s=0)
    writer.execute(
        "INSERT INTO jobs (id, kind, params, state) VALUES (42, 'probe-kind', '{}', 'pending')"
    )
    writer.close()

    result = queue_runner.cmd_run_one(42, None, tmp_path / "meta.json")

    # The child found the row (a generation would say "no such job") and stopped at dispatch.
    assert result == 2
    assert "no dispatch entry for 'probe-kind'" in capsys.readouterr().out
