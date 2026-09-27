"""P16 construction dry-run never invents missing calibration evidence."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import numpy as np

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


def test_calibration_uses_every_retained_snapshot_for_each_book(con, monkeypatch):
    dates = [date(2026, 9, 24), date(2026, 9, 25)]
    cutoffs = {
        dates[0]: "2026-09-24T20:00:00Z",
        dates[1]: "2026-09-25T20:00:00Z",
    }
    monkeypatch.setattr(p16_runner, "_calibration_dates", lambda *_args: dates)
    monkeypatch.setattr(
        p16_runner.p16_eval_inputs, "load_origin",
        lambda _con, *, market_date, report_cutoff: {
            "market_date": market_date.isoformat(),
            "scoring_information_cutoff_at": cutoffs[market_date],
        },
    )

    def snapshot(_con, origin, cutoff):
        index = dates.index(date.fromisoformat(origin["market_date"]))
        assert cutoff.isoformat() == cutoffs[dates[index]].replace("Z", "+00:00")
        values = {
            "alpha_h5": np.array([0.001, 0.002]),
            "covariance_h5": np.eye(2) * 0.001,
            "beta": np.ones(2),
        }
        return {
            "market_date": dates[index], "tickers": ["AAA", "BBB"],
            "sectors": ["a", "b"], "risk": {"champion": values, "rule": values},
            "risk_sha256": str(index + 1) * 64,
            "score_sha256": str(index + 3) * 64,
            "cost_per_turnover": 0.001 + index * 0.001,
        }

    def calibrate(cases):
        assert len(cases) == 4
        assert [row["book_id"] for row in cases] == [
            "p16_construct_ai", "p16_construct_rule",
            "p16_construct_ai", "p16_construct_rule",
        ]
        return {
            "status": "target_unattainable_on_grid", "selected_lambda": None,
            "selected_at_grid_endpoint": None, "grid_bounds": [0.1, 1000.0],
            "curve": [],
        }

    monkeypatch.setattr(p16_runner, "_snapshot", snapshot)
    monkeypatch.setattr(p16_runner.p16_calibration, "calibrate_lambda", calibrate)

    result = p16_runner.calibrate(
        con, market_date=dates[-1],
        generated_at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
    )

    assert result["snapshot_dates"] == [item.isoformat() for item in dates]
    assert result["risk_snapshot_sha256s"] == ["1" * 64, "2" * 64]
    assert result["cost_per_turnover"] == 0.002


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
