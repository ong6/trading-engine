"""Database setup helpers shared by read-model tests."""

def screen_table(con):
    con.execute(
        """
        CREATE TABLE screen_results (
            run_date DATE, ticker VARCHAR, close DOUBLE, rs_rank INTEGER,
            template_score INTEGER, passes_template BOOLEAN,
            dist_50d DOUBLE, dist_200d DOUBLE, off_52w_low DOUBLE,
            off_52w_high DOUBLE, base_tight BOOLEAN, vol_dryup BOOLEAN,
            new_today BOOLEAN
        )
        """
    )


def liquid_universe(con, tickers):
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.executemany(
        "INSERT INTO universe VALUES (?, TRUE, TRUE)",
        [(ticker,) for ticker in tickers],
    )


def portfolio(con, portfolio_id, *, active=True):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES (?, ?, 'none', '{}', DATE '2026-09-01', ?, 39000)",
        [portfolio_id, portfolio_id, active],
    )
