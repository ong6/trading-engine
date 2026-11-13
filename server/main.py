"""FastAPI backend for the local mock-trading and research dashboard.

Binds 127.0.0.1 only, no auth (mock system). GET endpoints open the DB read-only
per request; write endpoints open read-write and map a contended write lock to
HTTP 503 (the nightly league run holds it). This server never fills orders or
steps the league — a submitted ticket becomes a *pending* sim_orders row that the
existing nightly step fills at the next open.

Run from repo root:  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import pathlib
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Annotated, Any, Iterator, Literal, TypeAlias, TypeVar
from zoneinfo import ZoneInfo

import duckdb
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse

from engine import p15_evaluation
from engine.lib.resources import write_text_atomic
from engine.lib.settings import DATA_DIR, META_PATH
from tools import agent_trial_register

from . import (
    accounts_routes,
    agent_attribution_read_models,
    agent_authority_read_models,
    agent_context,
    agent_contract,
    agent_corporate_action_observations,
    agent_evaluation,
    agent_fault_drills,
    agent_independent_price_evidence,
    agent_model_client,
    agent_paper_decisions,
    agent_policy,
    agent_policy_read_models,
    agent_price_observations,
    agent_proposal_read_models,
    agent_proposals,
    agent_provider_responses,
    agent_release_readiness,
    agent_shadow_read_models,
    agent_shadow_schedule,
    daily_opportunity_read_models,
    journal_read_models,
    league_read_models,
    market_read_models,
    meta_projection,
    order_read_models,
    p7_trial_status,
    p16_status_adapter,
    paper_read_models,
    position_read_models,
    ticket_contract,
    tickets,
)
from . import db as server_db
from . import research_readiness as readiness
from .db import DBBusyError, read_con, write_con
from .read_model_utils import (
    PUBLIC_PORTFOLIO_ID_MAX_CHARS,
    PUBLIC_SAFE_INTEGER_MAX,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_ticker,
)
from .status_validation import iso_date

T = TypeVar("T")
OrderStatus = Literal["pending", "filled", "rejected", "cancelled"]
AgentProposalStatus = Literal["shadow_accepted", "shadow_rejected"]
NONBLANK_PATTERN = r".*\S.*"
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})
HEALTH_FIELDS = frozenset({"ok", "status", "db_readable"})
HEALTH_STATUSES = frozenset({"ok", "degraded", "busy", "unreadable"})
AsgiReceive: TypeAlias = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend: TypeAlias = Callable[[dict[str, Any]], Awaitable[None]]
AsgiApp: TypeAlias = Callable[[dict[str, Any], AsgiReceive, AsgiSend], Awaitable[None]]

P15_AUDITED_TABLES = (
    "prices",
    "portfolios",
    "sim_orders",
    "sim_fills",
    "sim_equity",
    "bitemporal_facts",
    "source_response_receipts",
    "agent_evaluation_traces",
    "agent_evaluation_decisions",
    "agent_evaluation_labels_v2",
    "agent_evaluation_execution_links",
    "daily_opportunity_exit_rules",
    "daily_opportunity_exit_events",
    "p15_evaluation_origin_grid",
    "p15_evaluation_looks",
    "p15_evaluation_look_anchors",
    "p15_price_fetch_batches",
    "price_fetch_attempts",
    "p15_open_label_fetch_receipts",
    "p15_scoring_runs",
    "p15_scoring_samples",
    "p15_scoring_news_responses",
    "p15_preopen_runs",
    "p15_preopen_decisions",
    "p15_preopen_news_responses",
    "p15_execution_quality",
    "p15_book_contracts",
    "p15_book_state",
    "p15_order_intents",
    "p15_position_rules",
    "p15_limit_attempts",
    "p15_book_windows",
    "p15_book_fills",
    "p15_limit_labels",
    "p15_event_source_state",
    "p15_event_triggers",
    "p15_event_windows",
    "p15_event_calls",
    "p15_event_decisions",
    "p15_event_labels",
)
_EVALUATION_CACHE_LOCK = Lock()
_EVALUATION_CACHE: tuple[tuple, tuple[dict, dict]] | None = None
EVALUATION_CACHE_FILE = "evaluation-projection-cache.json"
# The warmer checks the newest generation this often (and at once when a request found the
# inputs changed), so a publication's new inputs are projected about a minute after it.
EVALUATION_WARM_INTERVAL_S = 60.0
EVALUATION_WARMER_ENABLED = os.environ.get("TRADING_ENGINE_EVALUATION_WARMER", "1") == "1"
_PROJECTION_STATE: ContextVar[bool | None] = ContextVar("evaluation_projection_current",
                                                       default=None)


def _is_allowed_host_header(value: str) -> bool:
    host, separator, port = value.lower().partition(":")
    return host in ALLOWED_HOSTNAMES and (
        not separator
        or (port.isascii() and port.isdecimal() and len(port) <= 5 and 1 <= int(port) <= 65_535)
    )


class ExactHostMiddleware:
    """Reject requests not addressed to the two documented loopback origins."""

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if scope["type"] == "http":
            hosts = [
                value.decode("latin-1").lower()
                for name, value in scope["headers"]
                if name.lower() == b"host"
            ]
            if len(hosts) != 1 or not _is_allowed_host_header(hosts[0]):
                await PlainTextResponse("Invalid host header", status_code=400)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class DataSourceHeaderMiddleware:
    """Identify responses served from an immutable database snapshot."""

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with server_db.response_data_source() as state:
            async def send_with_source(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start" and state["source"] == "snapshot":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-data-source", b"snapshot"))
                    headers.append(
                        (b"x-snapshot-as-of", str(state["snapshot_as_of"]).encode("ascii"))
                    )
                    headers.append(
                        (b"x-generation-id", str(state["generation_id"]).encode("ascii"))
                    )
                    served = state.get("generation") or {}
                    headers.append(
                        (b"x-generation-stale", b"true" if served.get("stale") else b"false")
                    )
                    pending = served.get("pending_publication")
                    headers.append((
                        b"x-pending-publication",
                        b"unknown" if pending is None else b"true" if pending else b"false",
                    ))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_source)


app = FastAPI(title="trading-engine paper backend", version="0.1.0")
app.add_middleware(ExactHostMiddleware)
app.add_middleware(DataSourceHeaderMiddleware)
app.include_router(accounts_routes.router)


@contextmanager
def _connection(factory: Callable[[], T]) -> Iterator[T]:
    """Own one request-scoped connection and always close it."""
    con = factory()
    try:
        yield con
    finally:
        con.close()


def _require_json_content_type(
    content_type: Annotated[str, Header()],
) -> None:
    """Force browser mutations through a non-simple, JSON request boundary."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "mutation requests require application/json")


JSON_MUTATION_DEPENDENCY = [Depends(_require_json_content_type)]


def _validated_portfolio_id(value: str) -> str:
    try:
        return require_public_portfolio_id(value)
    except ValueError as exc:
        raise HTTPException(422, "portfolio identifier is invalid") from exc


def _validated_ticker(value: str) -> str:
    try:
        return require_public_ticker(value.upper())
    except ValueError as exc:
        raise HTTPException(422, "ticker is invalid") from exc


def _validated_ticket_id(value: int) -> int:
    try:
        return require_public_positive_integer(value)
    except ValueError as exc:
        raise HTTPException(422, "ticket identifier is invalid") from exc


# The modules that compute the evaluation projection. Their code identity covers them and
# every repo-local module they import, transitively (tools.affected_tests.import_closure):
# a change to any of it invalidates a persisted projection even when the registration and
# the evidence did not change.
EVALUATION_CODE_ROOTS = (
    "engine/p15_evaluation.py",
    "server/agent_evaluation.py",
    "server/main.py",
    "server/p16_status_adapter.py",
    "tools/agent_trial_register.py",
)
_EVALUATION_ET = ZoneInfo("America/New_York")
_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]


def evaluation_code_files(root: pathlib.Path = _REPOSITORY_ROOT) -> tuple[str, ...]:
    from tools.affected_tests import import_closure

    return import_closure(EVALUATION_CODE_ROOTS, root)


def _evaluation_code_sha256(root: pathlib.Path = _REPOSITORY_ROOT) -> str:
    digest = hashlib.sha256()
    for relative in evaluation_code_files(root):
        digest.update(relative.encode() + b"\0")
        digest.update(hashlib.sha256((root / relative).read_bytes()).digest())
    return digest.hexdigest()


@functools.cache
def evaluation_code_sha256() -> str:
    """This process's projection code identity: the code this process imported."""
    return _evaluation_code_sha256()


# Fixed when the API process imports this module (about 2 s), not on the first request, so a
# checkout that changes in between cannot label the old code's projection with the new code.
evaluation_code_sha256()


def _evaluation_clock(generated_at: datetime) -> tuple[str, str]:
    """The projection's dependence on the evaluation time.

    Maturity and the missing-label grace (p15_evaluation ``_mature``) count observed sessions
    through the UTC evaluation date, event maturity counts them through the New York date,
    and every other cutoff compares stored timestamps, all at or before the generation's
    capture. Every maturity or label-grace boundary is therefore a change of one of these two
    dates, so keying on both invalidates the projection at each boundary (and at most twice
    a day otherwise).
    """
    utc = generated_at.astimezone(timezone.utc)
    return utc.date().isoformat(), utc.astimezone(_EVALUATION_ET).date().isoformat()


def _evaluation_table_signatures(con: duckdb.DuckDBPyConnection) -> tuple:
    """A content signature of every table the projection reads.

    A served generation carries each table's logical SHA-256 in its manifest (cold tables
    through their append-only part fingerprints), so an in-place correction changes the
    signature at no read cost. A connection without a generation (tests, tools) hashes the
    rows themselves: count plus an order-independent sum of row hashes.
    """
    info = getattr(con, "generation_info", None)
    published = ((info.source_snapshot or {}).get("table_sha256") if info is not None else None)
    if published:
        return tuple((table, published.get(f"main.{table}")) for table in P15_AUDITED_TABLES)
    present = {row[0] for row in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()}
    signatures = []
    for table in P15_AUDITED_TABLES:
        if table not in present:
            signatures.append((table, None))
            continue
        count, content = con.execute(
            f'SELECT COUNT(*), CAST(COALESCE(SUM(hash(t)), 0) AS VARCHAR) FROM "{table}" t'
        ).fetchone()
        signatures.append((table, f"{int(count)}:{content}"))
    return tuple(signatures)


def _evaluation_generation_key(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> tuple:
    """Identity of every input to the evidence validation and projection: registration,
    projection code, evaluation dates and the content of every audited table."""
    return (
        p15_evaluation.registration_sha256(),
        evaluation_code_sha256(),
        _evaluation_clock(generated_at),
        _evaluation_table_signatures(con),
    )


def _compute_p15_projection(con, generated_at: datetime) -> tuple[dict, dict]:
    evidence_status = agent_evaluation.validate_p15_evidence(con, generated_at) or {}
    p15 = p16_status_adapter.with_primary_kill(
        p15_evaluation.project(con, generated_at=generated_at),
    )
    return evidence_status, p15


def _cache_path():
    """Beside the primary, or ``TRADING_ENGINE_EVALUATION_CACHE`` (empty: memory only)."""
    override = os.environ.get("TRADING_ENGINE_EVALUATION_CACHE")
    if override is not None:
        return None if override == "" else pathlib.Path(override)
    return server_db.db_path().with_name(EVALUATION_CACHE_FILE)


def _store_evaluation_cache(key: tuple, value: tuple[dict, dict]) -> None:
    """Keep the projection in memory and on disk, keyed by the identity of its inputs."""
    global _EVALUATION_CACHE
    with _EVALUATION_CACHE_LOCK:
        _EVALUATION_CACHE = key, deepcopy(value)
    path = _cache_path()
    if path is None:
        return
    try:
        write_text_atomic(path, json.dumps(
            {"key": jsonable_encoder(key), "value": jsonable_encoder(value)}, sort_keys=True,
        ))
    except OSError:
        pass  # the in-memory copy still serves; the next process recomputes once


def _loaded_evaluation_cache() -> tuple | None:
    """The in-memory projection, or the one a previous API process left on disk."""
    global _EVALUATION_CACHE
    with _EVALUATION_CACHE_LOCK:
        if _EVALUATION_CACHE is not None:
            return _EVALUATION_CACHE
    path = _cache_path()
    if path is None:
        return None
    try:
        stored = json.loads(path.read_text())
        key = _json_key(stored["key"])
        value = tuple(stored["value"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    with _EVALUATION_CACHE_LOCK:
        if _EVALUATION_CACHE is None:
            _EVALUATION_CACHE = key, value
        return _EVALUATION_CACHE


def _json_key(key) -> tuple:
    return tuple(json.loads(json.dumps(jsonable_encoder(key))))


def _cached_p15_projection(
    con: duckdb.DuckDBPyConnection, generated_at: datetime,
) -> tuple[dict, dict]:
    """The P15 projection for the served generation's evidence inputs.

    The cache is keyed by the identity of the inputs (registration, projection code,
    evaluation dates and each audited table's content signature), so a republication that
    changed none of them reuses it, in
    this process or, through the file beside the primary, in the next one. When the inputs
    changed, the previous projection is served (flagged by ``evaluation_projection_current``)
    while the background warmer recomputes it, so no request waits for the cold projection;
    only a store that never had one computes it in the request.
    """
    key = _json_key(_evaluation_generation_key(con, generated_at))
    cached = _loaded_evaluation_cache()
    if cached is not None and cached[0] == key:
        _PROJECTION_STATE.set(True)
        return deepcopy(cached[1])
    if cached is not None:
        _PROJECTION_STATE.set(False)
        _evaluation_warmer.request()
        return deepcopy(cached[1])
    value = _compute_p15_projection(con, generated_at)
    _store_evaluation_cache(key, value)
    _PROJECTION_STATE.set(True)
    return deepcopy(value)


class _EvaluationWarmer:
    """Recompute the projection off the request path whenever its inputs change."""

    def __init__(self) -> None:
        self._wake = Event()
        self._started = False
        self._lock = Lock()

    def request(self) -> None:
        with self._lock:
            if not self._started and EVALUATION_WARMER_ENABLED:
                Thread(target=self._run, name="evaluation-warmer", daemon=True).start()
                self._started = True
        self._wake.set()

    def warm_once(self) -> bool:
        """Recompute for the newest generation if its inputs changed; True if it did."""
        try:
            con = read_con()
        except DBBusyError:
            return False
        try:
            now = datetime.now(timezone.utc)
            key = _json_key(_evaluation_generation_key(con, now))
            cached = _loaded_evaluation_cache()
            if cached is not None and cached[0] == key:
                return False
            _store_evaluation_cache(key, _compute_p15_projection(con, now))
            return True
        finally:
            con.close()

    def _run(self) -> None:  # pragma: no cover - exercised by the rehearsal, not unit tests
        while True:
            self._wake.wait(EVALUATION_WARM_INTERVAL_S)
            self._wake.clear()
            try:
                self.warm_once()
            except Exception:  # noqa: BLE001 - a failed warm leaves the previous projection
                time.sleep(EVALUATION_WARM_INTERVAL_S)


_evaluation_warmer = _EvaluationWarmer()


def _reset_evaluation_cache() -> None:
    global _EVALUATION_CACHE
    with _EVALUATION_CACHE_LOCK:
        _EVALUATION_CACHE = None


@app.exception_handler(DBBusyError)
async def _busy_handler(_request: Request, _exc: DBBusyError):
    return JSONResponse(
        status_code=503,
        content={"detail": "database busy (nightly run?) — retry later"},
    )


# --------------------------------------------------------------------------- #
# health / meta
# --------------------------------------------------------------------------- #
def _validate_health_payload(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != HEALTH_FIELDS:
        raise ValueError("public health projection shape is invalid")
    status = payload["status"]
    readable = status in {"ok", "degraded"}
    if (
        status not in HEALTH_STATUSES
        or type(payload["ok"]) is not bool
        or type(payload["db_readable"]) is not bool
        or payload["ok"] != readable
        or payload["db_readable"] != readable
    ):
        raise ValueError("public health projection is inconsistent")


@app.get("/health")
def health():
    status = "ok"
    try:
        with _connection(read_con) as con:
            con.execute("SELECT 1")
            served = server_db.served_generation()
            if served is not None and served["stale"]:
                status = "degraded"  # readable, but the newest generation is past its budget
    except DBBusyError:
        status = "busy"
    except Exception:  # noqa: BLE001 - health must fail closed for any unreadable store
        status = "unreadable"
    readable = status in {"ok", "degraded"}
    payload = {
        "ok": readable,
        "status": status,
        "db_readable": readable,
    }
    _validate_health_payload(payload)
    return payload if readable else JSONResponse(status_code=503, content=payload)


@app.get("/meta")
def meta():
    with _connection(read_con) as con:
        projection = meta_projection.project(con, meta_path=META_PATH, data_dir=DATA_DIR)
        return {**projection, "generation": server_db.served_generation()}


@app.get("/research/readiness")
def research_readiness():
    with _connection(read_con) as con:
        return readiness.assess(con)


@app.get("/screen/latest")
def screen_latest(page: Annotated[int, Query(ge=1, le=1_000_000)] = 1):
    with _connection(read_con) as con:
        market_date = market_read_models.latest_prices_date(con)
        payload = (
            None
            if market_date is None
            else market_read_models.screen(con, through=market_date, page=page)
        )
        if payload is None:
            raise HTTPException(404, "no screen_results")
        return payload


@app.get("/screen/{run_date}")
def screen_by_date(
    run_date: str,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
):
    try:
        parsed_date = iso_date(run_date)
    except ValueError as exc:
        raise HTTPException(400, "run_date must be YYYY-MM-DD") from exc
    with _connection(read_con) as con:
        payload = market_read_models.screen(con, parsed_date, page=page)
        if payload is None:
            raise HTTPException(404, f"no screen for {run_date}")
        return payload


# --------------------------------------------------------------------------- #
# league
# --------------------------------------------------------------------------- #
@app.get("/league")
def league():
    with _connection(read_con) as con:
        return league_read_models.league(con)


@app.get("/league/equities")
def league_equities():
    with _connection(read_con) as con:
        return league_read_models.equities(con)


@app.get("/league/{portfolio_id}/equity")
def league_equity(
    portfolio_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=PUBLIC_PORTFOLIO_ID_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ],
):
    portfolio_id = _validated_portfolio_id(portfolio_id)
    with _connection(read_con) as con:
        payload = league_read_models.equity(con, portfolio_id)
        if payload is None:
            raise HTTPException(404, f"no equity for {portfolio_id}")
        return payload


# --------------------------------------------------------------------------- #
# candidates
# --------------------------------------------------------------------------- #
@app.get("/candidates/{ticker}")
def candidate(
    ticker: Annotated[
        str,
        Path(
            min_length=1,
            max_length=ticket_contract.TICKER_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ],
):
    ticker = _validated_ticker(ticker)
    with _connection(read_con) as con:
        try:
            payload = market_read_models.candidate(con, ticker)
        except market_read_models.InadmissiblePriceData as exc:
            raise HTTPException(422, detail=exc.detail) from exc
        if payload is None:
            raise HTTPException(404, f"no price bars for {ticker}")
        return payload


# --------------------------------------------------------------------------- #
# positions
# --------------------------------------------------------------------------- #
@app.get("/positions")
def positions(
    portfolio: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=PUBLIC_PORTFOLIO_ID_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ] = None,
):
    if portfolio is not None:
        portfolio = _validated_portfolio_id(portfolio)
    with _connection(read_con) as con:
        payload = position_read_models.positions(con, portfolio, discretionary_id=tickets.DISC_ID)
        if payload is None:
            raise HTTPException(404, f"no active portfolio {portfolio}")
        return payload


# --------------------------------------------------------------------------- #
# orders
# --------------------------------------------------------------------------- #
@app.get("/orders")
def orders(status: Annotated[OrderStatus | None, Query()] = None):
    with _connection(read_con) as con:
        return order_read_models.orders(con, status)


# --------------------------------------------------------------------------- #
# journal
# --------------------------------------------------------------------------- #
@app.get("/journal")
def journal():
    with _connection(read_con) as con:
        return journal_read_models.journal(con)


@app.get("/tickets/context")
def ticket_context():
    with _connection(read_con) as con:
        return paper_read_models.ticket_context(con)


@app.get("/agent/context")
def paper_agent_context(
    strategy_id: Annotated[
        str,
        Query(
            min_length=1,
            max_length=agent_contract.IDENTIFIER_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ],
    ticker: Annotated[
        str,
        Query(
            min_length=1,
            max_length=agent_contract.PUBLIC_TICKER_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ],
    policy_id: Annotated[
        str,
        Query(
            min_length=1,
            max_length=agent_contract.IDENTIFIER_MAX_CHARS,
            pattern=NONBLANK_PATTERN,
        ),
    ] = "dual_momentum_agent_shadow_v1",
):
    with _connection(read_con) as con:
        try:
            return agent_context.build(
                con,
                strategy_id,
                ticker,
                policy_id=policy_id,
            )
        except agent_context.ContextError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.get("/agent/data/daily-prices")
def agent_daily_price_observation_status():
    with _connection(read_con) as con:
        try:
            return agent_price_observations.status(con)
        except agent_price_observations.ObservationError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/data/corporate-actions")
def agent_corporate_action_observation_status():
    with _connection(read_con) as con:
        try:
            return agent_corporate_action_observations.status(con)
        except agent_corporate_action_observations.ObservationError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/data/provider-responses")
def agent_provider_response_status():
    with _connection(read_con) as con:
        try:
            return agent_provider_responses.status(con)
        except agent_provider_responses.ProviderResponseError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/data/independent-price-evidence")
def agent_independent_price_evidence_status():
    with _connection(read_con) as con:
        try:
            return agent_independent_price_evidence.status(con)
        except agent_independent_price_evidence.IndependentPriceEvidenceError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/proposals")
def agent_proposal_ledger(
    status: Annotated[AgentProposalStatus | None, Query()] = None,
):
    with _connection(read_con) as con:
        return agent_proposal_read_models.proposals(con, status)


@app.get("/agent/model/status")
def agent_model_status():
    try:
        return agent_model_client.status()
    except agent_model_client.ConnectorError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/agent/policies/evaluation")
def agent_policy_evaluation():
    with _connection(read_con) as con:
        try:
            return agent_policy_read_models.evaluation(con)
        except agent_policy.PolicyError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/attribution")
def agent_decision_attribution():
    with _connection(read_con) as con:
        try:
            return agent_attribution_read_models.attribution(con)
        except agent_policy.PolicyError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/authority/readiness")
def agent_authority_readiness():
    release_status = agent_release_readiness.inspect()
    with _connection(read_con) as con:
        try:
            return agent_authority_read_models.readiness(
                con,
                release_status=release_status,
            )
        except agent_policy.PolicyError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/fault-drills")
def agent_fault_drill_status():
    with _connection(read_con) as con:
        try:
            return agent_fault_drills.status(con)
        except agent_fault_drills.FaultDrillError as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/agent/shadow/attempts")
def agent_shadow_attempt_ledger():
    with _connection(read_con) as con:
        return agent_shadow_read_models.attempts(con)


@app.get("/agent/shadow/control")
def agent_shadow_control_status():
    try:
        return agent_shadow_schedule.control_status()
    except agent_shadow_schedule.ScheduleError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/paper-trial/status")
def paper_trial_status():
    with _connection(read_con) as con:
        try:
            return p7_trial_status.project(con)
        except p7_trial_status.TrialStatusError as exc:
            raise HTTPException(503, "paper trial status unavailable") from exc


@app.get("/daily-opportunities/status")
def daily_opportunity_status():
    with _connection(read_con) as con:
        return daily_opportunity_read_models.status(con)


@app.get("/agent/evaluation/status")
def agent_evaluation_status():
    with server_db.require_fresh_evidence_snapshot():
        with _connection(read_con) as con:
            try:
                generated_at = datetime.now(timezone.utc)
                evidence_status, p15 = _cached_p15_projection(con, generated_at)
                result = {**agent_evaluation.status(con), **evidence_status,
                          "schema_version": 3, **p15,
                          "trial_count_register": agent_trial_register.project(con, generated_at)}
            except (OSError, ValueError, agent_evaluation.EvaluationError) as exc:
                raise HTTPException(503, "agent evaluation status unavailable") from exc
            served = server_db.served_generation()
            if served is not None:
                served = {**served, "evaluation_projection_current": _PROJECTION_STATE.get()}
            return {**result, "p16": p16_status_adapter.project(con, generated_at=generated_at),
                    "generation": served}


@app.post("/agent/proposals/shadow", dependencies=JSON_MUTATION_DEPENDENCY)
def submit_shadow_agent_proposal(body: agent_contract.TradeProposalRequest):
    with _connection(write_con) as con:
        try:
            return agent_proposals.submit(con, asdict(body))
        except agent_contract.ProposalError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc


@app.post("/agent/paper/decisions", dependencies=JSON_MUTATION_DEPENDENCY)
def consume_agent_paper_decision(
    body: agent_paper_decisions.PaperDecisionRequest,
    x_agent_paper_token: Annotated[str | None, Header(max_length=512)] = None,
):
    try:
        agent_paper_decisions.authenticate(x_agent_paper_token)
    except agent_paper_decisions.PaperDecisionError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    with _connection(write_con) as con:
        try:
            return agent_paper_decisions.consume(
                con,
                body.decision_window,
                confirmation=body.confirmation,
            )
        except agent_paper_decisions.PaperDecisionError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        except duckdb.Error as exc:
            for _attempt in range(5):
                try:
                    replay = agent_paper_decisions.replay_after_contention(
                        con, body.decision_window
                    )
                except (duckdb.Error, agent_paper_decisions.PaperDecisionError):
                    replay = None
                if replay is not None:
                    return replay
                time.sleep(0.01)
            raise HTTPException(503, "agent paper decision contention; retry") from exc


@app.post("/tickets", dependencies=JSON_MUTATION_DEPENDENCY)
def create_ticket(body: ticket_contract.TicketRequest):
    with _connection(write_con) as con:
        try:
            return tickets.create(con, asdict(body))
        except ticket_contract.TicketError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc


@app.post("/tickets/{ticket_id}/cancel", dependencies=JSON_MUTATION_DEPENDENCY)
def cancel_ticket(ticket_id: Annotated[int, Path(ge=1, le=PUBLIC_SAFE_INTEGER_MAX)]):
    ticket_id = _validated_ticket_id(ticket_id)
    with _connection(write_con) as con:
        try:
            return tickets.cancel(con, ticket_id)
        except ticket_contract.TicketError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc


@app.post("/review-done", dependencies=JSON_MUTATION_DEPENDENCY)
def review_done():
    with _connection(write_con) as con:
        return tickets.mark_review_done(con)
