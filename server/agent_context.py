"""Deterministic, bounded context for shadow agent proposals."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib.data_quality import data_snapshot, quarantine_reason
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256, runtime_source_hash
from engine.lib.settings import REPO_ROOT
from engine.lib.util import table_exists
from sim.strategies.configs import config_by_id

from . import (
    agent_algorithm_candidate,
    agent_corporate_action_observations,
    agent_data_contract,
    agent_model_client,
    agent_policy,
    agent_price_observations,
    agent_provider_responses,
)
from .json_utils import loads_object
from .market_read_models import latest_prices_date
from .read_model_utils import require_public_ticker

CONTEXT_SCHEMA_VERSION = 10
ALLOWED_STRATEGIES = frozenset(
    {
        "dual_momentum",
        "dual_momentum_gated",
        "sector_momentum",
    }
)
BOUNDARY_FILES = (
    "engine/verify_prices.py",
    "server/agent-shadow-registration.json",
    "server/agent_algorithm_candidate.py",
    "server/agent_attribution_read_models.py",
    "server/agent_authority_read_models.py",
    "server/agent_contract.py",
    "server/agent_context.py",
    "server/agent_corporate_action_observations.py",
    "server/agent_data_contract.py",
    "server/agent_data_discrepancy_adjudication.py",
    "server/agent_decision_contract.py",
    "server/agent_fault_drills.py",
    "server/agent_independent_price_evidence.py",
    "server/agent_model_client.py",
    "server/agent_paper_attribution.py",
    "server/agent_paper_book_plan.py",
    "server/agent_paper_book_preflight.py",
    "server/agent_paper_evidence.py",
    "server/agent_policy.py",
    "server/agent_policy_read_models.py",
    "server/agent_price_observations.py",
    "server/agent_provider_responses.py",
    "server/agent_proposal_read_models.py",
    "server/agent_proposal_validation.py",
    "server/agent_proposals.py",
    "server/agent_release_readiness.py",
    "server/agent_release_review_store.py",
    "server/agent_shadow_read_models.py",
    "server/agent_shadow_runner.py",
    "server/agent_shadow_schedule.py",
    "server/agent_shadow_store.py",
    "server/agent_store.py",
    "server/agent_veto_contract.py",
    "server/main.py",
)


class ContextError(ValueError):
    """The requested bounded context cannot be built from admitted data."""


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value: date) -> str:
    return value.isoformat()


def _boundary_sha256(repo_root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256()
    for relative in BOUNDARY_FILES:
        path = repo_root / relative
        if path.is_symlink() or not path.is_file():
            raise ContextError("agent boundary source is unavailable")
        encoded = relative.encode()
        content = path.read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _strategy(strategy_id: str) -> dict:
    if strategy_id not in ALLOWED_STRATEGIES:
        raise ContextError("strategy is not admitted for agent shadow proposals")
    try:
        config = config_by_id(strategy_id)
    except KeyError as exc:  # pragma: no cover - allowlist and registry must move together
        raise ContextError("strategy registration is missing") from exc
    if config.get("active", True) is not True:
        raise ContextError("strategy is not active")
    params = config.get("params")
    if not isinstance(params, dict):
        raise ContextError("strategy parameters are invalid")
    return config


def _allowed_tickers(config: dict) -> frozenset[str]:
    params = config["params"]
    values: list[str] = []
    for field in ("assets", "sectors"):
        raw = params.get(field, [])
        if isinstance(raw, list):
            values.extend(value for value in raw if isinstance(value, str))
    for field in ("cash_proxy", "ticker"):
        value = params.get(field)
        if isinstance(value, str):
            values.append(value)
    return frozenset(values)


def _lookbacks(config: dict) -> tuple[int, ...]:
    params = config["params"]
    raw = params.get("lookbacks")
    if raw is None:
        raw = [params.get("lookback")]
    if (
        not isinstance(raw, list)
        or not raw
        or len(raw) > 3
        or any(isinstance(value, bool) or not isinstance(value, int) for value in raw)
        or any(value < 1 or value > 252 for value in raw)
        or len(set(raw)) != len(raw)
    ):
        raise ContextError("strategy lookbacks are invalid")
    return tuple(sorted(raw))


def _registration(con: duckdb.DuckDBPyConnection, config: dict) -> dict:
    row = con.execute(
        "SELECT strategy, config, active, initial_cash, execution_profile "
        "FROM portfolios WHERE id = ?",
        [config["id"]],
    ).fetchone()
    if row is None or row[2] is not True:
        raise ContextError("strategy portfolio is not active")
    try:
        stored_config = loads_object(row[1])
    except (TypeError, ValueError) as exc:
        raise ContextError("strategy portfolio registration is invalid") from exc
    config_sha256 = canonical_sha256(config)
    if row[0] != config["strategy"] or canonical_sha256(stored_config) != config_sha256:
        raise ContextError("strategy portfolio registration does not match source")
    initial_cash = row[3]
    if (
        isinstance(initial_cash, bool)
        or not isinstance(initial_cash, (int, float))
        or not math.isfinite(initial_cash)
        or initial_cash <= 0
    ):
        raise ContextError("strategy portfolio initial capital is invalid")
    execution_profile = row[4]
    if (
        not isinstance(execution_profile, str)
        or not execution_profile.strip()
        or execution_profile != execution_profile.strip()
        or len(execution_profile) > 128
        or not execution_profile.isprintable()
    ):
        raise ContextError("strategy portfolio execution profile is invalid")
    return {
        "id": config["id"],
        "active": True,
        "initial_cash": float(initial_cash),
        "shadow_max_notional": float(initial_cash),
        "execution_profile": execution_profile,
        "config_sha256": config_sha256,
    }


def _unavailable_feature(
    ticker: str,
    market_date: date,
    lookbacks: tuple[int, ...],
    observed_sessions: int,
    reason: str,
) -> dict:
    return {
        "schema_version": 1,
        "ticker": ticker,
        "as_of": _date(market_date),
        "status": "unavailable",
        "unavailable_reason": reason,
        "calculation": "unreinvested_cash_total_return_v1",
        "formula": "(end_close + cash_dividends_ex_after_start_through_end) / start_close - 1",
        "required_session_count": max(lookbacks) + 1,
        "observed_session_count": observed_sessions,
        "lookbacks": [],
        "corporate_action_coverage": None,
        "feature_sha256": None,
    }


def _action_coverage(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
) -> dict | None:
    if not table_exists(con, "corporate_actions") or not table_exists(
        con, "actions_fetch_log"
    ):
        return None
    row = con.execute(
        "SELECT fetched_on, status, source, attempted_at, n_splits, n_dividends "
        "FROM actions_fetch_log WHERE ticker = ? "
        "ORDER BY fetched_on DESC, attempted_at DESC NULLS LAST LIMIT 1",
        [ticker],
    ).fetchone()
    if (
        row is None
        or row[0] < market_date
        or row[1] not in {"ok", "empty"}
        or row[2] != agent_data_contract.SOURCE_NAME
        or type(row[3]) is not datetime
        or isinstance(row[4], bool)
        or not isinstance(row[4], int)
        or row[4] < 0
        or isinstance(row[5], bool)
        or not isinstance(row[5], int)
        or row[5] < 0
    ):
        return None
    record = {
        "ticker": ticker,
        "through_market_date": _date(market_date),
        "fetched_on": _date(row[0]),
        "attempt_status": row[1],
        "source": row[2],
        "attempted_at": _timestamp(row[3]),
        "reported_split_count": row[4],
        "reported_dividend_count": row[5],
    }
    return {**record, "record_sha256": canonical_sha256(record)}


def _price_fact(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    row: tuple,
) -> dict:
    try:
        observation_row = (ticker, *row)
        value = {
            "ticker": ticker,
            "market_date": row[0].isoformat(),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]),
            "source": row[6],
        }
        source_observation = agent_provider_responses.source_observation_for_fact(
            con,
            dataset="daily_price",
            ticker=ticker,
            fact_date=row[0],
            kind="daily_price",
            value_sha256=canonical_sha256(value),
        )
        immutable_observation = (
            source_observation
            or agent_price_observations.observation_for_price_row(
                con, observation_row
            )
        )
        provider_evidence = (
            agent_provider_responses.evidence_for_observation(
                con, immutable_observation["observation_sha256"]
            )
            if immutable_observation is not None
            else None
        )
        return agent_data_contract.daily_price_fact(
            ticker=ticker,
            market_date=row[0],
            open_price=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            source=row[6],
            fetched_at=(
                datetime.fromisoformat(
                    source_observation["source_fetched_at"].replace(
                        "Z", "+00:00"
                    )
                )
                if source_observation is not None
                else row[7]
            ),
            immutable_observation=immutable_observation,
            provider_evidence=provider_evidence,
        )
    except (
        agent_data_contract.DataContractError,
        agent_price_observations.ObservationError,
        agent_provider_responses.ProviderResponseError,
    ) as exc:
        raise ContextError(str(exc)) from exc


def _dividends(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    start: date,
    end: date,
) -> list[dict]:
    result = []
    for row in con.execute(
        "SELECT ex_date, value, source, fetched_at FROM corporate_actions "
        "WHERE ticker = ? AND kind = 'dividend' AND ex_date > ? AND ex_date <= ? "
        "ORDER BY ex_date",
        [ticker, start, end],
    ).fetchall():
        try:
            observation_row = (ticker, row[0], "dividend", *row[1:])
            value_record = {
                "ticker": ticker,
                "ex_date": row[0].isoformat(),
                "kind": "dividend",
                "value": float(row[1]),
                "source": row[2],
            }
            source_observation = (
                agent_provider_responses.source_observation_for_fact(
                    con,
                    dataset="corporate_action",
                    ticker=ticker,
                    fact_date=row[0],
                    kind="dividend",
                    value_sha256=canonical_sha256(value_record),
                )
            )
            immutable_observation = (
                source_observation
                or agent_corporate_action_observations.observation_for_action_row(
                    con, observation_row
                )
            )
            provider_evidence = (
                agent_provider_responses.evidence_for_observation(
                    con, immutable_observation["observation_sha256"]
                )
                if immutable_observation is not None
                else None
            )
            result.append(
                agent_data_contract.dividend_fact(
                    ticker=ticker,
                    ex_date=row[0],
                    value=row[1],
                    source=row[2],
                    fetched_at=(
                        datetime.fromisoformat(
                            source_observation["source_fetched_at"].replace(
                                "Z", "+00:00"
                            )
                        )
                        if source_observation is not None
                        else row[3]
                    ),
                    immutable_observation=immutable_observation,
                    provider_evidence=provider_evidence,
                )
            )
        except (
            agent_corporate_action_observations.ObservationError,
            agent_data_contract.DataContractError,
            agent_provider_responses.ProviderResponseError,
        ) as exc:
            raise ContextError(str(exc)) from exc
    return result


def _momentum_feature(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
    lookbacks: tuple[int, ...],
) -> dict:
    eligibility = con.execute(
        "SELECT active, liquid, etf FROM universe WHERE ticker = ?",
        [ticker],
    ).fetchone()
    if eligibility is None or eligibility != (True, True, True):
        return _unavailable_feature(
            ticker, market_date, lookbacks, 0, "instrument_not_active_liquid_etf"
        )
    quarantine = quarantine_reason(con, ticker)
    if quarantine:
        return _unavailable_feature(
            ticker, market_date, lookbacks, 0, "instrument_quarantined"
        )
    required = max(lookbacks) + 1
    price_rows = con.execute(
        "SELECT date, open, high, low, close, volume, source, fetched_at "
        "FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?",
        [ticker, market_date, required],
    ).fetchall()
    if len(price_rows) < required or not price_rows or price_rows[0][0] != market_date:
        return _unavailable_feature(
            ticker,
            market_date,
            lookbacks,
            len(price_rows),
            "insufficient_or_stale_price_history",
        )
    coverage = _action_coverage(con, ticker, market_date)
    if coverage is None:
        return _unavailable_feature(
            ticker,
            market_date,
            lookbacks,
            len(price_rows),
            "corporate_action_coverage_unavailable",
        )
    end_fact = _price_fact(con, ticker, price_rows[0])
    values = []
    for lookback in lookbacks:
        start_fact = _price_fact(con, ticker, price_rows[lookback])
        start_date = price_rows[lookback][0]
        dividends = _dividends(con, ticker, start_date, market_date)
        dividend_cash = sum(
            item["record"]["normalized"]["cash_per_share"] for item in dividends
        )
        start_close = start_fact["record"]["normalized"]["close"]
        end_close = end_fact["record"]["normalized"]["close"]
        total_return = (end_close + dividend_cash) / start_close - 1
        if not math.isfinite(total_return):
            raise ContextError("derived total return is not finite")
        calculation = {
            "sessions": lookback,
            "start_price": start_fact,
            "end_price": end_fact,
            "dividends": dividends,
            "cash_dividends_per_share": dividend_cash,
            "total_return": total_return,
        }
        values.append(
            {**calculation, "calculation_sha256": canonical_sha256(calculation)}
        )
    feature = {
        "schema_version": 1,
        "ticker": ticker,
        "as_of": _date(market_date),
        "status": "complete",
        "unavailable_reason": None,
        "calculation": "unreinvested_cash_total_return_v1",
        "formula": "(end_close + cash_dividends_ex_after_start_through_end) / start_close - 1",
        "required_session_count": required,
        "observed_session_count": len(price_rows),
        "lookbacks": values,
        "corporate_action_coverage": coverage,
    }
    return {**feature, "feature_sha256": canonical_sha256(feature)}


def _decision_features(
    con: duckdb.DuckDBPyConnection,
    config: dict,
    market_date: date,
) -> dict:
    lookbacks = _lookbacks(config)
    tickers = sorted(_allowed_tickers(config))
    if not tickers or len(tickers) > 16:
        raise ContextError("strategy instrument universe is invalid")
    assets = [
        _momentum_feature(con, ticker, market_date, lookbacks) for ticker in tickers
    ]
    return {
        "schema_version": 1,
        "kind": "registered_universe_total_returns",
        "strategy_id": config["id"],
        "as_of": _date(market_date),
        "lookback_sessions": list(lookbacks),
        "required_tickers": tickers,
        "complete_tickers": [
            asset["ticker"] for asset in assets if asset["status"] == "complete"
        ],
        "assets": assets,
    }


def _instrument(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
) -> dict:
    row = con.execute(
        "SELECT active, liquid, etf FROM universe WHERE ticker = ?",
        [ticker],
    ).fetchone()
    if row is None or row[0] is not True or row[1] is not True or row[2] is not True:
        raise ContextError("instrument is not an active liquid ETF")
    quote = con.execute(
        f"SELECT date, open, high, low, close, volume, source, fetched_at FROM prices "
        f"WHERE ticker = ? AND date <= ? AND {REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 1",
        [ticker, market_date],
    ).fetchone()
    if quote is None or quote[0] != market_date or quote[4] is None:
        raise ContextError("instrument has no current eligible quote")
    close = float(quote[4])
    if not math.isfinite(close) or close <= 0:
        raise ContextError("instrument quote is not positive and finite")
    source = quote[6]
    fetched_at = quote[7]
    quarantine = quarantine_reason(con, ticker)
    if quarantine:
        raise ContextError(f"instrument is quarantined: {quarantine}")
    try:
        value = {
            "ticker": ticker,
            "market_date": quote[0].isoformat(),
            "open": float(quote[1]),
            "high": float(quote[2]),
            "low": float(quote[3]),
            "close": float(quote[4]),
            "volume": int(quote[5]),
            "source": source,
        }
        source_observation = agent_provider_responses.source_observation_for_fact(
            con,
            dataset="daily_price",
            ticker=ticker,
            fact_date=quote[0],
            kind="daily_price",
            value_sha256=canonical_sha256(value),
        )
        immutable_observation = (
            source_observation
            or agent_price_observations.observation_for_price_row(
                con, (ticker, *quote)
            )
        )
        provider_evidence = (
            agent_provider_responses.evidence_for_observation(
                con, immutable_observation["observation_sha256"]
            )
            if immutable_observation is not None
            else None
        )
        data_contract = agent_data_contract.daily_price_fact(
            ticker=ticker,
            market_date=quote[0],
            open_price=quote[1],
            high=quote[2],
            low=quote[3],
            close=quote[4],
            volume=quote[5],
            source=source,
            fetched_at=(
                datetime.fromisoformat(
                    source_observation["source_fetched_at"].replace(
                        "Z", "+00:00"
                    )
                )
                if source_observation is not None
                else fetched_at
            ),
            immutable_observation=immutable_observation,
            provider_evidence=provider_evidence,
        )
    except (
        agent_data_contract.DataContractError,
        agent_price_observations.ObservationError,
        agent_provider_responses.ProviderResponseError,
    ) as exc:
        raise ContextError(str(exc)) from exc
    return {
        "ticker": ticker,
        "active": True,
        "liquid": True,
        "etf": True,
        "quote_date": _date(quote[0]),
        "close": close,
        "source": source,
        "fetched_at": _timestamp(fetched_at),
        "quarantine": None,
        "data_contract": data_contract,
    }


def build(
    con: duckdb.DuckDBPyConnection,
    strategy_id: str,
    ticker: str,
    *,
    policy_id: str = "dual_momentum_agent_shadow_v1",
    repo_root: Path = REPO_ROOT,
    policy_path: Path = agent_policy.REGISTRATION_PATH,
    allow_reserved_portfolio: bool = False,
) -> dict:
    """Build the exact server-derived context one proposal must echo."""
    config = _strategy(strategy_id)
    try:
        policy = agent_policy.get(policy_id, path=policy_path)
    except agent_policy.PolicyError as exc:
        raise ContextError(str(exc)) from exc
    if policy["strategy_id"] != strategy_id:
        raise ContextError("agent policy does not match the requested strategy")
    if ticker not in policy["allowed_symbols"]:
        raise ContextError("ticker is not allowlisted by the agent policy")
    try:
        ticker = require_public_ticker(ticker)
    except ValueError as exc:
        raise ContextError("ticker is invalid") from exc
    if ticker != ticker.upper() or ticker not in _allowed_tickers(config):
        raise ContextError("ticker is not allowlisted by the strategy registration")
    registration = _registration(con, config)
    try:
        agent_policy.validate_live_registration(
            con,
            policy,
            allow_reserved_portfolio=allow_reserved_portfolio,
        )
    except agent_policy.PolicyError as exc:
        raise ContextError(str(exc)) from exc
    registration["shadow_max_notional"] = min(
        registration["shadow_max_notional"],
        policy["max_order_notional"],
    )
    market_date = latest_prices_date(con)
    if market_date is None:
        raise ContextError("no breadth-qualified market date")

    source_sha256, source_file_count = runtime_source_hash(repo_root)
    snapshot = data_snapshot(con)
    try:
        algorithm_candidate = (
            agent_algorithm_candidate.materialize(
                con,
                policy,
                market_date,
                allow_reserved_portfolio=allow_reserved_portfolio,
            )
            if policy["mode"] == "hybrid"
            else None
        )
    except agent_algorithm_candidate.CandidateError as exc:
        raise ContextError(str(exc)) from exc
    body = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "execution_authority": "none",
        "mode": "shadow",
        "market_date": _date(market_date),
        "policy": {
            "id": policy["id"],
            "registration_sha256": policy["registration_sha256"],
            "registry_sha256": policy["registry_sha256"],
            "mode": policy["mode"],
            "authority_stage": policy["authority_stage"],
            "reserved_portfolio_id": policy["reserved_portfolio_id"],
            "control_id": policy["control_id"],
            "cadence": policy["cadence"],
            "model_role": policy["model_role"],
            "model_failure_policy": policy["model_failure_policy"],
            "hybrid_behavior": policy["hybrid_behavior"],
            "allowed_symbols": policy["allowed_symbols"],
            "capital_ceiling": policy["capital_ceiling"],
            "max_order_notional": policy["max_order_notional"],
            "execution_profile_id": policy["execution_profile_id"],
            "execution_profile_sha256": policy["execution_profile_sha256"],
            "attribution": policy["attribution"],
            "generation_enabled": policy["generation_enabled"],
            "execution_authority": "none",
        },
        "strategy": {
            "id": config["id"],
            "implementation": config["strategy"],
            "cadence": config["cadence"],
            "params": config["params"],
            "config_sha256": canonical_sha256(config),
        },
        "portfolio": registration,
        "instrument": _instrument(con, ticker, market_date),
        "decision_features": _decision_features(con, config, market_date),
        "algorithm_candidate": algorithm_candidate,
        "decision_model": agent_model_client.identity(
            role="veto" if policy["mode"] == "hybrid" else "proposal"
        ),
        "provenance": {
            "agent_boundary_sha256": _boundary_sha256(repo_root),
            "runtime_source_sha256": source_sha256,
            "runtime_source_file_count": source_file_count,
            "data_snapshot_sha256": snapshot["sha256"],
        },
    }
    return {**body, "context_sha256": canonical_sha256(body)}
