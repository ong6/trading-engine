"""The data-discrepancy review CLI is bounded, read-only, and non-authorizing."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

import duckdb

from server import agent_provider_responses
from tests.conftest import PRICES_DDL
from tests.test_agent_provider_responses import _body, _response
from tools import review_agent_data_discrepancy

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _database(tmp_path):
    database = tmp_path / "review.duckdb"
    con = duckdb.connect(str(database))
    con.execute(PRICES_DDL)
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('SPY', DATE '2026-09-11', 100, 102, 99, 100, 1000000, "
        "'yfinance', TIMESTAMP '2026-09-12 00:00:00')"
    )
    agent_provider_responses.init_schema(con)
    body = _body(
        "SPY",
        open_price=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1_000_000,
    )
    receipt, facts = agent_provider_responses._receipt(
        ticker="SPY",
        provider_ticker="SPY",
        start=date(2026, 9, 11),
        end=date(2026, 9, 12),
        requested_at=NOW,
        response=_response(body),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])
    before = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "prices",
            "agent_provider_responses",
            "agent_provider_response_links",
            "agent_provider_source_observations",
        )
    }
    con.close()
    return database, before


def _counts(database) -> dict[str, int]:
    con = duckdb.connect(str(database), read_only=True)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "prices",
                "agent_provider_responses",
                "agent_provider_response_links",
                "agent_provider_source_observations",
            )
        }
    finally:
        con.close()


def test_build_and_verify_round_trip_without_database_mutation(tmp_path):
    database, before = _database(tmp_path)
    built = io.StringIO()
    errors = io.StringIO()

    exit_code = review_agent_data_discrepancy.main(
        [
            "build",
            "daily_price",
            "SPY",
            "2026-09-11",
            "daily_price",
            "--db",
            str(database),
        ],
        stdout=built,
        stderr=errors,
        now=NOW + timedelta(seconds=1),
    )

    assert exit_code == 0
    assert errors.getvalue() == ""
    packet = json.loads(built.getvalue())
    assert packet["discrepancy_classification"] == "current_cache_value_drift"
    assert packet["decision_present"] is False
    assert packet["execution_authority"] == "none"

    verified = io.StringIO()
    exit_code = review_agent_data_discrepancy.main(
        ["verify", "--db", str(database)],
        stdin=io.BytesIO(built.getvalue().encode()),
        stdout=verified,
        stderr=errors,
        now=NOW + timedelta(seconds=2),
    )

    assert exit_code == 0
    assert json.loads(verified.getvalue()) == packet
    assert errors.getvalue() == ""
    assert _counts(database) == before


def test_list_returns_hash_only_discovery_without_database_mutation(tmp_path):
    database, before = _database(tmp_path)
    output = io.StringIO()
    errors = io.StringIO()

    exit_code = review_agent_data_discrepancy.main(
        ["list", "--db", str(database)],
        stdout=output,
        stderr=errors,
        now=NOW + timedelta(seconds=1),
    )

    assert exit_code == 0
    assert errors.getvalue() == ""
    result = json.loads(output.getvalue())
    assert result["matching_count"] == 1
    assert result["market_values_exposed"] is False
    assert "value" not in result["items"][0]
    assert _counts(database) == before


def test_verify_rejects_duplicate_keys_before_database_open(monkeypatch):
    opened = False

    def forbidden(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("database must not open")

    monkeypatch.setattr(
        review_agent_data_discrepancy.engine_db,
        "connect",
        forbidden,
    )
    errors = io.StringIO()

    exit_code = review_agent_data_discrepancy.main(
        ["verify"],
        stdin=io.BytesIO(b'{"schema_version":1,"schema_version":1}'),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "stdin is invalid" in errors.getvalue()
    assert opened is False


def test_verify_rejects_oversized_stdin_before_database_open(monkeypatch):
    monkeypatch.setattr(
        review_agent_data_discrepancy.engine_db,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("database must not open")
        ),
    )
    errors = io.StringIO()

    exit_code = review_agent_data_discrepancy.main(
        ["verify"],
        stdin=io.BytesIO(
            b"{" + b" " * review_agent_data_discrepancy.MAX_PACKET_BYTES
        ),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "exceeds the input limit" in errors.getvalue()


def test_database_helpers_force_read_only_connections(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connections = []

    def connect(database, *, read_only, wait_s):
        assert database.name == "review.duckdb"
        assert read_only is True
        assert wait_s == 0
        connection = Connection()
        connections.append(connection)
        return connection

    packet = {"packet": "value"}
    monkeypatch.setattr(
        review_agent_data_discrepancy.engine_db,
        "connect",
        connect,
    )
    monkeypatch.setattr(
        review_agent_data_discrepancy.agent_data_discrepancy_review,
        "build",
        lambda con, **kwargs: (
            packet
            if con is connections[-1]
            and kwargs["dataset"] == "daily_price"
            and kwargs["ticker"] == "SPY"
            else (_ for _ in ()).throw(AssertionError("wrong build inputs"))
        ),
    )
    monkeypatch.setattr(
        review_agent_data_discrepancy.agent_data_discrepancy_review,
        "verify_retained",
        lambda con, actual, **kwargs: (
            packet
            if con is connections[-1]
            and actual is packet
            and kwargs["reviewed_at"] == NOW
            else (_ for _ in ()).throw(AssertionError("wrong verify inputs"))
        ),
    )

    assert (
        review_agent_data_discrepancy.build_database(
            review_agent_data_discrepancy.Path("review.duckdb"),
            dataset="daily_price",
            ticker="SPY",
            fact_date=date(2026, 9, 11),
            kind="daily_price",
            generated_at=NOW,
        )
        is packet
    )
    assert (
        review_agent_data_discrepancy.verify_database(
            review_agent_data_discrepancy.Path("review.duckdb"),
            packet,
            reviewed_at=NOW,
        )
        is packet
    )
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)


def test_module_has_no_writer_adjudication_or_authority_surface():
    assert {
        "accept",
        "activate",
        "adjudicate",
        "authorize",
        "insert",
        "persist",
        "quarantine",
        "resolve",
        "submit",
        "update",
        "write",
    }.isdisjoint(vars(review_agent_data_discrepancy))
