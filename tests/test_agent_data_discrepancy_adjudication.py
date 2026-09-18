"""Data-discrepancy adjudication is append-only and operationally inert."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_data_discrepancy_adjudication,
    agent_data_discrepancy_review,
    agent_provider_responses,
)
from tests.test_agent_provider_responses import _body, _response

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
FACT_DATE = date(2026, 9, 11)


def _setup(con, *, ticker: str = "SPY", cache_close: float = 100.0) -> dict:
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES (?, ?, 100, 102, 99, ?, 1000000, 'yfinance', ?)",
        [ticker, FACT_DATE, cache_close, datetime(2026, 9, 12)],
    )
    agent_provider_responses.init_schema(con)
    body = _body(
        ticker,
        open_price=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1_000_000,
    )
    receipt, facts = agent_provider_responses._receipt(
        ticker=ticker,
        provider_ticker=ticker,
        start=FACT_DATE,
        end=date(2026, 9, 12),
        requested_at=NOW,
        response=_response(body),
    )
    agent_provider_responses._persist(con, [(receipt, body, facts)])
    return agent_data_discrepancy_review.build(
        con,
        dataset="daily_price",
        ticker=ticker,
        fact_date=FACT_DATE,
        kind="daily_price",
        generated_at=NOW + timedelta(seconds=1),
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


def _record(con, packet: dict, **overrides) -> dict:
    values = {
        "decision_id": "decision-spy-2026-09-11-v1",
        "disposition": "defer_pending_more_evidence",
        "operator_id": "operator-jun",
        "justification": "Await another independent retained observation.",
        "decided_at": NOW + timedelta(seconds=2),
    }
    values.update(overrides)
    return agent_data_discrepancy_adjudication.record_decision(
        con,
        packet,
        **values,
    )


def test_record_is_hash_chained_exact_replay_and_operationally_inert(con):
    packet = _setup(con)
    before = _counts(con)

    first = _record(con, packet)
    replay = _record(
        con,
        packet,
        decided_at=NOW + timedelta(seconds=3),
    )

    assert replay == first
    assert first["schema_version"] == 1
    assert first["decision_sequence"] == 1
    assert first["review_packet_sha256"] == packet["review_packet_sha256"]
    assert first["disposition"] == "defer_pending_more_evidence"
    assert first["operational_effect"] == (
        "record_only_separate_follow_up_required"
    )
    assert first["cache_mutation_implemented"] is False
    assert first["quarantine_mutation_implemented"] is False
    assert first["execution_authority"] == "none"
    assert first["decision_sha256"] == canonical_sha256(
        {
            key: value
            for key, value in first.items()
            if key != "decision_sha256"
        }
    )
    assert _counts(con) == before
    assert con.execute(
        "SELECT COUNT(*) FROM agent_data_discrepancy_decisions"
    ).fetchone() == (1,)

    status = agent_data_discrepancy_adjudication.status(con)
    assert status["decision_count"] == 1
    assert status["decisions_by_disposition"][
        "defer_pending_more_evidence"
    ] == 1
    assert status["latest_decision_sha256"] == first["decision_sha256"]
    assert "justification" not in status
    assert status["execution_authority"] == "none"


def test_exact_replay_survives_packet_expiry_and_later_cache_change(con):
    packet = _setup(con)
    first = _record(con, packet)
    con.execute(
        "UPDATE prices SET close = 99 WHERE ticker = 'SPY' AND date = ?",
        [FACT_DATE],
    )

    replay = _record(
        con,
        packet,
        decided_at=NOW
        + timedelta(
            seconds=agent_data_discrepancy_review.REVIEW_TTL_SECONDS + 2
        ),
    )

    assert replay == first
    assert con.execute(
        "SELECT COUNT(*) FROM agent_data_discrepancy_decisions"
    ).fetchone() == (1,)


def test_two_distinct_states_form_one_global_chain(con):
    first_packet = _setup(con, ticker="SPY")
    first = _record(con, first_packet)
    second_packet = _setup(con, ticker="EFA")
    second = _record(
        con,
        second_packet,
        decision_id="decision-efa-2026-09-11-v1",
        disposition="retain_current_cache_with_justification",
        justification="The cache remains authoritative pending source metadata.",
        decided_at=NOW + timedelta(seconds=3),
    )

    assert second["decision_sequence"] == 2
    assert second["prior_decision_sha256"] == first["decision_sha256"]
    assert agent_data_discrepancy_adjudication.status(con)[
        "latest_decision_sha256"
    ] == second["decision_sha256"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"decision_id": "different-id"}, "conflicts"),
        (
            {"disposition": "quarantine_ticker"},
            "conflicts",
        ),
        ({"operator_id": "another-operator"}, "conflicts"),
        ({"justification": "Different rationale."}, "conflicts"),
    ],
)
def test_state_or_decision_id_cannot_be_reused_for_a_conflicting_decision(
    con, overrides, message
):
    packet = _setup(con)
    _record(con, packet)

    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match=message,
    ):
        _record(
            con,
            packet,
            decided_at=NOW + timedelta(seconds=3),
            **overrides,
        )

    assert con.execute(
        "SELECT COUNT(*) FROM agent_data_discrepancy_decisions"
    ).fetchone() == (1,)


def test_forged_stale_or_changed_evidence_aborts_without_schema_or_event(con):
    packet = _setup(con)
    forged = deepcopy(packet)
    forged["source_observation"]["value"]["close"] = 102.0
    forged["source_observation"]["value_sha256"] = canonical_sha256(
        forged["source_observation"]["value"]
    )
    forged["differences"][0]["source_value"] = 102.0
    forged["review_packet_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in forged.items()
            if key != "review_packet_sha256"
        }
    )

    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="does not match retained evidence",
    ):
        _record(con, forged)

    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_data_discrepancy_decisions'"
    ).fetchone() == (0,)

    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="expired",
    ):
        _record(
            con,
            packet,
            decided_at=NOW
            + timedelta(
                seconds=agent_data_discrepancy_review.REVIEW_TTL_SECONDS + 2
            ),
        )

    con.execute(
        "UPDATE prices SET close = 99 WHERE ticker = 'SPY' AND date = ?",
        [FACT_DATE],
    )
    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="does not match retained evidence",
    ):
        _record(con, packet)

    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_data_discrepancy_decisions'"
    ).fetchone() == (0,)


def test_invalid_input_fails_before_creating_schema(con):
    packet = _setup(con)

    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="disposition",
    ):
        _record(con, packet, disposition="accept_anything")
    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="operator identifier",
    ):
        _record(con, packet, operator_id="operator with spaces")
    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="justification",
    ):
        _record(con, packet, justification="")

    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_data_discrepancy_decisions'"
    ).fetchone() == (0,)


def test_tampered_or_incompatible_retained_ledger_fails_closed(con):
    packet = _setup(con)
    _record(con, packet)
    con.execute(
        "UPDATE agent_data_discrepancy_decisions "
        "SET justification = 'tampered'"
    )
    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="stored data discrepancy decision is invalid",
    ):
        agent_data_discrepancy_adjudication.status(con)

    con.execute("DROP TABLE agent_data_discrepancy_decisions")
    con.execute(
        "CREATE TABLE agent_data_discrepancy_decisions "
        "(decision_sequence VARCHAR)"
    )
    with pytest.raises(
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        match="schema is invalid",
    ):
        agent_data_discrepancy_adjudication.status(con)


def test_module_has_no_remediation_or_authority_surface():
    assert {
        "activate",
        "authorize",
        "grant",
        "quarantine",
        "repair",
        "submit",
        "update_cache",
    }.isdisjoint(vars(agent_data_discrepancy_adjudication))
