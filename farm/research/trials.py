"""Append-only, hash-chained trial events shared by research backends."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_bytes, canonical_sha256, file_sha256

TRIAL_SCHEMA_VERSION = 1
PUBLIC_CENSUS_SHA256 = "07ba583900406735b422d91437ebd21db4cfdd59ba4d160db86f7f73a34395b7"
EVENT_KINDS = frozenset({
    "registered",
    "evaluation_started",
    "evaluated",
    "failed",
    "abandoned",
    "holdout_opened",
    "confirmed",
    "retired",
    "alias",
    "withdrawn",
    "legacy_outcome",
    "inventory_reconciliation",
})
ATTEMPT_KINDS = frozenset({"evaluation_started", "evaluated", "failed", "abandoned"})
TERMINAL_ATTEMPT_KINDS = frozenset({"evaluated", "failed", "abandoned"})


class TrialLedgerError(ValueError):
    pass


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TrialLedgerError("trial event timestamp must have an explicit timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def trial_id(study_sha256: str, parameters: Mapping[str, Any]) -> str:
    return canonical_sha256({"parameters": parameters, "study_sha256": study_sha256})


def _event_core(
    *, kind: str, event_id: str, trial: str | None, attempt: str | None,
    event_at: str | None, payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "event_id": event_id,
        "trial_id": trial,
        "attempt_id": attempt,
        "event_at": event_at,
        "payload": json.loads(canonical_bytes(payload)),
    }


def _record(
    core: Mapping[str, Any], *, sequence: int, recorded_at: str, previous: str | None,
) -> dict[str, Any]:
    unsigned = {
        "schema_version": TRIAL_SCHEMA_VERSION,
        "sequence": sequence,
        **core,
        "recorded_at": recorded_at,
        "previous_row_sha256": previous,
    }
    return {**unsigned, "row_sha256": canonical_sha256(unsigned)}


def _registration_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "study_sha256", "parents", "n_contribution", "selection_start", "selection_end",
        "source_ref",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise TrialLedgerError("registration payload fields differ")
    parents, source = payload["parents"], payload["source_ref"]
    contribution = payload["n_contribution"]
    start, end = payload["selection_start"], payload["selection_end"]
    if (not isinstance(payload["study_sha256"], str) or len(payload["study_sha256"]) != 64
            or not isinstance(parents, list) or any(not isinstance(item, str) or not item for item in parents)
            or parents != sorted(set(parents))
            or type(contribution) is not int or contribution < 1
            or type(start) is not int or type(end) is not int
            or end - start + 1 != contribution
            or not isinstance(source, Mapping) or not source):
        raise TrialLedgerError("registration payload is invalid")
    try:
        int(payload["study_sha256"], 16)
    except ValueError as exc:
        raise TrialLedgerError("registration study identity is invalid") from exc
    return json.loads(canonical_bytes(payload))


def _sha_valid(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _runtime_payload(kind: str, payload: Mapping[str, Any]) -> None:
    if set(payload) != {"source_ref"} or not isinstance(payload["source_ref"], Mapping):
        raise TrialLedgerError(f"{kind} payload fields differ")
    source = payload["source_ref"]
    if kind == "evaluation_started":
        required = {"study_sha256", "feature_sha256", "phase"}
        if (set(source) != required
                or not _sha_valid(source["study_sha256"])
                or not _sha_valid(source["feature_sha256"])
                or source["phase"] not in {"pilot", "development", "holdout"}):
            raise TrialLedgerError("evaluation_started evidence differs")
    elif kind == "evaluated":
        required = {
            "attempt_id", "feature_sha256", "label_sha256", "outcome_accessed", "phase",
            "predictions_sha256", "result_sha256", "study_sha256", "trial_id",
            "census_reconciliation", "strategy_workers", "worker_pids",
        }
        if (set(source) != required
                or not all(_sha_valid(source[name]) for name in (
                    "feature_sha256", "predictions_sha256", "study_sha256"
                ))
                or (source["result_sha256"] is None and not (
                    source["phase"] == "pilot" and source["outcome_accessed"] is False))
                or (source["result_sha256"] is not None
                    and not _sha_valid(source["result_sha256"]))
                or (source["label_sha256"] is not None
                    and not _sha_valid(source["label_sha256"]))
                or not isinstance(source["census_reconciliation"], Mapping)):
            raise TrialLedgerError("evaluated evidence differs")
    elif kind == "failed":
        required = {"error", "message", "study_sha256"}
        if (set(source) != required or not source["error"] or not source["message"]
                or not _sha_valid(source["study_sha256"])):
            raise TrialLedgerError("failed evidence differs")
    elif kind == "abandoned":
        if (set(source) != {"reason", "evidence_sha256"} or not source["reason"]
                or not _sha_valid(source["evidence_sha256"])):
            raise TrialLedgerError("abandoned evidence differs")


@dataclass(frozen=True)
class CensusGenesis:
    source: str
    source_sha256: str
    row_count: int
    n_contribution: int
    register_sha256: str
    reconciliation_sha256: str

    @classmethod
    def from_public_census(cls, path: str | Path) -> "CensusGenesis":
        source = Path(path)
        observed = file_sha256(source)
        if observed != PUBLIC_CENSUS_SHA256:
            raise TrialLedgerError("accepted public census hash differs")
        try:
            rows = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrialLedgerError("accepted public census is unreadable") from exc
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(row, dict) or type(row.get("n_contribution")) is not int
                       or row["n_contribution"] < 0 for row in rows)):
            raise TrialLedgerError("accepted public census rows differ")
        contribution = sum(row["n_contribution"] for row in rows)
        register = canonical_sha256(rows)
        material = {
            "source_sha256": observed,
            "row_count": len(rows),
            "n_contribution": contribution,
            "register_sha256": register,
        }
        return cls(
            "docs/p16-trial-census.json", observed, len(rows), contribution, register,
            canonical_sha256(material),
        )

    @classmethod
    def accepted(cls) -> "CensusGenesis":
        return cls.from_public_census(Path(__file__).resolve().parents[2] / "docs" / "p16-trial-census.json")

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_sha256": self.source_sha256,
            "row_count": self.row_count,
            "n_contribution": self.n_contribution,
            "register_sha256": self.register_sha256,
            "reconciliation_sha256": self.reconciliation_sha256,
        }


def _validate_records(records: Sequence[Mapping[str, Any]], genesis: CensusGenesis) -> None:
    previous, event_ids, registrations = None, {}, {}
    attempts: dict[tuple[str, str], list[str]] = {}
    holdouts, retired, withdrawn, confirmed = set(), set(), set(), set()
    selection_n = genesis.n_contribution
    required = {
        "schema_version", "sequence", "kind", "event_id", "trial_id", "attempt_id",
        "event_at", "payload", "recorded_at", "previous_row_sha256", "row_sha256",
    }
    for index, row in enumerate(records, 1):
        if not isinstance(row, Mapping) or set(row) != required:
            raise TrialLedgerError(f"trial row {index} fields differ")
        unsigned = {key: row[key] for key in required - {"row_sha256"}}
        if (row["schema_version"] != TRIAL_SCHEMA_VERSION or row["sequence"] != index
                or row["previous_row_sha256"] != previous
                or row["row_sha256"] != canonical_sha256(unsigned)
                or row["kind"] not in EVENT_KINDS
                or not isinstance(row["event_id"], str) or not row["event_id"]
                or not isinstance(row["payload"], Mapping)):
            raise TrialLedgerError(f"trial row {index} identity differs")
        try:
            event_at = (None if row["event_at"] is None else
                        datetime.fromisoformat(row["event_at"].replace("Z", "+00:00")))
            recorded_at = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise TrialLedgerError(f"trial row {index} timestamp differs") from exc
        if ((event_at is None and row["kind"] not in {"withdrawn", "legacy_outcome"})
                or (event_at is not None and (
                    event_at.utcoffset() != timezone.utc.utcoffset(event_at)
                    or recorded_at < event_at))):
            raise TrialLedgerError(f"trial row {index} timestamp differs")
        core = _event_core(
            kind=row["kind"], event_id=row["event_id"], trial=row["trial_id"],
            attempt=row["attempt_id"], event_at=row["event_at"], payload=row["payload"],
        )
        existing = event_ids.setdefault(row["event_id"], core)
        if existing is not core:
            raise TrialLedgerError(f"trial event id is duplicated: {row['event_id']}")
        kind, current_trial, attempt = row["kind"], row["trial_id"], row["attempt_id"]
        if kind == "registered":
            if not isinstance(current_trial, str) or not current_trial or attempt is not None:
                raise TrialLedgerError("registration identity is invalid")
            if current_trial in registrations:
                raise TrialLedgerError("trial registration is duplicated")
            payload = _registration_payload(row["payload"])
            if any(parent not in registrations for parent in payload["parents"]):
                raise TrialLedgerError("trial parent must be registered first")
            if payload["selection_start"] != selection_n + 1:
                raise TrialLedgerError("selection count is not gap-free")
            selection_n = payload["selection_end"]
            registrations[current_trial] = row
        elif kind == "inventory_reconciliation":
            if current_trial is not None or attempt is not None:
                raise TrialLedgerError("reconciliation cannot name a trial or attempt")
            expected = {
                "sealed_through_sequence", "sealed_row_sha256", "register_sha256",
                "selection_n", "source_hashes", "genesis",
            }
            payload = row["payload"]
            bound = index - 1
            before = records[:bound]
            if (set(payload) != expected or payload["sealed_through_sequence"] != bound
                    or payload["sealed_row_sha256"] != previous
                    or payload["register_sha256"] != canonical_sha256(
                        [item["row_sha256"] for item in before]
                    )
                    or payload["selection_n"] != selection_n
                    or payload["genesis"] != genesis.as_dict()
                    or not isinstance(payload["source_hashes"], Mapping)
                    or any(not isinstance(key, str) or not key or not isinstance(value, str)
                           or len(value) != 64 for key, value in payload["source_hashes"].items())):
                raise TrialLedgerError("inventory reconciliation differs")
        else:
            if not isinstance(current_trial, str) or current_trial not in registrations:
                raise TrialLedgerError("trial event has no prior registration")
            if kind in ATTEMPT_KINDS:
                if not isinstance(attempt, str) or not attempt:
                    raise TrialLedgerError("attempt event needs an attempt id")
                key = current_trial, attempt
                history = attempts.setdefault(key, [])
                if kind == "evaluation_started":
                    if history or current_trial in retired | withdrawn | confirmed:
                        raise TrialLedgerError("attempt has already started")
                elif not history or history[0] != "evaluation_started":
                    raise TrialLedgerError("attempt terminal event has no start")
                elif any(item in TERMINAL_ATTEMPT_KINDS for item in history):
                    raise TrialLedgerError("attempt already has a terminal event")
                _runtime_payload(kind, row["payload"])
                if history and event_at is not None:
                    start = datetime.fromisoformat(
                        next(item for item in records if item["trial_id"] == current_trial
                             and item["attempt_id"] == attempt
                             and item["kind"] == "evaluation_started")["event_at"].replace(
                                 "Z", "+00:00"))
                    if event_at < start:
                        raise TrialLedgerError("attempt terminal predates evaluation_started")
                history.append(kind)
            elif attempt is not None:
                raise TrialLedgerError(f"{kind} cannot name an attempt")
            if kind == "holdout_opened":
                if current_trial in holdouts:
                    raise TrialLedgerError("holdout has already been opened")
                if not any(key[0] == current_trial for key in attempts):
                    raise TrialLedgerError("holdout cannot open before an evaluation starts")
                holdouts.add(current_trial)
            elif kind == "confirmed" and current_trial not in holdouts:
                raise TrialLedgerError("confirmation requires an opened holdout")
            elif kind == "confirmed":
                if current_trial in confirmed:
                    raise TrialLedgerError("trial has already been confirmed")
                source = row["payload"].get("source_ref", {})
                if (set(row["payload"]) != {"source_ref"}
                        or set(source) != {"evidence_sha256", "result_sha256", "reason"}
                        or not _sha_valid(source["evidence_sha256"])
                        or not _sha_valid(source["result_sha256"]) or not source["reason"]):
                    raise TrialLedgerError("confirmation evidence differs")
                confirmed.add(current_trial)
            elif kind == "retired":
                if current_trial in retired:
                    raise TrialLedgerError("trial has already been retired")
                source = row["payload"].get("source_ref", {})
                if (set(row["payload"]) != {"source_ref"}
                        or set(source) != {"evidence_sha256", "result_sha256", "reason"}
                        or not _sha_valid(source["evidence_sha256"])
                        or not _sha_valid(source["result_sha256"]) or not source["reason"]):
                    raise TrialLedgerError("retirement evidence differs")
                retired.add(current_trial)
            elif kind == "alias":
                target = row["payload"].get("canonical_trial_id")
                if target not in registrations or target == current_trial:
                    raise TrialLedgerError("trial alias target is invalid")
            elif kind in {"withdrawn", "legacy_outcome"}:
                provenance = row["payload"].get("time_provenance")
                if (row["event_at"] is not None or not isinstance(provenance, dict)
                        or provenance.get("kind") != "unknown_after_registration"
                        or not isinstance(row["payload"].get("source_row"), dict)):
                    raise TrialLedgerError("legacy lifecycle provenance differs")
                if kind == "withdrawn":
                    withdrawn.add(current_trial)
        previous = row["row_sha256"]


@dataclass(frozen=True)
class LedgerSummary:
    status: str
    selection_n: int
    selection_contributions: int
    registered_trials: int
    attempts: int
    row_count: int
    row_sha256: str | None
    register_sha256: str


class JsonlTrialLedger:
    """Process-safe JSONL adapter; reports and CSVs are projections of these events."""

    def __init__(self, path: str | Path, *, genesis: CensusGenesis | None = None):
        self.path = Path(path)
        self.genesis = genesis or CensusGenesis.accepted()

    def _read_stream(self, stream) -> list[dict[str, Any]]:
        stream.seek(0)
        raw = stream.read()
        if raw and not raw.endswith("\n"):
            raise TrialLedgerError("trial ledger has a torn final row")
        records = []
        for index, line in enumerate(raw.splitlines(), 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrialLedgerError(f"trial row {index} is not JSON") from exc
            records.append(row)
        _validate_records(records, self.genesis)
        return records

    def read(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            try:
                return tuple(self._read_stream(stream))
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        *,
        kind: str,
        event_id: str,
        payload: Mapping[str, Any],
        trial: str | None = None,
        attempt: str | None = None,
        event_at: datetime | None = None,
        recorded_at: datetime | None = None,
        event_time_known: bool = True,
    ) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise TrialLedgerError(f"unknown trial event kind: {kind}")
        event_time, recorded_time = event_at or _now(), recorded_at or _now()
        core = _event_core(
            kind=kind,
            event_id=event_id,
            trial=trial,
            attempt=attempt,
            event_at=_timestamp(event_time) if event_time_known else None,
            payload=payload,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                records = self._read_stream(stream)
                prior = next((row for row in records if row["event_id"] == event_id), None)
                if prior is not None:
                    prior_core = _event_core(
                        kind=prior["kind"], event_id=prior["event_id"], trial=prior["trial_id"],
                        attempt=prior["attempt_id"], event_at=prior["event_at"],
                        payload=prior["payload"],
                    )
                    comparable = {key: value for key, value in core.items() if key != "event_at"}
                    previous = {key: value for key, value in prior_core.items() if key != "event_at"}
                    if comparable != previous:
                        raise TrialLedgerError(f"event id was reused with different content: {event_id}")
                    return prior
                row = _record(
                    core,
                    sequence=len(records) + 1,
                    recorded_at=_timestamp(recorded_time),
                    previous=records[-1]["row_sha256"] if records else None,
                )
                _validate_records([*records, row], self.genesis)
                stream.seek(0, os.SEEK_END)
                stream.write(canonical_bytes(row, newline=True).decode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
                return row
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def append_terminal_cas(
        self,
        reconciliation: Mapping[str, Any],
        *,
        trial: str,
        attempt: str,
        payload: Mapping[str, Any],
        invalid_payload: Mapping[str, Any],
        event_at: datetime | None = None,
    ) -> bool:
        """Append evaluated only if the reconciled snapshot still bounds this attempt."""
        descriptor = os.open(self.path, os.O_RDWR)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                records = self._read_stream(stream)
                sequence = reconciliation.get("reconciliation_sequence")
                sealed = next((row for row in records if row["sequence"] == sequence), None)
                tail = records[sequence:] if type(sequence) is int else records
                valid = (
                    sealed is not None
                    and sealed["kind"] == "inventory_reconciliation"
                    and sealed["row_sha256"] == reconciliation.get("row_sha256")
                    and all(
                        row["trial_id"] == trial
                        and (row["kind"] == "evaluation_started" and row["attempt_id"] == attempt
                             or row["kind"] == "holdout_opened" and row["attempt_id"] is None)
                        for row in tail
                    )
                )
                kind = "evaluated" if valid else "failed"
                selected_payload = payload if valid else invalid_payload
                core = _event_core(
                    kind=kind,
                    event_id=f"{kind}:{attempt}",
                    trial=trial,
                    attempt=attempt,
                    event_at=_timestamp(event_at or _now()),
                    payload=selected_payload,
                )
                row = _record(
                    core,
                    sequence=len(records) + 1,
                    recorded_at=_timestamp(_now()),
                    previous=records[-1]["row_sha256"],
                )
                _validate_records([*records, row], self.genesis)
                stream.seek(0, os.SEEK_END)
                stream.write(canonical_bytes(row, newline=True).decode())
                stream.flush()
                os.fsync(stream.fileno())
                return valid
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def register(
        self,
        *,
        trial: str,
        study_sha256: str,
        source_ref: Mapping[str, Any],
        selection_start: int,
        n_contribution: int = 1,
        parents: Sequence[str] = (),
        event_at: datetime | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        return self.append(
            kind="registered",
            event_id=event_id or f"registered:{trial}",
            trial=trial,
            payload={
                "study_sha256": study_sha256,
                "parents": sorted(set(parents)),
                "n_contribution": n_contribution,
                "selection_start": selection_start,
                "selection_end": selection_start + n_contribution - 1,
                "source_ref": dict(source_ref),
            },
            event_at=event_at,
        )

    def reconcile(
        self,
        source_hashes: Mapping[str, str],
        *,
        event_id: str,
        event_at: datetime | None = None,
    ) -> dict[str, Any]:
        records = self.read()
        summary = _summary(records, self.genesis)
        return self.append(
            kind="inventory_reconciliation",
            event_id=event_id,
            payload={
                "sealed_through_sequence": len(records),
                "sealed_row_sha256": records[-1]["row_sha256"] if records else None,
                "register_sha256": canonical_sha256([row["row_sha256"] for row in records]),
                "selection_n": summary.selection_n,
                "source_hashes": dict(source_hashes),
                "genesis": self.genesis.as_dict(),
            },
            event_at=event_at,
        )

    def summary(self) -> LedgerSummary:
        return _summary(self.read(), self.genesis)

    def selection_n(self, *, require_reconciled: bool = True) -> int:
        summary = self.summary()
        if require_reconciled and summary.status != "complete":
            raise TrialLedgerError(f"trial ledger is {summary.status}; DSR census is unavailable")
        return summary.selection_n

    def reconciliation_receipt(self) -> dict[str, Any]:
        records = self.read()
        summary = _summary(records, self.genesis)
        reconciliations = [row for row in records if row["kind"] == "inventory_reconciliation"]
        if summary.status != "complete" or not reconciliations:
            raise TrialLedgerError(f"trial ledger is {summary.status}; reconciliation is unavailable")
        latest = reconciliations[-1]
        return {
            "status": "complete",
            "row_sha256": latest["row_sha256"],
            "register_sha256": latest["payload"]["register_sha256"],
            "selection_n": latest["payload"]["selection_n"],
            "sealed_through_sequence": latest["payload"]["sealed_through_sequence"],
            "reconciliation_sequence": latest["sequence"],
        }

    def terminal_receipt(self, trial: str) -> dict[str, Any]:
        rows = self.read()
        terminal = [
            row for row in rows
            if row["trial_id"] == trial and row["kind"] in {"confirmed", "retired"}
        ]
        if len(terminal) != 1:
            raise TrialLedgerError("trial does not have exactly one evidence terminal")
        row = terminal[0]
        return {
            "kind": row["kind"],
            "row_sha256": row["row_sha256"],
            "trial_id": trial,
            "evidence_sha256": row["payload"]["source_ref"]["evidence_sha256"],
            "result_sha256": row["payload"]["source_ref"]["result_sha256"],
        }


def _summary(records: Sequence[Mapping[str, Any]], genesis: CensusGenesis) -> LedgerSummary:
    _validate_records(records, genesis)
    registrations = [row for row in records if row["kind"] == "registered"]
    selection_n = max(
        (row["payload"]["selection_end"] for row in registrations),
        default=genesis.n_contribution,
    )
    contributions = sum(row["payload"]["n_contribution"] for row in registrations)
    reconciliations = [row for row in records if row["kind"] == "inventory_reconciliation"]
    latest = reconciliations[-1] if reconciliations else None
    if latest is None:
        status = "unreconciled"
    elif any(row["kind"] != "inventory_reconciliation"
             for row in records[latest["sequence"]:]):
        status = "stale"
    else:
        status = "complete"
    return LedgerSummary(
        status=status,
        selection_n=selection_n,
        selection_contributions=contributions,
        registered_trials=len(registrations),
        attempts=len({(row["trial_id"], row["attempt_id"]) for row in records
                      if row["kind"] == "evaluation_started"}),
        row_count=len(records),
        row_sha256=records[-1]["row_sha256"] if records else None,
        register_sha256=canonical_sha256([row["row_sha256"] for row in records]),
    )
