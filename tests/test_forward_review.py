"""Maturity and frozen-criterion tests for the live forward-paper monitor."""

import copy
import json
import shutil
import sys
from datetime import date, timedelta

import pytest

from engine import forward_review


@pytest.fixture(autouse=True)
def _test_baseline(monkeypatch):
    state = {
        portfolio_id: {
            "cash": 0.0,
            "equity": 100.0,
            "n_positions": 1,
            "positions": [["TEST", 1.0, 100.0, 100.0]],
        }
        for portfolio_id in (forward_review.CANDIDATE_ID, forward_review.CONTROL_ID)
    }
    monkeypatch.setattr(
        forward_review,
        "EXPECTED_BASELINE_EQUITY",
        {forward_review.CANDIDATE_ID: 100.0, forward_review.CONTROL_ID: 100.0},
    )
    monkeypatch.setattr(forward_review, "EXPECTED_BASELINE_STATE", state)
    monkeypatch.setattr(
        forward_review, "EXPECTED_BASELINE_STATE_SHA256", forward_review.canonical_sha256(state)
    )


def _setup(con, *, criterion=forward_review.EXPECTED_KILL_CRITERION):
    con.execute(
        "INSERT OR IGNORE INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES ('TEST', ?, 100, 100, 100, 100, 1000000)",
        [forward_review.OBSERVATION_START],
    )
    for portfolio_id in (forward_review.CANDIDATE_ID, forward_review.CONTROL_ID):
        if portfolio_id == forward_review.CANDIDATE_ID:
            config = {
                "id": "sector_momentum",
                "name": "Sector ETF Rotation",
                "strategy": "sector_momentum",
                "cadence": "monthly",
                "params": {
                    "sectors": [
                        "XLK",
                        "XLF",
                        "XLE",
                        "XLV",
                        "XLI",
                        "XLY",
                        "XLP",
                        "XLU",
                        "XLB",
                        "XLRE",
                        "XLC",
                    ],
                    "n": 3,
                    "lookbacks": [63, 126, 252],
                },
                "description": "Monthly: score the 11 SPDR sector ETFs by their mean 3/6/"
                "12-month total return, hold the top 3 equal-weight; a slot whose ETF has "
                "a non-positive 12-month return sits in cash.",
                "expectation": "Market-like return with lower drawdown — it wins by losing "
                "less in downturns, not by out-running the index.",
                "kill_criterion": criterion,
            }
        else:
            config = {
                "id": "spy_benchmark",
                "name": "SPY Buy & Hold",
                "strategy": "spy_benchmark",
                "cadence": "once",
                "params": {"ticker": "SPY"},
                "description": "Buy SPY once at inception and hold. The market benchmark.",
                "expectation": "Baseline market return; the absolute-return yardstick.",
                "kill_criterion": "Reference benchmark — not killed.",
            }
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, execution_profile) "
            "VALUES (?, ?, ?, ?, DATE '2024-01-02', TRUE, 0, 39000, 'baseline_v1')",
            [portfolio_id, portfolio_id, portfolio_id, json.dumps(config)],
        )
        con.execute(
            "INSERT INTO sim_positions VALUES (?, 'TEST', 1, 100)", [portfolio_id]
        )


def _equity(
    con, start: date, n: int, candidate_end: float, control_end: float, *, step_days: int = 2
):
    for i in range(n):
        d = start + timedelta(days=i * step_days)
        frac = i / (n - 1)
        candidate = 100 + (candidate_end - 100) * frac
        control = 100 + (control_end - 100) * frac
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 0, 1)",
            [forward_review.CANDIDATE_ID, d, candidate],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 0, 1)",
            [forward_review.CONTROL_ID, d, control],
        )


def test_partial_forward_record_never_fires_kill(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 30, 70, 120)
    result = forward_review.evaluate(con)
    assert result["status"] == "ACCUMULATING"
    assert result["checks"]["trails_control_by_more_than_10pp"] is True
    assert result["checks"]["kill_triggered"] is False


def test_plus_months_clamps_month_end():
    assert forward_review._plus_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert forward_review._plus_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


@pytest.mark.parametrize("bad_equity", [float("nan"), float("inf"), 0.0, -1.0])
def test_forward_metrics_reject_nonfinite_or_nonpositive_equity(bad_equity):
    rows = [(forward_review.OBSERVATION_START, bad_equity, 100.0)]
    with pytest.raises(ValueError, match="finite positive"):
        forward_review._book_metrics(rows, 1)


def test_mature_record_requests_kill_review_when_both_clauses_hold(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 400, 90, 120, step_days=1)
    result = forward_review.evaluate(con)
    assert result["observation"]["mature"] is True
    assert result["checks"]["has_lower_drawdown"] is False
    assert result["status"] == "REVIEW-KILL"


def test_drawdown_improvement_prevents_kill(con):
    _setup(con)
    start = forward_review.OBSERVATION_START
    for i in range(400):
        d = start + timedelta(days=i)
        frac = i / 399
        candidate = 100 + 5 * frac
        control = (100 - 30 * (i / 199)) if i < 200 else (70 + 50 * ((i - 200) / 199))
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 0, 1)",
            [forward_review.CANDIDATE_ID, d, candidate],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 0, 1)", [forward_review.CONTROL_ID, d, control]
        )
    result = forward_review.evaluate(con)
    assert result["metrics"]["excess_return"] < -0.10
    assert result["checks"]["has_lower_drawdown"] is True
    assert result["status"] == "CONTINUE"


def test_registration_change_fails_closed(con):
    _setup(con, criterion="changed after observation")
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    with pytest.raises(ValueError, match="kill criterion changed"):
        forward_review.evaluate(con)


def test_noncriterion_config_change_fails_closed(con):
    _setup(con)
    config = json.loads(
        con.execute(
            "SELECT config FROM portfolios WHERE id = ?", [forward_review.CANDIDATE_ID]
        ).fetchone()[0]
    )
    config["params"]["n"] = 4
    con.execute(
        "UPDATE portfolios SET config = ? WHERE id = ?",
        [json.dumps(config), forward_review.CANDIDATE_ID],
    )
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    with pytest.raises(ValueError, match="config changed"):
        forward_review.evaluate(con)


def test_report_writes_markdown_and_json(con, tmp_path):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 3, 101, 102)
    result = forward_review.evaluate(con)
    md_path, json_path = forward_review.write_report(result, tmp_path)
    assert "Status **ACCUMULATING**" in md_path.read_text()
    assert json.loads(json_path.read_text())["automatic_action"] == "none"


def test_pre_boundary_equity_is_not_credited(con):
    _setup(con)
    _equity(con, date(2026, 8, 1), 2, 200, 50)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    result = forward_review.evaluate(con)
    assert result["observation"]["first_shared_date"] == "2026-09-04"
    assert result["metrics"]["excess_return"] == pytest.approx(0.0)


def test_missing_boundary_mark_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START + timedelta(days=1), 2, 100, 100)
    with pytest.raises(ValueError, match="missing frozen forward baseline"):
        forward_review.evaluate(con)


def test_fill_model_change_fails_closed(con, monkeypatch):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    monkeypatch.setattr(forward_review, "FILL_MODEL_VERSION", "v-next")
    with pytest.raises(ValueError, match="fill model changed"):
        forward_review.evaluate(con)


def test_execution_profile_change_fails_closed(con, monkeypatch):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    monkeypatch.setattr(forward_review, "EXPECTED_PROFILE_SHA256", "changed")
    with pytest.raises(ValueError, match="execution profile .* changed"):
        forward_review.evaluate(con)


def test_runtime_contract_change_fails_closed(con, monkeypatch):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    monkeypatch.setattr(forward_review, "EXPECTED_RUNTIME_CONTRACT_SHA256", "changed")
    with pytest.raises(ValueError, match="strategy/execution source changed"):
        forward_review.evaluate(con)


def test_runtime_contract_hash_covers_true_dependency(tmp_path):
    for relative in forward_review.RUNTIME_CONTRACT_FILES:
        source = forward_review.REPO_ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    assert (
        forward_review._runtime_contract_sha256(tmp_path)
        == forward_review.EXPECTED_RUNTIME_CONTRACT_SHA256
    )
    dependency = tmp_path / "engine" / "lib" / "db.py"
    dependency.write_text(dependency.read_text() + "\n# contract mutation probe\n")
    assert (
        forward_review._runtime_contract_sha256(tmp_path)
        != forward_review.EXPECTED_RUNTIME_CONTRACT_SHA256
    )


def test_unrelated_strategy_registration_does_not_invalidate_monitor(con, monkeypatch):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    monkeypatch.setitem(forward_review.REGISTRY, "unrelated_research_probe", object)
    assert forward_review.evaluate(con)["status"] == "ACCUMULATING"


def test_monitored_strategy_registry_remap_fails_closed(con, monkeypatch):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    monkeypatch.setitem(forward_review.REGISTRY, forward_review.CANDIDATE_ID, object)
    with pytest.raises(ValueError, match="registry mapping changed"):
        forward_review.evaluate(con)


def test_baseline_equity_change_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    con.execute(
        "UPDATE sim_equity SET equity = 99 WHERE portfolio_id = ? AND date = ?",
        [forward_review.CANDIDATE_ID, forward_review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline equity changed"):
        forward_review.evaluate(con)


def test_baseline_cash_change_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    con.execute(
        "UPDATE sim_equity SET cash = 1 WHERE portfolio_id = ? AND date = ?",
        [forward_review.CANDIDATE_ID, forward_review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline account state changed"):
        forward_review.evaluate(con)


def test_baseline_position_count_change_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    con.execute(
        "UPDATE sim_equity SET n_positions = 2 WHERE portfolio_id = ? AND date = ?",
        [forward_review.CANDIDATE_ID, forward_review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline account state changed"):
        forward_review.evaluate(con)


def test_baseline_mark_change_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    con.execute(
        "UPDATE prices SET close = 99 WHERE ticker = 'TEST' AND date = ?",
        [forward_review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline mark is unavailable"):
        forward_review.evaluate(con)


def _post_boundary_fill(con, *, cost_bps=10.0):
    signal = forward_review.OBSERVATION_START
    fill_date = signal + timedelta(days=1)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'TEST', 'buy', 1, ?, 'filled', NULL)",
        [forward_review.CANDIDATE_ID, signal],
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(1, ?, 'TEST', 'buy', 1, ?, 100, ?, 10, ?)",
        [forward_review.CANDIDATE_ID, fill_date, 100 * (1 + cost_bps / 1e4), cost_bps],
    )
    con.execute(
        "INSERT INTO sim_fill_costs VALUES "
        "(1, 'baseline_v1', 0.001, 10, 0, 0, ?)", [cost_bps]
    )
    con.execute(
        "INSERT INTO sim_execution_attempts VALUES "
        "(1, ?, 'baseline_v1', 100, 100000, 0.001, 'filled', NULL)", [fill_date]
    )


def test_forward_fill_ledger_is_validated_and_hashed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    _post_boundary_fill(con)
    result = forward_review.evaluate(con)
    assert result["schema_version"] == 2
    assert (
        result["frozen_runtime"]["runtime_contract_version"]
        == forward_review.RUNTIME_CONTRACT_VERSION
    )
    assert (
        result["frozen_runtime"]["superseded_runtime_contract_sha256"]
        == forward_review.SUPERSEDED_RUNTIME_CONTRACT_SHA256
    )
    assert "interruption-safe transaction cleanup" in (
        result["frozen_runtime"]["runtime_contract_migration"]
    )
    assert result["execution"][forward_review.CANDIDATE_ID]["filled"] == 1
    assert len(result["observation"]["forward_ledger_sha256"]) == 64


def _prior_v6_result(con) -> dict:
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    prior = forward_review.evaluate(con)
    prior["frozen_runtime"].update(
        runtime_contract_version=forward_review.PRIOR_RUNTIME_CONTRACT_VERSION,
        runtime_contract_sha256=forward_review.PRIOR_RUNTIME_CONTRACT_SHA256,
        superseded_runtime_contract_sha256=(
            forward_review.PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256
        ),
        runtime_contract_migration=forward_review.PRIOR_RUNTIME_CONTRACT_MIGRATION,
        runtime_contract_files=list(forward_review.PRIOR_RUNTIME_CONTRACT_FILES),
    )
    return prior


def test_normal_run_refuses_silent_runtime_contract_migration(con):
    prior = _prior_v6_result(con)

    with pytest.raises(ValueError, match="requires explicit migration"):
        forward_review.evaluate(con, prior_result=prior)


def test_runtime_contract_migration_preserves_complete_prior_result(con):
    prior = _prior_v6_result(con)

    migrated = forward_review.migrate_runtime_contract(con, prior)

    expected = copy.deepcopy(prior)
    expected["frozen_runtime"].update(forward_review._runtime_metadata())
    assert migrated == expected
    assert (
        migrated["frozen_runtime"]["runtime_contract_version"]
        == forward_review.RUNTIME_CONTRACT_VERSION
    )


def test_runtime_contract_migration_rejects_changed_prior_evidence(con):
    prior = _prior_v6_result(con)
    prior["observation"]["equity_sha256"] = "changed"

    with pytest.raises(ValueError, match="not the exact migration checkpoint"):
        forward_review.migrate_runtime_contract(con, prior)


def test_filled_order_without_cost_detail_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    _post_boundary_fill(con)
    con.execute("DELETE FROM sim_fill_costs WHERE order_id = 1")
    with pytest.raises(ValueError, match="fill-cost ledger is incomplete"):
        forward_review.evaluate(con)


def test_filled_order_without_execution_attempt_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    _post_boundary_fill(con)
    con.execute("DELETE FROM sim_execution_attempts WHERE order_id = 1")
    with pytest.raises(ValueError, match="no matching execution attempt"):
        forward_review.evaluate(con)


def test_forged_fill_arithmetic_fails_closed(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    _post_boundary_fill(con)
    con.execute("UPDATE sim_fills SET fill_px = 99 WHERE order_id = 1")
    with pytest.raises(ValueError, match="fill price is inconsistent"):
        forward_review.evaluate(con)


def test_previous_published_execution_ledger_cannot_be_rewritten(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    _post_boundary_fill(con)
    prior = forward_review.evaluate(con)
    con.execute(
        "UPDATE sim_execution_attempts SET raw_notional = 101 WHERE order_id = 1"
    )
    with pytest.raises(ValueError, match="published forward execution ledger changed"):
        forward_review.evaluate(con, prior_result=prior)


def test_pending_order_may_fill_after_prior_checkpoint(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    signal = forward_review.OBSERVATION_START + timedelta(days=2)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'TEST', 'buy', 1, ?, 'pending', NULL)",
        [forward_review.CANDIDATE_ID, signal],
    )
    prior = forward_review.evaluate(con)
    fill_date = signal + timedelta(days=1)
    con.execute("UPDATE sim_orders SET status = 'filled' WHERE id = 1")
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(1, ?, 'TEST', 'buy', 1, ?, 100, 100.1, 10, 10)",
        [forward_review.CANDIDATE_ID, fill_date],
    )
    con.execute(
        "INSERT INTO sim_fill_costs VALUES "
        "(1, 'baseline_v1', 0.001, 10, 0, 0, 10)"
    )
    con.execute(
        "INSERT INTO sim_execution_attempts VALUES "
        "(1, ?, 'baseline_v1', 100, 100000, 0.001, 'filled', NULL)", [fill_date]
    )
    for portfolio_id, equity in (
        (forward_review.CANDIDATE_ID, 102),
        (forward_review.CONTROL_ID, 101),
    ):
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 0, 1)",
            [portfolio_id, fill_date, equity],
        )
    result = forward_review.evaluate(con, prior_result=prior)
    assert result["execution"][forward_review.CANDIDATE_ID]["filled"] == 1


def test_previous_published_equity_cannot_be_rewritten(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 3, 105, 103)
    prior = forward_review.evaluate(con)
    con.execute(
        "UPDATE sim_equity SET equity = equity + 1 WHERE portfolio_id = ? AND date = ?",
        [forward_review.CANDIDATE_ID, forward_review.OBSERVATION_START + timedelta(days=2)],
    )
    with pytest.raises(ValueError, match="previously published forward equity window changed"):
        forward_review.evaluate(con, prior_result=prior)


def test_previous_published_equity_may_only_be_extended(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    prior = forward_review.evaluate(con)
    d = forward_review.OBSERVATION_START + timedelta(days=4)
    con.execute(
        "INSERT INTO sim_equity VALUES (?, ?, 102, 0, 1)",
        [forward_review.CANDIDATE_ID, d],
    )
    con.execute(
        "INSERT INTO sim_equity VALUES (?, ?, 101, 0, 1)",
        [forward_review.CONTROL_ID, d],
    )
    result = forward_review.evaluate(con, prior_result=prior)
    assert result["observation"]["shared_sessions_available"] == 3


def test_rolling_window_never_releases_old_equity_prefix(con):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 400, 110, 108, step_days=1)
    prior = forward_review.evaluate(con)
    assert prior["observation"]["window_start"] != prior["observation"]["first_shared_date"]
    con.execute(
        "UPDATE sim_equity SET equity = equity + 1 WHERE portfolio_id = ? AND date = ?",
        [forward_review.CANDIDATE_ID, forward_review.OBSERVATION_START + timedelta(days=1)],
    )
    with pytest.raises(ValueError, match="previously published forward equity window changed"):
        forward_review.evaluate(con, prior_result=prior)


def test_main_replaces_stale_report_with_invalid_on_evaluation_failure(
    con, tmp_path, monkeypatch
):
    _setup(con, criterion="changed after observation")
    _equity(con, forward_review.OBSERVATION_START, 2, 100, 100)
    report_dir = tmp_path / "reports" / "forward"
    report_dir.mkdir(parents=True)
    (report_dir / "sector_momentum.json").write_text(
        json.dumps({"status": "ACCUMULATING", "stale": True})
    )
    (report_dir / "sector_momentum.md").write_text("stale accumulating report")
    monkeypatch.setattr(forward_review.db, "connect", lambda *_args, **_kwargs: con)
    monkeypatch.setattr(
        sys, "argv", ["forward_review.py", "--db", "ignored", "--data-dir", str(tmp_path)]
    )

    assert forward_review.main() == 1
    payload = json.loads((report_dir / "sector_momentum.json").read_text())
    assert payload["status"] == "INVALID"
    assert payload["paper_only"] is True
    assert payload["automatic_action"] == "none"
    assert payload["error"]["type"] == "ValueError"
    markdown = (report_dir / "sector_momentum.md").read_text()
    assert "Status **INVALID**" in markdown
    assert "stale accumulating report" not in markdown


def test_main_preserves_last_valid_checkpoint_through_invalid_report(
    con, tmp_path, monkeypatch
):
    _setup(con)
    _equity(con, forward_review.OBSERVATION_START, 2, 101, 100)
    valid = forward_review.evaluate(con)
    report_dir = tmp_path / "reports" / "forward"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "sector_momentum.json"
    report_path.write_text(json.dumps(valid, default=str))
    class ConnectionProxy:
        def __getattr__(self, name):
            return getattr(con, name)

        def close(self):
            pass

    monkeypatch.setattr(
        forward_review.db, "connect", lambda *_args, **_kwargs: ConnectionProxy()
    )
    monkeypatch.setattr(
        sys, "argv", ["forward_review.py", "--db", "ignored", "--data-dir", str(tmp_path)]
    )
    con.execute(
        "UPDATE portfolios SET execution_profile = 'changed' WHERE id = ?",
        [forward_review.CANDIDATE_ID],
    )
    assert forward_review.main() == 1
    invalid = json.loads(report_path.read_text())
    assert invalid["last_valid_result"]["observation"] == valid["observation"]
    con.execute(
        "UPDATE portfolios SET execution_profile = 'baseline_v1' WHERE id = ?",
        [forward_review.CANDIDATE_ID],
    )
    assert forward_review.main() == 0
    restored = json.loads(report_path.read_text())
    assert restored["status"] == "ACCUMULATING"
    assert restored["observation"] == valid["observation"]
