"""Tests for server HTTP route contracts and connection ownership."""

import asyncio
import json
import re
from datetime import date
from pathlib import Path as FilePath

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from engine.lib.db import DBBusyError
from server import (
    main,
    market_read_models,
    read_model_utils,
)

REPO_ROOT = FilePath(__file__).resolve().parents[1]


class _Con:
    def __init__(self):
        self.closed = False

    def execute(self, _sql):
        return self

    def close(self):
        self.closed = True


async def _request_status(
    method: str,
    path: str,
    query: str = "",
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> int:
    messages = []
    request_headers = list(headers or [])
    if not any(name.lower() == b"host" for name, _value in request_headers):
        request_headers.append((b"host", b"127.0.0.1:8000"))

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await main.app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": request_headers,
            "client": ("test", 1),
            "server": ("test", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"host", b"attacker.invalid")],
        [(b"host", b"localhost.attacker.invalid:8000")],
        [(b"host", b"localhost:0")],
        [(b"host", b"localhost:65536")],
        [(b"host", b"localhost:not-a-port")],
        [(b"host", b"localhost:" + (b"9" * 10_000))],
        [(b"host", b"127.0.0.1:8000"), (b"host", b"attacker.invalid")],
    ],
)
def test_host_boundary_rejects_missing_external_or_duplicate_host_before_database_open(
    monkeypatch, headers
):
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be opened")),
    )

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(
        main.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/health",
                "raw_path": b"/health",
                "query_string": b"",
                "headers": headers,
                "client": ("test", 1),
                "server": ("test", 80),
                "root_path": "",
            },
            receive,
            send,
        )
    )

    assert (
        next(message["status"] for message in messages if message["type"] == "http.response.start")
        == 400
    )


@pytest.mark.parametrize(
    "host",
    [
        b"127.0.0.1",
        b"127.0.0.1:8000",
        b"localhost",
        b"localhost:18000",
        b"LOCALHOST:8000",
    ],
)
def test_host_boundary_accepts_exact_loopback_origins(monkeypatch, host):
    monkeypatch.setattr(main, "read_con", lambda: _Con())

    assert asyncio.run(_request_status("GET", "/health", headers=[(b"host", host)])) == 200


def test_orders_route_schema_restricts_status_query_to_known_states():
    parameter = main.app.openapi()["paths"]["/orders"]["get"]["parameters"][0]

    assert parameter["name"] == "status"
    assert parameter["schema"]["anyOf"][0]["enum"] == [
        "pending",
        "filled",
        "rejected",
        "cancelled",
    ]


def test_screen_route_schema_bounds_page_queries():
    paths = main.app.openapi()["paths"]

    for route in ("/screen/latest", "/screen/{run_date}"):
        page = next(item for item in paths[route]["get"]["parameters"] if item["name"] == "page")
        assert page["required"] is False
        assert page["schema"] == {
            "type": "integer",
            "maximum": 1_000_000,
            "minimum": 1,
            "default": 1,
            "title": "Page",
        }


def test_identifier_route_schemas_bound_public_inputs():
    paths = main.app.openapi()["paths"]

    expected = {
        ("/candidates/{ticker}", "get", "ticker"): {
            "type": "string",
            "maxLength": main.ticket_contract.TICKER_MAX_CHARS,
            "minLength": 1,
            "pattern": main.NONBLANK_PATTERN,
            "title": "Ticker",
        },
        ("/league/{portfolio_id}/equity", "get", "portfolio_id"): {
            "type": "string",
            "maxLength": read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS,
            "minLength": 1,
            "pattern": main.NONBLANK_PATTERN,
            "title": "Portfolio Id",
        },
        ("/tickets/{ticket_id}/cancel", "post", "ticket_id"): {
            "type": "integer",
            "maximum": read_model_utils.PUBLIC_SAFE_INTEGER_MAX,
            "minimum": 1,
            "title": "Ticket Id",
        },
    }
    for (route, method, name), schema in expected.items():
        parameter = next(
            item for item in paths[route][method]["parameters"] if item["name"] == name
        )
        assert parameter["required"] is True
        assert parameter["schema"] == schema

    portfolio = next(
        item for item in paths["/positions"]["get"]["parameters"] if item["name"] == "portfolio"
    )
    assert portfolio["required"] is False
    assert portfolio["schema"] == {
        "anyOf": [
            {
                "type": "string",
                "maxLength": read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS,
                "minLength": 1,
                "pattern": main.NONBLANK_PATTERN,
            },
            {"type": "null"},
        ],
        "title": "Portfolio",
    }


def test_browser_portfolio_identifier_limit_matches_backend():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "response-contracts.js").read_text()
    match = re.search(
        r"^export const PUBLIC_PORTFOLIO_ID_MAX_CHARS = (\d+);$",
        source,
        re.MULTILINE,
    )

    assert match is not None
    assert int(match[1]) == read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS


def test_browser_ticker_limit_matches_backend():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "candidate-route.js").read_text()
    match = re.search(
        r"^export const CANDIDATE_TICKER_MAX_CHARS = (\d+);$",
        source,
        re.MULTILINE,
    )

    assert match is not None
    assert int(match[1]) == read_model_utils.PUBLIC_TICKER_MAX_CHARS


def test_browser_safe_integer_limit_matches_backend():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "response-contracts.js").read_text()
    match = re.search(
        r"^export const PUBLIC_SAFE_INTEGER_MAX = (\d+);$",
        source,
        re.MULTILINE,
    )

    assert match is not None
    assert int(match[1]) == read_model_utils.PUBLIC_SAFE_INTEGER_MAX


def test_cancel_route_rejects_unsafe_identifier_before_database_open(monkeypatch):
    monkeypatch.setattr(
        main,
        "write_con",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be opened")),
    )

    with pytest.raises(HTTPException, match="ticket identifier is invalid") as exc_info:
        main.cancel_ticket(read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1)

    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("value", [" book", "book ", "book\nother", "book\tother"])
def test_portfolio_routes_reject_noncanonical_identity_before_database_open(monkeypatch, value):
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("read database should not be opened")),
    )

    with pytest.raises(HTTPException) as equity_error:
        main.league_equity(value)
    with pytest.raises(HTTPException) as positions_error:
        main.positions(value)

    assert equity_error.value.status_code == 422
    assert positions_error.value.status_code == 422


@pytest.mark.parametrize("value", [" AAA", "AAA ", "AA\nA", "AA\tA"])
def test_candidate_route_rejects_noncanonical_ticker_before_database_open(monkeypatch, value):
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("read database should not be opened")),
    )

    with pytest.raises(HTTPException) as error:
        main.candidate(value)

    assert error.value.status_code == 422


def test_mutation_schemas_require_content_type_header():
    paths = main.app.openapi()["paths"]

    for route in ("/tickets", "/tickets/{ticket_id}/cancel", "/review-done"):
        parameter = next(
            item for item in paths[route]["post"]["parameters"] if item["name"] == "content-type"
        )
        assert parameter == {
            "name": "content-type",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "title": "Content-Type"},
        }


@pytest.mark.parametrize(
    ("method", "path", "query"),
    [
        (
            "GET",
            f"/candidates/{'A' * (main.ticket_contract.TICKER_MAX_CHARS + 1)}",
            "",
        ),
        (
            "GET",
            f"/league/{'p' * (read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS + 1)}/equity",
            "",
        ),
        ("GET", "/positions", "portfolio="),
        ("GET", "/positions", "portfolio=%20"),
        ("GET", "/candidates/ ", ""),
        (
            "GET",
            "/positions",
            f"portfolio={'p' * (read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS + 1)}",
        ),
        ("POST", "/tickets/0/cancel", ""),
    ],
)
def test_fastapi_rejects_invalid_public_identifiers_before_database_open(
    monkeypatch, method, path, query
):
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("read database should not be opened")),
    )
    monkeypatch.setattr(
        main,
        "write_con",
        lambda: (_ for _ in ()).throw(AssertionError("write database should not be opened")),
    )

    assert (
        asyncio.run(
            _request_status(
                method,
                path,
                query,
                headers=[(b"content-type", b"application/json")],
            )
        )
        == 422
    )


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"],
)
@pytest.mark.parametrize("path", ["/tickets", "/tickets/1/cancel", "/review-done"])
def test_mutations_require_json_before_database_open(monkeypatch, path, content_type):
    monkeypatch.setattr(
        main,
        "write_con",
        lambda: (_ for _ in ()).throw(AssertionError("write database should not be opened")),
    )
    headers = [(b"content-type", content_type.encode())]

    assert asyncio.run(_request_status("POST", path, headers=headers)) == 415


@pytest.mark.parametrize("path", ["/tickets", "/tickets/1/cancel", "/review-done"])
def test_mutations_require_content_type_header_before_database_open(monkeypatch, path):
    monkeypatch.setattr(
        main,
        "write_con",
        lambda: (_ for _ in ()).throw(AssertionError("write database should not be opened")),
    )

    assert asyncio.run(_request_status("POST", path)) == 422


def test_json_media_type_with_parameters_reaches_mutation_route(monkeypatch):
    connection = _Con()
    monkeypatch.setattr(main, "write_con", lambda: connection)
    monkeypatch.setattr(
        main.tickets,
        "mark_review_done",
        lambda con: {"ok": True, "connection": con is connection},
    )

    status = asyncio.run(
        _request_status(
            "POST",
            "/review-done",
            headers=[(b"content-type", b"application/json; charset=utf-8")],
        )
    )

    assert status == 200
    assert connection.closed is True


def test_health_ok_when_db_is_readable(monkeypatch):
    monkeypatch.setattr(main, "read_con", lambda: _Con())
    result = main.health()
    assert result == {"ok": True, "status": "ok", "db_readable": True}


def test_health_projection_requires_exact_coherent_fields():
    main._validate_health_payload({"ok": True, "status": "ok", "db_readable": True})

    with pytest.raises(ValueError, match="projection shape"):
        main._validate_health_payload(
            {"ok": True, "status": "ok", "db_readable": True, "internal": True}
        )
    with pytest.raises(ValueError, match="projection is inconsistent"):
        main._validate_health_payload({"ok": True, "status": "busy", "db_readable": False})


def test_health_503_when_db_is_busy(monkeypatch):
    def busy():
        raise DBBusyError("locked")

    monkeypatch.setattr(main, "read_con", busy)
    result = main.health()
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert json.loads(result.body) == {
        "ok": False,
        "status": "busy",
        "db_readable": False,
    }


def test_database_busy_handler_returns_stable_503_without_internal_detail():
    result = asyncio.run(main._busy_handler(None, DBBusyError("private lock detail")))

    assert result.status_code == 503
    assert b"database busy" in result.body
    assert b"private lock detail" not in result.body


def test_health_503_when_database_is_unreadable(monkeypatch):
    def broken():
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(main, "read_con", broken)
    result = main.health()
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert json.loads(result.body) == {
        "ok": False,
        "status": "unreadable",
        "db_readable": False,
    }


@pytest.mark.parametrize("run_date", ["not-a-date", "20260909", "2026-W37-3"])
def test_invalid_screen_date_is_400_without_opening_database(monkeypatch, run_date):
    monkeypatch.setattr(
        main,
        "read_con",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be opened")),
    )

    with pytest.raises(HTTPException, match="run_date must be YYYY-MM-DD") as exc_info:
        main.screen_by_date(run_date)

    assert exc_info.value.status_code == 400


def test_latest_screen_route_caps_projection_at_operational_date(monkeypatch):
    connection = _Con()
    operational = date(2026, 9, 4)
    observed = []
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda con: operational)
    monkeypatch.setattr(
        market_read_models,
        "screen",
        lambda con, *, through, page: (
            observed.append((through, page)) or {"run_date": through, "page": page}
        ),
    )

    assert main.screen_latest(page=3) == {"run_date": operational, "page": 3}
    assert observed == [(operational, 3)]


def test_latest_screen_route_fails_closed_without_operational_date(monkeypatch):
    connection = _Con()
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda con: None)
    monkeypatch.setattr(
        market_read_models,
        "screen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("screen projection must not run")
        ),
    )

    with pytest.raises(HTTPException, match="no screen_results") as exc_info:
        main.screen_latest()

    assert exc_info.value.status_code == 404


def test_dated_screen_route_parses_date_delegates_and_closes_connection(monkeypatch):
    connection = _Con()
    observed = []
    payload = {"run_date": date(2026, 9, 4), "page": 2}
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(
        market_read_models,
        "screen",
        lambda con, run_date, *, page: observed.append((con, run_date, page)) or payload,
    )

    assert main.screen_by_date("2026-09-04", page=2) == payload
    assert observed == [(connection, date(2026, 9, 4), 2)]
    assert connection.closed is True


@pytest.mark.parametrize(
    ("route_name", "owner_name", "projection_name", "route_args", "model_args"),
    [
        ("league", "league_read_models", "league", (), ()),
        ("orders", "order_read_models", "orders", ("pending",), ("pending",)),
        ("journal", "journal_read_models", "journal", (), ()),
    ],
)
def test_simple_read_routes_delegate_and_close_connection(
    monkeypatch,
    route_name,
    owner_name,
    projection_name,
    route_args,
    model_args,
):
    connection = _Con()
    observed = []
    payload = {"route": route_name}
    owner = getattr(main, owner_name)
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(
        owner,
        projection_name,
        lambda con, *args: observed.append((con, args)) or payload,
    )

    assert getattr(main, route_name)(*route_args) == payload
    assert observed == [(connection, model_args)]
    assert connection.closed is True


def test_candidate_route_normalizes_ticker_delegates_and_closes_connection(monkeypatch):
    connection = _Con()
    observed = []
    payload = {"ticker": "AAA"}
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(
        market_read_models,
        "candidate",
        lambda con, ticker: observed.append((con, ticker)) or payload,
    )

    assert main.candidate("aaa") == payload
    assert observed == [(connection, "AAA")]
    assert connection.closed is True


def test_single_equity_route_404s_and_closes_connection(monkeypatch):
    connection = _Con()
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(main.league_read_models, "equity", lambda con, portfolio_id: None)

    with pytest.raises(HTTPException, match="no equity for missing") as exc_info:
        main.league_equity("missing")

    assert exc_info.value.status_code == 404
    assert connection.closed is True


def test_positions_route_404s_for_non_active_portfolio(monkeypatch):
    connection = _Con()
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(main.position_read_models, "positions", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        main.positions("retired")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "no active portfolio retired"


def test_bulk_equity_route_returns_projection_and_closes_connection(monkeypatch):
    connection = _Con()
    connection.closed = False
    connection.close = lambda: setattr(connection, "closed", True)
    payload = {
        "as_of": "2026-09-04",
        "limit_per_portfolio": 500,
        "equity_by_portfolio": {"book": [{"portfolio_id": "book", "equity": 101.0}]},
        "matching_count_by_portfolio": {"book": 1},
        "truncated_by_portfolio": {"book": False},
    }
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(main.league_read_models, "equities", lambda con: payload)

    assert main.league_equities() == payload
    assert connection.closed is True


def test_ticket_context_route_returns_projection_and_closes_connection(monkeypatch):
    connection = _Con()
    connection.closed = False
    connection.close = lambda: setattr(connection, "closed", True)
    payload = {"status": "active", "equity": 40_000.0, "risk_pct": 0.01}
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(main.paper_read_models, "ticket_context", lambda con: payload)

    assert main.ticket_context() == payload
    assert connection.closed is True


def test_review_done_route_delegates_and_closes_connection(monkeypatch):
    connection = _Con()
    payload = {"ok": True, "kind": "circuit_breaker"}
    monkeypatch.setattr(main, "write_con", lambda: connection)
    monkeypatch.setattr(main.tickets, "mark_review_done", lambda con: payload)

    assert main.review_done() == payload
    assert connection.closed is True


def test_route_connection_closes_after_unexpected_projection_error(monkeypatch):
    connection = _Con()
    connection.closed = False
    connection.close = lambda: setattr(connection, "closed", True)
    monkeypatch.setattr(main, "read_con", lambda: connection)
    monkeypatch.setattr(
        main.journal_read_models,
        "journal",
        lambda con: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        main.journal()

    assert connection.closed is True
