"""Read-only durable loader for retained automatic-paper authority epochs.

The loader accepts an externally trusted global row count and chain head,
requires a twice-stable complete retention table, reconstructs every lease and
epoch from canonical payloads, and delegates authority-state interpretation to
``broker_paper_startup_scan``. It cannot create the table, append events, or
grant startup or submission authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import datetime, timezone

import duckdb

from engine.lib.provenance import canonical_sha256

from . import broker_paper_startup_scan
from .broker_contract import require_identifier
from .broker_paper_lease import (
    LEASE_SCHEMA_VERSION,
    PaperAuthorityLease,
    PaperLeaseError,
)
from .broker_paper_runtime import RuntimeControlBindings
from .json_utils import loads_object

RETENTION_SCHEMA_VERSION = 1
RETENTION_TABLE = "broker_paper_authority_retained_events"
MAX_RETAINED_ROWS = (
    broker_paper_startup_scan.MAX_RETAINED_EPOCHS * 18
)
MAX_PAYLOAD_BYTES = 65_536
RETENTION_COLUMNS = (
    ("global_sequence", "BIGINT"),
    ("account_id", "VARCHAR"),
    ("mode", "VARCHAR"),
    ("lease_id", "VARCHAR"),
    ("lease_sha256", "VARCHAR"),
    ("lease_payload", "VARCHAR"),
    ("event_sequence", "INTEGER"),
    ("event_type", "VARCHAR"),
    ("event_payload", "VARCHAR"),
    ("event_sha256", "VARCHAR"),
    ("trusted_activation_event_sha256", "VARCHAR"),
    ("candidate_assessment_sha256", "VARCHAR"),
    ("startup_assessment_sha256", "VARCHAR"),
    ("activation_runtime_epoch_sha256", "VARCHAR"),
    ("prior_global_row_sha256", "VARCHAR"),
    ("row_sha256", "VARCHAR"),
)
RETENTION_SCHEMA = tuple(
    (
        name,
        kind,
        "YES" if name == "prior_global_row_sha256" else "NO",
        None,
    )
    for name, kind in RETENTION_COLUMNS
)
_COLUMN_NAMES = tuple(name for name, _kind in RETENTION_COLUMNS)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEASE_FIELDS = frozenset(field.name for field in fields(PaperAuthorityLease))
_LEASE_PAYLOAD_FIELDS = _LEASE_FIELDS | {"schema_version"}


class PaperAuthorityStartupStoreError(ValueError):
    """The durable retained authority history is unavailable or untrusted."""


def _sha256(
    value: object,
    label: str,
    *,
    optional: bool = False,
) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperAuthorityStartupStoreError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PaperAuthorityStartupStoreError(
            f"{label} must be a nonnegative integer"
        )
    return value


def _positive_integer(value: object, label: str) -> int:
    value = _nonnegative_integer(value, label)
    if value < 1:
        raise PaperAuthorityStartupStoreError(
            f"{label} must be a positive integer"
        )
    return value


def _canonical_json(payload: dict) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _payload(value: object, label: str) -> tuple[dict, str]:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_PAYLOAD_BYTES
    ):
        raise PaperAuthorityStartupStoreError(
            f"{label} is unavailable or exceeds the size limit"
        )
    try:
        parsed = loads_object(value)
        canonical = _canonical_json(parsed)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperAuthorityStartupStoreError(
            f"{label} is not strict canonical JSON"
        ) from exc
    if canonical != value:
        raise PaperAuthorityStartupStoreError(
            f"{label} is not strict canonical JSON"
        )
    return parsed, canonical


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperAuthorityStartupStoreError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperAuthorityStartupStoreError(f"{label} is invalid") from exc
    if (
        parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
        or parsed.isoformat().replace("+00:00", "Z") != value
    ):
        raise PaperAuthorityStartupStoreError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)


def _lease(value: object, *, expected_sha256: str) -> tuple[PaperAuthorityLease, str]:
    payload, canonical = _payload(value, "retained paper lease payload")
    if (
        set(payload) != _LEASE_PAYLOAD_FIELDS
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != LEASE_SCHEMA_VERSION
        or not isinstance(payload.get("allowed_symbols"), list)
    ):
        raise PaperAuthorityStartupStoreError(
            "retained paper lease payload shape is invalid"
        )
    values = {name: payload[name] for name in _LEASE_FIELDS}
    values["allowed_symbols"] = tuple(values["allowed_symbols"])
    for name in ("approved_at", "not_before", "expires_at"):
        values[name] = _parse_utc(values[name], f"retained paper lease {name}")
    try:
        lease = PaperAuthorityLease(**values)
    except (PaperLeaseError, TypeError, ValueError) as exc:
        raise PaperAuthorityStartupStoreError(
            "retained paper lease payload is invalid"
        ) from exc
    if (
        lease.sha256() != expected_sha256
        or _canonical_json(lease.payload()) != canonical
    ):
        raise PaperAuthorityStartupStoreError(
            "retained paper lease payload or hash does not match"
        )
    return lease, canonical


def _retained_row_body(
    *,
    global_sequence: int,
    account_id: str,
    mode: str,
    lease_id: str,
    lease_sha256: str,
    lease_payload: dict,
    event_sequence: int,
    event_type: str,
    event_payload: dict,
    event_sha256: str,
    trusted_activation_event_sha256: str,
    candidate_assessment_sha256: str,
    startup_assessment_sha256: str,
    activation_runtime_epoch_sha256: str,
    prior_global_row_sha256: str | None,
) -> dict:
    """Return the exact body committed by one retained global row hash."""
    return {
        "schema_version": RETENTION_SCHEMA_VERSION,
        "global_sequence": global_sequence,
        "account_id": account_id,
        "mode": mode,
        "lease_id": lease_id,
        "lease_sha256": lease_sha256,
        "lease_payload": lease_payload,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "event_payload": event_payload,
        "event_sha256": event_sha256,
        "trusted_activation_event_sha256": (
            trusted_activation_event_sha256
        ),
        "candidate_assessment_sha256": candidate_assessment_sha256,
        "startup_assessment_sha256": startup_assessment_sha256,
        "activation_runtime_epoch_sha256": (
            activation_runtime_epoch_sha256
        ),
        "prior_global_row_sha256": prior_global_row_sha256,
    }


def _table_schema(
    con: duckdb.DuckDBPyConnection,
) -> tuple[tuple[str, str, str, object], ...] | None:
    tables = con.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [RETENTION_TABLE],
    ).fetchall()
    if not tables:
        return None
    if tables != [("BASE TABLE",)]:
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table type is invalid"
        )
    rows = con.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
        [RETENTION_TABLE],
    ).fetchall()
    if not rows:
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table schema is invalid"
        )
    return tuple(
        (str(name), str(kind), str(nullable), default)
        for name, kind, nullable, default in rows
    )


def _capture_rows(
    con: duckdb.DuckDBPyConnection,
) -> tuple[tuple[object, ...], ...] | None:
    schema = _table_schema(con)
    if schema is None:
        return None
    if schema != RETENTION_SCHEMA:
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table schema is invalid"
        )
    rows = con.execute(
        f"SELECT {', '.join(_COLUMN_NAMES)} FROM {RETENTION_TABLE} "
        "ORDER BY global_sequence LIMIT ?",
        [MAX_RETAINED_ROWS + 1],
    ).fetchall()
    if len(rows) > MAX_RETAINED_ROWS:
        raise PaperAuthorityStartupStoreError(
            "paper authority retained row count exceeds the startup bound"
        )
    return tuple(tuple(row) for row in rows)


def _stable_rows(
    con: duckdb.DuckDBPyConnection,
) -> tuple[tuple[object, ...], ...]:
    try:
        first = _capture_rows(con)
        second = _capture_rows(con)
    except duckdb.Error as exc:
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table is unreadable"
        ) from exc
    if first != second:
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table changed during capture"
        )
    return () if second is None else second


def _epochs(
    rows: tuple[tuple[object, ...], ...],
    *,
    account_id: str,
) -> tuple[broker_paper_startup_scan.RetainedAuthorityEpoch, ...]:
    prior_global_sha256 = None
    epoch_order: list[str] = []
    epochs: dict[str, dict] = {}
    lease_hash_owners: dict[str, str] = {}
    activation_owners: dict[str, str] = {}

    for expected_global_sequence, row in enumerate(rows, 1):
        values = dict(zip(_COLUMN_NAMES, row, strict=True))
        global_sequence = _positive_integer(
            values["global_sequence"],
            "retained global sequence",
        )
        event_sequence = _positive_integer(
            values["event_sequence"],
            "retained authority event sequence",
        )
        for field, label in (
            ("lease_sha256", "retained paper lease identity"),
            ("event_sha256", "retained authority event identity"),
            (
                "trusted_activation_event_sha256",
                "retained activation identity",
            ),
            (
                "candidate_assessment_sha256",
                "retained candidate assessment identity",
            ),
            (
                "startup_assessment_sha256",
                "retained startup assessment identity",
            ),
            (
                "activation_runtime_epoch_sha256",
                "retained activation runtime identity",
            ),
            ("row_sha256", "retained global row identity"),
        ):
            _sha256(values[field], label)
        _sha256(
            values["prior_global_row_sha256"],
            "prior retained global row identity",
            optional=True,
        )
        try:
            require_identifier(values["account_id"], "retained account identifier")
            require_identifier(values["lease_id"], "retained lease identifier")
        except ValueError as exc:
            raise PaperAuthorityStartupStoreError(str(exc)) from exc
        if values["mode"] not in {"agent_only", "hybrid"}:
            raise PaperAuthorityStartupStoreError(
                "retained authority mode is invalid"
            )
        if not isinstance(values["event_type"], str):
            raise PaperAuthorityStartupStoreError(
                "retained authority event type is invalid"
            )
        lease, canonical_lease = _lease(
            values["lease_payload"],
            expected_sha256=values["lease_sha256"],
        )
        event, canonical_event = _payload(
            values["event_payload"],
            "retained authority event payload",
        )
        body = _retained_row_body(
            global_sequence=global_sequence,
            account_id=values["account_id"],
            mode=values["mode"],
            lease_id=values["lease_id"],
            lease_sha256=values["lease_sha256"],
            lease_payload=lease.payload(),
            event_sequence=event_sequence,
            event_type=values["event_type"],
            event_payload=event,
            event_sha256=values["event_sha256"],
            trusted_activation_event_sha256=values[
                "trusted_activation_event_sha256"
            ],
            candidate_assessment_sha256=values[
                "candidate_assessment_sha256"
            ],
            startup_assessment_sha256=values[
                "startup_assessment_sha256"
            ],
            activation_runtime_epoch_sha256=values[
                "activation_runtime_epoch_sha256"
            ],
            prior_global_row_sha256=values["prior_global_row_sha256"],
        )
        if (
            global_sequence != expected_global_sequence
            or values["prior_global_row_sha256"] != prior_global_sha256
            or canonical_sha256(body) != values["row_sha256"]
        ):
            raise PaperAuthorityStartupStoreError(
                "retained global row chain is incomplete or invalid"
            )
        if (
            values["account_id"] != account_id
            or lease.account_id != account_id
            or values["lease_id"] != lease.lease_id
            or values["mode"] != lease.mode
            or event.get("lease_id") != lease.lease_id
            or event.get("lease_sha256") != lease.sha256()
            or event.get("account_id") != account_id
            or event.get("mode") != lease.mode
            or event.get("event_sequence") != event_sequence
            or event.get("event_type") != values["event_type"]
            or event.get("event_sha256") != values["event_sha256"]
        ):
            raise PaperAuthorityStartupStoreError(
                "retained authority account, mode, lease, or event binding drifted"
            )

        lease_id = lease.lease_id
        existing_lease_owner = lease_hash_owners.setdefault(
            lease.sha256(),
            lease_id,
        )
        existing_activation_owner = activation_owners.setdefault(
            values["trusted_activation_event_sha256"],
            lease_id,
        )
        if (
            existing_lease_owner != lease_id
            or existing_activation_owner != lease_id
        ):
            raise PaperAuthorityStartupStoreError(
                "retained lease or activation identity is duplicated"
            )
        epoch = epochs.get(lease_id)
        immutable = (
            lease.sha256(),
            canonical_lease,
            values["trusted_activation_event_sha256"],
            values["candidate_assessment_sha256"],
            values["startup_assessment_sha256"],
            values["activation_runtime_epoch_sha256"],
        )
        if epoch is None:
            epoch = {
                "lease": lease,
                "immutable": immutable,
                "events": [],
                "canonical_events": [],
            }
            epochs[lease_id] = epoch
            epoch_order.append(lease_id)
        if (
            epoch["immutable"] != immutable
            or event_sequence != len(epoch["events"]) + 1
            or canonical_event in epoch["canonical_events"]
        ):
            raise PaperAuthorityStartupStoreError(
                "retained authority epoch is incomplete, duplicated, or drifted"
            )
        epoch["events"].append(event)
        epoch["canonical_events"].append(canonical_event)
        prior_global_sha256 = values["row_sha256"]

    result = []
    for lease_id in epoch_order:
        epoch = epochs[lease_id]
        events = tuple(epoch["events"])
        (
            _lease_sha256,
            _lease_payload,
            activation_sha256,
            candidate_sha256,
            startup_sha256,
            runtime_sha256,
        ) = epoch["immutable"]
        if events[0].get("event_sha256") != activation_sha256:
            raise PaperAuthorityStartupStoreError(
                "retained activation identity does not match the epoch"
            )
        result.append(
            broker_paper_startup_scan.RetainedAuthorityEpoch(
                lease=epoch["lease"],
                events=events,
                retained_event_count=len(events),
                retained_latest_event_sha256=events[-1]["event_sha256"],
                trusted_activation_event_sha256=activation_sha256,
                candidate_assessment_sha256=candidate_sha256,
                startup_assessment_sha256=startup_sha256,
                activation_runtime_epoch_sha256=runtime_sha256,
            )
        )
    return tuple(result)


def load_and_scan_startup(
    con: duckdb.DuckDBPyConnection,
    runtime: RuntimeControlBindings,
    *,
    account_id: str,
    trusted_row_count: int,
    trusted_latest_row_sha256: str | None,
    now: datetime,
) -> dict:
    """Load every retained row and run the non-authorizing startup scanner."""
    try:
        require_identifier(account_id, "account identifier")
    except ValueError as exc:
        raise PaperAuthorityStartupStoreError(str(exc)) from exc
    trusted_row_count = _nonnegative_integer(
        trusted_row_count,
        "trusted retained row count",
    )
    if trusted_row_count > MAX_RETAINED_ROWS:
        raise PaperAuthorityStartupStoreError(
            "trusted retained row count exceeds the startup bound"
        )
    trusted_latest_row_sha256 = _sha256(
        trusted_latest_row_sha256,
        "trusted latest retained row identity",
        optional=trusted_row_count == 0,
    )
    if (
        (trusted_row_count == 0 and trusted_latest_row_sha256 is not None)
        or (trusted_row_count > 0 and trusted_latest_row_sha256 is None)
    ):
        raise PaperAuthorityStartupStoreError(
            "trusted retained row count and head are inconsistent"
        )

    rows = _stable_rows(con)
    if (
        len(rows) != trusted_row_count
        or (
            rows
            and rows[-1][_COLUMN_NAMES.index("row_sha256")]
            != trusted_latest_row_sha256
        )
    ):
        raise PaperAuthorityStartupStoreError(
            "paper authority retention table does not match the trusted global head"
        )
    epochs = _epochs(rows, account_id=account_id)
    try:
        scan = broker_paper_startup_scan.scan_startup(
            epochs,
            runtime,
            account_id=account_id,
            now=now,
        )
    except (
        broker_paper_startup_scan.PaperAuthorityStartupScanError,
        TypeError,
        ValueError,
    ) as exc:
        raise PaperAuthorityStartupStoreError(
            "retained paper authority startup scan failed"
        ) from exc
    retention_body = {
        "schema_version": RETENTION_SCHEMA_VERSION,
        "account_id": account_id,
        "trusted_retained_row_count": trusted_row_count,
        "trusted_latest_retained_row_sha256": trusted_latest_row_sha256,
        "scan_sha256": scan["scan_sha256"],
        "runtime_evidence_sha256": runtime.evidence_sha256,
        "execution_authority": "none",
    }
    return {
        **scan,
        "retention_schema_version": RETENTION_SCHEMA_VERSION,
        "trusted_retained_row_count": trusted_row_count,
        "trusted_latest_retained_row_sha256": trusted_latest_row_sha256,
        "retention_evidence_sha256": canonical_sha256(retention_body),
    }
