"""W4 isolated-store and logical-clock tests."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from farm.replay.clock import record_phase_checkpoint
from farm.replay.store import (
    ReplayStoreError,
    append_exact,
    checked_store_path,
    load_record,
    open_store,
)

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)


def _paths(tmp_path):
    root = tmp_path / "research"
    live = tmp_path / "live.duckdb"
    root.mkdir()
    live.touch()
    return root, live, root / "control" / "shared.duckdb"


def test_store_requires_explicit_external_non_live_path(tmp_path):
    root, live, target = _paths(tmp_path)
    assert checked_store_path(target, research_root=root, live_db_path=live) == target
    with pytest.raises(ReplayStoreError, match="absolute"):
        checked_store_path(Path(target.name), research_root=root, live_db_path=live)
    with pytest.raises(ReplayStoreError, match="outside_research_root"):
        checked_store_path(tmp_path / "other.duckdb", research_root=root, live_db_path=live)
    with pytest.raises(ReplayStoreError, match="inside_checkout"):
        checked_store_path(
            research_root=Path.cwd(),
            path=Path.cwd() / "w4.duckdb",
            live_db_path=live,
        )


def test_store_rejects_symlink_and_live_database_inode(tmp_path):
    root, live, _target = _paths(tmp_path)
    link = root / "linked.duckdb"
    link.symlink_to(live)
    with pytest.raises(ReplayStoreError):
        checked_store_path(link, research_root=root, live_db_path=live)
    hardlink = root / "hardlink.duckdb"
    os.link(live, hardlink)
    with pytest.raises(ReplayStoreError, match="inode"):
        checked_store_path(hardlink, research_root=root, live_db_path=live)


def test_append_is_exact_or_conflict_and_connection_is_released(tmp_path):
    root, live, target = _paths(tmp_path)
    with open_store(target, research_root=root, live_db_path=live, kind="control") as con:
        first = append_exact(
            con,
            record_type="registration",
            record_key="trial-1",
            payload={"status": "registered"},
            recorded_at=NOW,
        )
        assert append_exact(
            con,
            record_type="registration",
            record_key="trial-1",
            payload={"status": "registered"},
            recorded_at=NOW,
        ) == first
        with pytest.raises(ReplayStoreError, match="immutable_record_conflict"):
            append_exact(
                con,
                record_type="registration",
                record_key="trial-1",
                payload={"status": "retired"},
                recorded_at=NOW,
            )
    moved = target.with_name("moved.duckdb")
    target.rename(moved)
    assert moved.is_file()


def test_store_kind_is_bound_to_the_file(tmp_path):
    root, live, target = _paths(tmp_path)
    with open_store(target, research_root=root, live_db_path=live, kind="catalog"):
        pass
    with pytest.raises(ReplayStoreError, match="store_kind_conflict"):
        with open_store(target, research_root=root, live_db_path=live, kind="replay"):
            pass


def test_clock_advances_only_after_terminal_coverage_and_in_order(tmp_path):
    root, live, target = _paths(tmp_path)
    session = date(2024, 1, 2)
    with open_store(target, research_root=root, live_db_path=live, kind="replay") as con:
        with pytest.raises(ReplayStoreError, match="coverage_incomplete"):
            record_phase_checkpoint(
                con,
                cohort_id="cohort",
                policy_id="policy",
                session=session,
                phase="PREOPEN",
                logical_at=NOW,
                terminal_rows=[{"status": "completed"}],
                expected_rows=2,
                recorded_at=NOW,
            )
        with pytest.raises(ReplayStoreError, match="row_not_terminal"):
            record_phase_checkpoint(
                con,
                cohort_id="cohort",
                policy_id="policy",
                session=session,
                phase="PREOPEN",
                logical_at=NOW,
                terminal_rows=[{"status": "running"}],
                expected_rows=1,
                recorded_at=NOW,
            )
        with pytest.raises(ReplayStoreError, match="previous_phase_missing"):
            record_phase_checkpoint(
                con,
                cohort_id="cohort",
                policy_id="policy",
                session=session,
                phase="OPEN",
                logical_at=NOW,
                terminal_rows=[],
                expected_rows=0,
                recorded_at=NOW,
            )
        first = record_phase_checkpoint(
            con,
            cohort_id="cohort",
            policy_id="policy",
            session=session,
            phase="PREOPEN",
            logical_at=NOW,
            terminal_rows=[{"status": "unavailable"}],
            expected_rows=1,
            recorded_at=NOW,
        )
        assert first == record_phase_checkpoint(
            con,
            cohort_id="cohort",
            policy_id="policy",
            session=session,
            phase="PREOPEN",
            logical_at=NOW,
            terminal_rows=[{"status": "unavailable"}],
            expected_rows=1,
            recorded_at=NOW,
        )
        second = record_phase_checkpoint(
            con,
            cohort_id="cohort",
            policy_id="policy",
            session=session,
            phase="OPEN",
            logical_at=NOW + timedelta(hours=1),
            terminal_rows=[{"status": "failed"}],
            expected_rows=1,
            recorded_at=NOW + timedelta(hours=1),
        )
        assert load_record(con, f"clock:cohort:policy:{session}", "OPEN")[
            "payload"
        ]["previous_checkpoint_sha256"] == first
        assert second
        with pytest.raises(ReplayStoreError, match="not_monotone"):
            record_phase_checkpoint(
                con,
                cohort_id="cohort",
                policy_id="policy",
                session=session,
                phase="CLOSE",
                logical_at=NOW,
                terminal_rows=[],
                expected_rows=0,
                recorded_at=NOW + timedelta(hours=2),
            )
