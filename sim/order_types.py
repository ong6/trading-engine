"""Account-engine order vocabulary, lifecycle, and authoritative clock rules."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo

from . import nyse

NEW_YORK = ZoneInfo("America/New_York")
MOO_CUTOFF = time(9, 28)
MOC_CUTOFF = time(15, 50)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


class OrderType(StrEnum):
    NEXT_OPEN = "next_open"
    MOO = "moo"
    MOC = "moc"
    MARKET = "market"
    LIMIT = "limit"
    LIMIT_ON_OPEN = "limit_on_open"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


class TimeInForce(StrEnum):
    DAY = "day"


class OrderState(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    REFUSED = "refused"


STATE_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.RECEIVED: frozenset({OrderState.QUEUED, OrderState.REFUSED}),
    OrderState.QUEUED: frozenset({
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.REJECTED,
    }),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.EXPIRED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.REFUSED: frozenset(),
}


class OrderTimingError(ValueError):
    """The engine receipt timestamp falls outside the order's window."""


def can_transition(current: OrderState | str, target: OrderState | str) -> bool:
    return OrderState(target) in STATE_TRANSITIONS[OrderState(current)]


def coarse_status(state: OrderState | str) -> str:
    """Project fine-grained account state onto the legacy sim_orders status."""
    state = OrderState(state)
    if state in {OrderState.RECEIVED, OrderState.QUEUED}:
        return "pending"
    if state is OrderState.FILLED:
        return "filled"
    if state is OrderState.CANCELLED:
        return "cancelled"
    if state is OrderState.EXPIRED:
        return "expired"
    if state is OrderState.REJECTED:
        return "rejected"
    raise ValueError("refused orders have no sim_orders row or coarse status")


def cutoff_at(order_type: OrderType | str, session_date: date) -> datetime | None:
    """Return the inclusive exchange cutoff in UTC, if the type has one."""
    order_type = OrderType(order_type)
    cutoff = None
    if order_type in {OrderType.MOO, OrderType.LIMIT_ON_OPEN}:
        cutoff = moo_cutoff(session_date)
    if order_type is OrderType.MOC:
        cutoff = moc_cutoff(session_date)
    if cutoff is None:
        return None
    return cutoff.astimezone(timezone.utc)


def session_close(session_date: date) -> datetime:
    """Return the timezone-aware scheduled NYSE close for a session."""
    return datetime.combine(session_date, nyse.session_close(session_date), NEW_YORK)


def moc_cutoff(session_date: date) -> datetime:
    """Return the inclusive MOC deadline, ten minutes before the session close."""
    return session_close(session_date) - timedelta(minutes=10)


def moo_cutoff(session_date: date) -> datetime:
    """Return the inclusive 09:28 ET MOO deadline for a session."""
    return datetime.combine(session_date, MOO_CUTOFF, NEW_YORK)


def _previous_session(session_date: date) -> date:
    cursor = session_date.fromordinal(session_date.toordinal() - 1)
    while not nyse.is_session(cursor):
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return cursor


def received_at_allowed(order_type: OrderType | str, session_date: date,
                        received_at: datetime) -> bool:
    """Apply the v2 arrival window using the engine-stamped receipt time."""
    if received_at.utcoffset() is None or not nyse.is_session(session_date):
        return False
    order_type = OrderType(order_type)
    received_et = received_at.astimezone(NEW_YORK)
    previous = _previous_session(session_date)
    prior_close = datetime.combine(previous, nyse.session_close(previous), NEW_YORK)
    if order_type is OrderType.NEXT_OPEN:
        signal_close = session_close(session_date)
        next_open = datetime.combine(nyse.next_session(session_date), MARKET_OPEN, NEW_YORK)
        return signal_close <= received_et < next_open
    if order_type in {OrderType.MOO, OrderType.LIMIT_ON_OPEN}:
        return prior_close <= received_et <= moo_cutoff(session_date)
    if order_type is OrderType.MOC:
        return prior_close <= received_et <= moc_cutoff(session_date)
    if order_type is OrderType.MARKET:
        return (
            datetime.combine(session_date, MARKET_OPEN, NEW_YORK)
            <= received_et
            < session_close(session_date)
        )
    return prior_close <= received_et < session_close(session_date)


def validate_received_at(order_type: OrderType | str, session_date: date,
                         received_at: datetime) -> datetime:
    """Return the authoritative UTC receipt stamp or raise on a closed window."""
    if received_at.utcoffset() is None:
        raise OrderTimingError("received_at must include its timezone")
    if not received_at_allowed(order_type, session_date, received_at):
        raise OrderTimingError("received_at is outside the order acceptance window")
    return received_at.astimezone(timezone.utc)
