"""One-shot D0 migration of existing simulator books to dollar commissions."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db
from sim import book_breaks
from sim.schema import (
    init_sim_schema,
    next_order_id,
    portfolio_account,
    set_portfolio_account,
)

TARGET_COST_PROFILE = book_breaks.COMMISSION_COST_PROFILE
REGISTRATION_REVISION = 13


class MigrationRefused(RuntimeError):
    """The store is not at the safe pre-D0 migration boundary."""


def _engine_for(con, portfolio_id: str, current: dict) -> str:
    if portfolio_id.startswith("p15_"):
        return "p15"
    if portfolio_id.startswith("p16_"):
        return "p16"
    if current["engine"] == "account":
        return "account"
    if con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name='paper_account_specs'"
    ).fetchone() and con.execute(
        "SELECT 1 FROM paper_account_specs WHERE account_id=?", [portfolio_id]
    ).fetchone():
        return "account"
    return "league"


def _bootstrap_sequence_above_orders(con) -> int:
    return next_order_id(con)


def migrate(
    con,
    d0: date,
    *,
    registration_revision: int = REGISTRATION_REVISION,
    migrated_at: datetime | None = None,
) -> dict:
    """Apply the cost break exactly once in one transaction."""
    if not isinstance(d0, date):
        raise TypeError("D0 must be a date")
    db.init_schema(con)
    init_sim_schema(con)
    timestamp = (migrated_at or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    ).replace(tzinfo=None)
    with db.transaction(con):
        prior = int(con.execute(
            "SELECT COUNT(*) FROM sim_book_breaks WHERE kind='cost_profile'"
        ).fetchone()[0])
        if prior:
            raise MigrationRefused("cost-profile migration has already run")
        post_boundary = int(con.execute(
            "SELECT COUNT(*) FROM sim_equity WHERE date>=?", [d0]
        ).fetchone()[0])
        if post_boundary:
            raise MigrationRefused("sim_equity already contains D0-or-later rows")

        portfolios = [row[0] for row in con.execute(
            "SELECT id FROM portfolios ORDER BY id"
        ).fetchall()]
        for portfolio_id in portfolios:
            current = portfolio_account(con, portfolio_id)
            engine = _engine_for(con, portfolio_id, current)
            set_portfolio_account(
                con,
                portfolio_id,
                engine=engine,
                cost_profile=TARGET_COST_PROFILE,
                account_type=(
                    current["account_type"] if engine == "account" else "cash_legacy"
                ),
                visibility=current["visibility"],
                status=current["status"] if engine == "account" else None,
                price_source=current["price_source"],
                day_trade_rule=current["day_trade_rule"],
                allow_short=current["allow_short"] if engine == "account" else False,
                updated_at=timestamp,
            )
            con.execute(
                "INSERT INTO sim_book_breaks VALUES (?,?,?,?,?,?,?,?)",
                [
                    portfolio_id,
                    d0,
                    "cost_profile",
                    current["cost_profile"],
                    TARGET_COST_PROFILE,
                    registration_revision,
                    "commissions begin and the book evaluation clock restarts",
                    timestamp,
                ],
            )

        reserved_order_id = _bootstrap_sequence_above_orders(con)
        backfill = getattr(db, "backfill_first_fetched_at", None)
        backfilled = None if backfill is None else backfill(con)
    return {
        "status": "migrated",
        "d0": d0.isoformat(),
        "portfolio_count": len(portfolios),
        "break_count": len(portfolios),
        "reserved_order_id": reserved_order_id,
        "first_fetched_at_backfill": backfilled,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply the one-shot simulator commission break."
    )
    parser.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB store path")
    parser.add_argument("--d0", required=True, help="first commission session (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    args = parser.parse_args(argv)
    if not args.apply:
        parser.error("refusing without --apply")
    try:
        d0 = date.fromisoformat(args.d0)
    except ValueError as exc:
        parser.error(f"invalid --d0: {exc}")
    con = db.connect(Path(args.db))
    try:
        result = migrate(con, d0)
    finally:
        con.close()
    print(
        f"migrated {result['portfolio_count']} portfolios at D0={result['d0']}; "
        f"reserved order id {result['reserved_order_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
