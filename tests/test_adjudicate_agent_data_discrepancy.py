"""The discrepancy-adjudication CLI is bounded and non-remediating."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

import duckdb

from server import agent_data_discrepancy_review, agent_provider_responses
from tests.conftest import PRICES_DDL
from tests.test_agent_provider_responses import _body, _response
from tools import adjudicate_agent_data_discrepancy

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _database(tmp_path):
    database = tmp_path / "adjudication.duckdb"
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
    packet = agent_data_discrepancy_review.build(
        con,
        dataset="daily_price",
        ticker="SPY",
        fact_date=date(2026, 9, 11),
        kind="daily_price",
        generated_at=NOW + timedelta(seconds=1),
    )
    con.close()
    return database, packet


def _request(packet: dict) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "decision_id": "decision-spy-2026-09-11-v1",
            "disposition": "defer_pending_more_evidence",
            "operator_id": "operator-jun",
            "justification": "Await another independent retained observation.",
            "review_packet": packet,
        },
        separators=(",", ":"),
    ).encode()


def test_record_then_status_does_not_change_market_or_simulator_rows(tmp_path):
    database, packet = _database(tmp_path)
    output = io.StringIO()
    errors = io.StringIO()

    assert adjudicate_agent_data_discrepancy.main(
        ["--db", str(database), "record"],
        stdin=io.BytesIO(_request(packet)),
        stdout=output,
        stderr=errors,
        now=NOW + timedelta(seconds=2),
    ) == 0
    decision = json.loads(output.getvalue())
    assert decision["disposition"] == "defer_pending_more_evidence"
    assert decision["operational_effect"] == (
        "record_only_separate_follow_up_required"
    )
    assert decision["execution_authority"] == "none"
    assert errors.getvalue() == ""

    status_output = io.StringIO()
    assert adjudicate_agent_data_discrepancy.main(
        ["--db", str(database), "status"],
        stdout=status_output,
        stderr=errors,
    ) == 0
    status = json.loads(status_output.getvalue())
    assert status["decision_count"] == 1
    assert status["latest_decision_sha256"] == decision["decision_sha256"]
    assert "justification" not in status
    assert errors.getvalue() == ""

    con = duckdb.connect(str(database), read_only=True)
    try:
        assert con.execute(
            "SELECT close FROM prices WHERE ticker = 'SPY'"
        ).fetchone() == (100.0,)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_data_discrepancy_decisions"
        ).fetchone() == (1,)
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()
    assert "price_quarantine" not in tables
    assert "sim_orders" not in tables
    assert "sim_fills" not in tables


def test_record_rejects_duplicate_keys_before_database_open(monkeypatch):
    opened = False

    def forbidden(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("database must not open")

    monkeypatch.setattr(
        adjudicate_agent_data_discrepancy.engine_db,
        "connect",
        forbidden,
    )
    errors = io.StringIO()

    exit_code = adjudicate_agent_data_discrepancy.main(
        ["record"],
        stdin=io.BytesIO(b'{"schema_version":1,"schema_version":1}'),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "stdin is invalid" in errors.getvalue()
    assert opened is False


def test_record_rejects_oversized_input_before_database_open(monkeypatch):
    monkeypatch.setattr(
        adjudicate_agent_data_discrepancy.engine_db,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("database must not open")
        ),
    )
    errors = io.StringIO()

    exit_code = adjudicate_agent_data_discrepancy.main(
        ["record"],
        stdin=io.BytesIO(
            b"{" + b" " * adjudicate_agent_data_discrepancy.MAX_REQUEST_BYTES
        ),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "exceeds the input limit" in errors.getvalue()


def test_database_helpers_use_expected_connection_modes(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connections = []

    def connect(database, *, read_only, wait_s):
        assert database.name == "adjudication.duckdb"
        assert wait_s == 0
        connection = Connection()
        connections.append((connection, read_only))
        return connection

    monkeypatch.setattr(
        adjudicate_agent_data_discrepancy.engine_db,
        "connect",
        connect,
    )
    monkeypatch.setattr(
        adjudicate_agent_data_discrepancy.agent_data_discrepancy_adjudication,
        "record_decision",
        lambda con, packet, **kwargs: {
            "connection": con,
            "packet": packet,
            **kwargs,
        },
    )
    monkeypatch.setattr(
        adjudicate_agent_data_discrepancy.agent_data_discrepancy_adjudication,
        "status",
        lambda con: {"connection": con},
    )
    request = {
        "review_packet": {"packet": "value"},
        "decision_id": "decision-1",
        "disposition": "defer_pending_more_evidence",
        "operator_id": "operator-1",
        "justification": "Wait.",
    }
    database = adjudicate_agent_data_discrepancy.Path("adjudication.duckdb")

    recorded = adjudicate_agent_data_discrepancy.record_database(
        database,
        request,
        decided_at=NOW,
    )
    inspected = adjudicate_agent_data_discrepancy.status_database(database)

    assert recorded["connection"] is connections[0][0]
    assert inspected["connection"] is connections[1][0]
    assert [read_only for _connection, read_only in connections] == [False, True]
    assert all(connection.closed for connection, _read_only in connections)


def test_cli_has_no_repair_quarantine_or_authority_command():
    parser = adjudicate_agent_data_discrepancy._parser()
    for command in ("repair", "quarantine", "authorize", "submit"):
        try:
            parser.parse_args([command])
        except SystemExit as exc:
            assert exc.code != 0
        else:  # pragma: no cover - a forbidden command would fail the assertion
            raise AssertionError(f"forbidden command accepted: {command}")
