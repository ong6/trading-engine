"""Order enums, lifecycle projection, and receipt cutoffs."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from sim.order_types import (
    OrderState,
    OrderTimingError,
    OrderType,
    Side,
    TimeInForce,
    can_transition,
    coarse_status,
    cutoff_at,
    received_at_allowed,
    validate_received_at,
)

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 10, 12)


def test_wire_enums_are_stable_strings():
    assert {value.value for value in OrderType} == {
        "next_open", "moo", "moc", "market", "limit", "limit_on_open",
    }
    assert {value.value for value in Side} == {"buy", "sell", "short", "cover"}
    assert list(TimeInForce) == [TimeInForce.DAY]


def test_state_machine_and_legacy_status_projection():
    assert can_transition("received", "queued")
    assert can_transition("received", "refused")
    assert can_transition("queued", "filled")
    assert not can_transition("filled", "cancelled")
    assert coarse_status(OrderState.RECEIVED) == "pending"
    assert coarse_status(OrderState.QUEUED) == "pending"
    assert coarse_status(OrderState.EXPIRED) == "rejected"
    assert coarse_status(OrderState.CANCELLED) == "cancelled"


@pytest.mark.parametrize(
    "order_type,accepted,rejected",
    [
        ("moo", datetime(2026, 10, 12, 9, 28, tzinfo=ET),
         datetime(2026, 10, 12, 9, 28, 1, tzinfo=ET)),
        ("moc", datetime(2026, 10, 12, 15, 50, tzinfo=ET),
         datetime(2026, 10, 12, 15, 50, 1, tzinfo=ET)),
    ],
)
def test_auction_cutoffs_are_inclusive(order_type, accepted, rejected):
    assert received_at_allowed(order_type, SESSION, accepted)
    assert not received_at_allowed(order_type, SESSION, rejected)
    assert validate_received_at(order_type, SESSION, accepted).tzinfo is not None
    with pytest.raises(OrderTimingError):
        validate_received_at(order_type, SESSION, rejected)


def test_cutoffs_are_eastern_instants_reported_in_utc():
    assert cutoff_at("moo", SESSION) == datetime(2026, 10, 12, 13, 28, tzinfo=ZoneInfo("UTC"))
    assert cutoff_at("moc", SESSION) == datetime(2026, 10, 12, 19, 50, tzinfo=ZoneInfo("UTC"))
    assert cutoff_at("market", SESSION) is None


def test_next_open_and_intraday_windows():
    assert received_at_allowed(
        "next_open", SESSION, datetime(2026, 10, 12, 16, 0, tzinfo=ET),
    )
    assert not received_at_allowed(
        "next_open", SESSION, datetime(2026, 10, 13, 9, 30, tzinfo=ET),
    )
    assert received_at_allowed(
        "market", SESSION, datetime(2026, 10, 12, 10, 17, tzinfo=ET),
    )
    assert not received_at_allowed(
        "market", SESSION, datetime(2026, 10, 12, 16, 0, tzinfo=ET),
    )
