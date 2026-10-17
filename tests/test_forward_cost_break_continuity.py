"""Exercise the two book-forward families together across the registered cost break."""
from copy import deepcopy
from datetime import date

import pytest

from engine import forward_review as sector
from engine import xs_forward_review as xs
from tests.test_sector_forward_status import _setup_live_sector_forward
from tests.test_xs_forward_review import _deployed_v21_result, _freeze, _setup, _transition
from tools.migrate_cost_profiles import migrate


def test_both_forward_families_retain_prefix_across_repeated_cost_break_reviews(con):
    _setup_live_sector_forward(con)
    _setup(con)
    waiting = _freeze(con)
    _transition(con)
    priors = {sector: sector.evaluate(con), xs: xs.evaluate(con, prior_result=waiting)}
    predecessor = deepcopy(priors[sector])
    predecessor["frozen_runtime"].update(
        runtime_contract_version=sector.PRIOR_RUNTIME_CONTRACT_VERSION,
        runtime_contract_sha256=sector.PRIOR_RUNTIME_CONTRACT_SHA256,
        superseded_runtime_contract_sha256=sector.PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        runtime_contract_migration=sector.PRIOR_RUNTIME_CONTRACT_MIGRATION,
        runtime_contract_files=list(sector.PRIOR_RUNTIME_CONTRACT_FILES), fill_model="v4")
    for field in ("evaluation_clock_start", "cost_break_session", "pre_break_shared_sessions"):
        del predecessor["observation"][field]
    priors[sector] = sector.migrate_runtime_contract(con, predecessor)
    priors[xs] = xs.migrate_runtime_contract(con, _deployed_v21_result(priors[xs]))
    retained_hashes = {monitor: prior["observation"]["equity_sha256"]
                       for monitor, prior in priors.items()}
    retained_counts = {sector: 1, xs: 1}
    d0 = date(2026, 10, 19)
    assert migrate(con, d0)["routing_changes"] == []
    for day, expected_count in ((date(2026, 10, 1), 0), (d0, 1), (date(2026, 10, 20), 2)):
        if day >= d0:
            for monitor in priors:
                for book in (monitor.CANDIDATE_ID, monitor.CONTROL_ID):
                    equity, cash, count = con.execute(
                        "SELECT equity,cash,n_positions FROM sim_equity WHERE portfolio_id=? "
                        "ORDER BY date DESC LIMIT 1", [book]).fetchone()
                    con.execute("INSERT INTO sim_equity VALUES (?, ?, ?, ?, ?)",
                                [book, day, equity, cash, count])
        for monitor in priors:
            count_field = "shared_sessions_available" if monitor is sector else "shared_sessions"
            first = monitor.evaluate(con, prior_result=priors[monitor])
            second = monitor.evaluate(con, prior_result=first)
            assert second == first
            assert first["observation"][count_field] == expected_count
            assert first["observation"]["pre_break_shared_sessions"] == retained_counts[monitor]
            if expected_count == 0:
                assert first["observation"]["equity_sha256"] == retained_hashes[monitor]
            priors[monitor] = second
    for monitor, prior in priors.items():
        changed = deepcopy(prior)
        field = "shared_sessions_available" if monitor is sector else "shared_sessions"
        changed["observation"][field] -= 1
        changed["observation"]["pre_break_shared_sessions"] += 1
        with pytest.raises(ValueError, match="previously published"):
            monitor.evaluate(con, prior_result=changed)
        con.execute("UPDATE sim_equity SET equity=equity+1 WHERE portfolio_id=? AND date=?",
                    [monitor.CANDIDATE_ID, monitor.OBSERVATION_START])
        with pytest.raises(ValueError, match="baseline equity changed|previously published"):
            monitor.evaluate(con, prior_result=prior)
