"""Independent Nasdaq evidence is exact, append-only, and non-operational."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine import verify_prices
from engine.lib import db
from server import agent_independent_price_evidence
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _body(
    ticker: str,
    *,
    market_date: date = date(2026, 9, 11),
    close: float = 100.0,
    volume: int = 1_000_000,
) -> bytes:
    return json.dumps(
        {
            "data": {
                "symbol": ticker,
                "tradesTable": {
                    "rows": [
                        {
                            "date": market_date.strftime("%m/%d/%Y"),
                            "open": f"${close - 1}",
                            "high": f"${close + 1}",
                            "low": f"${close - 2}",
                            "close": f"${close}",
                            "volume": f"{volume:,}",
                        }
                    ]
                },
            },
            "status": {"rCode": 200, "bCodeMessage": None},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _response(
    ticker: str,
    *,
    close: float = 100.0,
    received_at: datetime = NOW,
) -> verify_prices.NasdaqResponse:
    return verify_prices.NasdaqResponse(
        body=_body(ticker, close=close),
        content_type="application/json; charset=utf-8",
        status_code=200,
        received_at=received_at,
    )


def _database(tmp_path, con, *, prepare: bool = True) -> tuple:
    if prepare:
        fixed_etf_market(con)
        market_date = complete_dual_momentum_history(con)
    else:
        market_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    path = tmp_path / "market.duckdb"
    con.execute(f"ATTACH '{path}' AS target")
    for table in (
        "prices",
        "portfolios",
        "sim_orders",
        "sim_fills",
        "universe",
    ):
        con.execute(f"CREATE TABLE target.{table} AS FROM main.{table}")
    con.execute("DETACH target")
    return path, market_date


def _capture(path, market_date, *, received_at=NOW, closes=None):
    closes = closes or {"BIL": 100.0, "EFA": 110.0, "SPY": 120.0}

    def fetch(ticker, asset_class, start, end):
        assert asset_class == "etf"
        assert start < end == market_date
        return _response(
            ticker,
            close=closes[ticker],
            received_at=received_at,
        )

    return agent_independent_price_evidence.capture(
        path,
        "dual_momentum",
        market_date,
        sessions=5,
        fetch=fetch,
        now=lambda: received_at,
    )


def test_capture_retains_exact_responses_and_never_mutates_operational_state(
    con, tmp_path
):
    path, market_date = _database(tmp_path, con)
    before = duckdb.connect(str(path), read_only=True)
    try:
        price_rows = before.execute("SELECT * FROM prices ORDER BY ticker, date").fetchall()
        order_rows = before.execute("SELECT * FROM sim_orders ORDER BY id").fetchall()
    finally:
        before.close()

    result = _capture(path, market_date)

    assert result == {
        "schema_version": 1,
        "strategy_id": "dual_momentum",
        "market_date": market_date.isoformat(),
        "sessions": 5,
        "required_tickers": ["BIL", "EFA", "SPY"],
        "selected_responses": 3,
        "inserted_responses": 3,
        "inserted_observations": 3,
        "operational_price_mutation": False,
        "quarantine_mutation": False,
        "execution_authority": "none",
    }
    stored = duckdb.connect(str(path), read_only=True)
    try:
        status = agent_independent_price_evidence.status(stored)
        evidence = agent_independent_price_evidence.evidence_for_fact(
            stored,
            ticker="SPY",
            market_date=date(2026, 9, 11),
        )
        assert stored.execute("SELECT * FROM prices ORDER BY ticker, date").fetchall() == price_rows
        assert stored.execute("SELECT * FROM sim_orders ORDER BY id").fetchall() == order_rows
        assert bytes(
            stored.execute(
                "SELECT response_body FROM agent_independent_price_responses "
                "WHERE ticker = 'SPY'"
            ).fetchone()[0]
        ) == _body("SPY", close=120.0)
    finally:
        stored.close()

    assert status["status"] == "capturing"
    assert status["response_count"] == 3
    assert status["observation_count"] == 3
    assert status["ticker_count"] == 3
    assert status["raw_response_bodies_retained"] is True
    assert status["execution_authority"] == "none"
    assert evidence["value"]["close"] == 120.0
    assert evidence["matching_response_count"] == 1
    assert evidence["raw_response_body_retained"] is True
    assert evidence["source_publication_time_available"] is False
    assert evidence["provider_dataset_version"] is None
    assert evidence["execution_authority"] == "none"


def test_repeated_response_is_corroboration_and_changed_value_is_revision(con, tmp_path):
    path, market_date = _database(tmp_path, con)
    first = _capture(path, market_date)
    later = NOW + timedelta(days=1)
    second = _capture(path, market_date, received_at=later)
    latest = later + timedelta(days=1)
    third = _capture(
        path,
        market_date,
        received_at=latest,
        closes={"BIL": 100.0, "EFA": 110.0, "SPY": 121.0},
    )

    assert first["inserted_responses"] == 3
    assert second["inserted_responses"] == 3
    assert third["inserted_responses"] == 3
    stored = duckdb.connect(str(path), read_only=True)
    try:
        evidence = agent_independent_price_evidence.evidence_for_fact(
            stored,
            ticker="SPY",
            market_date=date(2026, 9, 11),
        )
        rows = stored.execute(
            "SELECT observation_sequence, value_revision, classification "
            "FROM agent_independent_price_observations "
            "WHERE ticker = 'SPY' ORDER BY observation_sequence"
        ).fetchall()
    finally:
        stored.close()

    assert rows == [
        (1, 1, "baseline_source_observation"),
        (2, 1, "unchanged_source_observation"),
        (3, 2, "source_value_revision"),
    ]
    assert evidence["value"]["close"] == 121.0
    assert evidence["matching_response_count"] == 1


def test_exact_receipt_replay_is_idempotent(con, tmp_path):
    path, market_date = _database(tmp_path, con)

    first = _capture(path, market_date)
    replay = _capture(path, market_date)

    assert first["inserted_responses"] == 3
    assert replay["inserted_responses"] == 0
    assert replay["inserted_observations"] == 0
    stored = duckdb.connect(str(path), read_only=True)
    try:
        assert agent_independent_price_evidence.status(stored)["response_count"] == 3
    finally:
        stored.close()


def test_capture_rejects_malformed_response_before_schema_write(con, tmp_path):
    path, market_date = _database(tmp_path, con)

    def malformed(_ticker, _asset_class, _start, _end):
        return verify_prices.NasdaqResponse(
            body=b"{}",
            content_type="application/json",
            status_code=200,
            received_at=NOW,
        )

    with pytest.raises(
        agent_independent_price_evidence.IndependentPriceEvidenceError,
        match="independent response body is invalid",
    ):
        agent_independent_price_evidence.capture(
            path,
            "dual_momentum",
            market_date,
            fetch=malformed,
            now=lambda: NOW,
        )

    stored = duckdb.connect(str(path), read_only=True)
    try:
        assert stored.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'agent_independent_price_responses'"
        ).fetchone() is None
    finally:
        stored.close()


def test_tampered_raw_response_or_chain_fails_closed(con, tmp_path):
    path, market_date = _database(tmp_path, con)
    _capture(path, market_date)
    stored = db.connect(path)
    try:
        stored.execute(
            "UPDATE agent_independent_price_responses SET response_body = ? "
            "WHERE ticker = 'SPY'",
            [b"{}"],
        )
        with pytest.raises(
            agent_independent_price_evidence.IndependentPriceEvidenceError,
            match="independent response body is invalid",
        ):
            agent_independent_price_evidence.status(stored)
    finally:
        stored.close()

    second = tmp_path / "second"
    second.mkdir()
    path_two, market_date = _database(second, con, prepare=False)
    _capture(path_two, market_date)
    stored = db.connect(path_two)
    try:
        stored.execute(
            "UPDATE agent_independent_price_observations "
            "SET previous_observation_sha256 = ? WHERE ticker = 'SPY'",
            ["f" * 64],
        )
        with pytest.raises(
            agent_independent_price_evidence.IndependentPriceEvidenceError,
            match="stored independent observation",
        ):
            agent_independent_price_evidence.status(stored)
    finally:
        stored.close()


def test_deleted_derived_fact_fails_receipt_completeness_check(con, tmp_path):
    path, market_date = _database(tmp_path, con)
    _capture(path, market_date)
    stored = db.connect(path)
    try:
        stored.execute(
            "DELETE FROM agent_independent_price_observations "
            "WHERE ticker = 'SPY'"
        )
        with pytest.raises(
            agent_independent_price_evidence.IndependentPriceEvidenceError,
            match="fact set is incomplete",
        ):
            agent_independent_price_evidence.status(stored)
    finally:
        stored.close()


def test_out_of_scope_response_fact_is_rejected(con, tmp_path):
    path, market_date = _database(tmp_path, con)

    def out_of_scope(ticker, _asset_class, _start, _end):
        return verify_prices.NasdaqResponse(
            body=_body(
                ticker,
                market_date=market_date + timedelta(days=1),
            ),
            content_type="application/json",
            status_code=200,
            received_at=NOW,
        )

    with pytest.raises(
        agent_independent_price_evidence.IndependentPriceEvidenceError,
        match="exceed request scope",
    ):
        agent_independent_price_evidence.capture(
            path,
            "dual_momentum",
            market_date,
            fetch=out_of_scope,
            now=lambda: NOW,
        )
