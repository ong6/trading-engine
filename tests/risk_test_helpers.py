"""Shared in-memory setup for discretionary-risk tests."""

from datetime import date, timedelta

from tests.conftest import insert_bars


def spy_days(n=200, start=date(2023, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def populate_risk_con(con):
    """200 SPY bars, rising -> risk-on. No discretionary book yet."""
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe (ticker, active, liquid) VALUES "
        "('SPY', TRUE, TRUE), ('AAA', TRUE, FALSE)"
    )
    days = spy_days()
    insert_bars(con, "SPY", days, close=[400.0 + i for i in range(200)])
    insert_bars(
        con, "AAA", days[-4:], open_=100.0, high=101.0, low=99.0, close=100.0
    )  # the ticket's ticker, at $100
    return con


def good_ticket(**over):
    # risk/share $1 * 90 sh = $90 <= $97.50 experiment cap; qty 90 <= 390 (1%);
    # R:R = (104-100)/1 = 4.
    t = dict(
        ticker="AAA",
        side="buy",
        qty=90,
        entry_ref=100.0,
        stop=99.0,
        target=104.0,
        playbook="vcp",
        acknowledge_earnings=True,
    )
    t.update(over)
    return t


def gate(gates, name):
    return next(g for g in gates if g["name"] == name)


def open_book(con, cash, positions):
    con.execute(
        "INSERT INTO portfolios (id, name, cash, active) VALUES ('discretionary', 'd', ?, TRUE)",
        [cash],
    )
    for tk, qty, avg in positions:
        con.execute("INSERT INTO sim_positions VALUES ('discretionary', ?, ?, ?)", [tk, qty, avg])


def insert_trip(con, oid, tk, side, qty, d, px, entry=None, stop=None):
    con.execute(
        "INSERT INTO sim_fills VALUES (?, 'discretionary', ?, ?, ?, ?, ?, ?, 10, 10)",
        [oid, tk, side, qty, d, px, px],
    )
    if side == "buy":
        con.execute(
            "INSERT INTO disc_tickets (id, ticker, entry_ref, stop, status, order_id) "
            "VALUES (?, ?, ?, ?, 'filled', ?)",
            [oid, tk, entry, stop, oid],
        )
