"""Resolve the breadth-qualified date allowed to advance nightly paper state."""
from __future__ import annotations

import argparse
from datetime import date

from engine.lib import db
from engine.lib.util import table_exists
from sim import nyse


def validate_league_continuity(con, market_date: date) -> None:
    """Refuse to skip a session or build on divergent active-book checkpoints."""
    if not table_exists(con, "portfolios"):
        return
    active = int(
        con.execute("SELECT COUNT(*) FROM portfolios WHERE active = TRUE").fetchone()[0]
    )
    if active == 0:
        return
    if not table_exists(con, "sim_equity"):
        raise ValueError("active portfolios exist but sim_equity is missing")
    rows = con.execute(
        "SELECT p.id, MAX(e.date) FROM portfolios p "
        "LEFT JOIN sim_equity e ON e.portfolio_id = p.id "
        "WHERE p.active = TRUE GROUP BY p.id ORDER BY p.id"
    ).fetchall()
    missing = [portfolio_id for portfolio_id, last_date in rows if last_date is None]
    if missing:
        raise ValueError(
            "active portfolios have no equity checkpoint: " + ", ".join(missing)
        )
    checkpoints = sorted({last_date for _, last_date in rows})
    if len(checkpoints) != 1:
        rendered = ", ".join(day.isoformat() for day in checkpoints)
        raise ValueError(f"active portfolio checkpoints disagree: {rendered}")
    checkpoint = checkpoints[0]
    if checkpoint == market_date:
        return
    if checkpoint > market_date:
        raise ValueError(
            f"active portfolio checkpoint {checkpoint.isoformat()} is newer than "
            f"qualified date {market_date.isoformat()}"
        )
    expected = nyse.next_session(checkpoint)
    if market_date != expected:
        raise ValueError(
            f"league session gap: active books last stepped {checkpoint.isoformat()}; "
            f"expected {expected.isoformat()} but qualified date is "
            f"{market_date.isoformat()}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path")
    args = parser.parse_args()
    con = db.connect(args.db, read_only=True)
    try:
        if not table_exists(con, "universe"):
            raise SystemExit("[market-date] no active liquid universe")
        active_liquid = int(
            con.execute(
                "SELECT COUNT(*) FROM universe WHERE active = TRUE AND liquid = TRUE"
            ).fetchone()[0]
        )
        if active_liquid == 0:
            raise SystemExit("[market-date] no active liquid universe")
        market_date = db.latest_operational_market_date(con)
        if market_date is None:
            raise SystemExit("[market-date] no breadth-qualified real-bar date")
        latest_real = db.latest_real_prices_date(con)
        if latest_real is not None and latest_real > market_date:
            raise SystemExit(
                "[market-date] incomplete real-bar tail: "
                f"latest real date {latest_real.isoformat()} is newer than "
                f"qualified date {market_date.isoformat()}"
            )
        try:
            validate_league_continuity(con, market_date)
        except ValueError as exc:
            raise SystemExit(f"[market-date] {exc}") from exc
    finally:
        con.close()
    print(market_date.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
