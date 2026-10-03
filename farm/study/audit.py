"""Pure, independently enumerated market-data coverage sidecars.

Raw bars enter before Panel normalization so duplicate keys cannot disappear. This
module never opens a database, runs a strategy, or changes an evaluator identity.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from engine.free_massive_minute import session_close
from sim import nyse

from .data import Bar
from .spec import parse_clock, validate_decision_time

AUDITOR_VERSION = "market-data-audit-v1"
_FIELDS = frozenset({"open", "high", "low", "close", "volume", "auction_volume"})
_CHECKS = frozenset({"coverage", "eligibility", "availability", "identity", "price_basis",
                     "revisions", "actions", "field_trace", "outcomes"})
_REASONS = ("missing", "invalid", "late", "unknown", "complete")


class AuditExecutionError(ValueError):
    """An invalid execution has no quality decision."""

    def as_dict(self) -> dict:
        return {"status": "error", "error": {"code": "invalid_audit_input", "message": str(self)}}


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise AuditExecutionError("audit evidence must contain finite canonical JSON values") from exc


def _day(value: Any) -> bool:
    return type(value) is date


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)


def _positive(value: Any) -> bool:
    return _finite(value) and value > 0


def _validate_digest(digest: str | None, actual: str) -> None:
    if digest is not None and digest != actual:
        raise AuditExecutionError("snapshot hash does not match its normalized evidence and metadata")


@dataclass(frozen=True)
class InputRequirement:
    field: str = "close"
    lookback: int = 1
    offset: int = 1
    predicate: str = "positive"

    def __post_init__(self) -> None:
        if (not isinstance(self.field, str) or not isinstance(self.predicate, str)
                or self.field not in _FIELDS or self.predicate not in {"positive", "nonnegative", "finite"}):
            raise AuditExecutionError("unsupported required field or validation predicate")
        if (type(self.lookback) is not int or self.lookback < 1
                or type(self.offset) is not int or self.offset < 0):
            raise AuditExecutionError("lookback must be positive and offset nonnegative")


@dataclass(frozen=True)
class AuditListing:
    ticker: str
    listed_from: date
    listed_through: date | None = None
    available_at: datetime | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.ticker, str) or not self.ticker or not _day(self.listed_from)
                or (self.listed_through is not None and
                    (not _day(self.listed_through) or self.listed_through < self.listed_from))
                or (self.available_at is not None and not _aware(self.available_at))):
            raise AuditExecutionError("invalid listing interval or availability timestamp")

    def contains(self, session: date) -> bool:
        return self.listed_from <= session and (
            self.listed_through is None or session <= self.listed_through)

    def canonical(self) -> dict:
        return {"ticker": self.ticker, "listed_from": self.listed_from.isoformat(),
                "listed_through": self.listed_through.isoformat() if self.listed_through else None,
                "available_at": self.available_at.isoformat() if self.available_at else None}


@dataclass(frozen=True)
class Availability:
    ticker: str
    session: date
    field: str
    available_at: datetime

    def __post_init__(self) -> None:
        if (not isinstance(self.ticker, str) or not self.ticker or not _day(self.session)
                or not isinstance(self.field, str) or self.field not in _FIELDS or not _aware(self.available_at)):
            raise AuditExecutionError("availability needs a field key and aware timestamp")

    def canonical(self) -> dict:
        return {"ticker": self.ticker, "session": self.session.isoformat(),
                "field": self.field, "available_at": self.available_at.isoformat()}


@dataclass(frozen=True)
class AuditSnapshot:
    source: str
    bars: tuple[Bar, ...]
    listings: tuple[AuditListing, ...] = ()
    availability: tuple[Availability, ...] = ()
    membership_complete: bool = True
    membership_basis: str = "historical_reference"
    price_basis: str = "raw"
    timezone: str = "America/New_York"
    session_open: str = "09:30"
    session_close: str = "16:00"
    daily_bar_lag_seconds: float = 0
    snapshot_sha256: str | None = None
    _sha256: str = field(init=False, repr=False)
    _bars: Mapping = field(init=False, repr=False, compare=False)
    _availability: Mapping = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise AuditExecutionError("snapshot source is required")
        if type(self.membership_complete) is not bool or not isinstance(self.membership_basis, str) or self.membership_basis not in {
                "historical_reference", "observed_source", "unknown"}:
            raise AuditExecutionError("invalid membership completeness or evidence basis")
        if not isinstance(self.price_basis, str) or self.price_basis not in {"raw", "split_adjusted", "total_return", "unknown"}:
            raise AuditExecutionError("invalid price basis")
        try:
            if not all(isinstance(v, str) for v in (self.timezone, self.session_open, self.session_close)):
                raise ValueError("clock strings required")
            ZoneInfo(self.timezone)
            parse_clock(self.session_open)
            parse_clock(self.session_close)
        except (ValueError, TypeError, KeyError) as exc:
            raise AuditExecutionError("invalid source timezone or session clock") from exc
        if not _finite(self.daily_bar_lag_seconds) or self.daily_bar_lag_seconds < 0:
            raise AuditExecutionError("daily bar lag must be finite and nonnegative")
        index: dict[str, dict[date, Bar]] = defaultdict(dict)
        bars = tuple(self.bars)
        for bar in bars:
            if not isinstance(bar, Bar) or not isinstance(bar.ticker, str) or not bar.ticker or not _day(bar.session) or not nyse.is_session(bar.session):
                raise AuditExecutionError("raw bars need NYSE session dates")
            if bar.session in index[bar.ticker]:
                raise AuditExecutionError("duplicate raw ticker/session bar")
            _json(bar.canonical())
            index[bar.ticker][bar.session] = bar
        available = tuple(self.availability)
        keys = {}
        for row in available:
            if not isinstance(row, Availability):
                raise AuditExecutionError("availability rows must be Availability records")
            key = row.ticker, row.session, row.field
            if key in keys:
                raise AuditExecutionError("duplicate field availability key; revision selection unsupported")
            keys[key] = row.available_at
        listings = tuple(self.listings)
        if any(not isinstance(row, AuditListing) for row in listings):
            raise AuditExecutionError("listing rows must be AuditListing records")
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "listings", listings)
        object.__setattr__(self, "availability", available)
        object.__setattr__(self, "_bars", MappingProxyType({
            ticker: MappingProxyType(rows) for ticker, rows in index.items()}))
        object.__setattr__(self, "_availability", MappingProxyType(keys))
        # Stream normalized rows into the digest; avoid constructing another dense panel.
        digest = hashlib.sha256(_json(self.metadata()))
        for name, rows in (
                ("bars", (bar.canonical() for bar in sorted(bars, key=lambda b: (b.session, b.ticker)))),
                ("listings", (row.canonical() for row in sorted(listings, key=lambda r: _json(r.canonical())))),
                ("availability", (row.canonical() for row in sorted(available, key=lambda r: _json(r.canonical()))))):
            digest.update(name.encode() + b"[")
            for row in rows:
                digest.update(_json(row) + b"\n")
            digest.update(b"]")
        actual = digest.hexdigest()
        _validate_digest(self.snapshot_sha256, actual)
        object.__setattr__(self, "_sha256", actual)

    @classmethod
    def declared(cls, **kwargs) -> AuditSnapshot:
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise AuditExecutionError("unknown or missing snapshot field") from exc

    @property
    def sha256(self) -> str:
        return self._sha256

    def metadata(self) -> dict:
        return {"source": self.source, "membership_complete": self.membership_complete,
                "membership_basis": self.membership_basis, "price_basis": self.price_basis,
                "timezone": self.timezone, "session_open": self.session_open,
                "session_close": self.session_close,
                "daily_bar_lag_seconds": self.daily_bar_lag_seconds}

    def get(self, ticker: str, session: date) -> Bar | None:
        return self._bars.get(ticker, {}).get(session)


@dataclass(frozen=True)
class AuditContract:
    study_id: str
    sessions: tuple[date, ...]
    hard_max_date: date
    requirements: tuple[InputRequirement, ...] = (InputRequirement(),)
    decision_time: str = "pre_open"
    window_sessions: int = 60
    min_history: int = 60
    min_price: float = 0
    min_mdv: float = 0
    liquidity_bins: tuple[float, ...] = (1_000_000, 5_000_000, 20_000_000)
    coverage_threshold: float = 1.0
    availability_basis: str = "declared_rule"
    required_checks: tuple[str, ...] = ("coverage", "eligibility")
    evidence_limit: int = 20
    study_run_id: str | None = None
    schema_version: int = 1
    purpose: str = "diagnostic"
    calendar: str = "NYSE"
    timezone: str = "America/New_York"
    open_as_indication: bool = False
    close_as_indication: bool = False

    def __post_init__(self) -> None:
        sessions, requirements = tuple(self.sessions), tuple(self.requirements)
        bins, checks = tuple(self.liquidity_bins), tuple(self.required_checks)
        if (not isinstance(self.study_id, str) or not self.study_id or type(self.schema_version) is not int or self.schema_version != 1
                or not isinstance(self.purpose, str) or self.purpose not in {"diagnostic", "historical_screen"} or self.calendar != "NYSE"
                or not _day(self.hard_max_date) or not sessions
                or any(not _day(day) or day > self.hard_max_date or not nyse.is_session(day)
                       for day in sessions) or tuple(sorted(set(sessions))) != sessions):
            raise AuditExecutionError("invalid study identity, calendar, or ordered decision sessions")
        try:
            if not isinstance(self.decision_time, str) or not isinstance(self.timezone, str):
                raise ValueError("clock strings required")
            validate_decision_time(self.decision_time)
            ZoneInfo(self.timezone)
        except (ValueError, TypeError, KeyError) as exc:
            raise AuditExecutionError("invalid decision clock") from exc
        if (type(self.window_sessions) is not int or self.window_sessions < 1
                or type(self.min_history) is not int or not 1 <= self.min_history <= self.window_sessions
                or not requirements or any(not isinstance(r, InputRequirement) for r in requirements)
                or len(set(requirements)) != len(requirements)):
            raise AuditExecutionError("invalid liquidity history or required inputs")
        if any(not _finite(v) or v < 0 for v in (self.min_price, self.min_mdv, *bins)):
            raise AuditExecutionError("thresholds and liquidity boundaries must be finite nonnegative")
        if tuple(sorted(set(bins))) != bins or not _finite(self.coverage_threshold) or not 0 <= self.coverage_threshold <= 1:
            raise AuditExecutionError("invalid coverage threshold or bin ordering")
        if not isinstance(self.availability_basis, str) or self.availability_basis not in {"declared_rule", "observed_source"}:
            raise AuditExecutionError("availability basis must be declared_rule or observed_source")
        if (type(self.open_as_indication) is not bool or type(self.close_as_indication) is not bool
                or not checks or any(not isinstance(check, str) or check not in _CHECKS for check in checks)
                or len(set(checks)) != len(checks) or not {"coverage", "eligibility"} <= set(checks)
                or type(self.evidence_limit) is not int or self.evidence_limit < 0
                or (self.study_run_id is not None and not isinstance(self.study_run_id, str))):
            raise AuditExecutionError("invalid required checks, evidence limit, or study run identity")
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "liquidity_bins", bins)
        object.__setattr__(self, "required_checks", checks)
        _json(self.canonical())

    @classmethod
    def from_dict(cls, value: Mapping) -> AuditContract:
        material = dict(value)
        try:
            material["sessions"] = tuple(date.fromisoformat(day) if isinstance(day, str) else day
                                         for day in material["sessions"])
            if isinstance(material.get("hard_max_date"), str):
                material["hard_max_date"] = date.fromisoformat(material["hard_max_date"])
            if "requirements" in material:
                material["requirements"] = tuple(InputRequirement(**row) for row in material["requirements"])
            return cls(**material)
        except (ValueError, TypeError, KeyError) as exc:
            raise AuditExecutionError("malformed or unknown contract field") from exc

    def canonical(self) -> dict:
        result = asdict(self)
        result["sessions"] = [day.isoformat() for day in self.sessions]
        result["hard_max_date"] = self.hard_max_date.isoformat()
        return result


def prior_sessions(session: date, count: int) -> tuple[date, ...]:
    """Frozen NYSE window, excluding the decision session and all absent calendar days."""
    result, day = [], session - timedelta(days=1)
    while len(result) < count:
        if nyse.is_session(day):
            result.append(day)
        day -= timedelta(days=1)
    return tuple(reversed(result))


def _moment(snapshot: AuditSnapshot, day: date, clock: str) -> datetime:
    hour, minute = parse_clock(clock)
    return datetime.combine(day, time(hour, minute), ZoneInfo(snapshot.timezone))


def _decision(contract: AuditContract, day: date) -> datetime:
    zone, native_zone = ZoneInfo(contract.timezone), ZoneInfo("America/New_York")
    clock = contract.decision_time
    if clock == "pre_open":
        return (datetime.combine(day, time(9, 30), native_zone) - timedelta(microseconds=1)).astimezone(zone)
    if clock in {"at_open", "at_close"}:
        at = time(9, 30) if clock == "at_open" else session_close(day)
        return datetime.combine(day, at, native_zone).astimezone(zone)
    return datetime.combine(day, time(*parse_clock(clock)), zone)


def _availability(snapshot: AuditSnapshot, ticker: str, day: date, name: str,
                  cutoff: datetime, contract: AuditContract) -> str | None:
    observed = snapshot._availability.get((ticker, day, name))
    declared = _moment(snapshot, day, snapshot.session_open if name == "open" else snapshot.session_close)
    if name != "open":
        declared += timedelta(seconds=snapshot.daily_bar_lag_seconds)
    # Source publication cannot authorize a field before the native market clock.
    native = datetime.combine(day, time(9, 30) if name == "open" else session_close(day),
                              ZoneInfo("America/New_York"))
    if cutoff < native or (observed is None and declared > cutoff) or (observed is not None and observed > cutoff):
        return "late"
    return "unknown" if observed is None and contract.availability_basis == "observed_source" else None


def _bin(value: float | None, boundaries: tuple[float, ...]) -> str:
    if value is None:
        return "unknown_liquidity"
    if not boundaries:
        return "all_liquidity"
    def text(number):
        return format(number, ".15f").rstrip("0").rstrip(".")
    if value < boundaries[0]:
        return f"below_{text(boundaries[0])}"
    for lower, upper in zip(boundaries, boundaries[1:], strict=False):
        if lower <= value < upper:
            return f"{text(lower)}_{text(upper)}"
    return f"at_least_{text(boundaries[-1])}"


def _counts() -> dict:
    return {"expected": 0, "complete_inputs": 0, "missing_inputs": 0,
            "invalid_inputs": 0, "late_inputs": 0, "unknown_inputs": 0,
            "unresolved_eligibility": 0}


def _ratio(row: dict, denominator_complete: bool = True) -> None:
    row["known_subset_coverage"] = row["complete_inputs"] / row["expected"] if row["expected"] else None
    row["denominator_complete"] = denominator_complete and not row["unresolved_eligibility"]
    row["coverage"] = row["known_subset_coverage"] if row["denominator_complete"] else None
    row["coverage_reason"] = ("incomplete_reference_membership" if not denominator_complete else
                              "known_subset_only" if row["unresolved_eligibility"] else
                              "empty_expected_population" if not row["expected"] else None)


def _valid(value: Any, predicate: str) -> bool:
    if not _finite(value):
        return False
    if predicate == "positive":
        return value > 0
    return predicate == "finite" or value >= 0


def _price_valid(bar: Bar) -> bool:
    values = (bar.open, bar.high, bar.low, bar.close)
    if any(value is None for value in values):
        return True  # Required-field presence is measured separately.
    return (all(_positive(value) for value in values)
            and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            and (bar.volume is None or (_finite(bar.volume) and bar.volume >= 0)))


def _inputs(contract: AuditContract, snapshot: AuditSnapshot, ticker: str, day: date,
            cutoff: datetime) -> tuple[str, tuple[str, ...]]:
    faults = set()
    for required in contract.requirements:
        previous = prior_sessions(day, required.offset + required.lookback)
        targets = previous[-(required.offset + required.lookback):]
        if required.offset == 0:
            targets = (*previous[-(required.lookback - 1):], day) if required.lookback > 1 else (day,)
        else:
            stop = len(previous) - required.offset + 1
            targets = previous[stop - required.lookback:stop]
        for target in targets:
            bar = snapshot.get(ticker, target)
            value = None if bar is None else getattr(bar, required.field)
            if value is None:
                faults.add("missing")
                continue
            if not _valid(value, required.predicate):
                faults.add("invalid")
            # Never read unavailable later OHLC values to classify an earlier signal.
            if all(_availability(snapshot, ticker, target, name, cutoff, contract) is None
                   for name in ("open", "high", "low", "close", "volume")) and not _price_valid(bar):
                faults.add("invalid")
            if (required.field == "open" and target == day
                    and contract.decision_time == "at_open" and not contract.open_as_indication):
                faults.add("late")
            if (required.field == "close" and target == day
                    and contract.decision_time == "at_close" and not contract.close_as_indication):
                faults.add("late")
            available = _availability(snapshot, ticker, target, required.field, cutoff, contract)
            if available:
                faults.add(available)
    ordered = tuple(reason for reason in _REASONS if reason in faults)
    return (ordered[0] if ordered else "complete"), ordered


def _eligibility(contract: AuditContract, reference: AuditSnapshot, ticker: str, day: date,
                 cutoff: datetime) -> tuple[str, float | None, str | None]:
    history = prior_sessions(day, contract.window_sessions)
    values, faults = [], set()
    last = reference.get(ticker, history[-1])
    if last is None or not _positive(last.close):
        return "unresolved", None, "reference_price_unknown"
    if _availability(reference, ticker, history[-1], "close", cutoff, contract):
        return "unresolved", None, "reference_price_availability_unknown"
    if last.close < contract.min_price:
        return "ineligible", None, None
    for target in history:
        bar = reference.get(ticker, target)
        if bar is None or not _positive(bar.close) or not _finite(bar.volume) or bar.volume < 0:
            continue
        for name in ("close", "volume"):
            problem = _availability(reference, ticker, target, name, cutoff, contract)
            if problem:
                faults.add(problem)
        if all(_availability(reference, ticker, target, name, cutoff, contract) is None
               for name in ("close", "volume")):
            dollar_volume = bar.close * bar.volume
            if math.isfinite(dollar_volume):
                values.append(dollar_volume)
    if len(values) < contract.min_history:
        return "unresolved", None, "reference_liquidity_availability_unknown" if faults else "reference_history_insufficient"
    mdv = float(statistics.median(values))
    return ("eligible" if mdv >= contract.min_mdv else "ineligible"), mdv, None


def _outcomes(value: Any) -> tuple[dict | None, Any]:
    if value is None:
        return None, None
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    # Serialize once to freeze caller-owned nested mutable mappings.
    normalized = json.loads(_json(value))
    if (not isinstance(normalized, dict) or normalized.get("kind") not in {"event", "portfolio"}
            or type(normalized.get("schema_version")) is not int or normalized["schema_version"] != 1):
        raise AuditExecutionError("outcomes must be a native event or portfolio ledger")
    if normalized["kind"] == "portfolio":
        days = normalized.get("days")
        if not isinstance(days, list) or any(not isinstance(row, dict) or "session" not in row
                                            or not isinstance(row.get("flags"), list) for row in days):
            raise AuditExecutionError("portfolio outcome days are missing")
        return {"kind": "portfolio", "recorded_days": len(days), "attempts": None,
                "reason": "portfolio marks do not enumerate attempted orders",
                "flags": dict(sorted(Counter(flag for row in days for flag in row.get("flags", ())).items()))}, normalized
    names = ("trades", "rejected_orders", "unfilled_orders", "open_positions")
    if any(not isinstance(normalized.get(name), list) for name in names):
        raise AuditExecutionError("event ledger must retain trades, exclusions and open positions")
    for name in names:
        for row in normalized[name]:
            needed = ({"ticker", "side", "entry_session", "exit_session", "entry_price", "exit_price", "notional", "flags"}
                      if name == "trades" else {"ticker", "side", "entry_session"} if name == "open_positions" else
                      {"ticker", "session", "reason"})
            if not isinstance(row, dict) or not needed <= row.keys():
                raise AuditExecutionError("malformed native outcome record")
            if not isinstance(row["ticker"], str) or not row["ticker"]:
                raise AuditExecutionError("invalid native outcome ticker")
            try:
                for key in needed & {"session", "entry_session", "exit_session"}:
                    date.fromisoformat(row[key])
            except (TypeError, ValueError) as exc:
                raise AuditExecutionError("invalid native outcome session") from exc
            if name in {"trades", "open_positions"} and row["side"] not in {"long", "short"}:
                raise AuditExecutionError("invalid native outcome side")
            if name == "trades" and (not _positive(row["entry_price"]) or not _positive(row["notional"])
                                     or not _finite(row["exit_price"]) or row["exit_price"] < 0
                                     or not isinstance(row["flags"], list)
                                     or any(not isinstance(flag, str) for flag in row["flags"])):
                raise AuditExecutionError("invalid native trade price, notional, or flags")
            if name in {"rejected_orders", "unfilled_orders"} and not isinstance(row["reason"], str):
                raise AuditExecutionError("invalid native outcome reason")
    categories = {name: len(normalized[name]) for name in names}
    attempts = sum(categories.values())
    reasons = Counter(row.get("reason", "unknown")
                      for name in ("rejected_orders", "unfilled_orders") for row in normalized[name])
    flags = Counter(flag for row in normalized["trades"] for flag in row.get("flags", ()))
    return {"kind": "event", "recorded_attempts": attempts, **categories,
            "exclusion_reasons": dict(sorted(reasons.items())), "flags": dict(sorted(flags.items())),
            "terminal_zero_trades": sum(row.get("exit_price") == 0 for row in normalized["trades"]),
            "reason": "recorded native attempts only; omitted signals cannot be reconstructed"}, normalized


def audit_study(contract: AuditContract, audited: AuditSnapshot, reference: AuditSnapshot, *,
                outcomes: Any = None) -> dict:
    """Return deterministic measurements; invalid executions raise without a decision."""
    if not isinstance(contract, AuditContract) or not all(isinstance(s, AuditSnapshot) for s in (audited, reference)):
        raise AuditExecutionError("audit needs a typed contract and two raw snapshots")
    outcome_counts, outcome_rows = _outcomes(outcomes)
    identity = {"auditor_version": AUDITOR_VERSION, "contract": contract.canonical(),
                "audited": audited.sha256, "reference": reference.sha256, "outcomes": outcome_rows}
    audit_id = hashlib.sha256(_json(identity)).hexdigest()
    listings: dict[str, list[AuditListing]] = defaultdict(list)
    for listing in reference.listings:
        listings[listing.ticker].append(listing)
    samples, findings, sessions = [], [], []
    examined, ambiguous, total_late, total_unknown = 0, False, 0, 0
    reason_counts = Counter()
    finding_total = 0
    for day in contract.sessions:
        cutoff = _decision(contract, day)
        row, bins = _counts(), {}
        base, ineligible = 0, 0
        for ticker, intervals in sorted(listings.items()):
            active = [listing for listing in intervals if listing.contains(day)]
            if not active:
                continue
            base += 1
            # v1 cannot confidently remap even disjoint reused intervals.
            if len(intervals) != 1:
                status, mdv, why = "unresolved", None, "identity_ambiguous"
                ambiguous = True
            elif (reference.membership_basis == "unknown" or
                  (reference.membership_basis == "observed_source" and active[0].available_at is None) or
                  (active[0].available_at is not None and active[0].available_at > cutoff)):
                status, mdv, why = "unresolved", None, "membership_availability_unknown"
            else:
                status, mdv, why = _eligibility(contract, reference, ticker, day, cutoff)
            if status == "ineligible":
                ineligible += 1
                continue
            group = _bin(mdv, contract.liquidity_bins)
            bin_row = bins.setdefault(group, _counts())
            examined += 1
            if status == "unresolved":
                row["unresolved_eligibility"] += 1
                bin_row["unresolved_eligibility"] += 1
                primary, faults = "unresolved", (why,)
            else:
                row["expected"] += 1
                bin_row["expected"] += 1
                primary, faults = _inputs(contract, audited, ticker, day, cutoff)
                key = f"{primary}_inputs"
                row[key] += 1
                bin_row[key] += 1
                total_late += "late" in faults
                total_unknown += "unknown" in faults
            reason_counts.update(faults)
            finding_total += bool(faults)
            detail = {"session": day.isoformat(), "ticker": ticker, "bin": group,
                      "status": primary, "reasons": list(faults), "reference_mdv": mdv,
                      "listed_through": active[0].listed_through.isoformat() if active[0].listed_through else None}
            if len(samples) < contract.evidence_limit:
                samples.append(detail)
            if faults and len(findings) < contract.evidence_limit:
                findings.append(detail)
        for counts in bins.values():
            _ratio(counts, reference.membership_complete)
        _ratio(row, reference.membership_complete)
        row.update(session=day.isoformat(), base_membership=base, ineligible=ineligible,
                   reference_membership_complete=reference.membership_complete,
                   bins=dict(sorted(bins.items())))
        sessions.append(row)
    def blocking_gap(counts):
        defects = sum(counts[f"{reason}_inputs"] for reason in ("missing", "invalid", "late"))
        if not counts["expected"]:
            return False
        if not counts["denominator_complete"]:
            return contract.coverage_threshold == 1 and defects > 0
        # Unknown input proof might yet establish complete data; use its optimistic bound.
        return (counts["expected"] - defects) / counts["expected"] < contract.coverage_threshold
    gap = any(blocking_gap(row) for row in sessions)
    bin_gap = any(blocking_gap(counts) for row in sessions for counts in row["bins"].values())
    uncertain_population = (not reference.membership_complete or reference.membership_basis == "unknown"
                            or any(row["unresolved_eligibility"] or not row["expected"] for row in sessions))
    uncertain = uncertain_population or total_unknown > 0
    def check(status: str, basis: str, reason: str) -> dict:
        return {"status": status, "evidence_basis": basis, "reason": reason}
    checks = {
        "coverage": check("fail" if gap or bin_gap else "unknown" if uncertain else "pass",
                          "independent_reference", "per-session and per-bin frozen coverage threshold"),
        "eligibility": check("unknown" if uncertain_population else "pass", "independent_reference",
                             "historical reference denominator; unresolved members are retained"),
        "availability": check("fail" if total_late else "unknown" if total_unknown else "pass",
                              contract.availability_basis, "required input clocks checked against decision cutoff"),
        "identity": check("unknown" if ambiguous else "pass", "independent_reference",
                          "ticker reuse cannot be remapped in this slice" if ambiguous else "one supplied interval per ticker"),
        "price_basis": check("unknown" if "unknown" in (audited.price_basis, reference.price_basis) else
                             "fail" if audited.price_basis != reference.price_basis else "pass",
                             "declared_rule", "compare declared audited/reference bases; adjustment correctness is separate"),
        "outcomes": check("unknown" if "outcomes" in contract.required_checks else "not_applicable",
                          "observed_source", "trace counted; no frozen outcome completeness policy in coverage slice"),
    }
    for name in ("actions", "revisions", "field_trace"):
        checks[name] = check("unknown" if name in contract.required_checks else "not_applicable",
                             "declared_rule", "unsupported evidence in offline coverage slice" if name in contract.required_checks else
                             "contract does not require this check; no claim of correctness")
    # Price mismatch is a blocking semantic conflict even when omitted from required_checks.
    for name, result in checks.items():
        result["required"] = name in contract.required_checks or name == "price_basis"
    required = [result["status"] for result in checks.values() if result["required"]]
    decision = ("unusable" if "fail" in required or checks["price_basis"]["status"] == "fail" else
                "limited" if "unknown" in required else "supported")
    return {"schema_version": 1, "auditor_version": AUDITOR_VERSION, "audit_id": audit_id,
            "study_id": contract.study_id, "study_run_id": contract.study_run_id,
            "decision": decision, "contract": contract.canonical(), "checks": checks,
            "sessions": sessions, "findings": findings,
            "finding_summary": {"total": finding_total, "displayed": len(findings),
                                "truncated": finding_total > len(findings),
                                "reason_counts": dict(sorted(reason_counts.items()))},
            "evidence": {"examined": examined, "sample_limit": contract.evidence_limit,
                         "truncated": examined > len(samples), "rows": samples,
                         "reason_counts": dict(sorted(reason_counts.items()))},
            "snapshots": {"audited": audited.sha256, "reference": reference.sha256},
            "inputs": {"audited": audited.metadata(), "reference": reference.metadata()},
            "outcomes": outcome_counts,
            "limitations": ["Passing coverage does not establish profitability or unrestricted strategy access.",
                            "Historical reference membership does not prove contemporary trader knowledge.",
                            "Declared source clocks are conservative; observed publication timestamps remain separate from native NYSE field permissions.",
                            "Unknown reference membership is not included in a complete-universe claim.",
                            "Raw snapshot indexes scale with input rows; full-size memory acceptance is unmeasured."]}
