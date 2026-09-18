"""FastAPI backend for the local mock-trading and research dashboard.

Binds 127.0.0.1 only, no auth (mock system). GET endpoints open the DB read-only
per request; write endpoints open read-write and map a contended write lock to
HTTP 503 (the nightly league run holds it). This server never fills orders or
steps the league — a submitted ticket becomes a *pending* sim_orders row that the
existing nightly step fills at the next open.

Run from repo root:  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Any, Iterator, Literal, TypeAlias, TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from engine.lib.settings import DATA_DIR, META_PATH

from . import (
    agent_attribution_read_models,
    agent_authority_read_models,
    agent_context,
    agent_contract,
    agent_corporate_action_observations,
    agent_fault_drills,
    agent_independent_price_evidence,
    agent_model_client,
    agent_policy,
    agent_policy_read_models,
    agent_price_observations,
    agent_proposal_read_models,
    agent_proposals,
    agent_provider_responses,
    agent_release_readiness,
    agent_shadow_read_models,
    agent_shadow_schedule,
    journal_read_models,
    league_read_models,
    market_read_models,
    meta_projection,
    order_read_models,
    paper_read_models,
    position_read_models,
    ticket_contract,
    tickets,
)
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
HEALTH_STATUSES = frozenset({"ok", "busy", "unreadable"})
AsgiReceive: TypeAlias = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend: TypeAlias = Callable[[dict[str, Any]], Awaitable[None]]
AsgiApp: TypeAlias = Callable[[dict[str, Any], AsgiReceive, AsgiSend], Awaitable[None]]


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


app = FastAPI(title="trading-engine paper backend", version="0.1.0")
app.add_middleware(ExactHostMiddleware)


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
    readable = status == "ok"
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
    except DBBusyError:
        status = "busy"
    except Exception:  # noqa: BLE001 - health must fail closed for any unreadable store
        status = "unreadable"
    readable = status == "ok"
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
        return meta_projection.project(con, meta_path=META_PATH, data_dir=DATA_DIR)


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
        payload = market_read_models.candidate(con, ticker)
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


@app.post("/agent/proposals/shadow", dependencies=JSON_MUTATION_DEPENDENCY)
def submit_shadow_agent_proposal(body: agent_contract.TradeProposalRequest):
    with _connection(write_con) as con:
        try:
            return agent_proposals.submit(con, asdict(body))
        except agent_contract.ProposalError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc


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
