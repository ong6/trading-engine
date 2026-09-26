from datetime import date, datetime, timedelta, timezone

import pytest

from engine import p16_screen_inputs as screens

DAY = date(2024, 7, 5)
NOW = datetime(2024, 7, 6, 2, tzinfo=timezone.utc)


def _screen(con):
    con.execute("CREATE TABLE screen_results (run_date DATE,ticker VARCHAR,rs_rank INTEGER)")
    con.execute("INSERT INTO screen_results VALUES (?,'AAA',95),(?,'BBB',80)", [DAY, DAY])
    screens.init_schema(con)


def test_unstamped_and_late_screen_cannot_enter_a_decision(con):
    _screen(con)
    assert screens.screen_as_known(con, DAY, information_cutoff_at=NOW)["status"] == "unavailable"
    snapshot = screens.record_computed_screen(con, DAY, computed_at=NOW)
    assert screens.screen_as_known(con, DAY, information_cutoff_at=NOW - timedelta(seconds=1))[
        "status"] == "unavailable"
    result = screens.screen_as_known(con, DAY, information_cutoff_at=NOW)
    assert result["rows"] == snapshot["rows"]
    assert result["screen_date_mismatch"] is False
    later = screens.screen_as_known(con, date(2024, 7, 8), information_cutoff_at=NOW + timedelta(days=3))
    assert later["screen_date_mismatch"] is True


def test_corrections_append_and_do_not_change_an_earlier_decision(con):
    _screen(con)
    first = screens.record_computed_screen(con, DAY, computed_at=NOW)
    con.execute("UPDATE screen_results SET rs_rank=5 WHERE ticker='AAA'")
    second = screens.record_computed_screen(con, DAY, computed_at=NOW + timedelta(hours=1))
    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    assert screens.screen_as_known(con, DAY, information_cutoff_at=NOW)["rows"] == first["rows"]
    assert con.execute("SELECT COUNT(*) FROM p16_screen_versions").fetchone() == (2,)
    con.execute("UPDATE screen_results SET rs_rank=95 WHERE ticker='AAA'")
    screens.record_computed_screen(con, DAY, computed_at=NOW + timedelta(hours=2))
    restored = screens.screen_as_known(con, DAY, information_cutoff_at=NOW + timedelta(hours=2))
    assert restored["rows"] == first["rows"]
    assert con.execute("SELECT COUNT(*) FROM p16_screen_versions").fetchone() == (3,)


def test_replay_preserves_first_compute_time_and_tampering_fails(con):
    _screen(con)
    first = screens.record_computed_screen(con, DAY, computed_at=NOW)
    replay = screens.record_computed_screen(con, DAY, computed_at=NOW + timedelta(hours=1))
    assert replay["replayed"] is True and replay["computed_at"] == first["computed_at"]
    with pytest.raises(ValueError, match="backdate"):
        screens.record_computed_screen(con, DAY, computed_at=NOW - timedelta(seconds=1))
    con.execute("UPDATE p16_screen_versions SET rows_payload='[]'")
    with pytest.raises(ValueError, match="differs"):
        screens.screen_as_known(con, DAY, information_cutoff_at=NOW)


def test_naive_compute_times_and_ambiguous_revisions_fail(con):
    _screen(con)
    with pytest.raises(ValueError, match="timezone"):
        screens.record_computed_screen(con, DAY, computed_at=NOW.replace(tzinfo=None))
    screens.record_computed_screen(con, DAY, computed_at=NOW)
    con.execute("UPDATE screen_results SET rs_rank=5 WHERE ticker='AAA'")
    with pytest.raises(ValueError, match="ambiguous"):
        screens.record_computed_screen(con, DAY, computed_at=NOW)
