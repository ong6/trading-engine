"""Loopback-only account-service routes with private-account bearer auth."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from threading import Lock
from typing import Annotated, Iterator

import duckdb
from fastapi import APIRouter, Header, HTTPException, Query

from engine import paper_accounts
from engine.accounts import api as account_api
from engine.accounts import service
from engine.accounts import sources as account_sources
from engine.lib import db as engine_db

from . import account_read_models
from . import db as server_db

router = APIRouter(prefix="/accounts", tags=["accounts"])
_WRITER_LOCK = Lock()


@contextmanager
def _connection(factory) -> Iterator[duckdb.DuckDBPyConnection]:
    con = factory()
    try:
        yield con
    finally:
        con.close()


def _write_con():
    try:
        return engine_db.connect(wait_s=180)
    except Exception as exc:
        if engine_db.is_lock_error(exc):
            raise server_db.DBBusyError(str(exc)) from exc
        raise


@contextmanager
def _write_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    try:
        with _WRITER_LOCK:
            with _connection(_write_con) as con:
                yield con
    except duckdb.TransactionException as exc:
        raise HTTPException(503, "account writer contention; retry",
                            headers={"Retry-After": "1"}) from exc


def _authorized(authorization: str | None) -> bool:
    return account_api.authenticated(authorization)


def _require_token(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(401, "valid account bearer token required",
                            headers={"WWW-Authenticate": "Bearer"})


def _require_account_access(con, account_id: str, authorization: str | None) -> None:
    if account_read_models.visibility(con, account_id) == "private":
        if not _authorized(authorization):
            raise HTTPException(404, "unknown account")


def _require_account_mutation(account_id: str, authorization: str | None) -> None:
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
    _require_token(authorization)


def _since(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value is not None else None
    except ValueError as exc:
        raise HTTPException(422, "since must be YYYY-MM-DD") from exc


def _invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except duckdb.TransactionException as exc:
        raise HTTPException(503, "account writer contention; retry",
                            headers={"Retry-After": "1"}) from exc
    except service.VerificationError as exc:
        raise HTTPException(409, exc.result) from exc
    except paper_accounts.AccountRefused as exc:
        status = 404 if str(exc) == "unknown account" else 409
        raise HTTPException(status, str(exc)) from exc


@router.get("")
def list_accounts(authorization: Annotated[str | None, Header()] = None):
    if authorization is not None and not _authorized(authorization):
        _require_token(authorization)
    with _connection(server_db.read_con) as con:
        return account_read_models.accounts(con, include_private=authorization is not None)


@router.post("")
def create_account(body: dict, authorization: Annotated[str | None, Header()] = None):
    _require_token(authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.create, con, body, now=received_at)


@router.get("/{account_id}")
def get_account(account_id: str, authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        with account_sources.production_sources(con):
            return _invoke(account_read_models.account, con, account_id)


@router.get("/{account_id}/positions")
def get_positions(account_id: str, authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        with account_sources.production_sources(con):
            return _invoke(account_read_models.positions, con, account_id)


@router.get("/{account_id}/orders")
def get_orders(account_id: str, since: Annotated[str | None, Query()] = None,
               authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        return _invoke(account_read_models.orders, con, account_id, since=_since(since))


@router.get("/{account_id}/fills")
def get_fills(account_id: str, since: Annotated[str | None, Query()] = None,
              authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        return _invoke(account_read_models.fills, con, account_id, since=_since(since))


@router.get("/{account_id}/cash-events")
def get_cash_events(account_id: str, since: Annotated[str | None, Query()] = None,
                    authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        return _invoke(account_read_models.cash_events, con, account_id, since=_since(since))


@router.get("/{account_id}/equity")
def get_equity(account_id: str, authorization: Annotated[str | None, Header()] = None):
    with _connection(server_db.read_con) as con:
        _invoke(_require_account_access, con, account_id, authorization)
        return _invoke(account_read_models.equity, con, account_id)


@router.get("/{account_id}/results")
def get_results(account_id: str, authorization: Annotated[str | None, Header()] = None):
    with _write_connection() as con:
        _invoke(_require_account_access, con, account_id, authorization)
        with account_sources.production_sources(con):
            return _invoke(account_read_models.result, con, account_id)


@router.post("/{account_id}/orders")
def submit_order(account_id: str, body: dict,
                 authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)  # authoritative: before writer acquisition
    if body.get("account_id") != account_id:
        raise HTTPException(422, "path and intent account identifiers differ")
    with _write_connection() as con:
        with account_sources.production_sources(con, tickers=[body.get("instrument_id", "")]):
            return _invoke(service.submit, con, body, received_at=received_at)


@router.post("/{account_id}/orders/{order_id}/cancel")
def cancel_order(account_id: str, order_id: int,
                 authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.cancel, con, account_id, order_id, now=received_at)


@router.post("/{account_id}/reconciliations")
def post_reconciliation(account_id: str, body: dict,
                        authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.reconcile, con, account_id, body, now=received_at)


@router.post("/{account_id}/halt")
def halt_account(account_id: str, body: dict | None = None,
                 authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.halt, con, account_id, note=(body or {}).get("note", ""),
                       now=received_at)


@router.post("/{account_id}/resume")
def resume_account(account_id: str, body: dict,
                   authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    if set(body) - {'by', 'note'}:
        raise HTTPException(409, 'resume is effective at receipt; a supplied effective time is not accepted')
    with _write_connection() as con:
        return _invoke(service.resume, con, account_id, resumed_by=body.get("by"),
                       note=body.get("note", ""), now=received_at)


@router.post("/{account_id}/retire")
def retire_account(account_id: str, authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.retire, con, account_id, now=received_at)


@router.post("/{account_id}/watch")
def replace_account_watch(account_id: str, body: dict,
                          authorization: Annotated[str | None, Header()] = None):
    _require_account_mutation(account_id, authorization)
    received_at = datetime.now(timezone.utc)
    with _write_connection() as con:
        return _invoke(service.replace_watch, con, account_id, body.get("tickers"),
                       now=received_at)
