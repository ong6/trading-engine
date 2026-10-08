"""Source-aware account marks shared by execution, maintenance and API reads."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from engine.paper_accounts import AccountRefused
from sim import bar_sources
from sim.schema import portfolio_account


@dataclass(frozen=True)
class Mark:
    price: float
    observed_at: datetime
    stale: bool
    source: str


def mark(con, account_id: str, ticker: str, day: date, *,
         price_source: str | None = None, as_of: datetime | None = None,
         available_at: datetime | None = None) -> Mark:
    """Carry an observed price; never omit an unpriced signed holding."""
    source = price_source or portfolio_account(con, account_id)['price_source']
    opened, closed = bar_sources.session_bounds(day)
    stamp = closed if as_of is None else bar_sources._naive_utc(as_of)
    observation = bar_sources.latest_close_observation(
        con, ticker, day, source=source, available_at=available_at,
        strictly_before=stamp < closed,
    )
    candidate = None
    if observation is not None:
        observed_day, price = observation
        candidate = Mark(price, bar_sources.session_bounds(observed_day)[1],
                         observed_day < day, source)
    if opened < stamp < closed:
        minute_source = 'massive_minute' if source == 'massive_daily' else 'intraday_prices'
        bars = bar_sources.minute_bars(con, ticker, day, source=minute_source,
                                      available_at=available_at)
        eligible = [bar for bar in bars if bar.ts + timedelta(minutes=1) <= stamp]
        if eligible:
            bar = eligible[-1]
            candidate = Mark(bar.close, bar.ts + timedelta(minutes=1), False, minute_source)
    if candidate is not None:
        return candidate
    row = con.execute(
        'SELECT f.fill_px,COALESCE(d.fill_ts,CAST(f.fill_date AS TIMESTAMP)) AS stamp '
        'FROM sim_fills f LEFT JOIN sim_fill_details d ON d.order_id=f.order_id '
        'WHERE f.portfolio_id=? AND f.ticker=? AND f.fill_date<=? '
        'AND COALESCE(d.fill_ts,CAST(f.fill_date AS TIMESTAMP))<=? '
        'ORDER BY stamp DESC,f.order_id DESC LIMIT 1',
        [account_id, ticker, day, stamp],
    ).fetchone()
    if row is not None and row[0] is not None and row[0] > 0:
        return Mark(float(row[0]), row[1], True, 'fill')
    raise AccountRefused(f'no price ever observed for {account_id} {ticker} by {stamp.isoformat()}')


def positions(con, account_id: str, day: date, **kwargs) -> list[dict]:
    rows = con.execute(
        'SELECT ticker,qty,avg_cost FROM sim_positions '
        'WHERE portfolio_id=? AND qty<>0 ORDER BY ticker', [account_id],
    ).fetchall()
    out = []
    for ticker, quantity, cost in rows:
        observed = mark(con, account_id, ticker, day, **kwargs)
        out.append({'instrument_id': ticker, 'quantity': float(quantity),
                    'avg_cost': float(cost), 'mark': observed.price,
                    'market_value': float(quantity) * observed.price,
                    'stale': observed.stale, 'mark_source': observed.source,
                    'observed_at': observed.observed_at.isoformat()})
    return out
