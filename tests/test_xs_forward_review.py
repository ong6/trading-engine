"""Prospective lifecycle tests for the raw-momentum forward monitor."""

from __future__ import annotations

import calendar
import json
import shutil
from datetime import date

import pytest

from engine import xs_forward_review as review
from sim.strategies.configs import config_by_id
from tests.conftest import insert_bars


def _setup(con) -> None:
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR, name VARCHAR, exchange VARCHAR, "
        "etf BOOLEAN, member VARCHAR, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute("INSERT INTO universe VALUES ('AAA', 'AAA', 'N', FALSE, 'listed', TRUE, TRUE)")
    con.execute(
        "CREATE TABLE universe_snapshot (snapshot_date DATE, ticker VARCHAR, name VARCHAR, "
        "exchange VARCHAR, etf BOOLEAN, member VARCHAR, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe_snapshot VALUES (?, 'AAA', 'AAA', 'N', FALSE, 'listed', TRUE, TRUE)",
        [review.SIGNAL_DATE],
    )
    con.execute(
        "CREATE TABLE screen_results (run_date DATE, ticker VARCHAR, close DOUBLE, "
        "rs_rank INTEGER, template_score INTEGER, passes_template BOOLEAN, "
        "dist_50d DOUBLE, dist_200d DOUBLE, off_52w_low DOUBLE, off_52w_high DOUBLE, "
        "base_tight BOOLEAN, vol_dryup BOOLEAN, new_today BOOLEAN, universe_policy VARCHAR)"
    )
    con.execute(
        "INSERT INTO screen_results VALUES (?, 'AAA', 100, 99, 8, TRUE, 0, 0, 1, 0, "
        "TRUE, TRUE, TRUE, 'all')",
        [review.SIGNAL_DATE],
    )
    sessions = []
    d = review.SIGNAL_DATE
    while len(sessions) < 253:
        if review.nyse.is_session(d):
            sessions.append(d)
        d = date.fromordinal(d.toordinal() - 1)
    insert_bars(con, "AAA", list(reversed(sessions)), open_=100.0, close=100.0)
    for portfolio_id in (review.CANDIDATE_ID, review.CONTROL_ID):
        cfg = config_by_id(portfolio_id)
        con.execute(
            "INSERT INTO portfolios "
            "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
            "VALUES (?,?,?,?,DATE '2026-09-02',TRUE,39000,39000,'baseline_v1')",
            [portfolio_id, cfg["name"], cfg["strategy"], json.dumps(cfg)],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,39000,39000,0)",
            [portfolio_id, review.SIGNAL_DATE],
        )
    quantities = {review.CANDIDATE_ID: 7.8, review.CONTROL_ID: 390.0}
    for i, portfolio_id in enumerate((review.CANDIDATE_ID, review.CONTROL_ID), start=1):
        con.execute(
            "INSERT INTO sim_orders VALUES (?,?,'AAA','buy',?,?,'pending',NULL)",
            [i, portfolio_id, quantities[portfolio_id], review.SIGNAL_DATE],
        )


def _transition(con, candidate=39_000.0, control=41_000.0, *, control_noop=False) -> None:
    quantities = {review.CANDIDATE_ID: 7.8, review.CONTROL_ID: 390.0}
    for i, portfolio_id in enumerate((review.CANDIDATE_ID, review.CONTROL_ID), start=1):
        if control_noop and portfolio_id == review.CONTROL_ID:
            continue
        con.execute("UPDATE sim_orders SET status='filled' WHERE id=?", [i])
        con.execute(
            "INSERT INTO sim_fills VALUES (?,?, 'AAA','buy',?,?,100,100,0,0)",
            [i, portfolio_id, quantities[portfolio_id], review.OBSERVATION_START],
        )
        con.execute(
            "INSERT OR REPLACE INTO sim_positions VALUES (?, 'AAA', ?, 100)",
            [portfolio_id, quantities[portfolio_id]],
        )
    for portfolio_id, equity in (
        (review.CANDIDATE_ID, candidate),
        (review.CONTROL_ID, control),
    ):
        con.execute(
            "UPDATE portfolios SET cash = ? WHERE id = ?",
            [equity - quantities[portfolio_id] * 100.0, portfolio_id],
        )
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,?,1)",
        [review.CANDIDATE_ID, review.OBSERVATION_START, candidate, candidate - 780.0],
    )
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,?,1)",
        [review.CONTROL_ID, review.OBSERVATION_START, control, control - 39_000.0],
    )


def _freeze(con) -> dict:
    result = review.evaluate(con)
    assert result["status"] == "WAITING"
    assert result["frozen_runtime"]["signal_boundary"] is not None
    return result


def _append_month_ends(con, months: int, *, candidate_step: float, control_step: float) -> None:
    candidate, control = 39_000.0, 41_000.0
    for offset in range(months):
        shifted = review._plus_months(review.OBSERVATION_START, offset)
        d = date(shifted.year, shifted.month, calendar.monthrange(shifted.year, shifted.month)[1])
        while not review.nyse.is_session(d):
            d = date.fromordinal(d.toordinal() - 1)
        candidate *= candidate_step
        control *= control_step
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
            [review.CANDIDATE_ID, d, candidate],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
            [review.CONTROL_ID, d, control],
        )


def test_waits_before_exact_post_fill_boundary(con):
    _setup(con)
    result = review.evaluate(con)
    assert result["status"] == "WAITING"
    assert result["paper_only"] is True and result["automatic_action"] == "none"
    assert result["observation"]["signal_boundary_frozen"] is True
    boundary = result["frozen_runtime"]["signal_boundary"]
    assert boundary["signal_input_hashes"]["candidate_signal_rows_sha256"]
    assert boundary["signal_input_hashes"]["control_target_rows_sha256"]
    assert boundary["signal_ledger_sha256"]


def test_signal_freeze_rejects_live_universe_that_differs_from_snapshot(con):
    _setup(con)
    con.execute("UPDATE universe SET liquid=FALSE WHERE ticker='AAA'")
    with pytest.raises(ValueError, match="snapshot does not match the signal universe"):
        review.evaluate(con)


def test_waiting_before_signal_has_no_frozen_boundary(con):
    _setup(con)
    con.execute("DELETE FROM sim_orders")
    con.execute("DELETE FROM sim_equity")
    for portfolio_id in (review.CANDIDATE_ID, review.CONTROL_ID):
        con.execute(
            "INSERT INTO sim_equity VALUES (?,DATE '2026-09-29',39000,39000,0)",
            [portfolio_id],
        )
    result = review.evaluate(con)
    assert result["status"] == "WAITING"
    assert result["observation"]["signal_boundary_frozen"] is False
    assert result["frozen_runtime"]["signal_boundary"] is None


def test_signal_freeze_rejects_preinvested_first_signal_candidate(con):
    _setup(con)
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [review.CANDIDATE_ID])
    con.execute(
        "UPDATE sim_equity SET cash=0,n_positions=1 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.SIGNAL_DATE],
    )
    con.execute("INSERT INTO sim_positions VALUES (?, 'AAA', 390, 100)", [review.CANDIDATE_ID])
    with pytest.raises(ValueError, match="already invested before its first signal"):
        review.evaluate(con)


def test_signal_freeze_rejects_position_count_mismatch(con):
    _setup(con)
    con.execute(
        "UPDATE sim_equity SET n_positions=1 WHERE portfolio_id=? AND date=?",
        [review.CONTROL_ID, review.SIGNAL_DATE],
    )
    with pytest.raises(ValueError, match="signal-date position count is inconsistent"):
        review.evaluate(con)


def test_signal_freeze_rejects_cash_mismatch(con):
    _setup(con)
    con.execute(
        "UPDATE sim_equity SET cash=cash-1 WHERE portfolio_id=? AND date=?",
        [review.CONTROL_ID, review.SIGNAL_DATE],
    )
    with pytest.raises(ValueError, match="signal-date cash is inconsistent"):
        review.evaluate(con)


def test_signal_freeze_rejects_equity_mismatch(con):
    _setup(con)
    con.execute(
        "UPDATE sim_equity SET equity=equity+1 WHERE portfolio_id=? AND date=?",
        [review.CONTROL_ID, review.SIGNAL_DATE],
    )
    with pytest.raises(ValueError, match="signal-date equity is inconsistent"):
        review.evaluate(con)


def test_exact_signal_to_next_open_transition_is_required(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute("UPDATE sim_orders SET signal_date=DATE '2026-09-29' WHERE id=1")
    with pytest.raises(ValueError, match="(emitted no orders|signal order hash changed)"):
        review.evaluate(con, prior_result=prior)


def test_baseline_refuses_to_start_without_published_signal_boundary(con):
    _setup(con)
    _transition(con)
    with pytest.raises(ValueError, match="was not published before execution"):
        review.evaluate(con)


def test_baseline_rejects_position_count_mismatch(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute(
        "UPDATE sim_equity SET n_positions=2 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline position count is inconsistent"):
        review.evaluate(con, prior_result=prior)


def test_baseline_rejects_portfolio_cash_mismatch(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute("UPDATE portfolios SET cash=cash+1 WHERE id=?", [review.CANDIDATE_ID])
    with pytest.raises(ValueError, match="baseline cash is inconsistent"):
        review.evaluate(con, prior_result=prior)


def test_baseline_rejects_equity_mismatch(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute(
        "UPDATE sim_equity SET equity=equity+1 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="baseline equity is inconsistent"):
        review.evaluate(con, prior_result=prior)


def test_repeated_signal_day_run_preserves_and_checks_boundary(con):
    _setup(con)
    prior = _freeze(con)
    repeated = review.evaluate(con, prior_result=prior)
    assert (
        repeated["frozen_runtime"]["signal_boundary"]
        == (prior["frozen_runtime"]["signal_boundary"])
    )
    con.execute("UPDATE sim_orders SET qty=qty+1 WHERE id=1")
    with pytest.raises(ValueError, match="signal order hash changed"):
        review.evaluate(con, prior_result=prior)


def test_signal_boundary_pins_complete_protocol_contract(con):
    _setup(con)
    prior = _freeze(con)
    boundary = prior["frozen_runtime"]["signal_boundary"]
    assert boundary["protocol_contract"]["runtime_contract_sha256"] == (
        review.EXPECTED_RUNTIME_CONTRACT_SHA256
    )
    boundary["protocol_contract"]["criterion_sha256"] = "changed"
    with pytest.raises(ValueError, match="protocol contract changed"):
        review.evaluate(con, prior_result=prior)


def test_published_signal_execution_ledger_cannot_be_rewritten(con):
    _setup(con)
    con.execute(
        "INSERT INTO sim_fills VALUES (99,?,'OLD','buy',1,DATE '2026-09-01',10,10,0,0)",
        [review.CONTROL_ID],
    )
    prior = _freeze(con)
    con.execute("UPDATE sim_fills SET fill_px=11 WHERE order_id=99")
    with pytest.raises(ValueError, match="frozen XS signal ledger changed"):
        review.evaluate(con, prior_result=prior)


def test_late_dividend_does_not_invalidate_signal_checkpoint(con):
    _setup(con)
    prior = _freeze(con)
    con.execute(
        "INSERT INTO sim_dividends VALUES (?, 'AAA', DATE '2026-09-29', 1, 1, 1)",
        [review.CONTROL_ID],
    )
    assert review.evaluate(con, prior_result=prior)["status"] == "WAITING"


def test_partial_record_accumulates_and_records_integrity(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    result = review.evaluate(con, prior_result=prior)
    assert result["status"] == "ACCUMULATING"
    assert result["observation"]["paired_complete_months"] == 2
    assert result["checks"]["execution_clean"] is True
    assert result["frozen_runtime"]["baseline_equity"] == {
        review.CANDIDATE_ID: 39_000.0,
        review.CONTROL_ID: 41_000.0,
    }


def test_month_counts_at_last_session_but_not_before(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    for d in (date(2026, 10, 29), date(2026, 10, 30)):
        con.execute("INSERT INTO sim_equity VALUES (?,?,40000,0,50)", [review.CANDIDATE_ID, d])
        con.execute("INSERT INTO sim_equity VALUES (?,?,41500,0,50)", [review.CONTROL_ID, d])
        result = review.evaluate(con, prior_result=prior)
        expected = 1 if d == date(2026, 10, 30) else 0
        assert result["observation"]["paired_complete_months"] == expected


def test_missing_complete_month_fails_closed(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    for portfolio_id in (review.CANDIDATE_ID, review.CONTROL_ID):
        con.execute(
            "INSERT INTO sim_equity VALUES (?,DATE '2026-11-02',40000,0,50)",
            [portfolio_id],
        )
    with pytest.raises(ValueError, match="missing scheduled month-end.*2026-10"):
        review.evaluate(con, prior_result=prior)


def test_invested_control_may_have_an_explicitly_hashed_noop_rebalance(con):
    _setup(con)
    con.execute("DELETE FROM sim_orders WHERE portfolio_id=?", [review.CONTROL_ID])
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [review.CONTROL_ID])
    con.execute(
        "UPDATE sim_equity SET cash=0,n_positions=1 WHERE portfolio_id=? AND date=?",
        [review.CONTROL_ID, review.SIGNAL_DATE],
    )
    con.execute("INSERT INTO sim_positions VALUES (?, 'AAA', 390, 100)", [review.CONTROL_ID])
    prior = _freeze(con)
    _transition(con, control_noop=True)
    result = review.evaluate(con, prior_result=prior)
    assert result["status"] == "ACCUMULATING"
    assert result["frozen_runtime"]["initial_transition_sha256"]


def test_candidate_must_trade_at_its_first_signal(con):
    _setup(con)
    con.execute("DELETE FROM sim_orders WHERE portfolio_id=?", [review.CANDIDATE_ID])
    with pytest.raises(ValueError, match="frozen signal orders do not match"):
        review.evaluate(con)


def test_mature_positive_edge_passes_only_after_five_years(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    _append_month_ends(con, 60, candidate_step=1.02, control_step=1.005)
    mature = review.OBSERVATION_START.replace(year=2031)
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
        [review.CANDIDATE_ID, mature, 39_000.0 * 1.02**60],
    )
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
        [review.CONTROL_ID, mature, 41_000.0 * 1.005**60],
    )
    result = review.evaluate(con, prior_result=prior)
    assert result["status"] == "PASS-FORWARD"
    assert result["observation"]["mature"] is True
    assert result["checks"]["mean_excess_ci_above_zero"] is True


def test_mature_nonpositive_edge_is_inconclusive(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    _append_month_ends(con, 60, candidate_step=1.005, control_step=1.01)
    mature = review.OBSERVATION_START.replace(year=2031)
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
        [review.CANDIDATE_ID, mature, 39_000.0 * 1.005**60],
    )
    con.execute(
        "INSERT INTO sim_equity VALUES (?,?,?,0,50)",
        [review.CONTROL_ID, mature, 41_000.0 * 1.01**60],
    )
    assert review.evaluate(con, prior_result=prior)["status"] == "INCONCLUSIVE"


def test_drawdown_requests_review_before_maturity(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    d = date(2026, 10, 30)
    con.execute("INSERT INTO sim_equity VALUES (?,?,15000,0,50)", [review.CANDIDATE_ID, d])
    con.execute("INSERT INTO sim_equity VALUES (?,?,40000,0,50)", [review.CONTROL_ID, d])
    assert review.evaluate(con, prior_result=prior)["status"] == "REVIEW-KILL"


def test_initial_rejected_order_invalidates_baseline(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (3,?,'BAD','buy',1,?,'rejected','probe')",
        [review.CANDIDATE_ID, review.SIGNAL_DATE],
    )
    with pytest.raises(ValueError, match="signal order hash changed"):
        review.evaluate(con, prior_result=prior)


def test_later_rejected_order_requests_review(con):
    _setup(con)
    prior = _freeze(con)
    _transition(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (3,?,'BAD','buy',1,?,'rejected','probe')",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    assert review.evaluate(con, prior_result=prior)["status"] == "REVIEW-KILL"


def test_published_equity_prefix_cannot_be_rewritten(con):
    _setup(con)
    frozen = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    prior = review.evaluate(con, prior_result=frozen)
    con.execute(
        "UPDATE sim_equity SET equity=equity+1 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="previously published"):
        review.evaluate(con, prior_result=prior)


def test_published_signal_inputs_cannot_be_rewritten(con):
    _setup(con)
    frozen = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    prior = review.evaluate(con, prior_result=frozen)
    con.execute("UPDATE universe_snapshot SET liquid=FALSE WHERE ticker='AAA'")
    with pytest.raises(
        ValueError, match="frozen XS (derived signal rows are missing|signal inputs changed)"
    ):
        review.evaluate(con, prior_result=prior)


def test_published_baseline_ledger_cannot_be_rewritten(con):
    _setup(con)
    frozen = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    prior = review.evaluate(con, prior_result=frozen)
    con.execute("UPDATE sim_fills SET fill_px=fill_px+1 WHERE order_id=1")
    with pytest.raises(ValueError, match="previously published"):
        review.evaluate(con, prior_result=prior)


def test_published_baseline_cash_cannot_be_rewritten(con):
    _setup(con)
    frozen = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    prior = review.evaluate(con, prior_result=frozen)
    con.execute(
        "UPDATE sim_equity SET cash=cash+1 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="previously published"):
        review.evaluate(con, prior_result=prior)


def test_runtime_contract_hash_covers_selection_dependency(tmp_path):
    for relative in review.RUNTIME_CONTRACT_FILES:
        source = review.REPO_ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    assert review._runtime_contract_sha256(tmp_path) == review.EXPECTED_RUNTIME_CONTRACT_SHA256
    target = tmp_path / "sim" / "strategies" / "xs_common.py"
    target.write_text(target.read_text() + "\n# mutation probe\n")
    assert review._runtime_contract_sha256(tmp_path) != review.EXPECTED_RUNTIME_CONTRACT_SHA256


def test_runtime_contract_migration_is_explicit(con):
    _setup(con)
    result = review.evaluate(con)
    frozen = result["frozen_runtime"]
    assert frozen["runtime_contract_version"] == review.RUNTIME_CONTRACT_VERSION
    assert frozen["superseded_runtime_contract_sha256"] == review.SUPERSEDED_RUNTIME_CONTRACT_SHA256
    assert "interruption-safe transaction cleanup" in (
        frozen["runtime_contract_migration"]
    )
    assert "engine/lib/resources.py" in frozen["runtime_contract_files"]


def _pre_signal_v17_checkpoint(con) -> dict:
    _setup(con)
    con.execute("DELETE FROM sim_orders")
    con.execute("DELETE FROM sim_equity")
    for portfolio_id in (review.CANDIDATE_ID, review.CONTROL_ID):
        con.execute(
            "INSERT INTO sim_equity VALUES (?, DATE '2026-09-29', 39000, 39000, 0)",
            [portfolio_id],
        )
    prior = review.evaluate(con)
    frozen = prior["frozen_runtime"]
    frozen["runtime_contract_version"] = review.PRIOR_RUNTIME_CONTRACT_VERSION
    frozen["runtime_contract_sha256"] = review.PRIOR_RUNTIME_CONTRACT_SHA256
    frozen["superseded_runtime_contract_sha256"] = review.PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256
    frozen["runtime_contract_migration"] = review.PRIOR_RUNTIME_CONTRACT_MIGRATION
    frozen["runtime_contract_files"] = list(review.PRIOR_RUNTIME_CONTRACT_FILES)
    return prior


def test_normal_run_refuses_silent_runtime_contract_migration(con):
    prior = _pre_signal_v17_checkpoint(con)

    with pytest.raises(ValueError, match="requires explicit migration"):
        review.evaluate(con, prior_result=prior)


def test_explicit_runtime_contract_migration_preserves_pre_signal_protocol(con):
    prior = _pre_signal_v17_checkpoint(con)

    migrated = review.migrate_runtime_contract(con, prior)

    assert migrated["status"] == "WAITING"
    assert migrated["candidate"] == prior["candidate"]
    assert migrated["control"] == prior["control"]
    assert migrated["criterion"] == prior["criterion"]
    assert migrated["observation"] == prior["observation"]
    assert migrated["frozen_runtime"]["signal_boundary"] is None
    assert (
        migrated["frozen_runtime"]["runtime_contract_version"]
        == review.RUNTIME_CONTRACT_VERSION
    )
    assert (
        migrated["frozen_runtime"]["superseded_runtime_contract_sha256"]
        == review.PRIOR_RUNTIME_CONTRACT_SHA256
    )


def test_runtime_contract_migration_refuses_existing_signal_boundary(con):
    prior = _pre_signal_v17_checkpoint(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (99, ?, 'AAA', 'buy', 1, ?, 'pending', NULL)",
        [review.CANDIDATE_ID, review.SIGNAL_DATE],
    )

    with pytest.raises(ValueError, match="only before its first signal"):
        review.migrate_runtime_contract(con, prior)


def test_invalid_result_is_safe():
    result = review._invalid_result(ValueError("private detail"))
    assert result["status"] == "INVALID"
    assert result["paper_only"] is True and result["automatic_action"] == "none"
    assert "private detail" not in result["error"]["message"]


def test_invalid_artifact_preserves_signal_boundary_for_recovery(con):
    _setup(con)
    frozen = _freeze(con)
    invalid = review._invalid_result(ValueError("transient"), frozen)
    assert invalid["last_valid_result"] == frozen
    _transition(con)
    assert review.evaluate(con, prior_result=invalid)["status"] == "ACCUMULATING"


def test_invalid_artifact_preserves_equity_continuity(con):
    _setup(con)
    frozen = _freeze(con)
    _transition(con)
    _append_month_ends(con, 2, candidate_step=1.02, control_step=1.01)
    prior = review.evaluate(con, prior_result=frozen)
    invalid = review._invalid_result(RuntimeError("transient"), prior)
    con.execute(
        "UPDATE sim_equity SET equity=equity+1 WHERE portfolio_id=? AND date=?",
        [review.CANDIDATE_ID, review.OBSERVATION_START],
    )
    with pytest.raises(ValueError, match="previously published"):
        review.evaluate(con, prior_result=invalid)
