"""Real API, nightly driver, and late-settle CLI account lifecycle proof."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from engine import free_sources
from engine.accounts import api as account_api
from engine.accounts import cli as account_cli
from engine.lib import db as engine_db
from server import accounts_routes
from server import db as server_db
from sim import league, ledger
from sim.schema import init_sim_schema, set_portfolio_account

PRIOR = date(2026, 10, 6)
DAY = date(2026, 10, 7)
RECEIVED = datetime(2026, 10, 7, 13, 27, tzinfo=timezone.utc)


def _main_store(path):
    con = duckdb.connect(str(path))
    engine_db.init_schema(con)
    engine_db.init_actions_schema(con)
    init_sim_schema(con)
    con.execute(
        "INSERT INTO prices "
        "(ticker,date,open,high,low,close,volume,source,fetched_at,first_fetched_at) "
        "VALUES ('SPY',?,100,100,100,100,1000000,'fixture',?,?)",
        [DAY, RECEIVED, RECEIVED],
    )
    con.execute(
        "INSERT INTO universe "
        "(ticker,yf_ticker,name,exchange,etf,member,added,active,liquid,backfill_done) "
        "VALUES ('LONG','LONG','Long','NYSE',FALSE,'fixture',?,TRUE,TRUE,TRUE),"
        "('SHORT','SHORT','Short','NYSE',FALSE,'fixture',?,TRUE,TRUE,TRUE),"
        "('RETIRE','RETIRE','Retire','NYSE',FALSE,'fixture',?,TRUE,TRUE,TRUE)",
        [PRIOR, PRIOR, PRIOR],
    )
    con.close()


def _daily_store(path):
    con = duckdb.connect(str(path))
    free_sources.init_schema(con)
    history = [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2),
               date(2026, 10, 5), PRIOR]
    rows = []
    for ticker in ("LONG", "SHORT", "RETIRE"):
        rows.extend(
            (session, ticker, 100, 100, 100, 100, 100_000, 100,
             "fixture", RECEIVED, f"{index:064x}")
            for index, session in enumerate(history, 1)
        )
    rows.append(
        (DAY, "LONG", 100, 102, 99, 101, 100_000, 100.5,
         "fixture", datetime(2026, 10, 7, 21), "f" * 64)
    )
    rows.append(
        (DAY, "RETIRE", 100, 102, 99, 101, 100_000, 100.5,
         "fixture", datetime(2026, 10, 7, 21), "a" * 64)
    )
    con.executemany("INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()


def _minute_store(path):
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE massive_minute_bars "
        "(ticker VARCHAR,ts_utc TIMESTAMP,o DOUBLE,h DOUBLE,l DOUBLE,c DOUBLE,v DOUBLE,"
        "vw DOUBLE,n BIGINT,session VARCHAR,source_sha256 VARCHAR,fetched_at TIMESTAMP)"
    )
    con.close()


def _short_store(path):
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    con.execute(
        "CREATE TABLE finra_short_interest "
        "(ticker VARCHAR,settlement_date DATE,days_to_cover DOUBLE,publication_date DATE)"
    )
    con.execute(
        "INSERT INTO finra_short_interest VALUES ('SHORT',?,1,?)", [PRIOR, PRIOR]
    )
    con.close()


def _spec(account_id="acct-a"):
    return {
        "schema_version": 2, "strategy_ref": "strategy-a", "strategy_version": "v1",
        "spec_sha256": "a" * 64, "artifact_sha256": "b" * 64,
        "registration_sha256": "c" * 64, "instrument_kinds": ["stock"],
        "capital_usd": 50_000, "account_id": account_id, "account_type": "margin",
        "max_position_fraction": 0.5, "max_gross_fraction": 1.0,
        "min_trade_usd": 1.0, "allow_short": True, "price_source": "massive_daily",
        "benchmark": "SPY", "day_trades_per_week_expected": 3,
        "day_trade_rule": "pdt_25k_legacy",
    }


def _intent(intent_id, ticker, side, order_type, *, contingent_on=None):
    return {
        "schema_version": 2, "intent_id": intent_id, "account_id": "acct-a",
        "spec_sha256": "a" * 64, "registration_sha256": "c" * 64,
        "instrument_id": ticker, "instrument_kind": "stock", "side": side,
        "quantity": 5.0, "order_type": order_type, "limit_price": None,
        "time_in_force": "day", "session_date": DAY.isoformat(),
        "contingent_on": contingent_on, "legs": [], "created_at": RECEIVED.isoformat(),
        "source_sha256": "d" * 64,
    }


def test_real_api_nightly_driver_and_late_cli_share_one_processor(
    tmp_path, monkeypatch, capsys,
):
    market = tmp_path / "market.duckdb"
    daily = tmp_path / "daily.duckdb"
    minute = tmp_path / "minute.duckdb"
    short = tmp_path / "short.duckdb"
    _main_store(market)
    _daily_store(daily)
    _minute_store(minute)
    _short_store(short)
    monkeypatch.setenv("TRADING_ENGINE_FREE_SOURCES_DB", str(daily))
    monkeypatch.setenv("TRADING_ENGINE_MASSIVE_MINUTE_DB", str(minute))
    monkeypatch.setenv("TRADING_ENGINE_SHORT_DATA_DB", str(short))
    monkeypatch.setattr(engine_db.settings, "DEFAULT_DB", market)
    monkeypatch.setattr(server_db, "DEFAULT_DB", market)
    token_file = tmp_path / "token"
    account_api.generate_token(path=token_file)
    monkeypatch.setenv(account_api.TOKEN_ENV, str(token_file))

    class Clock:
        current = RECEIVED

        @classmethod
        def now(cls, _tz):
            return cls.current

    monkeypatch.setattr(accounts_routes, "datetime", Clock)
    authorization = f"Bearer {account_api.read_token(path=token_file)}"
    assert accounts_routes.create_account(_spec(), authorization)["account_id"] == "acct-a"
    requests = [
        _intent("long-open", "LONG", "buy", "moo"),
        _intent("long-close", "LONG", "sell", "moc", contingent_on="long-open"),
        _intent("short-open", "SHORT", "short", "moo"),
        _intent("short-close", "SHORT", "cover", "moc", contingent_on="short-open"),
    ]
    assert all(
        accounts_routes.submit_order("acct-a", item, authorization)["state"] == "queued"
        for item in requests
    )
    assert accounts_routes.create_account(
        _spec("acct-retire"), authorization,
    )["account_id"] == "acct-retire"
    con = duckdb.connect(str(market))
    ledger.apply_fill(con, {
        "order_id": 100, "portfolio_id": "acct-retire", "ticker": "RETIRE",
        "side": "buy", "qty": 2, "fill_px": 100, "fill_date": PRIOR,
    })
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(100,'acct-retire','RETIRE','buy',2,?,100,100,0,0)", [PRIOR]
    )
    con.execute(
        "INSERT INTO sim_fill_details (order_id,fill_ts,fill_kind,price_source,multiplier) "
        "VALUES (100,'2026-10-06 13:30:00','open_auction','massive_daily',1)"
    )
    con.execute("UPDATE portfolios SET active=TRUE WHERE id='acct-retire'")
    set_portfolio_account(con, "acct-retire", status="active", updated_at=RECEIVED)
    con.close()
    Clock.current = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
    assert accounts_routes.retire_account("acct-retire", authorization)["status"] == (
        "retiring"
    )
    Clock.current = RECEIVED

    assert league.run(str(market), tmp_path / "reports", DAY.isoformat(), False, False) == 0
    con = duckdb.connect(str(market), read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id='acct-a'"
        ).fetchone() == (2,)
        assert con.execute(
            "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id='acct-a' AND status='pending'"
        ).fetchone() == (2,)
        assert con.execute(
            "SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-retire'"
        ).fetchone() == ("retired",)
    finally:
        con.close()
    con = duckdb.connect(str(daily))
    con.execute(
        "INSERT INTO free_daily_bars VALUES "
        "(?,'SHORT',100,101,98,99,100000,99.5,'fixture',?,'e')",
        [DAY, datetime(2026, 10, 8, 7)],
    )
    con.close()
    assert account_cli.main(["settle", "--late", "--date", DAY.isoformat()]) == 0
    capsys.readouterr()

    con = duckdb.connect(str(market), read_only=True)
    try:
        assert con.execute(
            "SELECT side,COUNT(*) FROM sim_fills WHERE portfolio_id='acct-a' "
            "GROUP BY side ORDER BY side"
        ).fetchall() == [("buy", 1), ("cover", 1), ("sell", 1), ("short", 1)]
        assert con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id='acct-a' ORDER BY ticker"
        ).fetchall() == [("LONG", 0.0), ("SHORT", 0.0)]
        assert con.execute(
            "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id='acct-a' AND date=?", [DAY]
        ).fetchone() == (1,)
        assert con.execute(
            "SELECT status FROM account_reconciliations WHERE portfolio_id='acct-a'"
        ).fetchall() == []
        before_rerun = {
            "fills": con.execute(
                "SELECT * FROM sim_fills WHERE portfolio_id='acct-a' ORDER BY order_id"
            ).fetchall(),
            "equity": con.execute(
                "SELECT * FROM sim_equity WHERE portfolio_id='acct-a' ORDER BY date"
            ).fetchall(),
            "state": con.execute(
                "SELECT * FROM account_state WHERE portfolio_id='acct-a'"
            ).fetchone(),
        }
    finally:
        con.close()

    assert league.run(
        str(market), tmp_path / "rerun-reports", DAY.isoformat(), False, True,
    ) == 0
    con = duckdb.connect(str(market), read_only=True)
    try:
        assert con.execute(
            "SELECT * FROM sim_fills WHERE portfolio_id='acct-a' ORDER BY order_id"
        ).fetchall() == before_rerun["fills"]
        assert con.execute(
            "SELECT * FROM sim_equity WHERE portfolio_id='acct-a' ORDER BY date"
        ).fetchall() == before_rerun["equity"]
        assert con.execute(
            "SELECT * FROM account_state WHERE portfolio_id='acct-a'"
        ).fetchone() == before_rerun["state"]
    finally:
        con.close()


def test_verify_cli_persists_mismatch_and_halts(tmp_path, monkeypatch, capsys):
    market = tmp_path / "market.duckdb"
    _main_store(market)
    monkeypatch.setattr(engine_db.settings, "DEFAULT_DB", market)
    con = duckdb.connect(str(market))
    from engine.accounts import service

    service.create(con, _spec(), now=RECEIVED)
    con.execute("UPDATE portfolios SET cash=49999,active=TRUE WHERE id='acct-a'")
    set_portfolio_account(con, "acct-a", status="active", updated_at=RECEIVED)
    con.close()

    assert account_cli.main(["verify", "acct-a"]) != 0
    capsys.readouterr()
    con = duckdb.connect(str(market), read_only=True)
    try:
        assert con.execute(
            "SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'"
        ).fetchone() == ("halted",)
        assert con.execute(
            "SELECT status FROM account_reconciliations WHERE portfolio_id='acct-a'"
        ).fetchone() == ("mismatch",)
    finally:
        con.close()

