"""Invariant registry, accepted-exception baseline and result assembly.

An invariant is a read-only check of one published snapshot. It returns ``facts`` (what it
measured, for the record) and ``violations`` (``subject``, ``class`` and ``detail`` each). The
baseline file accepts named exceptions; each entry carries an owner, a reason and an expiry
date, matches by class, by subject list or both (never a whole invariant), and stops matching
the day after it expires. A violation no live entry matches is a regression.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

BASELINE_PATH = Path(__file__).with_name("baseline.json")
RESULT_SCHEMA_VERSION = 1
STORED_VIOLATIONS = 200  # per invariant and kind; counts are always complete
AREAS = ("market_data", "books", "results")  # report order


class CannotEvaluate(RuntimeError):
    """The snapshot lacks what an invariant needs; the run cannot vouch for it."""


@dataclass(frozen=True)
class Context:
    con: duckdb.DuckDBPyConnection
    snapshot_as_of: datetime
    engine_root: Path


@dataclass(frozen=True)
class Invariant:
    name: str
    area: str
    tables: tuple[str, ...]
    check: Callable[[Context], tuple[dict, list[dict]]]


INVARIANTS: dict[str, Invariant] = {}


def register(name: str, area: str, *, tables: tuple[str, ...] = ()):
    def wrap(check: Callable[[Context], tuple[dict, list[dict]]]):
        if area not in AREAS:
            raise ValueError(f"invariant {name} has unknown area {area}")
        if name in INVARIANTS:
            raise ValueError(f"invariant {name} registered twice")
        INVARIANTS[name] = Invariant(name, area, tables, check)
        return check
    return wrap


def ordered_names() -> list[str]:
    return sorted(INVARIANTS, key=lambda name: AREAS.index(INVARIANTS[name].area))


def violation(subject: str, kind: str, **detail) -> dict:
    return {"subject": subject, "class": kind, "detail": detail}


def finite(value) -> bool:
    return value is not None and math.isfinite(float(value))


def json_value(value):
    """DuckDB row values as JSON: dates as ISO strings, non-finite floats as strings."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


# --------------------------------------------------------------------------- baseline


def load_baseline(path: Path = BASELINE_PATH) -> list[dict]:
    """Validated accepted exceptions. Raises ``ValueError`` on any malformed entry."""
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1 or not isinstance(payload.get("exceptions"), list):
        raise ValueError("baseline needs schema_version 1 and an exceptions list")
    entries = []
    for index, entry in enumerate(payload["exceptions"]):
        where = f"baseline exception {index}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object")
        unknown = set(entry) - {"invariant", "class", "subjects", "through", "owner", "reason",
                                "expires", "ref"}
        if unknown:
            raise ValueError(f"{where} has unknown keys {sorted(unknown)}")
        for key in ("invariant", "owner", "reason", "expires"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"{where} needs a non-empty {key}")
        if entry["invariant"] not in INVARIANTS:
            raise ValueError(f"{where} names unknown invariant {entry['invariant']}")
        if "class" not in entry and "subjects" not in entry:
            raise ValueError(f"{where} must match by class or subjects, not a whole invariant")
        subjects = entry.get("subjects")
        if subjects is not None and (not isinstance(subjects, list) or not subjects or not all(
                isinstance(item, str) and item for item in subjects)):
            raise ValueError(f"{where} subjects must be a non-empty list of strings")
        expires = date.fromisoformat(entry["expires"])
        through = date.fromisoformat(entry["through"]) if "through" in entry else None
        entries.append({**entry, "_expires": expires, "_through": through, "_index": index})
    return entries


def _matches(entry: dict, invariant: str, item: dict) -> bool:
    if entry["invariant"] != invariant:
        return False
    if "class" in entry and entry["class"] != item["class"]:
        return False
    if "subjects" in entry and item["subject"] not in entry["subjects"]:
        return False
    if entry["_through"] is not None:
        day = item["detail"].get("date")
        if not isinstance(day, str) or date.fromisoformat(day[:10]) > entry["_through"]:
            return False
    return True


def _public_entry(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if not key.startswith("_")}


# --------------------------------------------------------------------------- evaluation


def _evaluate_one(invariant: Invariant, ctx: Context) -> tuple[dict, list[dict], str | None]:
    missing = [table for table in invariant.tables if not ctx.con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table],
    ).fetchone()[0]]
    if missing:
        return {}, [], f"missing table(s): {', '.join(missing)}"
    try:
        facts, found = invariant.check(ctx)
    except CannotEvaluate as exc:
        return {}, [], str(exc)
    except duckdb.Error as exc:
        return {}, [], f"query failed: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    return facts, found, None


def evaluate(ctx: Context, baseline: list[dict], *, today: date,
             names: list[str] | None = None) -> dict:
    """Run every registered invariant (or ``names``) and split violations by the baseline."""
    live = [entry for entry in baseline if entry["_expires"] >= today]
    used: set[int] = set()
    invariants, regressions, errors = {}, 0, 0
    for name in names or ordered_names():
        invariant = INVARIANTS[name]
        started = time.monotonic()
        facts, found, error = _evaluate_one(invariant, ctx)
        new, accepted = [], []
        for item in found:
            entry = next((entry for entry in live if _matches(entry, name, item)), None)
            if entry is None:
                expired = next((entry for entry in baseline if entry["_expires"] < today
                                and _matches(entry, name, item)), None)
                new.append({**item, **({"expired_exception": expired["_index"]}
                                       if expired else {})})
            else:
                used.add(entry["_index"])
                accepted.append({**item, "exception": entry["_index"]})
        status = "error" if error else "regression" if new else "pass"
        regressions += len(new)
        errors += bool(error)
        invariants[name] = {
            "area": invariant.area, "status": status, "error": error,
            "seconds": round(time.monotonic() - started, 2), "facts": facts,
            "violation_count": len(found), "regression_count": len(new),
            "baselined_count": len(accepted),
            "regressions": new[:STORED_VIOLATIONS], "baselined": accepted[:STORED_VIOLATIONS],
            "truncated": max(len(new), len(accepted)) > STORED_VIOLATIONS,
        }
    return {
        "status": "regression" if regressions else "error" if errors else "pass",
        "regression_count": regressions,
        "error_count": errors,
        "invariants": invariants,
        "baseline": {
            "entries": len(baseline),
            "expired": [_public_entry(entry) for entry in baseline if entry["_expires"] < today],
            "unused": [entry["_index"] for entry in live if entry["_index"] not in used],
        },
    }


def exit_code(result: dict) -> int:
    return {"pass": 0, "regression": 2}.get(result["status"], 3)
