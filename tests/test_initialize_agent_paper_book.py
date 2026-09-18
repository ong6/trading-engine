"""Inactive agent paper-book initialization is backup-gated and atomic."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_paper_attribution, agent_policy
from sim.schema import init_sim_schema
from sim.strategies.configs import config_by_id
from tools import backup_database, initialize_agent_paper_book

START = date(2026, 9, 11)
PLANNED = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


def _database(path: Path, *, control_equity: bool = True) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE prices ("
        "ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, "
        "close DOUBLE, volume BIGINT, source VARCHAR, fetched_at TIMESTAMP)"
    )
    con.execute(
        "INSERT INTO prices VALUES "
        "('SPY', DATE '2026-09-11', 100, 101, 99, 100, 1000000, "
        "'yfinance', TIMESTAMP '2026-09-12 00:00:00')"
    )
    con.execute("CREATE TABLE jobs (id INTEGER, state VARCHAR)")
    con.execute("INSERT INTO jobs VALUES (1, 'done')")
    init_sim_schema(con)
    for portfolio_id in ("dual_momentum", "spy_benchmark"):
        config = config_by_id(portfolio_id)
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, "
            "execution_profile) VALUES (?, ?, ?, ?, DATE '2026-09-01', TRUE, "
            "39000, 39000, 'baseline_v1')",
            [
                config["id"],
                config["name"],
                config["strategy"],
                json.dumps(config),
            ],
        )
        if control_equity:
            con.execute(
                "INSERT INTO sim_equity VALUES (?, ?, 39000, 39000, 0)",
                [portfolio_id, START],
            )
    agent_paper_attribution.init_schema(con)
    con.close()


def _snapshot(path: Path) -> dict:
    con = duckdb.connect(str(path), read_only=True)
    try:
        name = con.execute("SELECT current_database()").fetchone()[0]
        return backup_database.database_snapshot(con, name)
    finally:
        con.close()


def _verified_backup(root: Path, database: Path) -> dict:
    snapshot = _snapshot(database)
    return {
        "status": "ok",
        "bundle": str(root.parent / "backup"),
        "manifest_sha256": "a" * 64,
        "database_sha256": "b" * 64,
        "database_size_bytes": database.stat().st_size,
        "database_snapshot_sha256": canonical_sha256(snapshot),
        "source_database": {
            "kind": "repository-relative",
            "path": database.relative_to(root).as_posix(),
        },
        "table_count": snapshot["table_count"],
        "evidence_file_count": 0,
        "operational_artifact_count": 0,
        "operational_control_count": 0,
    }


def _setup(
    tmp_path: Path,
    monkeypatch,
    *,
    control_equity: bool = True,
) -> tuple[Path, Path, dict]:
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    _database(database, control_equity=control_equity)
    verified = _verified_backup(root, database)
    monkeypatch.setattr(
        initialize_agent_paper_book.backup_database,
        "verify_backup",
        lambda _path: verified,
    )
    return root, database, verified


def _initialize(
    root: Path,
    database: Path,
    verified: dict,
    *,
    policy_id: str = "dual_momentum_agent_shadow_v1",
) -> dict:
    return initialize_agent_paper_book.initialize(
        database,
        root.parent / "backup",
        verified["manifest_sha256"],
        policy_id,
        START,
        repo_root=root,
        planned_at=PLANNED,
    )


@pytest.mark.parametrize(
    "policy_id",
    [
        "dual_momentum_agent_shadow_v1",
        "dual_momentum_hybrid_veto_shadow_v1",
    ],
)
def test_initializes_only_one_inactive_isolated_book(
    tmp_path, monkeypatch, policy_id
):
    root, database, verified = _setup(tmp_path, monkeypatch)
    before = _snapshot(database)

    result = _initialize(
        root,
        database,
        verified,
        policy_id=policy_id,
    )

    policy = agent_policy.get(policy_id)
    after = _snapshot(database)
    assert result["status"] == "inactive_agent_paper_book_initialized"
    assert result["policy_id"] == policy_id
    assert result["portfolio_id"] == policy["reserved_portfolio_id"]
    assert result["portfolio_active"] is False
    assert result["inserted_tables"] == [
        "portfolios",
        "agent_paper_book_attribution",
        "sim_equity",
    ]
    assert result["inserted_record_count"] == 3
    assert result["order_count"] == 0
    assert result["fill_count"] == 0
    assert result["position_count"] == 0
    assert result["scheduler_integration_implemented"] is False
    assert result["order_route_implemented"] is False
    assert result["initialization_performed"] is True
    assert result["execution_authority"] == "none"
    assert after["active_portfolio_count"] == before["active_portfolio_count"]
    assert after["active_portfolios_sha256"] == before["active_portfolios_sha256"]
    assert after["job_states"] == before["job_states"]
    assert after["latest_price_date"] == before["latest_price_date"]
    assert after["row_counts"] == {
        **before["row_counts"],
        "main.agent_paper_book_attribution": 1,
        "main.portfolios": before["row_counts"]["main.portfolios"] + 1,
        "main.sim_equity": before["row_counts"]["main.sim_equity"] + 1,
    }

    con = duckdb.connect(str(database), read_only=True)
    try:
        portfolio = con.execute(
            "SELECT active, cash, initial_cash FROM portfolios WHERE id = ?",
            [policy["reserved_portfolio_id"]],
        ).fetchone()
        attribution = agent_paper_attribution.assess_policy(
            con,
            policy,
            decision_records=[],
        )
    finally:
        con.close()
    assert portfolio == (False, 39_000.0, 39_000.0)
    assert attribution["status"] == "available"
    assert attribution["equity_observation_count"] == 1
    assert attribution["order_count"] == 0
    assert attribution["execution_authority"] == "none"


def test_rejects_stale_backup_before_inserting(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    stale = dict(verified)
    stale["database_snapshot_sha256"] = "c" * 64
    monkeypatch.setattr(
        initialize_agent_paper_book.backup_database,
        "verify_backup",
        lambda _path: stale,
    )
    before = _snapshot(database)

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match="does not match",
    ):
        _initialize(root, database, verified)

    assert _snapshot(database) == before


@pytest.mark.parametrize(
    ("field", "value", "expected_manifest", "message"),
    [
        (
            "manifest_sha256",
            "b" * 64,
            "b" * 64,
            "manifest identity",
        ),
        (
            "source_database",
            {"kind": "repository-relative", "path": "store/other.duckdb"},
            "a" * 64,
            "different source database",
        ),
    ],
)
def test_rejects_wrong_backup_identity(
    tmp_path,
    monkeypatch,
    field,
    value,
    expected_manifest,
    message,
):
    root, database, verified = _setup(tmp_path, monkeypatch)
    supplied = dict(verified)
    if field != "manifest_sha256":
        supplied[field] = value
        monkeypatch.setattr(
            initialize_agent_paper_book.backup_database,
            "verify_backup",
            lambda _path: supplied,
        )
    before = _snapshot(database)

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match=message,
    ):
        initialize_agent_paper_book.initialize(
            database,
            root.parent / "backup",
            expected_manifest,
            "dual_momentum_agent_shadow_v1",
            START,
            repo_root=root,
            planned_at=PLANNED,
        )

    assert _snapshot(database) == before


def test_blocked_preflight_inserts_nothing(tmp_path, monkeypatch):
    root, database, verified = _setup(
        tmp_path,
        monkeypatch,
        control_equity=False,
    )
    before = _snapshot(database)

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match="control_equity_anchor",
    ):
        _initialize(root, database, verified)

    assert _snapshot(database) == before


def test_repeated_initialization_fails_closed_without_changes(
    tmp_path, monkeypatch
):
    root, database, verified = _setup(tmp_path, monkeypatch)
    _initialize(root, database, verified)
    current = _snapshot(database)
    current_backup = _verified_backup(root, database)
    monkeypatch.setattr(
        initialize_agent_paper_book.backup_database,
        "verify_backup",
        lambda _path: current_backup,
    )

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match="reserved_identity_absent",
    ):
        _initialize(root, database, current_backup)

    assert _snapshot(database) == current


def test_post_insert_scope_failure_rolls_back(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    before = _snapshot(database)
    monkeypatch.setattr(
        initialize_agent_paper_book,
        "_require_scoped_change",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            initialize_agent_paper_book.PaperBookInitializationError(
                "forced scope failure"
            )
        ),
    )

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match="forced scope failure",
    ):
        _initialize(root, database, verified)

    assert _snapshot(database) == before
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM portfolios WHERE id = ?",
            [policy["reserved_portfolio_id"]],
        ).fetchone() == (0,)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_paper_book_attribution WHERE policy_id = ?",
            [policy["id"]],
        ).fetchone() == (0,)
    finally:
        con.close()


def test_policy_change_before_commit_rolls_back(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    before = _snapshot(database)
    monkeypatch.setattr(
        initialize_agent_paper_book,
        "_require_policy_stable",
        lambda *_args: (_ for _ in ()).throw(
            initialize_agent_paper_book.PaperBookInitializationError(
                "agent policy registration changed during initialization"
            )
        ),
    )

    with pytest.raises(
        initialize_agent_paper_book.PaperBookInitializationError,
        match="registration changed",
    ):
        _initialize(root, database, verified)

    assert _snapshot(database) == before
