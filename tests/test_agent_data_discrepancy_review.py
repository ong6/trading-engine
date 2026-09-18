"""Source/cache discrepancy packets are exact, read-only, and non-authorizing."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from engine import verify_prices
from engine.lib.provenance import canonical_sha256
from server import (
    agent_data_discrepancy_review,
    agent_independent_price_evidence,
    agent_provider_responses,
)
from tests.test_agent_provider_responses import _body, _response

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
FACT_DATE = date(2026, 9, 11)


def _price(con, *, close: float = 100.0) -> None:
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('SPY', ?, 100, 102, 99, ?, 1000000, 'yfinance', ?)",
        [FACT_DATE, close, datetime(2026, 9, 12)],
    )


def _capture(
    con,
    *,
    close: float,
    received_at: datetime = NOW,
) -> None:
    agent_provider_responses.init_schema(con)
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
        start=FACT_DATE,
        end=date(2026, 9, 12),
        requested_at=received_at,
        response=_response(body, received_at=received_at),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])


def _capture_dividend(
    con,
    *,
    dividend: float,
    received_at: datetime = NOW,
) -> None:
    agent_provider_responses.init_schema(con)
    body = _body(
        "BIL",
        open_price=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1_000_000,
        dividend=dividend,
    )
    receipt, facts = agent_provider_responses._receipt(
        ticker="BIL",
        provider_ticker="BIL",
        start=date(2026, 5, 1),
        end=date(2026, 9, 12),
        requested_at=received_at,
        response=_response(body, received_at=received_at),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])


def _capture_independent(
    con,
    *,
    close: float,
    received_at: datetime = NOW,
) -> None:
    body = __import__("json").dumps(
        {
            "data": {
                "symbol": "SPY",
                "tradesTable": {
                    "rows": [
                        {
                            "date": "09/11/2026",
                            "open": "$100",
                            "high": "$102",
                            "low": "$99",
                            "close": f"${close}",
                            "volume": "1,000,000",
                        }
                    ]
                },
            },
            "status": {"rCode": 200, "bCodeMessage": None},
        },
        separators=(",", ":"),
    ).encode()
    response = verify_prices.NasdaqResponse(
        body=body,
        content_type="application/json",
        status_code=200,
        received_at=received_at,
    )
    receipt, facts = agent_independent_price_evidence._receipt(
        ticker="SPY",
        asset_class="etf",
        period_start=FACT_DATE,
        period_end=FACT_DATE,
        requested_at=received_at,
        response=response,
    )
    agent_independent_price_evidence._persist(con, receipt, body, facts)


def _build(con, *, generated_at: datetime | None = None) -> dict:
    return agent_data_discrepancy_review.build(
        con,
        dataset="daily_price",
        ticker="SPY",
        fact_date=FACT_DATE,
        kind="daily_price",
        generated_at=generated_at or NOW + timedelta(seconds=1),
    )


def _counts(con) -> dict[str, int]:
    return {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "prices",
            "agent_provider_responses",
            "agent_provider_response_links",
            "agent_provider_source_observations",
            "sim_orders",
            "sim_fills",
        )
    }


def _rehash(packet: dict) -> None:
    body = {
        key: value
        for key, value in packet.items()
        if key != "review_packet_sha256"
    }
    packet["review_packet_sha256"] = canonical_sha256(body)


def test_build_and_retained_verify_bind_one_drift_without_mutation(con):
    _price(con)
    _capture(con, close=101.0)
    before = _counts(con)

    packet = _build(con)

    assert packet["schema_version"] == 2
    assert packet["status"] == "awaiting_operator_adjudication"
    assert packet["review_scope"] == (
        "one_exact_provider_source_cache_discrepancy"
    )
    assert packet["discrepancy_classification"] == "current_cache_value_drift"
    assert packet["source_observation"]["value"]["close"] == 101.0
    assert packet["current_cache"]["value"]["close"] == 100.0
    assert packet["differences"] == [
        {"field": "close", "cache_value": 100.0, "source_value": 101.0}
    ]
    assert packet["required_operator_decision"] == [
        "accept_source_revision_via_separate_guarded_repair",
        "retain_current_cache_with_justification",
        "quarantine_ticker",
        "defer_pending_more_evidence",
    ]
    assert packet["automatic_recommendation"] is None
    assert packet["decision_present"] is False
    assert packet["cache_mutation_implemented"] is False
    assert packet["quarantine_mutation_implemented"] is False
    assert packet["execution_authority"] == "none"
    assert packet["independent_evidence"] == {
        "status": "unavailable",
        "source": "nasdaq",
        "raw_response_body_retained": False,
        "execution_authority": "none",
    }
    assert agent_data_discrepancy_review.verify_retained(
        con,
        packet,
        reviewed_at=NOW + timedelta(seconds=2),
    ) == packet
    assert _counts(con) == before


def test_discrepancy_list_is_bounded_hash_only_and_read_only(con):
    _price(con)
    _capture(con, close=101.0)
    before = _counts(con)

    result = agent_data_discrepancy_review.discrepancies(con)

    assert result["status"] == "discrepancies_detected"
    assert result["matching_count"] == 1
    assert result["limit"] == 100
    assert result["truncated"] is False
    assert result["market_values_exposed"] is False
    assert result["automatic_recommendation"] is None
    assert result["execution_authority"] == "none"
    assert result["items"][0]["dataset"] == "daily_price"
    assert result["items"][0]["ticker"] == "SPY"
    assert result["items"][0]["fact_date"] == "2026-09-11"
    assert result["items"][0]["classification"] == "current_cache_value_drift"
    assert set(result["items"][0]) == {
        "dataset",
        "ticker",
        "fact_date",
        "kind",
        "classification",
        "source_value_sha256",
        "cache_value_sha256",
        "source_observation_sha256",
        "source_fetched_at",
        "discrepancy_sha256",
    }
    assert _counts(con) == before


def test_discrepancy_list_reports_total_and_truncation(monkeypatch, con):
    _price(con)
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('EFA', ?, 100, 102, 99, 100, 1000000, 'yfinance', ?)",
        [FACT_DATE, datetime(2026, 9, 12)],
    )
    _capture(con, close=101.0)
    body = _body(
        "EFA",
        open_price=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1_000_000,
    )
    receipt, facts = agent_provider_responses._receipt(
        ticker="EFA",
        provider_ticker="EFA",
        start=FACT_DATE,
        end=date(2026, 9, 12),
        requested_at=NOW,
        response=_response(body),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])
    monkeypatch.setattr(
        agent_data_discrepancy_review,
        "DISCREPANCY_LIST_LIMIT",
        1,
    )

    result = agent_data_discrepancy_review.discrepancies(con)

    assert result["matching_count"] == 2
    assert result["limit"] == 1
    assert result["truncated"] is True
    assert len(result["items"]) == 1


def test_build_rejects_aligned_fact(con):
    _price(con)
    _capture(con, close=100.0)

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="matches the current cache",
    ):
        _build(con)


def test_build_selects_newest_source_revision(con):
    _price(con)
    _capture(con, close=101.0)
    later = NOW + timedelta(days=1)
    _capture(con, close=102.0, received_at=later)

    packet = _build(con, generated_at=later + timedelta(seconds=1))

    assert packet["source_observation"]["observation_sequence"] == 2
    assert packet["source_observation"]["value_revision"] == 2
    assert packet["source_observation"]["classification"] == (
        "source_value_revision"
    )
    assert packet["differences"] == [
        {"field": "close", "cache_value": 100.0, "source_value": 102.0}
    ]


def test_packet_counts_repeated_confirmation_of_current_source_value(con):
    _price(con)
    _capture(con, close=101.0)
    later = NOW + timedelta(days=1)
    _capture(con, close=101.0, received_at=later)

    packet = _build(con, generated_at=later + timedelta(seconds=1))

    assert packet["source_observation"]["observation_sequence"] == 1
    assert packet["source_confirmations"]["matching_response_count"] == 2
    assert packet["source_confirmations"]["latest_received_at"] == (
        "2026-09-14T12:00:00Z"
    )
    assert len(packet["source_confirmations"]["latest_receipt_sha256"]) == 64
    assert len(packet["source_confirmations"]["latest_response_sha256"]) == 64


def test_packet_binds_exact_independent_evidence_and_compares_both_values(con):
    _price(con)
    _capture(con, close=101.0)
    _capture_independent(con, close=100.0)

    packet = _build(con, generated_at=NOW + timedelta(seconds=1))
    evidence = packet["independent_evidence"]

    assert evidence["status"] == "exact_raw_response_fact"
    assert evidence["source"] == "nasdaq"
    assert evidence["value"]["close"] == 100.0
    assert evidence["source_value_matches"] is False
    assert evidence["cache_value_matches"] is True
    assert evidence["source_value_comparison"] == {
        "comparable": True,
        "ohlc_agree_within_registered_tolerance": False,
        "tolerance_bp": 10.0,
        "tolerance_abs_usd": 0.01,
        "maximum_ohlc_difference_bp": 99.009901,
        "volume_difference_pct": 0.0,
    }
    assert evidence["cache_value_comparison"] == {
        "comparable": True,
        "ohlc_agree_within_registered_tolerance": True,
        "tolerance_bp": 10.0,
        "tolerance_abs_usd": 0.01,
        "maximum_ohlc_difference_bp": 0.0,
        "volume_difference_pct": 0.0,
    }
    assert evidence["source_differences"] == [
        {
            "field": "close",
            "independent_value": 100.0,
            "yahoo_source_value": 101.0,
        }
    ]
    assert evidence["cache_differences"] == []
    assert evidence["matching_response_count"] == 1
    assert evidence["raw_response_body_retained"] is True
    assert evidence["execution_authority"] == "none"
    assert agent_data_discrepancy_review.verify_retained(
        con,
        packet,
        reviewed_at=NOW + timedelta(seconds=2),
    ) == packet


def test_retained_verify_rejects_changed_independent_evidence(con):
    _price(con)
    _capture(con, close=101.0)
    _capture_independent(con, close=100.0)
    packet = _build(con, generated_at=NOW + timedelta(seconds=1))
    _capture_independent(
        con,
        close=102.0,
        received_at=NOW + timedelta(seconds=2),
    )

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="precedes independent evidence",
    ):
        agent_data_discrepancy_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=3),
        )


def test_build_rejects_independent_evidence_from_the_future(con):
    _price(con)
    _capture(con, close=101.0)
    _capture_independent(
        con,
        close=100.0,
        received_at=NOW + timedelta(seconds=2),
    )

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="precedes independent evidence",
    ):
        _build(con, generated_at=NOW + timedelta(seconds=1))


def test_missing_cache_row_is_explicit(con):
    _capture(con, close=101.0)

    packet = _build(con)

    assert packet["discrepancy_classification"] == "missing_current_cache_row"
    assert packet["current_cache"] is None
    assert {item["field"] for item in packet["differences"]} == {
        "close",
        "high",
        "low",
        "market_date",
        "open",
        "source",
        "ticker",
        "volume",
    }


def test_corporate_action_discrepancy_uses_exact_action_shape(con):
    con.execute(
        "CREATE TABLE corporate_actions ("
        "ticker VARCHAR, ex_date DATE, kind VARCHAR, value DOUBLE, "
        "source VARCHAR, fetched_at TIMESTAMP)"
    )
    con.execute(
        "INSERT INTO corporate_actions VALUES "
        "('BIL', DATE '2026-06-01', 'dividend', 3.5, 'yfinance', "
        "TIMESTAMP '2026-09-12 00:00:00')"
    )
    _capture_dividend(con, dividend=4.0)

    packet = agent_data_discrepancy_review.build(
        con,
        dataset="corporate_action",
        ticker="BIL",
        fact_date=date(2026, 6, 1),
        kind="dividend",
        generated_at=NOW + timedelta(seconds=1),
    )

    assert packet["discrepancy_classification"] == "current_cache_value_drift"
    assert packet["differences"] == [
        {"field": "value", "cache_value": 3.5, "source_value": 4.0}
    ]
    assert agent_data_discrepancy_review.verify(packet) == packet


def test_retained_verify_rejects_rehashed_forgery_and_cache_change(con):
    _price(con)
    _capture(con, close=101.0)
    packet = _build(con)
    forged = deepcopy(packet)
    forged["source_observation"]["value"]["close"] = 102.0
    forged["source_observation"]["value_sha256"] = canonical_sha256(
        forged["source_observation"]["value"]
    )
    forged["differences"] = [
        {"field": "close", "cache_value": 100.0, "source_value": 102.0}
    ]
    _rehash(forged)

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="does not match retained evidence",
    ):
        agent_data_discrepancy_review.verify_retained(
            con,
            forged,
            reviewed_at=NOW + timedelta(seconds=2),
        )

    con.execute(
        "UPDATE prices SET close = 99 WHERE ticker = 'SPY' AND date = ?",
        [FACT_DATE],
    )
    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="does not match retained evidence",
    ):
        agent_data_discrepancy_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=2),
        )


def test_retained_verify_rejects_expiry_and_tampered_source_ledger(con):
    _price(con)
    _capture(con, close=101.0)
    packet = _build(con)

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="expired",
    ):
        agent_data_discrepancy_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW
            + timedelta(
                seconds=agent_data_discrepancy_review.REVIEW_TTL_SECONDS + 1
            ),
        )

    con.execute(
        "UPDATE agent_provider_source_observations SET value_sha256 = ?",
        ["f" * 64],
    )
    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match="source observation is invalid",
    ):
        agent_data_discrepancy_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("ticker",), "spy", "identity"),
        (("required_operator_decision",), [], "packet is invalid"),
        (("source_confirmations", "matching_response_count"), 0, "packet is invalid"),
        (("differences",), [], "packet is invalid"),
        (("decision_present",), True, "packet is invalid"),
        (("cache_mutation_implemented",), True, "packet is invalid"),
        (("execution_authority",), "paper", "packet is invalid"),
    ],
)
def test_verify_rejects_rehashed_malformed_or_authorizing_packet(
    con, path, value, message
):
    _price(con)
    _capture(con, close=101.0)
    packet = _build(con)
    target = packet
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _rehash(packet)

    with pytest.raises(
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        match=message,
    ):
        agent_data_discrepancy_review.verify(packet)


def test_module_has_no_writer_or_authority_surface():
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
    }.isdisjoint(vars(agent_data_discrepancy_review))
