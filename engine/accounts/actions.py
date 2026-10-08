"""Captured corporate-action application for signed account ledgers."""
from __future__ import annotations

import json
from datetime import date

from engine.lib.util import table_exists
from sim import bar_sources


def recorded_splits(con, account_id: str, through: date | None = None):
    if not table_exists(con, 'account_events'):
        return []
    events = []
    for (payload,) in con.execute(
        "SELECT payload FROM account_events WHERE portfolio_id=? AND kind='split'",
        [account_id],
    ).fetchall():
        item = json.loads(payload)
        ex = date.fromisoformat(item['ex_date'])
        if through is None or ex <= through:
            events.append((item['instrument_id'], ex, float(item['ratio'])))
    return sorted(events, key=lambda item: (item[1], item[0]))


def apply_splits(con, account_id: str, day: date, now, record_event, *, replay=False) -> None:
    """Apply captured actions once, independently of price-restatement decisions."""
    if not table_exists(con, 'corporate_actions'):
        return
    applied = {(ticker, ex) for ticker, ex, _ in recorded_splits(con, account_id)}
    rows = con.execute(
        "SELECT ticker,ex_date,value FROM corporate_actions WHERE kind='split' "
        'AND ex_date<=? AND value>0 AND isfinite(value) '
        'AND (fetched_at IS NULL OR fetched_at<=?) AND ticker IN ('
        'SELECT ticker FROM sim_fills WHERE portfolio_id=? UNION '
        'SELECT ticker FROM sim_orders WHERE portfolio_id=?) ORDER BY ex_date,ticker',
        [day, now, account_id, account_id],
    ).fetchall()
    for ticker, ex, ratio in rows:
        already_applied = (ticker, ex) in applied
        if already_applied and not (replay and ex == day):
            continue
        # Only lots opened before the action change units.
        old_qty = con.execute(
            'SELECT COALESCE(SUM(qty),0) FROM sim_position_lots '
            'WHERE portfolio_id=? AND instrument_id=? AND opened_session<?',
            [account_id, ticker, ex],
        ).fetchone()[0]
        con.execute(
            'UPDATE sim_position_lots SET qty=qty*?,avg_px=avg_px/? '
            'WHERE portfolio_id=? AND instrument_id=? AND opened_session<?',
            [ratio, ratio, account_id, ticker, ex],
        )
        if old_qty:
            con.execute(
                'UPDATE sim_positions SET qty=qty+?,avg_cost=('
                'SELECT SUM(ABS(qty)*avg_px)/SUM(ABS(qty)) FROM sim_position_lots '
                'WHERE portfolio_id=? AND instrument_id=? AND qty<>0) '
                'WHERE portfolio_id=? AND ticker=?',
                [float(old_qty) * (ratio - 1), account_id, ticker, account_id, ticker],
            )
        opened, _ = bar_sources.session_bounds(ex)
        orders = con.execute(
            'SELECT o.id FROM sim_orders o JOIN sim_order_details d ON d.order_id=o.id '
            "WHERE o.portfolio_id=? AND o.ticker=? AND o.status='pending' "
            'AND d.received_at<?', [account_id, ticker, opened],
        ).fetchall()
        for (order_id,) in ([] if already_applied else orders):
            con.execute('UPDATE sim_orders SET qty=qty*? WHERE id=?', [ratio, order_id])
            con.execute('UPDATE sim_order_details SET limit_px=limit_px/? WHERE order_id=?',
                        [ratio, order_id])
        record_event(con, account_id, 'split',
                     {'instrument_id': ticker, 'ex_date': ex.isoformat(), 'ratio': ratio}, now)


def prepare_order(con, row: dict, day: date, now) -> dict:
    """Preview unapplied split units before pricing and global liquidity allocation."""
    if not table_exists(con, 'corporate_actions'):
        return row
    prepared = dict(row)
    applied = {(ticker, ex) for ticker, ex, _ in recorded_splits(con, row['portfolio_id'])}
    for ex, ratio in con.execute(
        "SELECT ex_date,value FROM corporate_actions WHERE ticker=? AND kind='split' "
        'AND ex_date<=? AND value>0 AND isfinite(value) '
        'AND (fetched_at IS NULL OR fetched_at<=?) ORDER BY ex_date',
        [row['ticker'], day, now],
    ).fetchall():
        if (row['ticker'], ex) in applied:
            continue
        if bar_sources._naive_utc(row['received_at']) < bar_sources.session_bounds(ex)[0]:
            prepared['qty'] *= ratio
            if prepared['limit_px'] is not None:
                prepared['limit_px'] /= ratio
    return prepared
