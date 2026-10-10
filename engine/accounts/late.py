"""Late delivery uses the same inception fold as nightly settlement."""
from datetime import datetime, timezone

from engine.accounts import settle as processor


def settle(con, *, session_date=None, short_con=None, settled_at=None) -> dict:
    now = settled_at or datetime.now(timezone.utc)
    latest = con.execute(
        'SELECT MAX(day) FROM (SELECT MAX(date) AS day FROM prices UNION ALL '
        'SELECT MAX(date) FROM sim_equity UNION ALL SELECT MAX(fill_date) FROM sim_fills)'
    ).fetchone()[0]
    end = max(day for day in (session_date, latest) if day is not None) if latest or session_date else now.date()
    return processor.settle_session(con, end, late=True, short_con=short_con, settled_at=now)
