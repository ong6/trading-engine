"""Engine-owned, separately funded paper accounts for opaque external strategy specs.

Private producers submit specifications and timely requests, never balances or fills.
Callers hold the engine's single DuckDB writer. No provider, broker, model or strategy runs
here. Existing league next-open fills/accounting remain the sole execution implementation.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine.free_massive_minute import session_close
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from sim import nyse, portfolio
from sim.execution import DEFAULT_PROFILE_ID
from sim.schema import init_sim_schema

TIERS = frozenset({10_000, 50_000, 100_000})
INSTRUMENTS = frozenset({"stock", "etf"})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SPEC_FIELDS = frozenset({"schema_version", "strategy_ref", "spec_sha256", "registration_sha256",
                         "instrument_kind", "capital_usd", "account_id", "max_position_fraction",
                         "max_gross_fraction", "min_trade_usd"})
INTENT_FIELDS = frozenset({"schema_version", "intent_id", "account_id", "spec_sha256",
                           "registration_sha256", "instrument_kind", "ticker", "side",
                           "quantity", "signal_date", "created_at", "source_sha256"})


class AccountRefused(ValueError):
    """An account or request fails a deterministic paper admission rule."""


def _positive(value, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise AccountRefused(f"{field} must be a finite positive number")
    return float(value)


def _identity(value, field: str, pattern=IDENTIFIER) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AccountRefused(f"invalid {field}")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise AccountRefused("timestamp must include its timezone")
    return value.astimezone(timezone.utc)


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or set(spec) != SPEC_FIELDS or spec["schema_version"] != 1:
        raise AccountRefused("invalid account specification v1")
    for field in ("strategy_ref", "account_id"):
        _identity(spec[field], field)
    for field in ("spec_sha256", "registration_sha256"):
        _identity(spec[field], field, SHA256)
    if spec["instrument_kind"] not in INSTRUMENTS:
        raise AccountRefused("unsupported execution instrument: only stock/etf paper fills exist")
    if type(spec["capital_usd"]) is not int or spec["capital_usd"] not in TIERS:
        raise AccountRefused("capital must be an independent USD 10000, 50000 or 100000 tier")
    position = _positive(spec["max_position_fraction"], "max_position_fraction")
    gross = _positive(spec["max_gross_fraction"], "max_gross_fraction")
    minimum = _positive(spec["min_trade_usd"], "min_trade_usd")
    if not position <= gross <= 1 or minimum > spec["capital_usd"] * position:
        raise AccountRefused("position/gross/minimum constraints are infeasible")
    return dict(spec)


def init_schema(con) -> None:
    init_sim_schema(con)
    con.execute("CREATE TABLE IF NOT EXISTS paper_account_specs ("
                "account_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL, "
                "sha256 VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS paper_account_intakes ("
                "intent_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, "
                "order_id BIGINT UNIQUE NOT NULL, payload VARCHAR NOT NULL, "
                "sha256 VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL)")


def create_account(con, spec: dict, *, now: datetime) -> dict:
    spec, now = validate_spec(spec), _utc(now)
    account_id, digest = spec["account_id"], canonical_sha256(spec)
    with db.transaction(con):
        init_schema(con)
        old = con.execute("SELECT payload,sha256 FROM paper_account_specs WHERE account_id=?",
                          [account_id]).fetchone()
        if old is not None:
            if old != (json.dumps(spec, sort_keys=True), digest):
                raise AccountRefused("account identity already bound to a different specification")
            return {"account_id": account_id, "replayed": True, "specification_sha256": digest}
        if con.execute("SELECT 1 FROM portfolios WHERE id=?", [account_id]).fetchone():
            raise AccountRefused("existing portfolio cannot be re-funded or rebound")
        capital = spec["capital_usd"]
        config = {"id": account_id, "strategy": "discretionary", "cadence": "daily",
                  "external_specification_sha256": digest, "params": {}}
        con.execute("INSERT INTO portfolios VALUES (?,?,?,?,?,FALSE,?,?,?)",
                    [account_id, account_id, "discretionary", json.dumps(config, sort_keys=True),
                     now.date(), capital, capital, DEFAULT_PROFILE_ID])
        con.execute("INSERT INTO paper_account_specs VALUES (?,?,?,?)",
                    [account_id, json.dumps(spec, sort_keys=True), digest, now])
    return {"account_id": account_id, "replayed": False, "specification_sha256": digest}


def _load_spec(con, account_id: str) -> dict:
    row = con.execute("SELECT payload,sha256 FROM paper_account_specs WHERE account_id=?",
                      [account_id]).fetchone()
    if row is None:
        raise AccountRefused("account has no admitted specification")
    spec = validate_spec(json.loads(row[0]))
    if canonical_sha256(spec) != row[1] or spec["account_id"] != account_id:
        raise AccountRefused("account specification identity differs")
    pf = con.execute("SELECT initial_cash,strategy,config FROM portfolios WHERE id=?",
                     [account_id]).fetchone()
    if (pf is None or pf[0] != spec["capital_usd"] or pf[1] != "discretionary"
            or json.loads(pf[2]).get("external_specification_sha256") != row[1]):
        raise AccountRefused("engine portfolio differs from admitted specification")
    return spec


def validate_intent(intent: dict, spec: dict, now: datetime) -> tuple[date, float]:
    """Pure envelope/clock admission; callers can preview without a database."""
    spec, now = validate_spec(spec), _utc(now)
    if not isinstance(intent, dict) or set(intent) != INTENT_FIELDS or intent["schema_version"] != 1:
        raise AccountRefused("invalid trade intent v1")
    for field in ("intent_id", "account_id", "ticker"):
        _identity(intent[field], field)
    _identity(intent["source_sha256"], "source_sha256", SHA256)
    for field in ("account_id", "spec_sha256", "registration_sha256", "instrument_kind"):
        if intent[field] != spec[field]:
            raise AccountRefused(f"intent {field} differs from account specification")
    if intent["instrument_kind"] not in INSTRUMENTS or intent["side"] not in {"buy", "sell"}:
        raise AccountRefused("unsupported execution instrument or side")
    quantity = _positive(intent["quantity"], "quantity")
    try:
        signal_date = date.fromisoformat(intent["signal_date"])
        created = _utc(datetime.fromisoformat(intent["created_at"]))
    except (TypeError, ValueError) as exc:
        raise AccountRefused("invalid intent clock") from exc
    next_open = datetime.combine(nyse.next_session(signal_date), time(9, 30),
                                 ZoneInfo("America/New_York")).astimezone(timezone.utc)
    close = datetime.combine(signal_date, session_close(signal_date), ZoneInfo("America/New_York"))
    if not nyse.is_session(signal_date) or not close <= created <= now < next_open:
        raise AccountRefused("intent is late, future-dated or not after the signal close")
    return signal_date, quantity


def _capacity(con, spec: dict, intent: dict, signal_date: date, quantity: float) -> None:
    account, ticker = spec["account_id"], intent["ticker"]
    row = con.execute("SELECT close FROM prices WHERE ticker=? AND date=?",
                      [ticker, signal_date]).fetchone()
    if row is None:
        raise AccountRefused("no exact signal-session reference price")
    price = _positive(row[0], "reference close")
    positions = portfolio.get_positions(con, account)
    pending = con.execute("SELECT ticker,side,qty FROM sim_orders "
                          "WHERE portfolio_id=? AND status='pending'", [account]).fetchall()
    if any(t == ticker and side == intent["side"] for t, side, _q in pending):
        raise AccountRefused("same account already has a pending order for this leg")
    held = positions.get(ticker, {}).get("qty", 0)
    if intent["side"] == "sell":
        if quantity > held:
            raise AccountRefused("sell exceeds this account's holdings")
        return
    requested = quantity * price
    values = {}
    for name, position in positions.items():
        close, carried = portfolio.close_on(con, name, signal_date)
        if close is None or carried:
            raise AccountRefused("held account position lacks an exact reference mark")
        values[name] = position["qty"] * _positive(close, "held close")
    reserved = _reserved_buys(con, pending, signal_date)
    cash = portfolio.get_cash(con, account)
    equity = cash + sum(values.values())
    gross = sum(values.values()) + sum(reserved.values()) + requested
    position_value = values.get(ticker, 0) + reserved.get(ticker, 0) + requested
    if (requested < spec["min_trade_usd"] or requested + sum(reserved.values()) > cash
            or gross > equity * spec["max_gross_fraction"]
            or position_value > equity * spec["max_position_fraction"]):
        raise AccountRefused("intent exceeds this account's cash/position/gross/minimum constraints")


def _reserved_buys(con, pending: list, signal_date: date) -> dict:
    reserved = {}
    for ticker, side, quantity in pending:
        if side != "buy":
            continue
        row = con.execute("SELECT close FROM prices WHERE ticker=? AND date=?",
                          [ticker, signal_date]).fetchone()
        if row is None:
            raise AccountRefused("pending order lacks an exact reference mark")
        reserved[ticker] = reserved.get(ticker, 0) + quantity * _positive(row[0], "pending close")
    return reserved


def submit_intent(con, intent: dict, *, now: datetime) -> dict:
    now = _utc(now)
    if not isinstance(intent, dict) or set(intent) != INTENT_FIELDS:
        raise AccountRefused("invalid trade intent v1")
    digest = canonical_sha256(intent)
    with db.transaction(con):
        spec = _load_spec(con, intent["account_id"])
        previous = con.execute("SELECT account_id,order_id,sha256 FROM paper_account_intakes "
                               "WHERE intent_id=?", [intent["intent_id"]]).fetchone()
        if previous is not None:
            if previous[0] != intent["account_id"] or previous[2] != digest:
                raise AccountRefused("intent identifier already bound to different evidence")
            return {"order_id": previous[1], "replayed": True}
        signal_date, quantity = validate_intent(intent, spec, now)
        latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        if latest != signal_date:
            raise AccountRefused("intent must use the current stored signal session")
        _capacity(con, spec, intent, signal_date, quantity)
        order_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM sim_orders").fetchone()[0]
        con.execute("INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
                    [order_id, intent["account_id"], intent["ticker"], intent["side"],
                     quantity, signal_date])
        con.execute("INSERT INTO paper_account_intakes VALUES (?,?,?,?,?,?)",
                    [intent["intent_id"], intent["account_id"], order_id,
                     json.dumps(intent, sort_keys=True), digest, now])
        con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [intent["account_id"]])
        portfolio.mark_to_market(con, intent["account_id"], signal_date)
    return {"order_id": order_id, "replayed": False}
