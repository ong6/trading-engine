"""The operator review CLI is read-only, bounded, and non-authorizing."""

from __future__ import annotations

import io
import json
from datetime import timedelta

import duckdb

from sim.schema import init_sim_schema
from tests.conftest import PRICES_DDL
from tests.test_agent_paper_evidence import NOW, _accepted, _request
from tools import review_agent_paper_intent


def _database(tmp_path, monkeypatch):
    database = tmp_path / "review.duckdb"
    con = duckdb.connect(str(database))
    con.execute(PRICES_DDL)
    init_sim_schema(con)
    result = _accepted(con, monkeypatch)
    counts = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "agent_shadow_attempts",
            "agent_shadow_events",
            "agent_proposals",
            "sim_orders",
            "sim_fills",
        )
    }
    con.close()
    return database, result, counts


def _counts(database) -> dict[str, int]:
    con = duckdb.connect(str(database), read_only=True)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "agent_shadow_attempts",
                "agent_shadow_events",
                "agent_proposals",
                "sim_orders",
                "sim_fills",
            )
        }
    finally:
        con.close()


def test_build_and_verify_round_trip_without_database_mutation(tmp_path, monkeypatch):
    database, result, before = _database(tmp_path, monkeypatch)
    built = io.StringIO()
    errors = io.StringIO()

    exit_code = review_agent_paper_intent.main(
        [
            "build",
            "agent_only",
            result["decision_window"],
            "future-paper-order-1",
            "agent_dual_momentum_shadow_v1",
            "SPY",
            "buy",
            "5",
            "2026-09-11",
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
    assert packet["schema_version"] == 2
    assert packet["review_summary"]["signal_close"] == 120.0
    assert packet["review_summary"]["request_notional"] == 600.0
    assert packet["approval_present"] is False
    assert packet["submission_authority"] == "none"

    verified = io.StringIO()
    exit_code = review_agent_paper_intent.main(
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


def test_verify_rejects_duplicate_json_keys_before_database_open(monkeypatch):
    opened = False

    def forbidden(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("database must not open")

    monkeypatch.setattr(review_agent_paper_intent.engine_db, "connect", forbidden)
    errors = io.StringIO()

    exit_code = review_agent_paper_intent.main(
        ["verify"],
        stdin=io.BytesIO(b'{"schema_version":2,"schema_version":2}'),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "stdin is invalid" in errors.getvalue()
    assert opened is False


def test_verify_rejects_oversized_stdin_before_database_open(monkeypatch):
    monkeypatch.setattr(
        review_agent_paper_intent.engine_db,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("database must not open")
        ),
    )
    errors = io.StringIO()

    exit_code = review_agent_paper_intent.main(
        ["verify"],
        stdin=io.BytesIO(b"{" + b" " * review_agent_paper_intent.MAX_PACKET_BYTES),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW,
    )

    assert exit_code == 2
    assert "exceeds the input limit" in errors.getvalue()


def test_verify_rejects_expired_packet(tmp_path, monkeypatch):
    database, result, before = _database(tmp_path, monkeypatch)
    request = _request()
    packet = review_agent_paper_intent.build_database(
        database,
        request,
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    errors = io.StringIO()

    exit_code = review_agent_paper_intent.main(
        ["verify", "--db", str(database)],
        stdin=io.BytesIO(json.dumps(packet).encode()),
        stdout=io.StringIO(),
        stderr=errors,
        now=NOW + timedelta(seconds=301),
    )

    assert exit_code == 2
    assert "packet expired" in errors.getvalue()
    assert _counts(database) == before


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

    request = _request()
    packet = {"packet": "value"}
    monkeypatch.setattr(review_agent_paper_intent.engine_db, "connect", connect)
    monkeypatch.setattr(
        review_agent_paper_intent.broker_human_paper_review,
        "build",
        lambda con, actual, **kwargs: (
            packet
            if con is connections[-1]
            and actual == request
            and kwargs["mode"] == "agent_only"
            else (_ for _ in ()).throw(AssertionError("wrong build inputs"))
        ),
    )
    monkeypatch.setattr(
        review_agent_paper_intent.broker_human_paper_review,
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
        review_agent_paper_intent.build_database(
            review_agent_paper_intent.Path("review.duckdb"),
            request,
            decision_window_id="window-1",
            mode="agent_only",
            generated_at=NOW,
        )
        is packet
    )
    assert (
        review_agent_paper_intent.verify_database(
            review_agent_paper_intent.Path("review.duckdb"),
            packet,
            reviewed_at=NOW,
        )
        is packet
    )
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)


def test_module_has_no_writer_approval_or_submission_surface():
    assert {
        "activate",
        "approve",
        "authorize",
        "create_table",
        "insert",
        "issue",
        "persist",
        "submit",
        "submit_order",
        "update",
        "write",
    }.isdisjoint(vars(review_agent_paper_intent))
