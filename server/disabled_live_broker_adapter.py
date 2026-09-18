"""Structurally disabled live-capital adapter.

This adapter satisfies the broker-neutral interface so fail-closed behavior can
be tested without a broker SDK, endpoint, credential, account, or usable toggle.
It cannot observe live state and every mutation rejects unconditionally.
"""

from __future__ import annotations

from .broker_contract import (
    BrokerAccount,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
    BrokerStateUnavailable,
    FillBatch,
    LiveTradingDisabled,
    SubmitOrderRequest,
    require_identifier,
)


class DisabledLiveBrokerAdapter(BrokerAdapter):
    """A permanent no-network implementation of the live adapter boundary."""

    @staticmethod
    def _unavailable(account_id: str) -> BrokerStateUnavailable:
        require_identifier(account_id, "account identifier")
        return BrokerStateUnavailable(
            f"live broker state for account {account_id!r} is unavailable: "
            "the adapter is disabled"
        )

    def get_account(self, account_id: str) -> BrokerAccount:
        raise self._unavailable(account_id)

    def get_positions(self, account_id: str) -> tuple[BrokerPosition, ...]:
        raise self._unavailable(account_id)

    def get_open_orders(self, account_id: str) -> tuple[BrokerOrder, ...]:
        raise self._unavailable(account_id)

    def submit_order(self, request: SubmitOrderRequest) -> BrokerOrder:
        if not isinstance(request, SubmitOrderRequest):
            raise TypeError("request must be a SubmitOrderRequest")
        raise LiveTradingDisabled("live order submission is structurally disabled")

    def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        require_identifier(account_id, "account identifier")
        require_identifier(broker_order_id, "broker order identifier")
        raise LiveTradingDisabled("live order cancellation is structurally disabled")

    def stream_fills(
        self,
        account_id: str,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> FillBatch:
        require_identifier(account_id, "account identifier")
        if after is not None:
            require_identifier(after, "fill cursor")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("fill limit must be from 1 through 500")
        raise self._unavailable(account_id)
