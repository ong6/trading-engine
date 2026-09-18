"""Shared setup for bounded agent-context and shadow-proposal tests."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from server import agent_context
from sim.strategies.configs import config_by_id


def fixed_etf_market(con, ticker: str = "SPY") -> None:
    con.execute(
        "CREATE TABLE universe ("
        "ticker VARCHAR PRIMARY KEY, yf_ticker VARCHAR, name VARCHAR, exchange VARCHAR, "
        "etf BOOLEAN, member VARCHAR, added DATE, active BOOLEAN, liquid BOOLEAN, "
        "backfill_done BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe VALUES (?, ?, ?, 'NYSE', TRUE, NULL, DATE '2020-01-01', "
        "TRUE, TRUE, TRUE)",
        [ticker, ticker, ticker],
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES (?, DATE '2026-09-11', 100, 101, 99, 100, 1000000, 'yfinance', "
        "TIMESTAMP '2026-09-12 00:00:00')",
        [ticker],
    )
    for strategy_id in agent_context.ALLOWED_STRATEGIES:
        config = config_by_id(strategy_id)
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, "
            "execution_profile) VALUES (?, ?, ?, ?, DATE '2026-09-01', TRUE, "
            "39000, 39000, 'baseline_v1')",
            [
                config["id"],
                config["name"],
                config["strategy"],
                json.dumps(config),
            ],
        )


def complete_dual_momentum_history(con) -> date:
    """Replace fixture prices with complete, liquid dual-momentum evidence."""
    con.execute("DELETE FROM prices")
    con.execute("DELETE FROM universe")
    end = date(2026, 9, 11)
    market_dates = []
    current = end
    while len(market_dates) < 253:
        if current.weekday() < 5:
            market_dates.append(current)
        current -= timedelta(days=1)
    market_dates.reverse()
    for ticker, start_close, end_close in (
        ("SPY", 100.0, 120.0),
        ("EFA", 100.0, 110.0),
        ("BIL", 100.0, 100.0),
    ):
        con.execute(
            "INSERT INTO universe VALUES (?, ?, ?, 'NYSE', TRUE, NULL, "
            "DATE '2020-01-01', TRUE, TRUE, TRUE)",
            [ticker, ticker, ticker],
        )
        rows = []
        for index, market_date in enumerate(market_dates):
            close = start_close + (end_close - start_close) * index / 252
            rows.append(
                (
                    ticker,
                    market_date,
                    close,
                    close + 1,
                    close - 1,
                    close,
                    1_000_000,
                    "yfinance",
                    datetime(2026, 9, 12),
                )
            )
        con.executemany(
            "INSERT INTO prices "
            "(ticker, date, open, high, low, close, volume, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    con.execute(
        "CREATE TABLE IF NOT EXISTS corporate_actions ("
        "ticker VARCHAR, ex_date DATE, kind VARCHAR, value DOUBLE, "
        "source VARCHAR, fetched_at TIMESTAMP)"
    )
    con.execute("DELETE FROM corporate_actions")
    con.execute(
        "INSERT INTO corporate_actions VALUES "
        "('BIL', DATE '2026-06-01', 'dividend', 4.0, 'yfinance', "
        "TIMESTAMP '2026-09-12 00:00:00')"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS actions_fetch_log ("
        "ticker VARCHAR, fetched_on DATE, n_splits INTEGER, n_dividends INTEGER, "
        "status VARCHAR, source VARCHAR, attempted_at TIMESTAMP)"
    )
    con.execute("DELETE FROM actions_fetch_log")
    for ticker in ("SPY", "EFA", "BIL"):
        con.execute(
            "INSERT INTO actions_fetch_log VALUES (?, ?, 0, ?, 'ok', 'yfinance', ?)",
            [
                ticker,
                market_dates[-1],
                1 if ticker == "BIL" else 0,
                datetime(2026, 9, 12),
            ],
        )
    return market_dates[-1]


def context(con, strategy_id: str = "dual_momentum", ticker: str = "SPY") -> dict:
    return agent_context.build(con, strategy_id, ticker)


def proposal_body(
    context_payload: dict,
    *,
    now: datetime | None = None,
    **overrides,
) -> dict:
    now = now or datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    body = {
        "schema_version": 2,
        "proposal_id": "proposal-0001",
        "idempotency_key": "decision-window-0001",
        "mode": context_payload["policy"]["mode"],
        "policy_id": context_payload["policy"]["id"],
        "policy_registration_sha256": context_payload["policy"][
            "registration_sha256"
        ],
        "agent_id": "paper-research-agent",
        "model": context_payload["decision_model"]["model"],
        "model_version": context_payload["decision_model"]["model_version"],
        "prompt_sha256": context_payload["decision_model"]["instructions_sha256"],
        "toolset_sha256": context_payload["decision_model"]["toolset_sha256"],
        "strategy_id": context_payload["strategy"]["id"],
        "strategy_config_sha256": context_payload["strategy"]["config_sha256"],
        "agent_boundary_sha256": context_payload["provenance"]["agent_boundary_sha256"],
        "runtime_source_sha256": context_payload["provenance"]["runtime_source_sha256"],
        "data_snapshot_sha256": context_payload["provenance"]["data_snapshot_sha256"],
        "context_sha256": context_payload["context_sha256"],
        "ticker": context_payload["instrument"]["ticker"],
        "side": "buy",
        "max_notional": 1_000,
        "stop": 90,
        "confidence": 0.6,
        "signal_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "thesis": "The frozen algorithm candidate remains valid under the bounded context.",
        "invalidation": "Do not act after expiry or if the deterministic signal changes.",
        "evidence_ids": [context_payload["context_sha256"]],
    }
    body.update(overrides)
    return body
