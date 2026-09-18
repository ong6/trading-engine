"""Exact responses retain raw facts and separately corroborate cache observations."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from server import (
    agent_context,
    agent_corporate_action_observations,
    agent_price_observations,
    agent_provider_responses,
)
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _body(
    ticker: str,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: int,
    dividend: float | None = None,
) -> bytes:
    events = {}
    if dividend is not None:
        events["dividends"] = {
            "1780335000": {
                "amount": dividend,
                "date": 1780335000,
            }
        }
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": ticker,
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [1789147800],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [open_price],
                                    "high": [high],
                                    "low": [low],
                                    "close": [close],
                                    "volume": [volume],
                                }
                            ]
                        },
                        "events": events,
                    }
                ],
                "error": None,
            }
        },
        separators=(",", ":"),
    ).encode()


def _response(body: bytes, *, received_at: datetime = NOW) -> agent_provider_responses.Response:
    return agent_provider_responses.Response(
        body=body,
        content_type="application/json;charset=utf-8",
        status_code=200,
        received_at=received_at,
    )


def _file_database(tmp_path, con):
    path = tmp_path / "market.duckdb"
    con.execute(f"ATTACH '{path}' AS target")
    for table in (
        "prices",
        "portfolios",
        "universe",
        "corporate_actions",
        "agent_daily_price_observations",
        "agent_corporate_action_observations",
    ):
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if exists is not None:
            con.execute(f"CREATE TABLE target.{table} AS FROM main.{table}")
    con.execute("DETACH target")
    return path


def test_capture_retains_exact_response_and_links_only_matching_observations(
    con, tmp_path
):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    database = _file_database(tmp_path, con)
    requested = []

    def fetch(ticker, start, end):
        requested.append((ticker, start, end))
        if ticker == "BIL":
            return _response(
                _body(
                    ticker,
                    open_price=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1_000_000,
                    dividend=4.0,
                )
            )
        if ticker == "EFA":
            return _response(
                _body(
                    ticker,
                    open_price=110.0,
                    high=111.0,
                    low=109.0,
                    close=110.0,
                    volume=1_000_000,
                )
            )
        return _response(
            _body(
                ticker,
                open_price=120.0,
                high=121.0,
                low=119.0,
                close=121.0,
                volume=1_000_000,
            )
        )

    result = agent_provider_responses.capture(
        database,
        "dual_momentum",
        market_date,
        fetch=fetch,
        now=lambda: NOW,
    )

    assert result["inserted_responses"] == 3
    assert result["extracted_facts"] == 4
    assert result["inserted_source_observations"] == 4
    # BIL/EFA latest prices and BIL dividend match. SPY close intentionally differs.
    assert result["linked_observations"] == 3
    assert [item[0] for item in requested] == ["BIL", "EFA", "SPY"]
    stored = __import__("duckdb").connect(str(database), read_only=True)
    try:
        status = agent_provider_responses.status(stored)
        body = stored.execute(
            "SELECT response_body FROM agent_provider_responses WHERE ticker = 'BIL'"
        ).fetchone()[0]
        bil_dividend = stored.execute(
            "SELECT observation_sha256 "
            "FROM agent_corporate_action_observations WHERE ticker = 'BIL'"
        ).fetchone()[0]
        evidence = agent_provider_responses.evidence_for_observation(
            stored, bil_dividend
        )
    finally:
        stored.close()
    assert bytes(body) == _body(
        "BIL",
        open_price=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1_000_000,
        dividend=4.0,
    )
    assert status["status"] == "capturing"
    assert status["response_count"] == 3
    assert status["ticker_count"] == 3
    assert status["extracted_fact_count"] == 4
    assert status["link_count"] == 3
    assert status["linked_observation_count"] == 3
    assert status["source_observation_count"] == 4
    assert status["schema_version"] == 2
    assert status["cache_alignment_status"] == (
        "current_cache_value_drift_detected"
    )
    assert status["cache_comparable_source_fact_count"] == 4
    assert status["cache_aligned_fact_count"] == 3
    assert status["cache_mismatched_fact_count"] == 1
    assert status["missing_cache_fact_count"] == 0
    assert status["cache_mismatches_by_dataset"] == {
        "corporate_action": 0,
        "daily_price": 1,
    }
    assert status["cache_alignment_affected_ticker_count"] == 1
    assert status["earliest_cache_mismatch_fact_date"] == "2026-09-11"
    assert status["latest_cache_mismatch_fact_date"] == "2026-09-11"
    assert status["latest_cache_mismatch_receipt_at"] == (
        "2026-09-13T12:00:00Z"
    )
    assert status["cache_mutation_implemented"] is False
    assert status["action_snapshot_count"] == 3
    assert status["action_set_change_count"] == 0
    assert status["action_addition_count"] == 0
    assert status["action_removal_count"] == 0
    assert status["raw_response_bodies_retained"] is True
    assert status["source_publication_time_available"] is False
    assert status["execution_authority"] == "none"
    assert evidence["relationship"] == "later_exact_value_corroboration"
    assert evidence["raw_response_body_retained"] is True
    assert evidence["observation_sha256"] == bil_dividend
    assert len(evidence["response_sha256"]) == 64


def test_exact_receipt_replay_is_idempotent(con, tmp_path):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    database = _file_database(tmp_path, con)

    def fetch(ticker, _start, _end):
        close = {"BIL": 100.0, "EFA": 110.0, "SPY": 120.0}[ticker]
        return _response(
            _body(
                ticker,
                open_price=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
        )

    first = agent_provider_responses.capture(
        database, "dual_momentum", market_date, fetch=fetch, now=lambda: NOW
    )
    second = agent_provider_responses.capture(
        database, "dual_momentum", market_date, fetch=fetch, now=lambda: NOW
    )

    assert first["inserted_responses"] == 3
    assert second["inserted_responses"] == 0
    stored = __import__("duckdb").connect(str(database), read_only=True)
    try:
        assert stored.execute(
            "SELECT COUNT(*) FROM agent_provider_responses"
        ).fetchone() == (3,)
    finally:
        stored.close()


def test_same_body_at_later_receipt_time_is_new_evidence(con, tmp_path):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    database = _file_database(tmp_path, con)
    received_at = NOW

    def fetch(ticker, _start, _end):
        close = {"BIL": 100.0, "EFA": 110.0, "SPY": 120.0}[ticker]
        return _response(
            _body(
                ticker,
                open_price=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            ),
            received_at=received_at,
        )

    agent_provider_responses.capture(
        database, "dual_momentum", market_date, fetch=fetch, now=lambda: received_at
    )
    received_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    second = agent_provider_responses.capture(
        database, "dual_momentum", market_date, fetch=fetch, now=lambda: received_at
    )

    assert second["inserted_responses"] == 3
    stored = __import__("duckdb").connect(str(database), read_only=True)
    try:
        assert stored.execute(
            "SELECT COUNT(*) FROM agent_provider_responses"
        ).fetchone() == (6,)
        assert stored.execute(
            "SELECT COUNT(*) FROM agent_provider_source_observations"
        ).fetchone() == (3,)
    finally:
        stored.close()


def test_changed_response_creates_a_hash_chained_source_revision(con):
    agent_provider_responses.init_schema(con)
    captures = []
    for received_at, close in (
        (NOW, 100.0),
        (datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc), 101.0),
    ):
        body = _body(
            "SPY",
            open_price=100.0,
            high=102.0,
            low=99.0,
            close=close,
            volume=1_000_000,
        )
        receipt, facts = agent_provider_responses._receipt(
            ticker="SPY",
            provider_ticker="SPY",
            start=date(2026, 9, 11),
            end=date(2026, 9, 12),
            requested_at=received_at,
            response=_response(body, received_at=received_at),
        )
        captures.append((receipt, body, facts))

    agent_provider_responses._persist(con, captures)

    rows = con.execute(
        "SELECT observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256 "
        "FROM agent_provider_source_observations "
        "ORDER BY observation_sequence"
    ).fetchall()
    assert [row[:3] for row in rows] == [
        (1, 1, "baseline_source_observation"),
        (2, 2, "source_value_revision"),
    ]
    assert rows[0][3] is None
    assert rows[1][3] == rows[0][4]
    assert agent_provider_responses.status(con)["source_observation_count"] == 2


def test_cache_alignment_uses_newest_source_revision_and_is_read_only(con):
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('SPY', DATE '2026-09-11', 100, 102, 99, 101, 1000000, "
        "'yfinance', TIMESTAMP '2026-09-12 00:00:00')"
    )
    agent_provider_responses.init_schema(con)
    captures = []
    for received_at, close in (
        (NOW, 100.0),
        (datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc), 101.0),
    ):
        body = _body(
            "SPY",
            open_price=100.0,
            high=102.0,
            low=99.0,
            close=close,
            volume=1_000_000,
        )
        receipt, facts = agent_provider_responses._receipt(
            ticker="SPY",
            provider_ticker="SPY",
            start=date(2026, 9, 11),
            end=date(2026, 9, 12),
            requested_at=received_at,
            response=_response(body, received_at=received_at),
        )
        captures.append((receipt, body, facts))
    agent_provider_responses._persist(con, captures)
    before = con.execute("SELECT * FROM prices").fetchall()

    status = agent_provider_responses.status(con)

    assert status["source_observation_count"] == 2
    assert status["cache_comparable_source_fact_count"] == 1
    assert status["cache_aligned_fact_count"] == 1
    assert status["cache_mismatched_fact_count"] == 0
    assert status["missing_cache_fact_count"] == 0
    assert status["cache_alignment_status"] == "current_cache_aligned"
    assert status["cache_alignment_affected_ticker_count"] == 0
    assert status["earliest_cache_mismatch_fact_date"] is None
    assert status["latest_cache_mismatch_fact_date"] is None
    assert status["latest_cache_mismatch_receipt_at"] is None
    assert con.execute("SELECT * FROM prices").fetchall() == before


def test_cache_alignment_separates_mismatch_from_absent_cache_row(con):
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('SPY', DATE '2026-09-11', 100, 101, 99, 100, 1000000, "
        "'yfinance', TIMESTAMP '2026-09-12 00:00:00')"
    )
    agent_provider_responses.init_schema(con)
    captures = []
    for ticker, close in (("SPY", 101.0), ("EFA", 110.0)):
        body = _body(
            ticker,
            open_price=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1_000_000,
        )
        receipt, facts = agent_provider_responses._receipt(
            ticker=ticker,
            provider_ticker=ticker,
            start=date(2026, 9, 11),
            end=date(2026, 9, 12),
            requested_at=NOW,
            response=_response(body),
        )
        captures.append((receipt, body, facts))
    repeated_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    repeated_body = _body(
        "SPY",
        open_price=101.0,
        high=102.0,
        low=100.0,
        close=101.0,
        volume=1_000_000,
    )
    repeated_receipt, repeated_facts = agent_provider_responses._receipt(
        ticker="SPY",
        provider_ticker="SPY",
        start=date(2026, 9, 11),
        end=date(2026, 9, 12),
        requested_at=repeated_at,
        response=_response(repeated_body, received_at=repeated_at),
    )
    captures.append((repeated_receipt, repeated_body, repeated_facts))
    agent_provider_responses._persist(con, captures)

    status = agent_provider_responses.status(con)

    assert status["cache_alignment_status"] == (
        "current_cache_drift_and_missing_rows_detected"
    )
    assert status["cache_comparable_source_fact_count"] == 2
    assert status["cache_aligned_fact_count"] == 0
    assert status["cache_mismatched_fact_count"] == 1
    assert status["missing_cache_fact_count"] == 1
    assert status["cache_mismatches_by_dataset"] == {
        "corporate_action": 0,
        "daily_price": 1,
    }
    assert status["cache_alignment_affected_ticker_count"] == 2
    assert status["earliest_cache_mismatch_fact_date"] == "2026-09-11"
    assert status["latest_cache_mismatch_fact_date"] == "2026-09-11"
    assert status["latest_cache_mismatch_receipt_at"] == (
        "2026-09-14T12:00:00Z"
    )


def test_source_observation_tampering_fails_closed(con):
    agent_provider_responses.init_schema(con)
    body = _body(
        "SPY",
        open_price=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
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
    con.execute(
        "UPDATE agent_provider_source_observations SET value_sha256 = ?",
        ["f" * 64],
    )

    with pytest.raises(
        agent_provider_responses.ProviderResponseError,
        match="source observation is invalid",
    ):
        agent_provider_responses.status(con)


def test_consecutive_response_snapshots_detect_action_removal(con):
    agent_provider_responses.init_schema(con)
    first_body = _body(
        "BIL",
        open_price=100,
        high=101,
        low=99,
        close=100,
        volume=1_000_000,
        dividend=4.0,
    )
    second_body = _body(
        "BIL",
        open_price=100,
        high=101,
        low=99,
        close=100,
        volume=1_000_000,
    )
    captures = []
    for received_at, body in (
        (NOW, first_body),
        (datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc), second_body),
    ):
        receipt, facts = agent_provider_responses._receipt(
            ticker="BIL",
            provider_ticker="BIL",
            start=date(2025, 9, 10),
            end=date(2026, 9, 12),
            requested_at=received_at,
            response=_response(body, received_at=received_at),
        )
        captures.append((receipt, body, facts))
    agent_provider_responses._persist(con, captures)

    status = agent_provider_responses.status(con)

    assert status["action_snapshot_count"] == 2
    assert status["action_set_change_count"] == 1
    assert status["action_addition_count"] == 0
    assert status["action_removal_count"] == 1


def test_shifted_response_windows_compare_actions_in_their_overlap(con):
    agent_provider_responses.init_schema(con)
    first_body = _body(
        "BIL",
        open_price=100,
        high=101,
        low=99,
        close=100,
        volume=1_000_000,
        dividend=4.0,
    )
    second_body = _body(
        "BIL",
        open_price=100,
        high=101,
        low=99,
        close=100,
        volume=1_000_000,
    )
    captures = []
    for start, end, received_at, body in (
        (date(2025, 9, 10), date(2026, 9, 12), NOW, first_body),
        (
            date(2025, 9, 11),
            date(2026, 9, 13),
            datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
            second_body,
        ),
    ):
        receipt, facts = agent_provider_responses._receipt(
            ticker="BIL",
            provider_ticker="BIL",
            start=start,
            end=end,
            requested_at=received_at,
            response=_response(body, received_at=received_at),
        )
        captures.append((receipt, body, facts))
    agent_provider_responses._persist(con, captures)

    status = agent_provider_responses.status(con)

    assert status["action_set_change_count"] == 1
    assert status["action_removal_count"] == 1


def test_context_prefers_verified_exact_response_source_observations(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    body = _body(
        "BIL",
        open_price=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1_000_000,
        dividend=4.0,
    )
    receipt, facts = agent_provider_responses._receipt(
        ticker="BIL",
        provider_ticker="BIL",
        start=date(2025, 9, 10),
        end=date(2026, 9, 12),
        requested_at=NOW,
        response=_response(body),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])

    context = agent_context.build(con, "dual_momentum", "SPY")
    bil = next(
        item
        for item in context["decision_features"]["assets"]
        if item["ticker"] == "BIL"
    )
    calculation = bil["lookbacks"][0]
    end_price = calculation["end_price"]
    dividend = calculation["dividends"][0]

    assert context["schema_version"] == 10
    assert end_price["provider_evidence"]["relationship"] == (
        "exact_response_source_observation"
    )
    assert dividend["provider_evidence"]["relationship"] == (
        "exact_response_source_observation"
    )
    assert end_price["provider_evidence"]["observation_sha256"] == end_price[
        "revision"
    ]["revision_id"]
    assert dividend["provider_evidence"]["observation_sha256"] == dividend[
        "revision"
    ]["revision_id"]
    assert calculation["start_price"]["provider_evidence"] is None
    assert end_price["record"]["raw_retained"] is True
    assert dividend["record"]["raw_retained"] is True
    assert end_price["record"]["raw_sha256"] == end_price[
        "provider_evidence"
    ]["response_sha256"]
    assert dividend["record"]["raw_sha256"] == dividend[
        "provider_evidence"
    ]["response_sha256"]
    assert end_price["source"]["adapter"] == "yahoo_finance.chart_v8"
    assert dividend["source"]["adapter"] == "yahoo_finance.chart_v8"
    assert end_price["source"]["provider_version"] is None
    assert dividend["availability"]["source_published_at"] is None


def test_invalid_response_is_rejected_before_database_write(con, tmp_path):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    database = _file_database(tmp_path, con)

    with pytest.raises(
        agent_provider_responses.ProviderResponseError,
        match="JSON is invalid",
    ):
        agent_provider_responses.capture(
            database,
            "dual_momentum",
            market_date,
            fetch=lambda *_args: _response(b"not-json"),
            now=lambda: NOW,
        )

    stored = __import__("duckdb").connect(str(database), read_only=True)
    try:
        exists = stored.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'agent_provider_responses'"
        ).fetchone()[0]
    finally:
        stored.close()
    assert exists == 0


def test_later_ticker_failure_preserves_prior_verified_receipt(con, tmp_path):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    database = _file_database(tmp_path, con)

    def fetch(ticker, _start, _end):
        if ticker == "EFA":
            return _response(b"not-json")
        close = {"BIL": 100.0, "SPY": 120.0}[ticker]
        return _response(
            _body(
                ticker,
                open_price=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
        )

    with pytest.raises(
        agent_provider_responses.ProviderResponseError,
        match="JSON is invalid",
    ):
        agent_provider_responses.capture(
            database,
            "dual_momentum",
            market_date,
            fetch=fetch,
            now=lambda: NOW,
        )

    stored = __import__("duckdb").connect(str(database), read_only=True)
    try:
        assert stored.execute(
            "SELECT ticker FROM agent_provider_responses"
        ).fetchall() == [("BIL",)]
        assert agent_provider_responses.status(stored)["response_count"] == 1
    finally:
        stored.close()


def test_status_detects_response_body_tampering(con):
    agent_provider_responses.init_schema(con)
    receipt, facts = agent_provider_responses._receipt(
        ticker="SPY",
        provider_ticker="SPY",
        start=date(2026, 9, 11),
        end=date(2026, 9, 12),
        requested_at=NOW,
        response=_response(
            _body(
                "SPY",
                open_price=100,
                high=101,
                low=99,
                close=100,
                volume=1_000_000,
            )
        ),
    )
    agent_provider_responses._persist(
        con, [(receipt, _response(
            _body(
                "SPY",
                open_price=100,
                high=101,
                low=99,
                close=100,
                volume=1_000_000,
            )
        ).body, facts)]
    )
    con.execute(
        "UPDATE agent_provider_responses SET response_body = ?",
        [b'{"tampered":true}'],
    )

    with pytest.raises(
        agent_provider_responses.ProviderResponseError,
        match="receipt is invalid",
    ):
        agent_provider_responses.status(con)
