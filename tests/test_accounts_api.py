"""Loopback account API authentication and receipt timing tests."""
import asyncio
import json
import stat
from contextlib import contextmanager
from datetime import date, datetime, timezone

import duckdb
import pytest
from fastapi import HTTPException

from engine.accounts import api, service
from engine.accounts import cli as accounts_cli
from engine.paper_accounts import AccountRefused
from server import accounts_routes, main
from sim import schema as sim_schema
from tests.conftest import insert_bars

NOW = datetime(2026, 10, 5, 13, 27, tzinfo=timezone.utc)


def _spec(account_id="acct-private"):
    return {
        "schema_version": 2, "strategy_ref": "strategy-a", "strategy_version": "v1",
        "spec_sha256": "a" * 64, "artifact_sha256": "b" * 64,
        "registration_sha256": "c" * 64, "instrument_kinds": ["stock"],
        "capital_usd": 10_000, "account_id": account_id, "account_type": "margin",
        "max_position_fraction": 1.0, "max_gross_fraction": 1.0, "min_trade_usd": 1.0,
        "allow_short": False, "price_source": "prices", "benchmark": "SPY",
        "day_trades_per_week_expected": 3, "day_trade_rule": "pdt_25k_legacy",
    }


def _intent(account_id="acct-private", *, intent_id="moo-parent", side="buy", quantity=5,
            order_type="moo", contingent_on=None, instrument_id="SAME"):
    return {
        "schema_version": 2, "intent_id": intent_id, "account_id": account_id,
        "spec_sha256": "a" * 64, "registration_sha256": "c" * 64,
        "instrument_id": instrument_id, "instrument_kind": "stock", "side": side,
        "quantity": quantity, "order_type": order_type, "limit_price": None,
        "time_in_force": "day", "session_date": "2026-10-05",
        "contingent_on": contingent_on, "legs": [], "created_at": NOW.isoformat(),
        "source_sha256": "d" * 64,
    }


@contextmanager
def _borrowed(con):
    yield con


def _api_account(con, monkeypatch, account_id="acct-private"):
    class Clock:
        @classmethod
        def now(cls, _tz):
            return NOW

    insert_bars(con, "SAME", [date(2026, 10, 2)], open_=100, close=100)
    service.create(con, _spec(account_id), now=NOW)
    monkeypatch.setattr(accounts_routes, "datetime", Clock)
    monkeypatch.setattr(accounts_routes, "_write_connection", lambda: _borrowed(con))
    monkeypatch.setattr(
        accounts_routes, "_require_account_mutation",
        lambda _account_id, _authorization: None,
    )
    monkeypatch.setattr(
        accounts_routes, "_require_account_access",
        lambda _con, _account_id, _authorization: None,
    )
    monkeypatch.setattr(accounts_routes, "_connection", lambda _factory: _borrowed(con))


def test_token_generation_is_private_and_authentication_is_constant_time(tmp_path):
    path = tmp_path / "config" / "accounts-api.token"
    assert api.generate_token(path=path) == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    token = api.read_token(path=path)
    assert len(token) >= 32
    assert api.authenticated(f"Bearer {token}", path=path)
    assert not api.authenticated("Bearer wrong", path=path)
    with pytest.raises(FileExistsError):
        api.generate_token(path=path)


def test_account_list_hides_private_without_token(con, monkeypatch, tmp_path):
    service.create(con, _spec(), now=NOW)
    service.create(con, _spec("acct-public"), now=NOW)
    sim_schema.set_portfolio_account(con, "acct-public", visibility="public", updated_at=NOW)
    token_path = tmp_path / "token"
    api.generate_token(path=token_path)
    token = api.read_token(path=token_path)
    monkeypatch.setenv(api.TOKEN_ENV, str(token_path))
    monkeypatch.setattr(accounts_routes, "_connection", lambda _factory: _borrowed(con))

    assert [row["id"] for row in accounts_routes.list_accounts()] == ["acct-public"]
    assert [row["id"] for row in accounts_routes.list_accounts(f"Bearer {token}")] == [
        "acct-private", "acct-public",
    ]
    with pytest.raises(HTTPException) as exc_info:
        accounts_routes.get_account("acct-private")
    assert exc_info.value.status_code == 404
    assert accounts_routes.get_account("acct-private", f"Bearer {token}")["id"] == (
        "acct-private"
    )


def test_order_route_stamps_received_at_before_opening_writer(con, monkeypatch):
    events = []

    class Clock:
        @classmethod
        def now(cls, tz):
            events.append("stamp")
            return NOW

    @contextmanager
    def connection(_factory):
        events.append("lock")
        yield con

    def submit(_con, _body, *, received_at):
        events.append("submit")
        return {"received_at": received_at.isoformat()}

    monkeypatch.setattr(accounts_routes, "datetime", Clock)
    monkeypatch.setattr(accounts_routes, "_write_connection", lambda: connection(None))
    monkeypatch.setattr(
        accounts_routes, "_require_account_mutation",
        lambda _account_id, _authorization: None,
    )
    monkeypatch.setattr(accounts_routes.service, "submit", submit)
    result = accounts_routes.submit_order("acct-a", {"account_id": "acct-a"}, "Bearer x")
    assert events == ["stamp", "lock", "submit"]
    assert result["received_at"] == NOW.isoformat()


def test_gross_cap_refusal_maps_through_api_and_cli(con, monkeypatch, capsys):
    error = AccountRefused("gross_cap")
    with pytest.raises(HTTPException) as exc_info:
        accounts_routes._invoke(lambda: (_ for _ in ()).throw(error))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "gross_cap"

    monkeypatch.setattr(accounts_cli.db, "connect", lambda **_kwargs: _borrowed(con))
    monkeypatch.setattr(
        accounts_cli, "_execute", lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    assert accounts_cli.main(["submit", "unused.json"]) == 2
    assert json.loads(capsys.readouterr().out)["refusal_reason"] == "gross_cap"
    assert accounts_cli.main(["list"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "gross_cap"}


def test_transaction_conflict_maps_to_retryable_503():
    with pytest.raises(HTTPException) as exc_info:
        accounts_routes._invoke(
            lambda: (_ for _ in ()).throw(duckdb.TransactionException("conflict"))
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "1"}


def test_writer_open_transaction_conflict_is_retryable(monkeypatch):
    monkeypatch.setattr(
        accounts_routes, "_write_con",
        lambda: (_ for _ in ()).throw(duckdb.TransactionException("conflict")),
    )
    with pytest.raises(HTTPException) as exc_info:
        with accounts_routes._write_connection():
            pass
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "1"}


def test_private_and_unknown_accounts_are_indistinguishable(con, monkeypatch):
    service.create(con, _spec(), now=NOW)
    monkeypatch.setattr(accounts_routes, "_connection", lambda _factory: _borrowed(con))
    errors = []
    for account_id in ("acct-private", "missing"):
        with pytest.raises(HTTPException) as exc_info:
            accounts_routes.get_account(account_id)
        errors.append((exc_info.value.status_code, exc_info.value.detail))
    assert errors == [(404, "unknown account"), (404, "unknown account")]
    with pytest.raises(HTTPException) as exc_info:
        accounts_routes.halt_account("acct-private")
    assert (exc_info.value.status_code, exc_info.value.detail) == (404, "unknown account")


def test_account_routes_reject_non_loopback_host_before_database_access(monkeypatch):
    monkeypatch.setattr(
        accounts_routes.server_db,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("database should not open")),
    )
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(main.app(
        {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
         "method": "GET", "scheme": "http", "path": "/accounts",
         "raw_path": b"/accounts", "query_string": b"",
         "headers": [(b"host", b"external.invalid")], "client": ("test", 1),
         "server": ("test", 80), "root_path": ""},
        receive, send,
    ))
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in messages)
    assert start["status"] == 400
    assert body == b"Invalid host header"


def test_api_accepts_moo_and_contingent_moc_and_exposes_linkage(con, monkeypatch):
    _api_account(con, monkeypatch)
    parent = accounts_routes.submit_order(
        "acct-private", _intent(), "Bearer token",
    )
    child = accounts_routes.submit_order(
        "acct-private",
        _intent(intent_id="moc-child", side="sell", order_type="moc",
                contingent_on="moo-parent"),
        "Bearer token",
    )
    assert parent["state"] == child["state"] == "queued"
    projected = accounts_routes.get_orders("acct-private", authorization="Bearer token")
    assert [(row["intent_id"], row["contingent_on"]) for row in projected] == [
        ("moo-parent", None), ("moc-child", "moo-parent"),
    ]

    con.execute(
        "INSERT INTO sim_fills VALUES (?, 'acct-private', 'SAME', 'buy', 5, "
        "DATE '2026-10-05', 100, 101, 100, 100)", [parent["order_id"]]
    )
    con.execute(
        "INSERT INTO sim_fill_details (order_id,reference_px,fill_kind,price_source) "
        "VALUES (?,100,'open_auction','prices')", [parent["order_id"]]
    )
    fills = accounts_routes.get_fills("acct-private", authorization="Bearer token")
    assert fills[0]["fill_price"] == 101
    assert fills[0]["reference_px"] == 100


def test_api_refuses_contingent_child_larger_than_parent(con, monkeypatch):
    _api_account(con, monkeypatch)
    accounts_routes.submit_order("acct-private", _intent(quantity=5), "Bearer token")
    with pytest.raises(HTTPException, match="exceeds parent quantity") as exc_info:
        accounts_routes.submit_order(
            "acct-private",
            _intent(intent_id="large-child", side="sell", quantity=6, order_type="moc",
                    contingent_on="moo-parent"),
            "Bearer token",
        )
    assert exc_info.value.status_code == 409


def test_api_refuses_contingent_child_from_another_account(con, monkeypatch):
    _api_account(con, monkeypatch)
    service.create(con, _spec("acct-other"), now=NOW)
    accounts_routes.submit_order("acct-private", _intent(), "Bearer token")
    with pytest.raises(HTTPException, match="another account") as exc_info:
        accounts_routes.submit_order(
            "acct-other",
            _intent("acct-other", intent_id="foreign-child", side="sell", order_type="moc",
                    contingent_on="moo-parent"),
            "Bearer token",
        )
    assert exc_info.value.status_code == 409


def test_api_refuses_contingent_child_of_cancelled_parent(con, monkeypatch):
    _api_account(con, monkeypatch)
    parent = accounts_routes.submit_order("acct-private", _intent(), "Bearer token")
    service.cancel(con, "acct-private", parent["order_id"], now=NOW)
    with pytest.raises(HTTPException, match="not queued") as exc_info:
        accounts_routes.submit_order(
            "acct-private",
            _intent(intent_id="cancelled-child", side="sell", order_type="moc",
                    contingent_on="moo-parent"),
            "Bearer token",
        )
    assert exc_info.value.status_code == 409
