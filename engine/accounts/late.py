"""Oldest-first recovery of unresolved account sessions and their dependent state."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from engine.accounts import account_portfolios, service
from engine.accounts import settle as processor
from engine.lib import db
from sim import bar_sources, nyse


def unresolved(con, account_id: str) -> set[date]:
    days = set()
    for signal, session, kind in con.execute(
        'SELECT o.signal_date,d.session_date,d.order_type FROM sim_orders o '
        'JOIN sim_order_details d ON d.order_id=o.id '
        "WHERE o.portfolio_id=? AND o.status='pending'", [account_id],
    ).fetchall():
        days.add(nyse.next_session(signal) if kind == 'next_open' else session)
    resolved = set()
    events = con.execute(
        "SELECT kind,payload FROM account_events WHERE portfolio_id=? AND kind IN "
        "('stale_mark','settlement_error','late_reconciled') ORDER BY id", [account_id],
    ).fetchall()
    for kind, raw in events:
        day = date.fromisoformat(json.loads(raw)['session_date'])
        if kind == 'late_reconciled':
            resolved.add(day)
        else:
            resolved.discard(day)
            days.add(day)
    days -= resolved
    days.update(row[0] for row in con.execute(
        'SELECT DISTINCT f.fill_date FROM sim_fills f LEFT JOIN sim_equity e '
        'ON e.portfolio_id=f.portfolio_id AND e.date=f.fill_date '
        'WHERE f.portfolio_id=? AND e.date IS NULL', [account_id],
    ).fetchall())
    return days


def settle(con, *, session_date=None, short_con=None, settled_at=None) -> dict:
    """Recover each affected account atomically through its latest dependent mark."""
    now = settled_at or datetime.now(timezone.utc)
    latest = con.execute(
        'SELECT MAX(session_day) FROM (SELECT MAX(date) AS session_day FROM prices UNION ALL '
        'SELECT MAX(date) FROM sim_equity)'
    ).fetchone()[0]
    counts = {'filled': 0, 'rejected': 0, 'expired': 0, 'pending': 0, 'late_settled': 0}
    out = {**counts, 'errors': {}, 'sessions': [], 'completed': [], 'carried': {},
           'affected_accounts': [], 'recovered_marks': []}
    for settings in account_portfolios(con, active_only=False):
        if settings['status'] not in {'active', 'halted', 'retiring'}:
            continue
        account_id = settings['portfolio_id']
        days = {day for day in unresolved(con, account_id)
                if bar_sources.session_bounds(day)[1] <= bar_sources._naive_utc(now)}
        if session_date is not None:
            days.add(session_date)
        if not days:
            continue
        end = max(value for value in (latest, session_date, min(days)) if value is not None)
        days = {day for day in days if day <= end}
        if not days:
            continue
        start = min(days)
        local = []
        day = start
        try:
            verification = service.verify(con, account_id, now=now, check_equity=False)
            if verification['status'] != 'ok':
                raise RuntimeError('ledger mismatch before late recovery')
            with db.transaction(con):
                while day <= end:
                    if nyse.is_session(day):
                        result = processor.settle_session(
                            con, day, late=True, short_con=short_con, settled_at=now,
                            portfolio_id=account_id, manage_transactions=False, replay=True,
                        )
                        local.append((day, result))
                        if not result['carried'] and not result['pending']:
                            processor._record_account_event(
                                con, account_id, 'late_reconciled', {'session_date': day.isoformat()}, now,
                            )
                    day += timedelta(days=1)
            for day, result in local:
                out['sessions'].append({'account_id': account_id, 'session_date': day.isoformat(),
                                        **result})
                for key in counts:
                    out[key] += result[key]
                out['carried'].update(result['carried'])
                for key in ('affected_accounts', 'recovered_marks'):
                    out[key] = sorted(set(out[key]) | set(result[key]))
            out['completed'].append(account_id)
        except Exception as exc:
            out['errors'][account_id] = {'exception_type': type(exc).__name__, 'message': str(exc)[:1000]}
            with db.transaction(con):
                processor._record_account_event(con, account_id, 'settlement_error',
                    {'session_date': day.isoformat(), 'exception_type': type(exc).__name__,
                     'message': str(exc)[:1000]}, now)
    return out
