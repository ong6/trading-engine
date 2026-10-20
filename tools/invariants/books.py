"""Book invariants: fee rows, equity marks, close-outs, P15 publication order and pre-open.

The P15 book ids and the fee profile are local constants (``tests/test_invariants.py`` pins
them to ``sim.p15_books`` and ``sim.costs``) so this module never imports the simulator.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .registry import CannotEvaluate, Context, finite, json_value, register, violation

NEW_YORK = ZoneInfo("America/New_York")
P15_BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
P15_AI_BOOK_IDS = ("p15_ai_ranked", "p15_hybrid_veto")
FEE_PROFILE = "ibkr_pro_tiered_v1"
FEE_DAY_ZERO = date(2026, 10, 19)  # used only for a book with no recorded cost-profile break
P15_SCORING_DEADLINE = time(12, 0)  # UTC on the next day: the scoring runner's deadline
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
PREOPEN_VOID_STATUSES = ("unavailable", "late")
PREOPEN_ENTRY_ROLE = "entry"
MARK_TOLERANCE = 1e-6


def _utc(stamp: datetime) -> datetime:
    """Naive store stamps are UTC."""
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def _new_york(day: date, at: time) -> datetime:
    return datetime.combine(day, at, NEW_YORK).astimezone(UTC)


@register("fee_row_per_fill", "books",
          tables=("sim_fills", "sim_fill_fees", "portfolio_accounts", "sim_book_breaks"))
def fee_row_per_fill(ctx: Context) -> tuple[dict, list[dict]]:
    """From each book's fee day zero, every fill has exactly one finite fee row of its profile.

    Day zero is the book's ``cost_profile`` break to ``FEE_PROFILE`` (``FEE_DAY_ZERO`` for a
    book on that profile without a break row).
    """
    rows = ctx.con.execute(
        """
        WITH zero AS (
            SELECT a.portfolio_id,
                   COALESCE(MIN(b.break_date) FILTER (WHERE b.kind = 'cost_profile'
                                                       AND b.to_value = ?), ?) AS day_zero
            FROM portfolio_accounts a
            LEFT JOIN sim_book_breaks b ON b.portfolio_id = a.portfolio_id
            WHERE a.cost_profile = ?
            GROUP BY a.portfolio_id
        )
        SELECT f.order_id, f.portfolio_id, f.ticker, f.fill_date, COUNT(ff.order_id),
               list(ff.cost_profile) FILTER (WHERE ff.order_id IS NOT NULL),
               bool_and(isfinite(ff.total_usd) AND ff.total_usd >= 0)
                   FILTER (WHERE ff.order_id IS NOT NULL),
               SUM(ff.total_usd)
        FROM sim_fills f JOIN zero z ON z.portfolio_id = f.portfolio_id
                                     AND f.fill_date >= z.day_zero
        LEFT JOIN sim_fill_fees ff ON ff.order_id = f.order_id
        GROUP BY ALL ORDER BY f.fill_date, f.order_id
        """, [FEE_PROFILE, FEE_DAY_ZERO, FEE_PROFILE]).fetchall()
    found, by_date = [], {}
    for order_id, book, ticker, day, count, profiles, total_ok, total in rows:
        stats = by_date.setdefault(day.isoformat(), {"fills": 0, "with_fee_row": 0,
                                                     "fees_usd": 0.0})
        stats["fills"] += 1
        stats["with_fee_row"] += count == 1
        stats["fees_usd"] += float(total) if count and total_ok else 0.0
        subject = f"order {order_id}"
        detail = {"date": day.isoformat(), "portfolio_id": book, "ticker": ticker}
        if count == 0:
            found.append(violation(subject, "missing", **detail))
        elif count > 1:
            found.append(violation(subject, "duplicate", rows=count, **detail))
        elif profiles != [FEE_PROFILE]:
            found.append(violation(subject, "wrong_profile", profile=profiles[0], **detail))
        elif not total_ok:
            found.append(violation(subject, "nonfinite", **detail))
    for stats in by_date.values():
        stats["fees_usd"] = round(stats["fees_usd"], 2)
    return {"profile": FEE_PROFILE, "fills_checked": len(rows), "by_fill_date": by_date}, found


@register("equity_per_active_book", "books",
          tables=("portfolios", "sim_equity", "prices", "p15_scoring_runs"))
def equity_per_active_book(ctx: Context) -> tuple[dict, list[dict]]:
    """Every active book has a finite, positive mark for the latest session its publisher ran.

    League books are marked by the nightly for the newest priced session. P15 books are
    marked by their scoring run for that session; until the run's deadline (12:00 UTC the next
    day) a P15 book one session behind is pending, not missing.
    """
    con = ctx.con
    prices_session = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    books = con.execute(
        "SELECT id, created FROM portfolios WHERE active ORDER BY id").fetchall()
    if prices_session is None or not books:
        raise CannotEvaluate("no prices or no active books")
    league = [book for book, _created in books if book not in P15_BOOK_IDS]
    marks = {(book, day): (equity, cash) for book, day, equity, cash in con.execute(
        "SELECT portfolio_id, date, equity, cash FROM sim_equity WHERE portfolio_id IN "
        "(SELECT id FROM portfolios WHERE active) AND date >= ?",
        [prices_session - timedelta(days=14)]).fetchall()}
    league_session = max((day for (book, day) in marks if book in league), default=None)
    found = []
    if league_session is None or league_session < prices_session:
        found.append(violation("league", "behind_prices", date=prices_session.isoformat(),
                               league_session=json_value(league_session)))
    league_session = league_session or prices_session
    scored = {day for (day,) in con.execute(
        "SELECT market_date FROM p15_scoring_runs WHERE status = 'completed'").fetchall()}
    p15_session, pending = league_session, []
    if league_session not in scored:
        due = datetime.combine(league_session + timedelta(days=1), P15_SCORING_DEADLINE, UTC)
        if ctx.snapshot_as_of < due:
            p15_session = max((day for day in scored if day < league_session), default=None)
            pending = [book for book, _created in books if book in P15_BOOK_IDS]
        else:
            found.append(violation("p15 scoring", "publisher_overdue",
                                   date=league_session.isoformat(), due=due.isoformat()))
    marked = 0
    for book, created in books:
        session = p15_session if book in P15_BOOK_IDS else league_session
        if session is None or (created is not None and created > session):
            continue
        mark = marks.get((book, session))
        if mark is None:
            found.append(violation(book, "missing", date=session.isoformat()))
        elif not (finite(mark[0]) and finite(mark[1]) and mark[0] > 0):
            found.append(violation(book, "nonfinite", date=session.isoformat(),
                                   equity=json_value(mark[0]), cash=json_value(mark[1])))
        else:
            marked += 1
    nonfinite_history = con.execute(
        "SELECT portfolio_id, date FROM sim_equity WHERE NOT (isfinite(equity) "
        "AND isfinite(cash)) ORDER BY date, portfolio_id").fetchall()
    found += [violation(book, "nonfinite", date=day.isoformat())
              for book, day in nonfinite_history
              if not any(item["subject"] == book and item["detail"]["date"] == day.isoformat()
                         for item in found)]
    facts = {
        "prices_session": prices_session.isoformat(),
        "league_session": league_session.isoformat(),
        "p15_session": json_value(p15_session), "pending_publisher": pending,
        "active_books": len(books), "books_with_equity": marked,
    }
    return facts, found


@register("closeouts_once", "books",
          tables=("sim_settlements", "sim_fills", "sim_positions", "portfolios"))
def closeouts_once(ctx: Context) -> tuple[dict, list[dict]]:
    """A cash close-out happens once per holding and leaves no position or later sale.

    A second cash settlement of the same book and name, a surviving position or a sell fill
    after the close-out are violations unless a buy fill re-opened the name in between.
    """
    con = ctx.con
    settlements = con.execute(
        "SELECT portfolio_id, ticker, effective, price, qty FROM sim_settlements "
        "WHERE kind = 'cash' ORDER BY portfolio_id, ticker, effective, created_at").fetchall()
    fills: dict[tuple[str, str], list[tuple[date, str]]] = {}
    for book, ticker, day, side in con.execute(
            "SELECT f.portfolio_id, f.ticker, f.fill_date, f.side FROM sim_fills f "
            "JOIN (SELECT DISTINCT portfolio_id, ticker FROM sim_settlements "
            "WHERE kind = 'cash') s USING (portfolio_id, ticker) "
            "ORDER BY f.fill_date").fetchall():
        fills.setdefault((book, ticker), []).append((day, side))
    held = {(book, ticker): qty for book, ticker, qty in con.execute(
        "SELECT portfolio_id, ticker, qty FROM sim_positions WHERE qty > 1e-9").fetchall()}
    by_holding: dict[tuple[str, str], list[tuple]] = {}
    for book, ticker, day, price, qty in settlements:
        by_holding.setdefault((book, ticker), []).append((day, price, qty))
    found = []
    for (book, ticker), events in by_holding.items():
        subject = f"{book} {ticker}"
        trades = fills.get((book, ticker), [])
        for (first, _p, _q), (second, price, _qty) in zip(events, events[1:], strict=False):
            if not any(side == "buy" and first <= day <= second for day, side in trades):
                found.append(violation(subject, "repeated", date=second.isoformat(),
                                       first=first.isoformat(), price=json_value(price)))
        last = events[-1][0]
        later = [(day, side) for day, side in trades if day > last]
        reopened = next((day for day, side in later if side == "buy"), None)
        sold = [day for day, side in later if side == "sell" and (reopened is None
                                                                  or day < reopened)]
        if sold:
            found.append(violation(subject, "sold_after_closeout", date=sold[0].isoformat(),
                                   closeout=last.isoformat()))
        if (book, ticker) in held and reopened is None:
            found.append(violation(subject, "position_survives", date=last.isoformat(),
                                   qty=held[(book, ticker)]))
    recent_from = ctx.snapshot_as_of.date() - timedelta(days=30)
    recent = [{"portfolio_id": book, "ticker": ticker, "effective": day.isoformat(),
               "price": json_value(price)} for book, ticker, day, price, _qty in settlements
              if day >= recent_from]
    return {"cash_closeouts": len(settlements), "holdings": len(by_holding),
            "recent": recent}, found


@register("publication_order", "books",
          tables=("portfolios", "sim_equity", "p15_book_windows", "p15_scoring_runs",
                  "p15_preopen_runs"))
def publication_order(ctx: Context) -> tuple[dict, list[dict]]:
    """P15 marks follow their book windows, windows follow scoring, pre-open precedes the open.

    - every P15 equity mark (except the inception mark at initial cash) equals the committed
      ``p15_book_windows`` mark of that book and session;
    - a session's windows exist for all three books or none;
    - each window committed after a completed scoring run for its session started, and that
      run started after the session's close;
    - each pre-open run started and finished before its session's 09:30 New York open.
    """
    con = ctx.con
    found = []
    placeholders = ",".join("?" for _ in P15_BOOK_IDS)
    inception = {book: cash for book, cash in con.execute(
        f"SELECT id, initial_cash FROM portfolios WHERE id IN ({placeholders})",
        list(P15_BOOK_IDS)).fetchall()}
    marks = con.execute(
        f"""
        SELECT e.portfolio_id, e.date, e.equity, w.equity, w.completed_at,
               e.date = MIN(e.date) OVER (PARTITION BY e.portfolio_id)
        FROM sim_equity e LEFT JOIN p15_book_windows w
          ON w.portfolio_id = e.portfolio_id AND w.market_date = e.date
        WHERE e.portfolio_id IN ({placeholders}) ORDER BY e.date, e.portfolio_id
        """, list(P15_BOOK_IDS)).fetchall()
    for book, day, equity, window_equity, completed, first in marks:
        subject = f"{book} {day.isoformat()}"
        if window_equity is None or completed is None:
            if first and equity == inception.get(book):
                continue
            found.append(violation(subject, "mark_without_window", date=day.isoformat(),
                                   equity=json_value(equity)))
        elif not (finite(equity) and abs(equity - window_equity)
                  <= MARK_TOLERANCE * max(1.0, abs(window_equity))):
            found.append(violation(subject, "mark_differs_from_window", date=day.isoformat(),
                                   equity=json_value(equity),
                                   window_equity=json_value(window_equity)))
    for day, books in con.execute(
            f"SELECT market_date, COUNT(DISTINCT portfolio_id) FROM p15_book_windows "
            f"WHERE portfolio_id IN ({placeholders}) GROUP BY 1 HAVING COUNT(DISTINCT "
            f"portfolio_id) <> {len(P15_BOOK_IDS)} ORDER BY 1", list(P15_BOOK_IDS)).fetchall():
        found.append(violation(f"windows {day.isoformat()}", "partial_window_set",
                               date=day.isoformat(), books=books))
    runs = {}
    for day, started in con.execute(
            "SELECT market_date, MIN(started_at) FROM p15_scoring_runs "
            "WHERE status = 'completed' GROUP BY 1").fetchall():
        runs[day] = _utc(started)
        if runs[day] < _new_york(day, SESSION_CLOSE):
            found.append(violation(f"scoring {day.isoformat()}", "scoring_before_close",
                                   date=day.isoformat(), started_at=runs[day].isoformat()))
    for book, day, completed in con.execute(
            f"SELECT portfolio_id, market_date, completed_at FROM p15_book_windows "
            f"WHERE portfolio_id IN ({placeholders}) ORDER BY 2, 1",
            list(P15_BOOK_IDS)).fetchall():
        subject = f"{book} {day.isoformat()}"
        if day not in runs:
            found.append(violation(subject, "window_without_scoring_run", date=day.isoformat()))
        elif completed is None or _utc(completed) < runs[day]:
            found.append(violation(subject, "window_before_scoring_run", date=day.isoformat(),
                                   completed_at=json_value(completed)))
    preopen = con.execute(
        "SELECT id, session_date, status, started_at, completed_at FROM p15_preopen_runs "
        "WHERE started_at IS NOT NULL ORDER BY session_date, id").fetchall()
    for run_id, day, status, started, completed in preopen:
        opened = _new_york(day, SESSION_OPEN)
        last = _utc(completed) if completed is not None else _utc(started)
        if status != "missed" and max(_utc(started), last) >= opened:
            found.append(violation(f"preopen {day.isoformat()}", "preopen_after_open",
                                   date=day.isoformat(), run_id=run_id, status=status,
                                   completed_at=last.isoformat()))
    windows = con.execute("SELECT COUNT(DISTINCT market_date) FROM p15_book_windows").fetchone()
    facts = {"p15_marks": len(marks), "window_sessions": windows[0],
             "scoring_runs": len(runs), "preopen_runs": len(preopen)}
    return facts, found


@register("preopen_not_voided", "books",
          tables=("p15_preopen_runs", "p15_book_fills", "p15_order_intents"))
def preopen_not_voided(ctx: Context) -> tuple[dict, list[dict]]:
    """Every AI-book entry that filled was reviewed by a usable pre-open run.

    ``voided``: a run ended ``unavailable`` or ``late``, so every AI decision defaulted to
    keep. ``stuck``: a run still ``running`` after its session. ``missed``: AI-book entries
    filled on a session that has no pre-open run at all.
    """
    con = ctx.con
    runs = con.execute(
        "SELECT id, session_date, status, reason FROM p15_preopen_runs "
        "ORDER BY session_date, id").fetchall()
    found = []
    for run_id, day, status, reason in runs:
        detail = {"date": day.isoformat(), "run_id": run_id, "status": status,
                  "reason": (reason or "")[:200]}
        if status in PREOPEN_VOID_STATUSES:
            found.append(violation(f"preopen {day.isoformat()}", "voided", **detail))
        elif status == "running" and day < ctx.snapshot_as_of.date():
            found.append(violation(f"preopen {day.isoformat()}", "stuck", **detail))
    placeholders = ",".join("?" for _ in P15_AI_BOOK_IDS)
    missed = con.execute(
        f"""
        SELECT f.fill_date, COUNT(*) FROM p15_book_fills f
        JOIN p15_order_intents i ON i.id = f.intent_id
        WHERE f.portfolio_id IN ({placeholders}) AND i.order_role = ?
          AND f.fill_date NOT IN (SELECT session_date FROM p15_preopen_runs)
        GROUP BY 1 ORDER BY 1
        """, [*P15_AI_BOOK_IDS, PREOPEN_ENTRY_ROLE]).fetchall()
    found += [violation(f"preopen {day.isoformat()}", "missed", date=day.isoformat(),
                        ai_entry_fills=count) for day, count in missed]
    by_status: dict[str, int] = {}
    for _id, _day, status, _reason in runs:
        by_status[status] = by_status.get(status, 0) + 1
    facts = {"runs": len(runs), "by_status": by_status,
             "voided_sessions": [item["detail"]["date"] for item in found
                                 if item["class"] == "voided"],
             "missed_sessions": [day.isoformat() for day, _count in missed]}
    return facts, found
