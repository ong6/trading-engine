"""The unattended historical grid must contain only meaningful live rules."""
import subprocess
import sys

import pytest

from engine.lib import db
from farm.backtest import grid, replay
from farm.backtest import report as backtest_report
from farm.walkforward import grid as walkforward_grid
from sim.schema import INITIAL_CASH


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_grid_excludes_retired_and_missing_historical_inputs():
    jobs = grid.grid()
    ids = {cid for cid, _window in jobs}
    assert not ids & {
        "news_gated_momo", "adaptive_mr", "adaptive_mr_frozen",
        "agentic_alloc", "agentic_alloc_frozen", "stop_tuner_turtle",
        "earnings_context_pead", "pead_ear", "discretionary",
        "macro_composite",
    }
    assert {"xs_momentum_12_1", "sector_momentum"} <= ids
    assert "multi_asset_trend" not in ids  # retired after its 2026-09-06 kill gate
    assert not any(cid == "multi_asset_trend"
                   for cid, _ in backtest_report.EXPECTED_GRID)
    assert any(cid == "multi_asset_trend"
               for cid, _ in backtest_report.RETAINED_RESULTS)


def test_strategy_level_exclusion_catches_twins():
    assert replay.excluded_reason("some_future_twin", "pead_ear")
    assert replay.excluded_reason("some_future_macro", "macro_composite")
    assert replay.excluded_reason("some_agent_book", "agent_only_policy")
    assert replay.excluded_reason("xs_momentum_12_1", "xs_momentum_12_1") is None


def test_direct_replay_refuses_retired_before_touching_store():
    with pytest.raises(SystemExit, match="retired"):
        replay.run_replay(None, "news_gated_momo", "6mo", write_result=False)


def test_registered_config_prefers_frozen_live_row(con):
    frozen = {"id": "sector_momentum", "name": "frozen",
              "strategy": "sector_momentum", "cadence": "monthly",
              "params": {"n": 2}}
    import json
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('sector_momentum','frozen','sector_momentum',?,DATE '2026-01-01',TRUE,?)",
        [json.dumps(frozen), INITIAL_CASH],
    )
    assert replay.registered_config(con, "sector_momentum") == frozen


@pytest.mark.parametrize("count", [0, 1, 2])
def test_replay_scratch_requires_exactly_one_portfolio(con, count):
    for index in range(count):
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash) "
            "VALUES (?, ?, 'none', '{}', DATE '2026-01-01', TRUE, ?)",
            [f"book-{index}", f"Book {index}", INITIAL_CASH],
        )

    if count == 1:
        replay._require_single_portfolio(con)
    else:
        with pytest.raises(
            RuntimeError,
            match=rf"exactly one portfolio; found {count}$",
        ):
            replay._require_single_portfolio(con)


def test_replay_scratch_cardinality_guard_survives_optimized_python():
    script = """
import duckdb

from farm.backtest.replay import _require_single_portfolio
from sim.schema import INITIAL_CASH, init_sim_schema

con = duckdb.connect()
init_sim_schema(con)
con.execute(
    "INSERT INTO portfolios "
    "(id, name, strategy, config, created, active, cash) VALUES "
    "('first', 'First', 'none', '{}', DATE '2026-01-01', TRUE, ?), "
    "('second', 'Second', 'none', '{}', DATE '2026-01-01', TRUE, ?)",
    [INITIAL_CASH, INITIAL_CASH],
)
try:
    _require_single_portfolio(con)
except RuntimeError as exc:
    if str(exc) != (
        "replay scratch database must contain exactly one portfolio; found 2"
    ):
        raise
else:
    raise SystemExit("optimized Python accepted contaminated replay scratch state")
finally:
    con.close()
"""
    subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )


def test_backtest_enqueue_dry_run_imports_packaged_queue_runner(con):
    db.init_schema(con)
    db.init_queue_schema(con)
    assert grid.enqueue(con, only_window="6mo", dry_run=True) == 0
    assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_walkforward_enqueue_dry_run_imports_packaged_queue_runner(con, monkeypatch):
    monkeypatch.setattr(walkforward_grid, "active_books", lambda _con: [{
        "id": "sector_momentum", "strategy": "sector_momentum", "excluded": None,
    }])
    assert walkforward_grid.enqueue(con, dry_run=True) == 0


@pytest.mark.parametrize("module", [grid, walkforward_grid])
def test_grid_main_closes_connection_on_schema_failure(monkeypatch, module):
    connection = _Connection()
    monkeypatch.setattr("sys.argv", ["grid.py", "--dry-run"])
    monkeypatch.setattr(module.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        module.db,
        "init_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected schema failure")),
    )

    with pytest.raises(RuntimeError, match="injected schema failure"):
        module.main()
    assert connection.closed is True
