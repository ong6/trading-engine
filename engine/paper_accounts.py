"""Engine-owned paper-account specifications and order intake.

The private alpha supplies immutable specifications and intents.  This module
validates them and writes only engine state; it never runs a strategy or talks
to a broker.  Callers own the single DuckDB writer and stamp ``received_at``
before acquiring that writer.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine.free_massive_minute import session_close
from engine.instruments import Instrument, ensure
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from sim import nyse, portfolio
from sim import schema as sim_schema
from sim.costs import IBKR_PRO_TIERED_V1
from sim.execution import DEFAULT_PROFILE_ID
from sim.order_types import OrderTimingError, OrderType, cutoff_at, validate_received_at

TIERS = frozenset({10_000, 50_000, 100_000})
V1_INSTRUMENTS = frozenset({"stock", "etf"})
INSTRUMENTS = frozenset({"stock", "etf", "option", "future"})
EXECUTABLE_INSTRUMENTS = V1_INSTRUMENTS
DAY_TRADE_RULES = frozenset({"pdt_25k_legacy", "intraday_margin_2026"})
PRICE_SOURCES = frozenset({"prices", "massive_daily"})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
SHA256 = re.compile(r"[0-9a-f]{64}")
V1_SPEC_FIELDS = frozenset({
    "schema_version", "strategy_ref", "spec_sha256", "registration_sha256",
    "instrument_kind", "capital_usd", "account_id", "max_position_fraction",
    "max_gross_fraction", "min_trade_usd",
})
V2_SPEC_FIELDS = frozenset({
    "schema_version", "strategy_ref", "strategy_version", "spec_sha256",
    "artifact_sha256", "registration_sha256", "instrument_kinds", "capital_usd",
    "account_id", "account_type", "max_position_fraction", "max_gross_fraction",
    "min_trade_usd", "allow_short", "price_source", "benchmark",
    "day_trades_per_week_expected", "day_trade_rule", "whole_shares",
})
V2_SPEC_OPTIONAL_FIELDS = frozenset({"day_trade_rule", "whole_shares"})
V1_INTENT_FIELDS = frozenset({
    "schema_version", "intent_id", "account_id", "spec_sha256",
    "registration_sha256", "instrument_kind", "ticker", "side", "quantity",
    "signal_date", "created_at", "source_sha256",
})
V2_INTENT_FIELDS = frozenset({
    "schema_version", "intent_id", "account_id", "spec_sha256",
    "registration_sha256", "instrument_id", "instrument_kind", "side", "quantity",
    "order_type", "limit_price", "time_in_force", "session_date", "contingent_on",
    "legs", "created_at", "source_sha256",
})
NEW_YORK = ZoneInfo("America/New_York")


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


def _session_on_or_before(value: datetime) -> date:
    session = value.astimezone(NEW_YORK).date()
    while not nyse.is_session(session):
        session = date.fromordinal(session.toordinal() - 1)
    return session


def _validate_limits(spec: dict, *, gross_ceiling: float) -> None:
    position = _positive(spec["max_position_fraction"], "max_position_fraction")
    gross = _positive(spec["max_gross_fraction"], "max_gross_fraction")
    minimum = _positive(spec["min_trade_usd"], "min_trade_usd")
    if not position <= gross <= gross_ceiling or minimum > spec["capital_usd"] * position:
        raise AccountRefused("position/gross/minimum constraints are infeasible")


def validate_spec(spec: dict) -> dict:
    """Validate and normalize an exact v1 or v2 account specification."""
    if not isinstance(spec, dict) or type(spec.get("schema_version")) is not int:
        raise AccountRefused("invalid account specification")
    version = spec["schema_version"]
    if version == 1:
        if set(spec) != V1_SPEC_FIELDS:
            raise AccountRefused("invalid account specification v1")
        for field in ("strategy_ref", "account_id"):
            _identity(spec[field], field)
        for field in ("spec_sha256", "registration_sha256"):
            _identity(spec[field], field, SHA256)
        if spec["instrument_kind"] not in V1_INSTRUMENTS:
            raise AccountRefused("unsupported execution instrument: only stock/etf paper fills exist")
        if type(spec["capital_usd"]) is not int or spec["capital_usd"] not in TIERS:
            raise AccountRefused("capital must be an independent USD 10000, 50000 or 100000 tier")
        _validate_limits(spec, gross_ceiling=1.0)
        return dict(spec)
    if version != 2 or not (V2_SPEC_FIELDS - V2_SPEC_OPTIONAL_FIELDS) <= set(spec) \
            or not set(spec) <= V2_SPEC_FIELDS:
        raise AccountRefused("invalid account specification v2")
    normalized = {**spec, "day_trade_rule": spec.get("day_trade_rule", "pdt_25k_legacy")}
    for field in ("strategy_ref", "strategy_version", "account_id"):
        _identity(normalized[field], field)
    for field in ("spec_sha256", "artifact_sha256", "registration_sha256"):
        _identity(normalized[field], field, SHA256)
    kinds = normalized["instrument_kinds"]
    if (not isinstance(kinds, list) or not kinds or any(kind not in INSTRUMENTS for kind in kinds)
            or len(kinds) != len(set(kinds))):
        raise AccountRefused("instrument_kinds must be a non-empty unique supported list")
    if type(normalized["capital_usd"]) is not int or normalized["capital_usd"] not in TIERS:
        raise AccountRefused("capital must be an independent USD 10000, 50000 or 100000 tier")
    if normalized["account_type"] != "margin":
        raise AccountRefused("account_type must be margin")
    if type(normalized["allow_short"]) is not bool:
        raise AccountRefused("allow_short must be boolean")
    if normalized["price_source"] not in PRICE_SOURCES or normalized["benchmark"] != "SPY":
        raise AccountRefused("unsupported price source or benchmark")
    expected = normalized["day_trades_per_week_expected"]
    if type(expected) is not int or expected < 0:
        raise AccountRefused("day_trades_per_week_expected must be a non-negative integer")
    if normalized["day_trade_rule"] not in DAY_TRADE_RULES:
        raise AccountRefused("unsupported day_trade_rule")
    if "whole_shares" in normalized and type(normalized["whole_shares"]) is not bool:
        raise AccountRefused("whole_shares must be boolean")
    _validate_limits(normalized, gross_ceiling=1.5)
    return normalized


def init_schema(con) -> None:
    """Initialize L0 simulation tables and additive account-service tables."""
    sim_schema.init_sim_schema(con)
    con.execute("CREATE TABLE IF NOT EXISTS paper_account_specs ("
                "account_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL, "
                "sha256 VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL)")
    con.execute("ALTER TABLE paper_account_specs ADD COLUMN IF NOT EXISTS schema_version "
                "INTEGER DEFAULT 1")
    con.execute("CREATE TABLE IF NOT EXISTS paper_account_intakes ("
                "intent_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, "
                "order_id BIGINT UNIQUE NOT NULL, payload VARCHAR NOT NULL, "
                "sha256 VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL)")
    con.execute("ALTER TABLE paper_account_intakes ADD COLUMN IF NOT EXISTS receipt VARCHAR")
    con.execute("CREATE TABLE IF NOT EXISTS account_state ("
                "portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL, "
        "prior_close_equity DOUBLE, drawdown_anchor_equity DOUBLE, "
        "halted_at TIMESTAMP, halt_reason VARCHAR, "
                "resumed_at TIMESTAMP, resumed_by VARCHAR, pdt_flagged_at TIMESTAMP, "
                "pdt_restricted_until DATE, retired_at TIMESTAMP, updated_at TIMESTAMP NOT NULL)")
    con.execute("ALTER TABLE account_state ADD COLUMN IF NOT EXISTS "
                "drawdown_anchor_equity DOUBLE")
    con.execute("CREATE TABLE IF NOT EXISTS account_events ("
                "id BIGINT PRIMARY KEY, portfolio_id VARCHAR, kind VARCHAR, "
                "payload VARCHAR, created_at TIMESTAMP)")
    con.execute("CREATE TABLE IF NOT EXISTS account_reconciliations ("
                "portfolio_id VARCHAR, session_date DATE, expected_sha256 VARCHAR, "
                "observed_sha256 VARCHAR, status VARCHAR, detail VARCHAR, "
                "created_at TIMESTAMP, PRIMARY KEY (portfolio_id, session_date))")
    con.execute("CREATE TABLE IF NOT EXISTS account_watch ("
                "portfolio_id VARCHAR, ticker VARCHAR, created_at TIMESTAMP NOT NULL, "
                "PRIMARY KEY (portfolio_id, ticker))")


def _v2_binding(spec: dict) -> dict:
    return {key: value for key, value in spec.items() if key != "artifact_sha256"}


def create_account(con, spec: dict, *, now: datetime) -> dict:
    spec, now = validate_spec(spec), _utc(now)
    account_id, digest = spec["account_id"], canonical_sha256(spec)
    with db.transaction(con):
        init_schema(con)
        old = con.execute(
            "SELECT payload,sha256 FROM paper_account_specs WHERE account_id=?", [account_id]
        ).fetchone()
        if old is not None:
            stored = validate_spec(json.loads(old[0]))
            same = old == (json.dumps(spec, sort_keys=True), digest)
            if spec["schema_version"] == 2:
                same = _v2_binding(stored) == _v2_binding(spec)
            if not same:
                raise AccountRefused("account identity already bound to a different specification")
            _load_spec(con, account_id)
            return {"account_id": account_id, "replayed": True,
                    "specification_sha256": old[1]}
        if con.execute("SELECT 1 FROM portfolios WHERE id=?", [account_id]).fetchone():
            raise AccountRefused("existing portfolio cannot be re-funded or rebound")
        capital = spec["capital_usd"]
        v2 = spec["schema_version"] == 2
        config = {"id": account_id, "strategy": "discretionary", "cadence": "daily",
                  "external_specification_sha256": digest, "params": {}}
        con.execute(
            "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
            "execution_profile) VALUES (?,?,?,?,?,FALSE,?,?,?)",
            [account_id, account_id, "discretionary", json.dumps(config, sort_keys=True),
             _session_on_or_before(now), capital, capital, DEFAULT_PROFILE_ID],
        )
        sim_schema.set_portfolio_account(
            con,
            account_id,
            engine="account" if v2 else "league",
            cost_profile=IBKR_PRO_TIERED_V1.id if v2 else "baseline_v1",
            account_type=spec.get("account_type", "cash_legacy"),
            visibility="private" if v2 else "public",
            status="inactive",
            price_source=spec.get("price_source", "prices"),
            day_trade_rule=spec.get("day_trade_rule", "pdt_25k_legacy"),
            allow_short=spec.get("allow_short", False),
            updated_at=now,
        )
        con.execute(
            "INSERT INTO paper_account_specs "
            "(account_id,payload,sha256,created_at,schema_version) VALUES (?,?,?,?,?)",
            [account_id, json.dumps(spec, sort_keys=True), digest, now, spec["schema_version"]],
        )
        con.execute(
            "INSERT INTO account_state (portfolio_id,peak_equity,prior_close_equity,"
            "drawdown_anchor_equity,updated_at) VALUES (?,?,?,?,?)",
            [account_id, capital, capital, capital, now],
        )
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
    if spec["schema_version"] == 2:
        settings = sim_schema.portfolio_account(con, account_id)
        if any((settings["engine"] != "account",
                settings["account_type"] != spec["account_type"],
                settings["price_source"] != spec["price_source"],
                settings["day_trade_rule"] != spec["day_trade_rule"],
                settings["allow_short"] is not spec["allow_short"])):
            raise AccountRefused("engine portfolio differs from admitted specification")
    return spec


def _validate_v1_intent(intent: dict, spec: dict, now: datetime) -> tuple[date, float]:
    if set(intent) != V1_INTENT_FIELDS:
        raise AccountRefused("invalid trade intent v1")
    for field in ("intent_id", "account_id", "ticker"):
        _identity(intent[field], field)
    _identity(intent["source_sha256"], "source_sha256", SHA256)
    for field in ("account_id", "spec_sha256", "registration_sha256", "instrument_kind"):
        if intent[field] != spec[field]:
            raise AccountRefused(f"intent {field} differs from account specification")
    if intent["instrument_kind"] not in V1_INSTRUMENTS or intent["side"] not in {"buy", "sell"}:
        raise AccountRefused("unsupported execution instrument or side")
    quantity = _positive(intent["quantity"], "quantity")
    try:
        signal_date = date.fromisoformat(intent["signal_date"])
        created = _utc(datetime.fromisoformat(intent["created_at"]))
    except (TypeError, ValueError) as exc:
        raise AccountRefused("invalid intent clock") from exc
    next_open = datetime.combine(nyse.next_session(signal_date), time(9, 30), NEW_YORK) \
        .astimezone(timezone.utc)
    close = datetime.combine(signal_date, session_close(signal_date), NEW_YORK)
    if not nyse.is_session(signal_date) or not close <= created <= now < next_open:
        raise AccountRefused("intent is late, future-dated or not after the signal close")
    return signal_date, quantity


def _validate_leg(leg: object) -> None:
    if not isinstance(leg, dict) or set(leg) != {"instrument_id", "side", "ratio"}:
        raise AccountRefused("invalid multi-leg order")
    _identity(leg["instrument_id"], "leg instrument_id")
    if leg["side"] not in {"buy", "sell", "short", "cover"}:
        raise AccountRefused("invalid leg side")
    if type(leg["ratio"]) is not int or leg["ratio"] == 0:
        raise AccountRefused("leg ratio must be a non-zero integer")


def _validate_v2_intent(intent: dict, spec: dict, received_at: datetime) -> tuple[date, float]:
    if set(intent) != V2_INTENT_FIELDS:
        raise AccountRefused("invalid trade intent v2")
    for field in ("intent_id", "account_id", "instrument_id"):
        _identity(intent[field], field)
    for field in ("source_sha256", "spec_sha256", "registration_sha256"):
        _identity(intent[field], field, SHA256)
    for field in ("account_id", "spec_sha256", "registration_sha256"):
        if intent[field] != spec[field]:
            raise AccountRefused(f"intent {field} differs from account specification")
    if intent["instrument_kind"] not in spec["instrument_kinds"]:
        raise AccountRefused("intent instrument_kind differs from account specification")
    if intent["side"] not in {"buy", "sell", "short", "cover"}:
        raise AccountRefused("unsupported execution side")
    if intent["side"] == "short" and not spec["allow_short"]:
        raise AccountRefused("account does not allow short sales")
    quantity = _positive(intent["quantity"], "quantity")
    if spec.get("whole_shares") and not quantity.is_integer():
        raise AccountRefused("account requires whole-share quantity")
    try:
        session_date = date.fromisoformat(intent["session_date"])
        _utc(datetime.fromisoformat(intent["created_at"]))
        order_type = OrderType(intent["order_type"])
        validate_received_at(order_type, session_date, received_at)
    except (TypeError, ValueError, OrderTimingError) as exc:
        raise AccountRefused("invalid intent clock or order type") from exc
    if intent["time_in_force"] != "day":
        raise AccountRefused("time_in_force must be day")
    if order_type is OrderType.LIMIT:
        _positive(intent["limit_price"], "limit_price")
    elif intent["limit_price"] is not None:
        raise AccountRefused("limit_price is only valid for limit orders")
    if not isinstance(intent["legs"], list):
        raise AccountRefused("legs must be a list")
    for leg in intent["legs"]:
        _validate_leg(leg)
    contingent = intent["contingent_on"]
    if contingent is not None:
        _identity(contingent, "contingent_on")
        if contingent == intent["intent_id"]:
            raise AccountRefused("an intent cannot be contingent on itself")
    return session_date, quantity


def validate_intent(intent: dict, spec: dict, now: datetime) -> tuple[date, float]:
    """Pure envelope and clock admission; ``now`` is the engine receipt stamp."""
    spec, now = validate_spec(spec), _utc(now)
    if not isinstance(intent, dict) or type(intent.get("schema_version")) is not int \
            or intent["schema_version"] != spec["schema_version"]:
        raise AccountRefused("invalid trade intent")
    if spec["schema_version"] == 1:
        return _validate_v1_intent(intent, spec, now)
    return _validate_v2_intent(intent, spec, now)


def _reference_date(spec: dict, intent: dict, session_date: date) -> date:
    if spec["schema_version"] == 1 or intent.get("order_type") == "next_open":
        return session_date
    previous = date.fromordinal(session_date.toordinal() - 1)
    while not nyse.is_session(previous):
        previous = date.fromordinal(previous.toordinal() - 1)
    return previous


def _marked_values(con, spec: dict, positions: dict, as_of: date) -> dict[str, float]:
    from sim import valuation

    return {name: float(position['qty']) * valuation.mark(
        con, spec['account_id'], name, as_of, price_source=spec.get('price_source', 'prices'),
    ).price for name, position in positions.items()}


def _reserved_orders(con, spec: dict, pending: list, as_of: date) -> dict[str, float]:
    from sim import valuation

    reserved: dict[str, float] = {}
    for ticker, side, quantity in pending:
        if side in {'buy', 'short'}:
            observed = valuation.mark(con, spec['account_id'], ticker, as_of,
                                      price_source=spec.get('price_source', 'prices'))
            reserved[ticker] = reserved.get(ticker, 0.0) + abs(quantity * observed.price)
    return reserved


def _contingent_parent(con, intent: dict, session_date: date, quantity: float) -> int | None:
    parent_intent = intent.get("contingent_on")
    if parent_intent is None:
        return None
    row = con.execute(
        "SELECT i.order_id,i.account_id,o.ticker,o.side,o.qty,o.signal_date,o.status,d.state,"
        "d.order_type,d.received_at "
        "FROM paper_account_intakes i JOIN sim_orders o ON o.id=i.order_id "
        "LEFT JOIN sim_order_details d ON d.order_id=o.id WHERE i.intent_id=?",
        [parent_intent],
    ).fetchone()
    if row is None:
        raise AccountRefused("contingent parent is unavailable")
    instrument_id = intent.get("ticker", intent.get("instrument_id"))
    expected_parent_side = {"sell": "buy", "cover": "short"}.get(intent["side"])
    if expected_parent_side is None:
        raise AccountRefused("only sell or cover may be contingent")
    if row[1] != intent["account_id"]:
        raise AccountRefused("contingent parent belongs to another account")
    if row[2] != instrument_id or row[5] != session_date:
        raise AccountRefused("contingent parent instrument or session differs")
    if row[3] != expected_parent_side:
        raise AccountRefused("contingent parent side is incompatible")
    if row[6] != "pending" or row[7] != "queued":
        raise AccountRefused("contingent parent is not queued")
    if quantity > float(row[4]):
        raise AccountRefused("contingent child exceeds parent quantity")
    phase = {"moo": 0, "market": 1, "limit": 1, "moc": 2, "next_open": 3}
    parent_phase = phase.get(row[8])
    child_phase = phase.get(intent["order_type"])
    if parent_phase is None or child_phase is None or parent_phase > child_phase:
        raise AccountRefused("contingent parent executes later than child")
    if row[8] == "limit" and intent["order_type"] == "market":
        raise AccountRefused("contingent parent executes later than child")
    return int(row[0])


def _capacity(con, spec: dict, intent: dict, session_date: date, quantity: float,
              *, contingent_parent: int | None = None) -> None:
    account = spec["account_id"]
    ticker = intent.get("ticker", intent.get("instrument_id"))
    reference_date = _reference_date(spec, intent, session_date)
    from sim import valuation

    price = valuation.mark(con, account, ticker, reference_date,
                           price_source=spec.get('price_source', 'prices')).price
    positions = portfolio.get_positions(con, account)
    pending = con.execute(
        "SELECT ticker,side,qty FROM sim_orders WHERE portfolio_id=? AND status='pending'",
        [account],
    ).fetchall()
    if any(name == ticker and side == intent["side"] for name, side, _qty in pending):
        raise AccountRefused("same account already has a pending order for this leg")
    held = float(positions.get(ticker, {}).get("qty", 0.0))
    side = intent["side"]
    if contingent_parent is not None:
        return
    if side == "sell" and quantity > max(held, 0.0):
        raise AccountRefused("sell exceeds this account's holdings")
    if side == "cover" and quantity > max(-held, 0.0):
        raise AccountRefused("cover exceeds this account's short position")
    if side in {"sell", "cover"}:
        return
    requested = quantity * price
    values = _marked_values(con, spec, positions, reference_date)
    reserved = _reserved_orders(con, spec, pending, reference_date)
    cash = portfolio.get_cash(con, account)
    equity = cash + sum(values.values())
    gross = sum(abs(value) for value in values.values()) + sum(reserved.values()) + requested
    position_value = abs(values.get(ticker, 0.0)) + reserved.get(ticker, 0.0) + requested
    cash_exceeded = spec["schema_version"] == 1 and requested + sum(reserved.values()) > cash
    if (requested < spec["min_trade_usd"] or cash_exceeded
            or gross > equity * spec["max_gross_fraction"]
            or position_value > equity * spec["max_position_fraction"]):
        raise AccountRefused("intent exceeds this account's cash/position/gross/minimum constraints")


def _validate_replayed_order(con, order_id, intent):
    row = con.execute("SELECT portfolio_id,ticker,side,qty,signal_date FROM sim_orders WHERE id=?",
                      [order_id]).fetchone()
    ticker = intent.get("ticker", intent.get("instrument_id"))
    session = intent.get("signal_date", intent.get("session_date"))
    quantity = float(intent['quantity'])
    for (payload,) in con.execute(
        "SELECT payload FROM account_events WHERE portfolio_id=? AND kind='split' ORDER BY id",
        [intent['account_id']],
    ).fetchall():
        action = json.loads(payload)
        if order_id in action.get('adjusted_order_ids', []):
            quantity *= float(action['ratio'])
    expected = (intent["account_id"], ticker, intent["side"], quantity,
                date.fromisoformat(session))
    if row != expected:
        raise AccountRefused("retained intake no longer matches its engine order")


def _activation_checkpoint(con, signal_date: date) -> bool:
    """Never make a new account's mark look like the whole nightly completed."""
    has_history = con.execute("SELECT 1 FROM sim_equity LIMIT 1").fetchone() is not None
    if not has_history:
        return False
    unfinished = con.execute(
        "SELECT p.id FROM portfolios p LEFT JOIN sim_equity e "
        "ON e.portfolio_id=p.id AND e.date=? WHERE p.active AND e.portfolio_id IS NULL",
        [signal_date],
    ).fetchall()
    if unfinished:
        raise AccountRefused("nightly accounting must complete before account intake")
    return con.execute("SELECT 1 FROM sim_equity WHERE date=? LIMIT 1",
                       [signal_date]).fetchone() is not None


def _receipt(order_id: int, received_at: datetime, order_type: str, session: date) -> dict:
    cutoff = cutoff_at(order_type, session)
    return {
        "order_id": order_id,
        "state": "queued",
        "received_at": received_at.isoformat(),
        "cutoff": cutoff.isoformat() if cutoff is not None else None,
        "refusal_reason": None,
    }


def submit_intent(con, intent: dict, *, now: datetime) -> dict:
    """Persist one accepted intent; ``now`` must have been captured before the writer lock."""
    received_at = _utc(now)
    if not isinstance(intent, dict) or type(intent.get("schema_version")) is not int:
        raise AccountRefused("invalid trade intent")
    fields = V1_INTENT_FIELDS if intent["schema_version"] == 1 else V2_INTENT_FIELDS
    if set(intent) != fields:
        raise AccountRefused(f"invalid trade intent v{intent['schema_version']}")
    digest = canonical_sha256(intent)
    with db.transaction(con):
        init_schema(con)
        spec = _load_spec(con, intent["account_id"])
        previous = con.execute(
            "SELECT account_id,order_id,sha256,payload,receipt FROM paper_account_intakes "
            "WHERE intent_id=?", [intent["intent_id"]],
        ).fetchone()
        if previous is not None:
            if (previous[0] != intent["account_id"] or previous[2] != digest
                    or canonical_sha256(json.loads(previous[3])) != digest):
                raise AccountRefused("intent identifier already bound to different evidence")
            _validate_replayed_order(con, previous[1], intent)
            if spec["schema_version"] == 1:
                return {"order_id": previous[1], "replayed": True}
            return json.loads(previous[4])
        session_date, quantity = validate_intent(intent, spec, received_at)
        status = sim_schema.portfolio_account(con, spec["account_id"])["status"]
        if status in {"halted", "retiring", "retired"}:
            raise AccountRefused(status)
        if spec["schema_version"] == 2 and (
            intent["instrument_kind"] not in EXECUTABLE_INSTRUMENTS or intent["legs"]
        ):
            raise AccountRefused("instrument_not_executable")
        if spec["schema_version"] == 1:
            latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
            if latest != session_date:
                raise AccountRefused("intent must use the current stored signal session")
            completed_checkpoint = _activation_checkpoint(con, session_date)
        else:
            reference_date = _reference_date(spec, intent, session_date)
            from sim import valuation

            valuation.mark(con, spec['account_id'], intent['instrument_id'], reference_date,
                           price_source=spec['price_source'])
            completed_checkpoint = False
        contingent_order = (
            _contingent_parent(con, intent, session_date, quantity)
            if spec["schema_version"] == 2 else None
        )
        _capacity(
            con, spec, intent, session_date, quantity,
            contingent_parent=contingent_order,
        )
        order_id = sim_schema.next_order_id(con)
        ticker = intent.get("ticker", intent.get("instrument_id"))
        con.execute(
            "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
            [order_id, intent["account_id"], ticker, intent["side"], quantity, session_date],
        )
        if spec["schema_version"] == 2:
            ensure(con, Instrument(ticker, intent["instrument_kind"], 1.0,
                                   source="account_intake", first_seen=session_date,
                                   last_seen=session_date))
            created = _utc(datetime.fromisoformat(intent["created_at"]))
            con.execute(
                "INSERT INTO sim_order_details "
                "(order_id,instrument_id,instrument_kind,order_type,side,tif,limit_px,"
                "session_date,received_at,created_at,contingent_on,state,state_at,source_sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [order_id, ticker, intent["instrument_kind"], intent["order_type"],
                 intent["side"], intent["time_in_force"], intent["limit_price"], session_date,
                 received_at, created, contingent_order, "queued", received_at,
                 intent["source_sha256"]],
            )
            receipt = _receipt(order_id, received_at, intent["order_type"], session_date)
        else:
            receipt = {"order_id": order_id, "replayed": False}
        con.execute(
            "INSERT INTO paper_account_intakes "
            "(intent_id,account_id,order_id,payload,sha256,received_at,receipt) "
            "VALUES (?,?,?,?,?,?,?)",
            [intent["intent_id"], intent["account_id"], order_id,
             json.dumps(intent, sort_keys=True), digest, received_at,
             json.dumps(receipt, sort_keys=True)],
        )
        con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [intent["account_id"]])
        sim_schema.set_portfolio_account(
            con, intent["account_id"], status="active", updated_at=received_at,
        )
        if completed_checkpoint:
            portfolio.mark_to_market(con, intent["account_id"], session_date)
    return receipt
