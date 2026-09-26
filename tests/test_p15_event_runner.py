"""P15 event decision, rate-limit, and shadow-authority tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts, p15_event_sources
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm import p15_event_runner
from server import agent_model_client
from tests.conftest import SESSIONS, insert_bars


def _setup(con):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    p15_event_sources.init_schema(con)
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    observed = datetime(2024, 7, 17, 14, 5, tzinfo=timezone.utc)
    con.execute("UPDATE prices SET fetched_at=?", [
        (observed - timedelta(days=1)).replace(tzinfo=None)
    ])
    receipt = bitemporal_facts.record_receipt(
        con, source="local_rss", dataset="headline", endpoint="news.jsonl", request={},
        requested_at=observed - timedelta(minutes=2),
        received_at=observed - timedelta(minutes=2), http_status=200,
        content_type="application/json", body=b"{}", license_class="public",
    )
    fact = bitemporal_facts.record_fact(
        con, entity_id="rss:one:AAA", security_id="AAA", fact_type="news.headline",
        event_at=observed - timedelta(minutes=3),
        published_at=observed - timedelta(minutes=3),
        available_at=observed - timedelta(minutes=2),
        ingested_at=observed - timedelta(minutes=2), payload={"title": "AAA update"},
        source="local_rss", source_version="test",
        receipt_sha256=receipt["receipt_sha256"],
    )
    identity = {"session_date": observed.date().isoformat(), "ticker": "AAA",
                "source": "rss", "event_type": "news.headline",
                "fact_sha256": fact["fact_sha256"], "triggered_at": observed.isoformat()}
    con.execute(
        "INSERT INTO p15_event_triggers VALUES "
        "(1,?,'AAA','rss','news.headline',?,?,?,?,'pending',NULL,?)",
        [observed.date(), observed - timedelta(minutes=3), observed - timedelta(minutes=2),
         observed.replace(tzinfo=None), fact["fact_sha256"], canonical_sha256(identity)],
    )
    return observed, fact["fact_sha256"]


def _result(payload, *, action="buy_candidate"):
    item = payload["events"][0]
    output = {"schema_version": 1, "assessments": [{
        "trigger_id": item["trigger_id"], "ticker": item["ticker"],
        "event_type": item["event_type"], "p_outperform_5": 0.6,
        "expected_excess_bp_5": 75.0, "expected_excess_bp_10": 100.0,
        "action": action, "thesis": "Positive event evidence.",
        "invalidation": "The event thesis fails.",
        "evidence_ids": [item["trigger_evidence_id"]],
    }]}
    return agent_model_client.ConnectorResult(
        output=output, response_id="event-response", model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION, proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="event-upstream",
        model_catalog_entry_sha256=agent_model_client.MODEL_CATALOG_ENTRY_SHA256,
        request_sha256=canonical_sha256(agent_model_client.p15_event_request_payload(payload)),
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def test_event_scoring_is_retained_rate_bounded_and_shadow_only(con):
    observed, fact_sha = _setup(con)
    calls = []

    result = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={"rss": {"status": "complete"}},
        generate=lambda payload: calls.append(payload) or _result(payload),
        clock=lambda: observed + timedelta(minutes=1),
    )
    replay = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={"rss": {"status": "changed"}},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("replayed")),
    )

    assert result == {"status": "completed", "decisions": 1, "skipped": 0,
                      "model_calls": 1, "unavailable": 0,
                      "labels": 0, "replayed": False, "execution_authority": "none"}
    assert replay["replayed"] is True and replay["decisions"] == 1
    assert calls[0]["events"][0]["allowed_evidence_ids"] == [fact_sha]
    assert con.execute(
        "SELECT scoring_status,latency_ms FROM p15_event_decisions"
    ).fetchone() == ("available", 60_000.0)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_trigger_after_window_cutoff_waits_for_next_window(con):
    observed, _fact_sha = _setup(con)
    con.execute(
        "UPDATE p15_event_triggers SET available_at=?,triggered_at=?",
        [(observed + timedelta(minutes=1)).replace(tzinfo=None)] * 2,
    )
    first = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        information_cutoff_at=observed, source_summary={},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("future trigger")),
        clock=lambda: observed,
    )
    later = observed + timedelta(minutes=15)
    second = p15_event_runner.score_pending(
        con, session_date=later.date(), observed_at=later,
        information_cutoff_at=later, source_summary={}, generate=_result,
        clock=lambda: later + timedelta(minutes=1),
    )
    assert first["decisions"] == first["model_calls"] == 0
    assert second["decisions"] == second["model_calls"] == 1


def test_invalid_event_output_is_explicitly_unavailable(con):
    observed, _fact_sha = _setup(con)

    def invalid(payload):
        result = _result(payload)
        result.output["assessments"][0]["ticker"] = "OTHER"
        return result

    result = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=invalid,
        clock=lambda: observed + timedelta(minutes=1),
    )
    assert result["unavailable"] == 1
    assert con.execute(
        "SELECT status FROM p15_event_triggers"
    ).fetchone() == ("unavailable",)
    payload = con.execute("SELECT decision_payload FROM p15_event_decisions").fetchone()[0]
    assert '"action":"unavailable"' in payload


def test_interrupted_event_call_recovers_without_second_model_call(con):
    observed, _fact_sha = _setup(con)
    with pytest.raises(KeyboardInterrupt):
        p15_event_runner.score_pending(
            con, session_date=observed.date(), observed_at=observed,
            source_summary={},
            generate=lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
            clock=lambda: observed + timedelta(minutes=1),
        )
    assert con.execute("SELECT status FROM p15_event_windows").fetchone() == ("running",)
    assert con.execute("SELECT status FROM p15_event_calls").fetchone() == ("running",)

    result = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={"changed": True},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("recalled model")),
    )

    assert result["status"] == "unavailable" and result["unavailable"] == 1
    assert result["replayed"] is True
    assert con.execute("SELECT status FROM p15_event_triggers").fetchone() == (
        "unavailable",
    )


def test_prior_session_interrupted_window_recovers_before_orphan_triggers(con):
    observed, _fact_sha = _setup(con)
    with pytest.raises(KeyboardInterrupt):
        p15_event_runner.score_pending(
            con, session_date=observed.date(), observed_at=observed,
            source_summary={},
            generate=lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
            clock=lambda: observed + timedelta(minutes=1),
        )
    later = observed + timedelta(days=1)

    result = p15_event_runner.score_pending(
        con, session_date=later.date(), observed_at=later, source_summary={},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("recalled model")),
        clock=lambda: later,
    )

    assert result["status"] == "completed" and result["decisions"] == 0
    assert con.execute(
        "SELECT status FROM p15_event_windows ORDER BY observed_at"
    ).fetchall() == [("unavailable",), ("completed",)]
    assert con.execute(
        "SELECT window_id,COUNT(*) FROM p15_event_decisions GROUP BY window_id"
    ).fetchall() == [(f"{p15_event_runner.POLICY_ID}:2024-07-17:10:05", 1)]


def test_stale_trigger_without_window_becomes_explicit_unavailable(con):
    observed, _fact_sha = _setup(con)
    later = observed + timedelta(days=1)
    con.execute(
        "UPDATE p15_event_triggers SET triggered_at=?",
        [(later + timedelta(minutes=1)).replace(tzinfo=None)],
    )

    result = p15_event_runner.score_pending(
        con, session_date=later.date(), observed_at=later,
        information_cutoff_at=later + timedelta(minutes=2),
        source_summary={},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("stale model")),
        clock=lambda: later,
    )

    assert result["decisions"] == 0
    assert con.execute("SELECT status FROM p15_event_triggers").fetchone() == (
        "unavailable",
    )
    assert con.execute(
        "SELECT scoring_status,latency_ms FROM p15_event_decisions"
    ).fetchone() == ("unavailable", 60_000.0)


def test_session_rate_limit_records_excess_without_model_calls(con):
    observed, fact_sha = _setup(con)
    con.execute("DELETE FROM p15_event_triggers")
    con.executemany(
        "INSERT INTO p15_event_triggers VALUES "
        "(?,?,?,'rss','news.headline',?,?,?,?,'scored',NULL,?)",
        [(index, observed.date(), f"OLD{index}", observed - timedelta(minutes=3),
          observed - timedelta(minutes=2), observed.replace(tzinfo=None),
          f"{index:064x}", f"{index + 100:064x}") for index in range(1, 61)],
    )
    con.executemany(
        "INSERT INTO p15_event_decisions VALUES "
        "(?, 'prior', ?, 'OLD', 'news.headline', 'available', '{}', ?, ?, ?, 1)",
        [(index, index, f"{index:064x}", observed.replace(tzinfo=None),
          observed.replace(tzinfo=None)) for index in range(1, 61)],
    )
    con.execute(
        "INSERT INTO p15_event_triggers VALUES "
        "(100,?,'AAA','rss','news.headline',?,?,?,?,'pending',NULL,?)",
        [observed.date(), observed - timedelta(minutes=3), observed - timedelta(minutes=2),
         observed.replace(tzinfo=None), fact_sha, "f" * 64],
    )

    result = p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={},
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("rate limited")),
        clock=lambda: observed,
    )

    assert result["decisions"] == 0 and result["skipped"] == 1
    assert con.execute("SELECT status FROM p15_event_triggers WHERE id=100").fetchone() == (
        "skipped_rate_limit",
    )


def test_event_validator_rejects_exit_for_unheld_and_extra_authority():
    context = [{"trigger_id": 1, "ticker": "AAA", "event_type": "news.headline",
                "held": False}]
    allowed = {1: {"a" * 64}}
    base = {"trigger_id": 1, "ticker": "AAA", "event_type": "news.headline",
            "p_outperform_5": 0.5, "expected_excess_bp_5": 0,
            "expected_excess_bp_10": 0, "action": "exit", "thesis": "Exit.",
            "invalidation": "Changed.", "evidence_ids": ["a" * 64]}
    with pytest.raises(p15_event_runner.EventRunError, match="action"):
        p15_event_runner._validate(
            {"schema_version": 1, "assessments": [base]}, context, allowed
        )
    with pytest.raises(p15_event_runner.EventRunError, match="shape"):
        p15_event_runner._validate(
            {"schema_version": 1, "assessments": [{**base, "order": "buy"}]},
            context, allowed,
        )


def test_event_runner_skips_holidays_and_post_early_close_without_writes(tmp_path):
    for index, observed in enumerate((
        datetime(2026, 12, 25, 15, 5, tzinfo=timezone.utc),
        datetime(2026, 11, 27, 18, 5, tzinfo=timezone.utc),
    )):
        database = tmp_path / f"market-{index}.duckdb"
        assert p15_event_runner.run_database(database, observed_at=observed) == {
            "status": "outside_session", "execution_authority": "none",
        }
        assert not database.exists()


def test_event_runner_operates_without_an_rss_file(tmp_path, monkeypatch):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    db.init_schema(con)
    con.close()
    observed = datetime(2026, 9, 28, 14, 5, tzinfo=timezone.utc)
    monkeypatch.delenv("TRADING_ENGINE_SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(
        p15_event_sources, "scan_intraday",
        lambda _con, *, observed_at: {
            "status": "complete", "universe": 0, "captured": 0,
            "facts": 0, "triggers": 0, "failures": [],
        },
    )

    result = p15_event_runner.run_database(
        database, observed_at=observed, rss_path=tmp_path / "missing.jsonl",
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("no triggers")),
        clock=lambda: observed + timedelta(minutes=1),
    )

    assert result["status"] == "completed" and result["decisions"] == 0
    con = db.connect(database, read_only=True)
    assert con.execute(
        "SELECT evidence_started_at,scanned_through_at FROM p15_event_source_state"
    ).fetchone() == (
        observed.replace(tzinfo=None),
        (observed + timedelta(minutes=1)).replace(tzinfo=None),
    )
    assert con.execute("SELECT COUNT(*) FROM p15_rss_checkpoints").fetchone() == (0,)
    con.close()


def test_sec_rotation_eventually_covers_aliasing_cohort_size():
    names = [f"T{index}" for index in range(131)]
    windows = [(hour, minute) for hour in range(10, 16) for minute in (5, 20, 35, 50)]
    windows = [(9, 35), (9, 50), *windows]
    covered = set()
    for day in (date(2026, 9, 28), date(2026, 9, 29)):
        for hour, minute in windows:
            covered.update(p15_event_runner._sec_names(names, day, hour, minute))
    assert covered == set(names)


def test_event_labels_use_next_common_bar_and_next_session_open(con):
    observed, _fact_sha = _setup(con)
    p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=_result,
        clock=lambda: observed + timedelta(minutes=1),
    )
    con.execute("UPDATE p15_event_decisions SET scoring_status='unavailable'")
    decision_at = observed + timedelta(minutes=1)
    labeled_at = datetime(2024, 7, 18, 21, tzinfo=timezone.utc)
    insert_bars(con, "AAA", SESSIONS[30:32], open_=[100, 106], close=[105, 107],
                high=[106, 108], low=[99, 105])
    insert_bars(con, "SPY", SESSIONS[30:32], open_=[100, 101], close=[101, 102],
                high=[102, 103], low=[99, 100])
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])
    receipt = bitemporal_facts.record_receipt(
        con, source="yfinance", dataset="intraday_quote", endpoint="https://example.test/bars",
        request={}, requested_at=decision_at + timedelta(minutes=4),
        received_at=decision_at + timedelta(minutes=5), http_status=200,
        content_type="application/json", body=b"{}", license_class="research",
    )
    for ticker, opening in (("AAA", 101.0), ("SPY", 100.5)):
        bitemporal_facts.record_fact(
            con, entity_id=ticker, security_id=ticker, fact_type="intraday.ohlcv.5m",
            event_at=decision_at + timedelta(minutes=4), published_at=None,
            available_at=decision_at + timedelta(minutes=5),
            ingested_at=decision_at + timedelta(minutes=5),
            payload={"open": opening, "high": opening + 1, "low": opening - 1,
                     "close": opening, "volume": 10_000}, source="yfinance",
            source_version="test", receipt_sha256=receipt["receipt_sha256"],
        )

    assert p15_event_runner.label_mature(con, labeled_at=labeled_at) == 2
    rows = con.execute(
        "SELECT label_basis,horizon_sessions,entry_at,entry_px,exit_date "
        "FROM p15_event_labels ORDER BY label_basis"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("next_bar", 1), ("next_session_open", 1),
    ]
    assert rows[0][2] == (decision_at + timedelta(minutes=4)).replace(tzinfo=None)
    assert rows[0][3] == 101.0 and rows[0][4] == SESSIONS[30]
    assert rows[1][2] == datetime(2024, 7, 18, 13, 30)
    assert rows[1][3] == 106.0 and rows[1][4] == SESSIONS[31]


def test_missing_next_session_entry_is_terminal_on_late_bar_arrival(con):
    observed, _fact_sha = _setup(con)
    p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=_result,
        clock=lambda: observed + timedelta(minutes=1),
    )
    labeled_at = datetime(2024, 7, 18, 21, tzinfo=timezone.utc)
    insert_bars(con, "SPY", SESSIONS[30:35], open_=100, close=101, high=102, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])

    assert p15_event_runner.label_mature(con, labeled_at=labeled_at) == 3
    assert con.execute(
        "SELECT label_basis,missing_bar_status FROM p15_event_labels "
        "WHERE horizon_sessions=1 ORDER BY label_basis"
    ).fetchall() == [
        ("next_bar", "missing_next_bar_last_available_close"),
        ("next_session_open", "missing_entry_last_available_close"),
    ]
    insert_bars(con, "AAA", [SESSIONS[31]], open_=100, close=101, high=102, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [labeled_at.replace(tzinfo=None), SESSIONS[31]],
    )
    assert p15_event_runner.label_mature(con, labeled_at=labeled_at) == 0
    assert con.execute("SELECT COUNT(*) FROM p15_event_labels").fetchone() == (3,)


def test_missing_next_session_entry_does_not_suppress_valid_next_bar(con):
    observed, _fact_sha = _setup(con)
    p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=_result,
        clock=lambda: observed + timedelta(minutes=1),
    )
    decision_at = observed + timedelta(minutes=1)
    labeled_at = datetime(2024, 7, 18, 21, tzinfo=timezone.utc)
    insert_bars(con, "AAA", [SESSIONS[30]], open_=100, close=101, high=102, low=99)
    insert_bars(con, "SPY", SESSIONS[30:35], open_=100, close=101, high=102, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])
    receipt = bitemporal_facts.record_receipt(
        con, source="yfinance", dataset="intraday_quote", endpoint="https://example.test/bars",
        request={}, requested_at=decision_at + timedelta(minutes=4),
        received_at=decision_at + timedelta(minutes=5), http_status=200,
        content_type="application/json", body=b"{}", license_class="research",
    )
    for ticker, opening in (("AAA", 100.5), ("SPY", 100.25)):
        bitemporal_facts.record_fact(
            con, entity_id=ticker, security_id=ticker, fact_type="intraday.ohlcv.5m",
            event_at=decision_at + timedelta(minutes=4), published_at=None,
            available_at=decision_at + timedelta(minutes=5),
            ingested_at=decision_at + timedelta(minutes=5),
            payload={"open": opening, "high": opening + 1, "low": opening - 1,
                     "close": opening, "volume": 10_000}, source="yfinance",
            source_version="test", receipt_sha256=receipt["receipt_sha256"],
        )

    assert p15_event_runner.label_mature(con, labeled_at=labeled_at) == 3
    assert con.execute(
        "SELECT label_basis,missing_bar_status FROM p15_event_labels "
        "WHERE horizon_sessions=1 ORDER BY label_basis"
    ).fetchall() == [
        ("next_bar", "complete"),
        ("next_session_open", "missing_entry_last_available_close"),
    ]


def test_missing_next_bar_is_not_terminal_before_session_close(con):
    observed, _fact_sha = _setup(con)
    p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=_result,
        clock=lambda: observed + timedelta(minutes=1),
    )
    before_close = observed + timedelta(minutes=2)
    insert_bars(con, "SPY", [SESSIONS[30]], open_=100, close=101, high=102, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='SPY' AND date=?",
        [before_close.replace(tzinfo=None), SESSIONS[30]],
    )

    assert p15_event_runner.label_mature(con, labeled_at=before_close) == 0
    assert con.execute("SELECT COUNT(*) FROM p15_event_labels").fetchone() == (0,)


def test_next_session_intraday_bar_cannot_suppress_missing_next_bar_label(con):
    observed, _fact_sha = _setup(con)
    p15_event_runner.score_pending(
        con, session_date=observed.date(), observed_at=observed,
        source_summary={}, generate=_result,
        clock=lambda: observed + timedelta(minutes=1),
    )
    labeled_at = datetime(2024, 7, 18, 21, tzinfo=timezone.utc)
    insert_bars(con, "SPY", SESSIONS[30:32], open_=100, close=101, high=102, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])
    receipt = bitemporal_facts.record_receipt(
        con, source="yfinance", dataset="intraday_quote", endpoint="https://example.test/bars",
        request={}, requested_at=datetime(2024, 7, 18, 13, 31, tzinfo=timezone.utc),
        received_at=datetime(2024, 7, 18, 13, 32, tzinfo=timezone.utc), http_status=200,
        content_type="application/json", body=b"{}", license_class="research",
    )
    for ticker in ("AAA", "SPY"):
        bitemporal_facts.record_fact(
            con, entity_id=ticker, security_id=ticker, fact_type="intraday.ohlcv.5m",
            event_at=datetime(2024, 7, 18, 13, 30, tzinfo=timezone.utc), published_at=None,
            available_at=datetime(2024, 7, 18, 13, 32, tzinfo=timezone.utc),
            ingested_at=datetime(2024, 7, 18, 13, 32, tzinfo=timezone.utc),
            payload={"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10_000},
            source="yfinance", source_version="test", receipt_sha256=receipt["receipt_sha256"],
        )

    assert p15_event_runner.label_mature(con, labeled_at=labeled_at) == 2
    assert con.execute(
        "SELECT label_basis,missing_bar_status FROM p15_event_labels ORDER BY label_basis"
    ).fetchall() == [
        ("next_bar", "missing_next_bar_last_available_close"),
        ("next_session_open", "missing_entry_last_available_close"),
    ]
