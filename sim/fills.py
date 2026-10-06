"""The fill model — honest by design (execution design §2).

An order created from a close-of-day-t signal fills at the day t+1 OPEN. There
are **no same-bar fills, ever**: ``fill_date > signal_date`` is enforced in
exactly one place (``attempt_fill``) and is the single look-ahead guard. The
guard raises unconditionally, including when Python runs with optimization.

The historical compatibility profile, ``baseline_v1``, uses:

    slippage_bps = max(half_spread_bps, 5) + 5          # +5/side = 10bp round-trip

    half_spread_bps (from 60-bar median dollar volume, conservative tiers):
        >= $50M -> 5 bp
        >= $20M -> 10 bp
        >= $5M  -> 15 bp
        else    -> 25 bp

    buys  fill at open * (1 + slippage_bps/1e4)
    sells fill at open * (1 - slippage_bps/1e4)

Other named profiles may change spread, adverse movement, participation impact,
fees, and the capacity ceiling; their full payload is serialized in research
artifacts. Under ``baseline_v1``, order notional (qty * open) may not exceed 1% of the name's
60-bar median daily dollar volume → the order is REJECTED (partial fills are not
modeled in v1). If the fill-date bar is missing (halt / delisting), has a non-positive open,
or printed zero volume (nobody traded — dead quotes from the feed look exactly
like this) the order stays pending; after 3 trading days with still no
tradeable bar it rejects as 'no_bar'. A bar is never invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import duckdb

from . import bar_sources, calendar, execution, nyse, order_types

OrderType = order_types.OrderType

MEDVOL_BARS = 60          # lookback for median dollar volume
# Compatibility alias. New code reads this from the named execution profile.
MAX_NOTIONAL_FRAC = execution.BASELINE.max_participation
PENDING_MAX_DAYS = 3      # trading days a bar may be missing before 'no_bar'


@dataclass
class FillResult:
    """Outcome of attempting to fill one order on a given date."""
    status: str                 # 'filled' | 'rejected' | 'pending'
    reject_reason: str | None = None
    open_px: float | None = None
    fill_px: float | None = None
    slippage_bps: float | None = None
    cost_bps: float | None = None
    median_dollar_vol: float | None = None
    participation: float | None = None
    impact_bps: float | None = None
    fee_bps: float | None = None
    execution_profile: str | None = None
    fill_kind: str | None = None
    price_source: str | None = None
    bar_ref: str | None = None
    fill_ts: datetime | None = None
    reference_px: float | None = None


def median_dollar_vol(
    con: duckdb.DuckDBPyConnection, ticker: str, as_of: date, bars: int = MEDVOL_BARS
) -> float | None:
    """Median of close*volume over the last `bars` sessions STRICTLY BEFORE
    `as_of`.

    The window excludes `as_of` itself (date < as_of): `as_of` is the fill date,
    so including its own close×volume in the liquidity cap and slippage tier would
    consume information from the bar being traded — a small look-ahead. Returns
    None if the name has no bars at all in the window.
    """
    row = con.execute(
        """
        SELECT MEDIAN(close * volume) FROM (
            SELECT close, volume FROM prices
            WHERE ticker = ? AND date < ?
            ORDER BY date DESC LIMIT ?
        )
        """,
        [ticker, as_of, bars],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def half_spread_bps(mdv: float | None) -> float:
    """Conservative liquidity-tiered half-spread estimate (documented above)."""
    return execution.half_spread_bps(mdv)


def slippage_bps_for(mdv: float | None,
                     profile: str | execution.ExecutionProfile | None = None,
                     *, side: str = "buy", qty: float = 1.0,
                     open_px: float = 1.0) -> float:
    """Per-side slippage in bps: max(half_spread, 5) + 5 (the +5 = 10bp r/t)."""
    return execution.cost_components(
        profile, side=side, qty=qty, open_px=open_px,
        median_dollar_volume=mdv)["total_bps"]


def attempt_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
    profile: str | execution.ExecutionProfile | None = None,
) -> FillResult:
    """Try to fill one order at `fill_date`'s open. The ONLY look-ahead guard.

    - Requires fill_date > signal_date (no same-bar fills, ever).
    - Missing bar: 'pending' until PENDING_MAX_DAYS trading days elapse, then
      'rejected' with reason 'no_bar' (a bar is never fabricated).
    - Liquidity guard: notional above the profile's participation cap is rejected.
    - Otherwise 'filled' at the slippage-adjusted open.
    """
    if fill_date <= signal_date:
        raise ValueError(
            f"look-ahead violation: fill_date {fill_date} !> signal_date {signal_date}"
        )

    bar = con.execute(
        "SELECT open, volume FROM prices WHERE ticker = ? AND date = ?",
        [ticker, fill_date],
    ).fetchone()

    if bar is None or bar[0] is None or bar[0] <= 0 or not bar[1]:
        # No TRADEABLE bar on the fill date — halt / delisting / missing data.
        # Three shapes count as "no bar": the row is absent; `open` is NULL or
        # non-positive (an `open = 0.0` row would fill a buy for $0 and book
        # free shares — 4 such rows exist in the store); or `volume` is NULL/0.
        # yfinance keeps emitting a dead quote as a zero-volume bar after a
        # name stops trading (BUILDLOG 2026-08-20c), and nobody could have
        # traded at it. A thin name's legitimate zero-volume day simply waits a
        # session; after PENDING_MAX_DAYS it rejects as 'no_bar' like any halt.
        elapsed = calendar.trading_days_between(con, signal_date, fill_date)
        if elapsed >= PENDING_MAX_DAYS:
            return FillResult(status="rejected", reject_reason="no_bar")
        return FillResult(status="pending")

    open_px = float(bar[0])
    mdv = median_dollar_vol(con, ticker, fill_date)

    selected = execution.resolve_profile(profile)
    components = execution.cost_components(
        selected, side=side, qty=qty, open_px=open_px,
        median_dollar_volume=mdv)

    # Liquidity guard (partial fills not modeled v1).
    if (mdv is not None
            and components["participation"] > selected.max_participation):
        return FillResult(
            status="rejected",
            reject_reason=f"illiquid: notional ${qty * open_px:,.0f} > "
            f"{selected.max_participation:.2%} of "
            f"median $vol ${mdv:,.0f} (profile {selected.id})",
            open_px=open_px,
            median_dollar_vol=mdv,
        )

    slip = components["total_bps"]
    if side == "buy":
        fill_px = open_px * (1 + slip / 1e4)
    elif side == "sell":
        fill_px = open_px * (1 - slip / 1e4)
    else:  # pragma: no cover - guarded upstream
        raise ValueError(f"bad side {side!r}")

    return FillResult(
        status="filled",
        open_px=open_px,
        fill_px=fill_px,
        slippage_bps=components["market_bps"],
        cost_bps=slip,
        median_dollar_vol=mdv,
        participation=components["participation"],
        impact_bps=components["impact_bps"],
        fee_bps=components["fee_bps"],
        execution_profile=selected.id,
    )


def _utc_naive(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _clock_at(session_date: date, value) -> datetime:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            return value.replace(tzinfo=bar_sources.NEW_YORK)
        return value.astimezone(bar_sources.NEW_YORK)
    return datetime.combine(session_date, value, bar_sources.NEW_YORK)


def _session_close_at(session_date: date) -> datetime:
    resolver = getattr(order_types, "session_close", None)
    if resolver is not None:
        return _clock_at(session_date, resolver(session_date))
    _opened, closed = bar_sources.session_bounds(session_date)
    return closed.replace(tzinfo=timezone.utc).astimezone(bar_sources.NEW_YORK)


def _moc_cutoff_at(session_date: date) -> datetime:
    resolver = getattr(order_types, "moc_cutoff", None)
    if resolver is not None:
        return _clock_at(session_date, resolver(session_date))
    return _session_close_at(session_date) - timedelta(minutes=10)


def _previous_session(session_date: date) -> date:
    cursor = session_date - timedelta(days=1)
    while not nyse.is_session(cursor):
        cursor -= timedelta(days=1)
    return cursor


def _received_at_allowed(
    order_type: OrderType, session_date: date, received_at: datetime,
) -> bool:
    """R13 transition shim; L0 will provide the same close-aware contract."""
    if received_at.utcoffset() is None or not nyse.is_session(session_date):
        return False
    received_et = received_at.astimezone(bar_sources.NEW_YORK)
    opened = datetime.combine(
        session_date, order_types.MARKET_OPEN, bar_sources.NEW_YORK,
    )
    closed = _session_close_at(session_date)
    prior_close = _session_close_at(_previous_session(session_date))
    if order_type is OrderType.NEXT_OPEN:
        next_open = datetime.combine(
            nyse.next_session(session_date), order_types.MARKET_OPEN,
            bar_sources.NEW_YORK,
        )
        return closed <= received_et < next_open
    if order_type in {OrderType.MOO, OrderType.LIMIT_ON_OPEN}:
        cutoff = datetime.combine(
            session_date, order_types.MOO_CUTOFF, bar_sources.NEW_YORK,
        )
        return prior_close <= received_et <= cutoff
    if order_type is OrderType.MOC:
        return prior_close <= received_et <= _moc_cutoff_at(session_date)
    if order_type is OrderType.MARKET:
        return opened <= received_et < closed
    return prior_close <= received_et < closed


def _v2_result(
    *,
    side: str,
    qty: float,
    reference_px: float,
    mdv: float | None,
    slip_bps: float,
    fill_kind: str,
    price_source: str,
    bar_ref: str,
    fill_ts: datetime,
    profile: str | execution.ExecutionProfile | None,
) -> FillResult:
    selected = execution.resolve_profile(profile)
    participation = (
        0.0 if mdv is None or mdv <= 0 else qty * reference_px / mdv
    )
    if mdv is not None and participation > selected.max_participation:
        return FillResult(
            status="rejected",
            reject_reason=f"illiquid: notional ${qty * reference_px:,.0f} > "
            f"{selected.max_participation:.2%} of median $vol ${mdv:,.0f} "
            f"(profile {selected.id})",
            open_px=reference_px,
            median_dollar_vol=mdv,
            participation=participation,
            execution_profile=selected.id,
            fill_kind=fill_kind,
            price_source=price_source,
            bar_ref=bar_ref,
            fill_ts=fill_ts,
            reference_px=reference_px,
        )
    direction = 1 if side in {"buy", "cover"} else -1
    if side not in {"buy", "sell", "short", "cover"}:
        raise ValueError(f"bad side {side!r}")
    fill_px = reference_px * (1 + direction * slip_bps / 1e4)
    return FillResult(
        status="filled",
        open_px=reference_px,
        fill_px=fill_px,
        slippage_bps=slip_bps,
        cost_bps=slip_bps,
        median_dollar_vol=mdv,
        participation=participation,
        impact_bps=0.0,
        fee_bps=0.0,
        execution_profile=selected.id,
        fill_kind=fill_kind,
        price_source=price_source,
        bar_ref=bar_ref,
        fill_ts=fill_ts,
        reference_px=reference_px,
    )


def attempt_next_open_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "prices",
    available_at: datetime | None = None,
    penalty_bps: float = 0.0,
) -> FillResult:
    """V2 next-open attempt with alternate daily sources and explicit sides."""
    if fill_date <= signal_date:
        raise ValueError(
            f"look-ahead violation: fill_date {fill_date} !> signal_date {signal_date}"
        )
    bar = bar_sources.daily_bar(
        con, ticker, fill_date, source=price_source, available_at=available_at,
    )
    if bar is None:
        elapsed = 0
        cursor = signal_date
        while cursor < fill_date:
            cursor += timedelta(days=1)
            if nyse.is_session(cursor):
                elapsed += 1
        if elapsed >= PENDING_MAX_DAYS:
            return FillResult(status="rejected", reject_reason="no_bar")
        return FillResult(status="pending", price_source=price_source)
    mdv = bar_sources.median_dollar_volume(
        con, ticker, fill_date, source=price_source, available_at=available_at,
    )
    slip = half_spread_bps(mdv) + 5.0 + penalty_bps
    fill_ts = datetime.combine(
        fill_date, datetime.min.time().replace(hour=9, minute=30),
        bar_sources.NEW_YORK,
    ).astimezone(timezone.utc).replace(tzinfo=None)
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=bar.open,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="next_open",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        fill_ts=fill_ts,
        profile=profile,
    )


def attempt_auction_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    order_type: str = "moo",
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "prices",
    available_at: datetime | None = None,
    penalty_bps: float = 0.0,
) -> FillResult:
    """Attempt an opening- or closing-auction fill without a same-bar peek."""
    kind = OrderType(order_type)
    if kind not in {OrderType.MOO, OrderType.MOC}:
        raise ValueError("auction order_type must be 'moo' or 'moc'")
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not _received_at_allowed(kind, session_date, received_at):
        return FillResult(status="rejected", reject_reason="cutoff")
    bar = bar_sources.daily_bar(
        con, ticker, session_date, source=price_source, available_at=available_at,
    )
    if bar is None:
        return FillResult(status="pending", price_source=price_source)
    opening = kind is OrderType.MOO
    reference = bar.open if opening else bar.close
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=price_source, available_at=available_at,
    )
    # Auction orders trade at one clearing print: half the normal estimated
    # half-spread tier and no fixed adverse-movement component.
    slip = half_spread_bps(mdv) / 2 + penalty_bps
    opened, _closed = bar_sources.session_bounds(session_date)
    fill_ts = opened if opening else _utc_naive(_session_close_at(session_date))
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=reference,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="open_auction" if opening else "close_auction",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        fill_ts=fill_ts,
        profile=profile,
    )


def _eligible_minutes(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    session_date: date,
    received_at: datetime,
    *,
    price_source: str,
    available_at: datetime | None,
) -> list[bar_sources.MinuteBar]:
    earliest = _utc_naive(received_at) + timedelta(minutes=1)
    return [
        bar for bar in bar_sources.minute_bars(
            con, ticker, session_date, source=price_source, available_at=available_at,
        )
        if bar.ts >= earliest
    ]


def attempt_intraday_market_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "intraday_prices",
    daily_price_source: str = "prices",
    available_at: datetime | None = None,
) -> FillResult:
    """Fill at the first minute bar at least 60 seconds after receipt."""
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not _received_at_allowed(OrderType.MARKET, session_date, received_at):
        return FillResult(status="rejected", reject_reason="market_closed")
    bars = _eligible_minutes(
        con, ticker, session_date, received_at,
        price_source=price_source, available_at=available_at,
    )
    if not bars:
        status = (
            "rejected" if bar_sources.minute_session_complete(
                con, ticker, session_date, source=price_source,
                available_at=available_at,
            ) else "pending"
        )
        return FillResult(
            status=status,
            reject_reason="no_bar" if status == "rejected" else None,
            price_source=price_source,
        )
    bar = bars[0]
    reference = bar.vwap if bar.vwap is not None and bar.vwap > 0 else (
        bar.open + bar.high + bar.low + bar.close
    ) / 4
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=daily_price_source, available_at=available_at,
    )
    slip = half_spread_bps(mdv) + 5.0
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=reference,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="intraday_bar",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        fill_ts=bar.ts,
        profile=profile,
    )


def tick_size(price: float) -> float:
    """US equity tick used by the deterministic limit-touch rule."""
    if price <= 0:
        raise ValueError("limit price must be positive")
    return 0.01 if price >= 1 else 0.0001


def attempt_intraday_limit_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    limit_px: float,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "intraday_prices",
    daily_price_source: str = "prices",
    available_at: datetime | None = None,
) -> FillResult:
    """Fill a day limit only after a full later minute bar crosses one tick."""
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not _received_at_allowed(OrderType.LIMIT, session_date, received_at):
        return FillResult(status="rejected", reject_reason="market_closed")
    bars = _eligible_minutes(
        con, ticker, session_date, received_at,
        price_source=price_source, available_at=available_at,
    )
    if not bars:
        complete = bar_sources.minute_session_complete(
            con, ticker, session_date, source=price_source,
            available_at=available_at,
        )
        return FillResult(
            status="expired" if complete else "pending",
            reject_reason="day_limit_not_touched" if complete else None,
            price_source=price_source,
        )
    tick = tick_size(limit_px)
    if side in {"buy", "cover"}:
        touched = next((bar for bar in bars if bar.low <= limit_px - tick), None)
    elif side in {"sell", "short"}:
        touched = next((bar for bar in bars if bar.high >= limit_px + tick), None)
    else:
        raise ValueError(f"bad side {side!r}")
    if touched is None and not bar_sources.minute_session_complete(
        con, ticker, session_date, source=price_source, available_at=available_at,
    ):
        return FillResult(status="pending", price_source=price_source)
    if touched is None:
        return FillResult(
            status="expired", reject_reason="day_limit_not_touched",
            price_source=price_source,
        )
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=daily_price_source, available_at=available_at,
    )
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=limit_px,
        mdv=mdv,
        slip_bps=0.0,
        fill_kind="limit_touch",
        price_source=price_source,
        bar_ref=touched.bar_ref,
        fill_ts=touched.ts,
        profile=profile,
    )
