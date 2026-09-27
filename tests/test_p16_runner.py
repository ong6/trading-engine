"""P16 construction dry-run never invents missing calibration evidence."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from engine.lib import db
from server import p16_runner
from sim.schema import init_sim_schema


def test_calibration_unavailable_without_a_valid_p15_origin(con):
    result = p16_runner.calibrate(
        con, market_date=date(2026, 9, 25),
        generated_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    assert result["status"] == "calibration_unavailable"
    assert result["selected_lambda"] is None
    assert [row["status"] for row in result["books"]] == [
        "core_collecting", "core_collecting",
    ]


def test_calibration_risk_snapshot_uses_retained_scoring_cutoff(con, monkeypatch):
    cutoff = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(p16_runner.p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: {
        "scoring_information_cutoff_at": "2026-09-25T20:00:00Z",
    })

    def inspect_cutoff(_con, _origin, observed_cutoff):
        assert observed_cutoff == cutoff
        raise ValueError("checked")

    monkeypatch.setattr(p16_runner, "_snapshot", inspect_cutoff)
    result = p16_runner.calibrate(
        con, market_date=date(2026, 9, 25),
        generated_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    assert result["status"] == "calibration_unavailable"
    assert result["reason"] == "checked"


def test_copied_store_dry_run_leaves_source_unchanged(tmp_path):
    database = tmp_path / "market.duckdb"
    con = duckdb.connect(str(database))
    db.init_schema(con)
    init_sim_schema(con)
    con.close()
    before = database.read_bytes()

    result = p16_runner.dry_run(
        database, generated_at=datetime(2026, 9, 27, 16, tzinfo=timezone.utc),
        lock_path=tmp_path / "nightly.lock",
    )

    assert result["status"] == "completed" and result["dry_run"] is True
    assert result["source_database_modified"] is False
    assert result["calibration"]["status"] == "calibration_unavailable"
    assert result["calibration"]["reason"] == "no_valid_p15_origin"
    assert database.read_bytes() == before
