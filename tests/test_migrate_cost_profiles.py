"""One-shot D0 cost-profile migration contracts."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from sim import book_breaks
from sim.schema import portfolio_account, set_portfolio_account
from tools import migrate_cost_profiles

D0 = date(2026, 10, 12)


def _portfolio(con, portfolio_id: str):
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES (?,?, 'none','{}',?,TRUE,10000,10000,'baseline_v1')",
        [portfolio_id, portfolio_id, date(2026, 1, 2)],
    )


def test_migration_routes_books_records_breaks_bootstraps_ids_and_runs_l4_backfill(
    con, monkeypatch,
):
    for portfolio_id in (
        "league-book", "p15_ai_ranked", "p16_construct_ai@sha256:abc", "acct-a"
    ):
        _portfolio(con, portfolio_id)
    con.execute("CREATE TABLE paper_account_specs (account_id VARCHAR)")
    con.execute("INSERT INTO paper_account_specs VALUES ('acct-a')")
    set_portfolio_account(
        con,
        "acct-a",
        account_type="margin",
        visibility="private",
        price_source="massive_daily",
        allow_short=True,
    )
    con.execute(
        "INSERT INTO sim_orders VALUES (50,'league-book','XYZ','buy',1,?,"
        "'pending',NULL)",
        [date(2026, 10, 9)],
    )
    calls = []
    monkeypatch.setattr(
        migrate_cost_profiles.db,
        "backfill_first_fetched_at",
        lambda connection: calls.append(connection) or 123,
        raising=False,
    )

    result = migrate_cost_profiles.migrate(
        con, D0, migrated_at=datetime(2026, 10, 11, 19, tzinfo=timezone.utc)
    )

    assert result == {
        "status": "migrated",
        "d0": D0.isoformat(),
        "portfolio_count": 4,
        "break_count": 4,
        "reserved_order_id": 51,
        "first_fetched_at_backfill": 123,
    }
    assert calls == [con]
    accounts = {
        portfolio_id: portfolio_account(con, portfolio_id)
        for portfolio_id in (
            "league-book", "p15_ai_ranked", "p16_construct_ai@sha256:abc", "acct-a"
        )
    }
    assert accounts["league-book"]["engine"] == "league"
    assert accounts["p15_ai_ranked"]["engine"] == "p15"
    assert accounts["p16_construct_ai@sha256:abc"]["engine"] == "p16"
    account_fields = {
        key: accounts["acct-a"][key] for key in (
            "engine", "account_type", "visibility", "price_source", "allow_short"
        )
    }
    assert account_fields == {
        "engine": "account",
        "account_type": "margin",
        "visibility": "private",
        "price_source": "massive_daily",
        "allow_short": True,
    }
    assert {
        account["cost_profile"] for account in accounts.values()
    } == {"ibkr_pro_tiered_v1"}
    assert con.execute(
        "SELECT COUNT(*),MIN(break_date),MAX(registration_revision) "
        "FROM sim_book_breaks"
    ).fetchone() == (4, D0, 13)
    assert con.execute(
        "SELECT last_value FROM duckdb_sequences() "
        "WHERE sequence_name='sim_order_id_seq'"
    ).fetchone()[0] > 50
    assert book_breaks.effective_cost_profile(
        con, "league-book", date(2026, 10, 9)
    ) == "baseline_v1"
    assert book_breaks.effective_cost_profile(
        con, "league-book", D0
    ) == "ibkr_pro_tiered_v1"

    with pytest.raises(
        migrate_cost_profiles.MigrationRefused, match="already run"
    ):
        migrate_cost_profiles.migrate(con, D0)


def test_migration_refuses_equity_at_or_after_d0_without_partial_writes(con):
    _portfolio(con, "league-book")
    con.execute(
        "INSERT INTO sim_equity VALUES ('league-book',?,10000,10000,0)", [D0]
    )

    with pytest.raises(
        migrate_cost_profiles.MigrationRefused, match="D0-or-later"
    ):
        migrate_cost_profiles.migrate(con, D0)

    assert con.execute("SELECT COUNT(*) FROM sim_book_breaks").fetchone() == (0,)
    assert portfolio_account(
        con, "league-book"
    )["cost_profile"] == "baseline_v1"


def test_cli_requires_explicit_apply():
    with pytest.raises(SystemExit) as exc:
        migrate_cost_profiles.main(["--d0", D0.isoformat()])
    assert exc.value.code == 2
