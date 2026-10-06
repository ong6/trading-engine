"""Loopback account API authentication and receipt timing tests."""
import asyncio
import stat
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from engine import paper_accounts
from engine.accounts import api, service
from server import accounts_routes, main

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


@contextmanager
def _borrowed(con):
    yield con


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
    paper_accounts.set_portfolio_account(con, "acct-public", visibility="public", updated_at=NOW)
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
    assert exc_info.value.status_code == 401
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
    monkeypatch.setattr(accounts_routes, "_connection", connection)
    monkeypatch.setattr(accounts_routes, "_require_token", lambda _authorization: None)
    monkeypatch.setattr(accounts_routes.service, "submit", submit)
    result = accounts_routes.submit_order("acct-a", {"account_id": "acct-a"}, "Bearer x")
    assert events == ["stamp", "lock", "submit"]
    assert result["received_at"] == NOW.isoformat()


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
