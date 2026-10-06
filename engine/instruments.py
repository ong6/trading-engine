"""Canonical instrument identities for the simulator and account engine."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal

import duckdb

_OCC_SUFFIX = re.compile(r"^(?P<root>[A-Z0-9.]{1,6})(?P<date>\d{6})"
                         r"(?P<right>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    kind: str
    multiplier: float
    underlying: str | None = None
    expiry: date | None = None
    strike: float | None = None
    right: str | None = None
    exercise_style: str | None = None
    settlement: str | None = None
    deliverable: str | None = None
    currency: str = "USD"
    source: str | None = None
    first_seen: date | None = None
    last_seen: date | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def normalise(instrument_id: str) -> str:
    """Strip OCC root padding while leaving non-option identifiers unchanged."""
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("instrument_id must be a non-empty string")
    candidate = instrument_id.strip()
    compact = candidate[:6].rstrip() + candidate[6:] if len(candidate) == 21 else candidate
    return compact.upper() if _OCC_SUFFIX.fullmatch(compact.upper()) else candidate


def parse_occ(symbol: str) -> Instrument:
    """Parse a padded or compact OCC option symbol into canonical fields."""
    instrument_id = normalise(symbol)
    matched = _OCC_SUFFIX.fullmatch(instrument_id)
    if matched is None:
        raise ValueError(f"invalid OCC option symbol {symbol!r}")
    expiry = datetime.strptime(matched.group("date"), "%y%m%d").date()
    strike = float(Decimal(matched.group("strike")) / Decimal(1000))
    underlying = matched.group("root")
    deliverable = json.dumps(
        [{"instrument_id": underlying, "qty": 100}],
        sort_keys=True,
        separators=(",", ":"),
    )
    return Instrument(
        instrument_id=instrument_id,
        kind="option",
        underlying=underlying,
        multiplier=100.0,
        expiry=expiry,
        strike=strike,
        right=matched.group("right"),
        exercise_style="american",
        settlement="physical",
        deliverable=deliverable,
    )


def format_occ(instrument: Instrument) -> str:
    """Return the 21-character padded OCC symbol for an option instrument."""
    if (instrument.kind != "option" or instrument.underlying is None
            or instrument.expiry is None or instrument.strike is None
            or instrument.right not in {"C", "P"}):
        raise ValueError("a complete option instrument is required")
    root = instrument.underlying.upper()
    if not 1 <= len(root) <= 6 or not re.fullmatch(r"[A-Z0-9.]+", root):
        raise ValueError("OCC root must contain one to six letters, digits, or dots")
    scaled = Decimal(str(instrument.strike)) * 1000
    if scaled != scaled.to_integral_value() or not 0 <= scaled <= 99_999_999:
        raise ValueError("OCC strike must be a non-negative multiple of 0.001")
    return f"{root:<6}{instrument.expiry:%y%m%d}{instrument.right}{int(scaled):08d}"


def ensure(con: duckdb.DuckDBPyConnection, instrument: Instrument) -> Instrument:
    """Insert or refresh one canonical instrument-master row."""
    expected = normalise(instrument.instrument_id)
    if expected != instrument.instrument_id:
        raise ValueError("instrument_id is not canonical")
    con.execute(
        """
        INSERT INTO instruments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (instrument_id) DO UPDATE SET
          kind=excluded.kind, underlying=excluded.underlying,
          multiplier=excluded.multiplier, expiry=excluded.expiry,
          strike=excluded.strike, "right"=excluded."right",
          exercise_style=excluded.exercise_style, settlement=excluded.settlement,
          deliverable=excluded.deliverable, currency=excluded.currency,
          source=excluded.source,
          first_seen=COALESCE(instruments.first_seen, excluded.first_seen),
          last_seen=excluded.last_seen
        """,
        [
            instrument.instrument_id,
            instrument.kind,
            instrument.underlying,
            instrument.multiplier,
            instrument.expiry,
            instrument.strike,
            instrument.right,
            instrument.exercise_style,
            instrument.settlement,
            instrument.deliverable,
            instrument.currency,
            instrument.source,
            instrument.first_seen,
            instrument.last_seen,
        ],
    )
    return instrument


def resolve(instrument_id: str, *, con: duckdb.DuckDBPyConnection | None = None) -> Instrument:
    """Resolve a master row, or parse an OCC identity without a connection."""
    canonical = normalise(instrument_id)
    if con is None:
        return parse_occ(canonical)
    row = con.execute(
        "SELECT instrument_id,kind,multiplier,underlying,expiry,strike,\"right\","
        "exercise_style,settlement,deliverable,currency,source,first_seen,last_seen "
        "FROM instruments WHERE instrument_id=?",
        [canonical],
    ).fetchone()
    if row is None:
        if _OCC_SUFFIX.fullmatch(canonical):
            return parse_occ(canonical)
        raise KeyError(f"unknown instrument {canonical!r}")
    return Instrument(*row)
