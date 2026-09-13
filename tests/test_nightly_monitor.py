"""Tests for nightly evidence monitoring."""

from datetime import date

import pytest

from server import nightly_monitor
from tests.nightly_test_helpers import nightly_fixture


def test_nightly_evidence_reconciles_core_database_and_reports(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)

    result = nightly_monitor.evidence_status(meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)

    assert result == {
        "status": "current",
        "as_of": date(2026, 9, 4),
        "screened": 2,
        "passing": 1,
        "new_today": 1,
        "universe_policy": "all",
        "active_portfolios": 1,
        "portfolios_with_equity": 1,
    }


@pytest.mark.parametrize(
    ("mutation", "status", "reason"),
    [
        (lambda meta, driver, con, root: meta.update(screened=3), "invalid", "evidence-invalid"),
        (
            lambda meta, driver, con, root: meta.update(screen_date="20260904"),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta, driver, con, root: con.execute(
                "DELETE FROM sim_equity WHERE portfolio_id='paper'"
            ),
            "incomplete",
            "active-equity-missing",
        ),
    ],
)
def test_nightly_evidence_fails_closed(con, tmp_path, mutation, status, reason):
    meta, driver = nightly_fixture(con, tmp_path)
    mutation(meta, driver, con, tmp_path)

    result = nightly_monitor.evidence_status(meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)

    assert result["status"] == status
    assert result["reason"] == reason
    if reason == "evidence-invalid":
        assert "detail" not in result
