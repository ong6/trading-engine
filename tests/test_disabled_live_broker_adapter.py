"""The live-capital adapter remains structurally unusable."""

from __future__ import annotations

from datetime import date

import pytest

from server.broker_contract import (
    BrokerAdapter,
    BrokerStateUnavailable,
    LiveTradingDisabled,
    SubmitOrderRequest,
)
from server.disabled_live_broker_adapter import DisabledLiveBrokerAdapter


def _request():
    return SubmitOrderRequest(
        idempotency_key="live-disabled-test",
        account_id="live-disabled",
        symbol="SPY",
        side="buy",
        quantity=1.0,
        signal_date=date(2026, 9, 11),
    )


def test_disabled_live_adapter_implements_contract_without_configuration():
    adapter = DisabledLiveBrokerAdapter()

    assert isinstance(adapter, BrokerAdapter)
    assert vars(adapter) == {}


@pytest.mark.parametrize(
    "operation",
    [
        lambda adapter: adapter.get_account("live-disabled"),
        lambda adapter: adapter.get_positions("live-disabled"),
        lambda adapter: adapter.get_open_orders("live-disabled"),
        lambda adapter: adapter.stream_fills("live-disabled"),
    ],
)
def test_live_state_reads_fail_as_unavailable(operation):
    with pytest.raises(BrokerStateUnavailable, match="adapter is disabled"):
        operation(DisabledLiveBrokerAdapter())


def test_live_submission_always_fails_closed():
    with pytest.raises(LiveTradingDisabled, match="structurally disabled"):
        DisabledLiveBrokerAdapter().submit_order(_request())


def test_live_cancellation_always_fails_closed():
    with pytest.raises(LiveTradingDisabled, match="structurally disabled"):
        DisabledLiveBrokerAdapter().cancel_order(
            "live-disabled",
            "live-order:1",
        )


def test_disabled_adapter_has_no_network_or_credential_imports():
    source_names = set(DisabledLiveBrokerAdapter.get_account.__globals__)
    assert source_names.isdisjoint(
        {
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
        }
    )
