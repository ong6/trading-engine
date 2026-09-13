"""Tests for generated nightly screen and league report validation."""

import os
from datetime import date

import pytest

from server import nightly_monitor, nightly_reports
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
