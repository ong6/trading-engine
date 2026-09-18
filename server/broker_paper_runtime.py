"""Read-only current-process and one-way halt-chain bindings.

The runtime epoch is generated from process-local entropy and the current
process identifier. It is never persisted, restored, or accepted from a
caller. The control anchor is derived from the complete verified halt chain.
This module cannot activate authority or mutate either ledger.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import asdict, dataclass

import duckdb

from engine.lib.provenance import canonical_sha256

from . import broker_risk_control
from .broker_contract import BrokerStateError, require_identifier
from .broker_paper_authority_transcript import ControlAnchor

RUNTIME_BINDING_SCHEMA_VERSION = 1
_PROCESS_NONCE = secrets.token_bytes(32)


class PaperRuntimeError(ValueError):
    """Current process/control state cannot form a trusted runtime binding."""


@dataclass(frozen=True, slots=True)
class RuntimeControlBindings:
    """Current non-persisted process epoch and verified halt-chain head."""

    account_id: str
    runtime_epoch_sha256: str
    control: ControlAnchor
    control_status_sha256: str
    evidence_sha256: str
    execution_authority: str = "none"


def runtime_epoch_sha256() -> str:
    """Return this process's stable, non-persisted runtime epoch identity."""
    digest = hashlib.sha256()
    digest.update(b"trading-engine-paper-runtime-v1\0")
    digest.update(_PROCESS_NONCE)
    digest.update(str(os.getpid()).encode("ascii"))
    return digest.hexdigest()


def _evidence_body(runtime: RuntimeControlBindings) -> dict:
    return {
        "schema_version": RUNTIME_BINDING_SCHEMA_VERSION,
        "account_id": runtime.account_id,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
        "control": runtime.control.payload(),
        "control_status_sha256": runtime.control_status_sha256,
        "execution_authority": runtime.execution_authority,
    }


def verify_runtime_control(
    runtime: RuntimeControlBindings,
    *,
    account_id: str,
) -> RuntimeControlBindings:
    """Verify a loaded binding belongs to this process and account."""
    if not isinstance(runtime, RuntimeControlBindings):
        raise TypeError("runtime must be RuntimeControlBindings")
    require_identifier(account_id, "account identifier")
    if (
        runtime.account_id != account_id
        or runtime.runtime_epoch_sha256 != runtime_epoch_sha256()
        or runtime.execution_authority != "none"
        or runtime.evidence_sha256 != canonical_sha256(_evidence_body(runtime))
    ):
        raise PaperRuntimeError("paper runtime binding is invalid")
    return runtime


def load_runtime_control(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> RuntimeControlBindings:
    """Load a twice-stable verified halt anchor for the current process."""
    require_identifier(account_id, "account identifier")
    try:
        first = broker_risk_control.status(con, account_id)
        second = broker_risk_control.status(con, account_id)
    except BrokerStateError as exc:
        raise PaperRuntimeError("paper runtime control verification failed") from exc
    if first != second:
        raise PaperRuntimeError("paper runtime control changed during capture")
    if (
        first.schema_version != broker_risk_control.CONTROL_SCHEMA_VERSION
        or first.account_id != account_id
        or first.halted is not True
        or first.execution_authority != "none"
        or first.event_count < 1
        or first.latest_event_sha256 is None
    ):
        raise PaperRuntimeError("paper runtime requires a verified halt-chain anchor")
    try:
        anchor = ControlAnchor(
            event_count=first.event_count,
            latest_event_sha256=first.latest_event_sha256,
        )
    except ValueError as exc:
        raise PaperRuntimeError("paper runtime control anchor is invalid") from exc
    epoch_sha256 = runtime_epoch_sha256()
    control_status_sha256 = canonical_sha256(asdict(first))
    loaded = RuntimeControlBindings(
        account_id=account_id,
        runtime_epoch_sha256=epoch_sha256,
        control=anchor,
        control_status_sha256=control_status_sha256,
        evidence_sha256="0" * 64,
    )
    return RuntimeControlBindings(
        account_id=loaded.account_id,
        runtime_epoch_sha256=loaded.runtime_epoch_sha256,
        control=loaded.control,
        control_status_sha256=loaded.control_status_sha256,
        evidence_sha256=canonical_sha256(_evidence_body(loaded)),
    )
