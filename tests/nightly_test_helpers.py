"""Shared setup for nightly database and generated-report reconciliation tests."""

from engine.lib import db


def nightly_fixture(con, tmp_path):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    con.executemany(
        "INSERT INTO screen_results "
        "(run_date,ticker,rs_rank,template_score,passes_template,new_today,universe_policy) "
        "VALUES (DATE '2026-09-04',?,?,?,?,?,?)",
        [
            ("AAA", 99, 8, True, True, "all"),
            ("BBB", 50, 6, False, False, "all"),
        ],
    )
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES ('paper','Paper','none','{}',DATE '2026-09-04',TRUE,100,100,'baseline_v1')"
    )
    con.execute("INSERT INTO sim_equity VALUES ('paper',DATE '2026-09-04',100,100,0)")
    screens = tmp_path / "screens"
    reports = tmp_path / "reports"
    screens.mkdir()
    reports.mkdir()
    screen_text = (
        "# Screen — 2026-09-04  (universe: 2 · passing: 1 · new today: 1 · "
        "regime: risk-on · policy: all)\n"
    )
    (screens / "2026-09-04.md").write_text(screen_text)
    (screens / "latest.md").write_text(screen_text)
    (reports / "league.md").write_text(
        "# Paper League — 2026-09-04\n\n"
        "| # | Portfolio | Inception | Equity | Total ret | vs SPY | Max DD | "
        "Open | Fills | Last 5d |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | Paper | 2026-09-04 | $100 | +0.00% | · | +0.00% | 0 | 0 | · |\n"
    )
    (reports / "league.csv").write_text("portfolio_id,date,equity\npaper,2026-09-04,100.0\n")
    meta = {
        "screen_date": "2026-09-04",
        "regime": "risk-on",
        "screened": 2,
        "passing_count": 1,
        "new_today_count": 1,
        "universe_policy": "all",
    }
    driver = {
        "name": "run_daily",
        "started_at": "2026-09-07T22:30:01Z",
        "finished_at": "2026-09-07T23:14:53Z",
        "status": "ok",
    }
    return meta, driver
