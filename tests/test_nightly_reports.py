"""Tests for generated nightly screen and league report validation."""

import os
from datetime import date

import pytest

from server import nightly_monitor, nightly_reports
from sim import book_breaks, league
from tests.nightly_test_helpers import nightly_fixture


def _replace_with_unsafe_path(path, kind, tmp_path):
    path.unlink()
    if kind == "symlink":
        external = tmp_path / f"external-{path.name}"
        external.write_text("external")
        path.symlink_to(external)
    elif kind == "dangling-symlink":
        path.symlink_to(tmp_path / f"missing-{path.name}")
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)


@pytest.mark.parametrize(
    ("mutation", "status", "reason"),
    [
        (
            lambda meta, driver, con, root: (root / "screens" / "latest.md").write_text("bad"),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta, driver, con, root: (root / "reports" / "league.md").write_text(
                "# Paper League — 2026-09-03\n"
            ),
            "stale",
            "league-report-behind",
        ),
        (
            lambda meta, driver, con, root: (root / "reports" / "league.csv").write_text(
                "portfolio_id,date,equity\npaper,2026-09-04,99.0\n"
            ),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta, driver, con, root: (root / "reports" / "league.md").write_text(
                (root / "reports" / "league.md").read_text()
                + "| 2 | Retired | 2026-09-04 | $100 | +0.00% | · | "
                "+0.00% | 0 | 0 | · |\n"
            ),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta, driver, con, root: (root / "reports" / "league.md").write_text(
                (root / "reports" / "league.md").read_text()
                + "\n| Book | Ticker | Qty | Last traded | Sessions stale | Frozen value | "
                "% of equity |\n"
                "|---|---|---|---|---|---|---|\n"
                "| news_gated_momo | FBRX | 1.0000 | 2026-09-03 | 1 | $1.00 | · |\n"
            ),
            "invalid",
            "evidence-invalid",
        ),
    ],
)
def test_nightly_reports_fail_closed(con, tmp_path, mutation, status, reason):
    meta, driver = nightly_fixture(con, tmp_path)
    mutation(meta, driver, con, tmp_path)

    result = nightly_monitor.evidence_status(
        meta, driver, con, date(2026, 9, 4), data_dir=tmp_path
    )

    assert result["status"] == status
    assert result["reason"] == reason


def test_league_csv_validation_streams_every_batch_and_rejects_last_row(con, tmp_path):
    _meta, _driver = nightly_fixture(con, tmp_path)
    extra_rows = nightly_reports.EQUITY_SCAN_BATCH_SIZE + 5
    con.executemany(
        "INSERT INTO sim_equity VALUES ('paper', ?, ?, ?, 0)",
        [
            (date(2025, 1, 1).fromordinal(date(2025, 1, 1).toordinal() + offset), 100 + offset, 100)
            for offset in range(extra_rows)
        ],
    )
    rows = con.execute(
        "SELECT portfolio_id, date, equity FROM sim_equity ORDER BY portfolio_id, date"
    ).fetchall()
    csv_path = tmp_path / "reports" / "league.csv"
    csv_path.write_text(
        "portfolio_id,date,equity\n"
        + "".join(f"{portfolio_id},{equity_date},{equity}\n" for portfolio_id, equity_date, equity in rows)
    )

    nightly_reports._validate_league_csv(con, tmp_path)

    csv_path.write_text(csv_path.read_text().rsplit(",", 1)[0] + ",999\n")
    with pytest.raises(ValueError, match="league CSV does not match stored equity"):
        nightly_reports._validate_league_csv(con, tmp_path)


def test_p15_equity_update_requires_league_rerender(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)
    latest = date(2026, 9, 4)
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES ('p15_ai_ranked','P15 AI Ranked','p15','{}',?,TRUE,10000,10000,"
        "'baseline_v1')",
        [latest],
    )
    con.execute(
        "INSERT INTO sim_equity VALUES ('p15_ai_ranked',?,10000,10000,0)",
        [latest],
    )
    league.write_reports(con, latest, tmp_path)
    assert nightly_monitor.evidence_status(
        meta, driver, con, latest, data_dir=tmp_path
    )["status"] == "current"

    con.execute(
        "UPDATE sim_equity SET equity = 9948.30 "
        "WHERE portfolio_id = 'p15_ai_ranked' AND date = ?",
        [latest],
    )
    assert nightly_monitor.evidence_status(
        meta, driver, con, latest, data_dir=tmp_path
    ) == {"status": "invalid", "reason": "evidence-invalid"}

    assert league.step(
        con, latest, tmp_path, rerun=False, verbose=False, skip_if_done=True
    ) == 0
    assert nightly_monitor.evidence_status(
        meta, driver, con, latest, data_dir=tmp_path
    )["status"] == "current"
    rendered = {
        name: (tmp_path / "reports" / name).read_bytes()
        for name in ("league.md", "league.csv")
    }
    assert league.step(
        con, latest, tmp_path, rerun=False, verbose=False, skip_if_done=True
    ) == 0
    assert {
        name: (tmp_path / "reports" / name).read_bytes()
        for name in ("league.md", "league.csv")
    } == rendered


def test_private_portfolio_is_excluded_from_nightly_report_evidence(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)
    latest = date(2026, 9, 4)
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES ('private','Private','none','{}',?,TRUE,100,100,'baseline_v1')",
        [latest],
    )
    con.execute("INSERT INTO sim_equity VALUES ('private',?,100,100,0)", [latest])
    book_breaks.set_portfolio_account(con, "private", visibility="private")

    league.write_reports(con, latest, tmp_path)

    assert nightly_monitor.evidence_status(
        meta, driver, con, latest, data_dir=tmp_path
    )["status"] == "current"
    assert "private" not in (tmp_path / "reports" / "league.csv").read_text()


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("screens/latest.md", "symlink"),
        ("screens/2026-09-04.md", "dangling-symlink"),
        ("reports/league.md", "directory"),
        ("reports/league.csv", "fifo"),
    ],
)
def test_nightly_reports_reject_non_regular_artifacts_without_blocking(
    con, tmp_path, relative, kind
):
    meta, driver = nightly_fixture(con, tmp_path)
    _replace_with_unsafe_path(tmp_path / relative, kind, tmp_path)

    result = nightly_monitor.evidence_status(
        meta, driver, con, date(2026, 9, 4), data_dir=tmp_path
    )

    assert result["status"] == "invalid"
    assert result["reason"] == "evidence-invalid"
    assert "detail" not in result


def test_nightly_reports_reject_oversized_artifact(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)
    (tmp_path / "screens" / "latest.md").write_bytes(
        b"x" * (nightly_reports.MAX_REPORT_FILE_BYTES + 1)
    )

    result = nightly_monitor.evidence_status(
        meta, driver, con, date(2026, 9, 4), data_dir=tmp_path
    )

    assert result["status"] == "invalid"
    assert result["reason"] == "evidence-invalid"
    assert "detail" not in result
