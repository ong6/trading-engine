"""Reconcile and project a cohort of published walk-forward results."""

from pathlib import Path

from engine.lib.provenance import canonical_sha256
from server import walkforward_artifacts
from server.file_utils import MAX_OPERATIONAL_FILE_BYTES, read_text
from server.json_utils import loads_unique_object, require_finite_numbers

MAX_RESULT_FILE_BYTES = MAX_OPERATIONAL_FILE_BYTES
DIAGNOSTIC_LIST_LIMIT = 100
DIAGNOSTIC_VALUE_MAX_CHARS = 256
DIAGNOSTIC_FIELDS = (
    "missing_results",
    "invalid_files",
    "config_mismatches",
    "registration_mismatches",
    "duplicate_config_ids",
    "invalid_registrations",
)


def empty_scan() -> dict:
    """Return a mutable accumulator with the closed artifact scan schema."""
    return {
        "rows": {},
        "invalid_files": [],
        "config_mismatches": set(),
        "registration_mismatches": set(),
        "duplicate_config_ids": set(),
        "source_by_id": {},
    }


def _scan_result_file(path: Path, registrations: dict[str, dict], scan: dict) -> None:
    raw = read_text(path, max_bytes=MAX_RESULT_FILE_BYTES, label="walk-forward result")
    payload = loads_unique_object(raw)
    config_id = payload["config_id"]
    if not isinstance(config_id, str) or not config_id:
        raise ValueError("invalid config_id")
    if config_id not in registrations:
        return
    require_finite_numbers(payload)
    if config_id in scan["source_by_id"]:
        scan["duplicate_config_ids"].add(config_id)
        scan["invalid_files"].extend((scan["source_by_id"][config_id].name, path.name))
        return
    scan["source_by_id"][config_id] = path
    registration = registrations[config_id]
    if payload.get("config_sha256") != registration["config_sha256"]:
        scan["config_mismatches"].add(config_id)
    walkforward_artifacts.validate_result(payload, registration)
    cohort, key = walkforward_artifacts.signature(payload)
    if (
        cohort["initial_cash"] != registration["initial_cash"]
        or canonical_sha256(cohort["execution_profile"]) != registration["execution_profile_sha256"]
        or payload.get("comparison") != registration["comparison"]
    ):
        scan["registration_mismatches"].add(config_id)
    scan["rows"][config_id] = (cohort, key)


def scan_results(root: Path, registrations: dict[str, dict]) -> dict:
    """Read all result JSON files and reconcile artifacts to registrations."""
    scan = empty_scan()
    if not root.exists():
        return scan
    for path in sorted(root.glob("*.json")):
        try:
            _scan_result_file(path, registrations, scan)
        except (OSError, KeyError, TypeError, ValueError):
            scan["invalid_files"].append(path.name)
    return scan


def status(
    *,
    scan: dict,
    invalid_registrations: list[str],
    missing: list[str],
    signatures: dict,
    cohort: dict | None,
    current_sha256: str,
) -> str:
    """Classify a complete scan against registration and source expectations."""
    if (
        invalid_registrations
        or scan["invalid_files"]
        or scan["config_mismatches"]
        or scan["duplicate_config_ids"]
    ):
        return "invalid"
    if missing:
        return "incomplete"
    if len(signatures) != 1:
        return "mixed-cohort"
    if scan["registration_mismatches"]:
        return "invalid"
    if cohort["source_sha256"] != current_sha256:
        return "stale-source"
    return "current"


def _cohort_payload(cohort: dict | None) -> dict:
    return {
        "cohort_source_sha256": cohort["source_sha256"] if cohort else None,
        "cohort_anchor": cohort["anchor"] if cohort else None,
        "cohort_train_months": cohort["train_months"] if cohort else None,
        "cohort_validate_months": cohort["validate_months"] if cohort else None,
        "cohort_step_months": cohort["step_months"] if cohort else None,
        "cohort_fill_model": cohort["fill_model"] if cohort else None,
        "cohort_universe_policy": cohort["universe_policy"] if cohort else None,
        "cohort_initial_cash": cohort["initial_cash"] if cohort else None,
        "cohort_execution_profile_id": cohort["execution_profile"]["id"] if cohort else None,
        "cohort_execution_profile_sha256": (
            canonical_sha256(cohort["execution_profile"]) if cohort else None
        ),
        "cohort_data_snapshot_sha256": cohort["data_snapshot_sha256"] if cohort else None,
        "cohort_comparison_protocol": cohort["comparison_protocol"] if cohort else None,
        "cohort_signature_sha256": canonical_sha256(cohort) if cohort else None,
    }


def _diagnostic_payload(field: str, values: list[str]) -> dict:
    visible_values = values[:DIAGNOSTIC_LIST_LIMIT]
    return {
        field: [value[:DIAGNOSTIC_VALUE_MAX_CHARS] for value in visible_values],
        f"{field}_count": len(values),
        f"{field}_truncated": len(values) > DIAGNOSTIC_LIST_LIMIT,
        f"{field}_values_truncated": any(
            len(value) > DIAGNOSTIC_VALUE_MAX_CHARS for value in visible_values
        ),
    }


def _scan_payload(expected: set[str], scan: dict, invalid_registrations: list[str]) -> dict:
    rows = scan["rows"]
    diagnostics = {
        "missing_results": sorted(expected - rows.keys()),
        "invalid_files": sorted(set(scan["invalid_files"])),
        "config_mismatches": sorted(scan["config_mismatches"]),
        "registration_mismatches": sorted(scan["registration_mismatches"]),
        "duplicate_config_ids": sorted(scan["duplicate_config_ids"]),
        "invalid_registrations": sorted(invalid_registrations),
    }
    result = {
        "expected_results": len(expected),
        "available_results": len(rows),
        "diagnostic_list_limit": DIAGNOSTIC_LIST_LIMIT,
        "diagnostic_value_max_chars": DIAGNOSTIC_VALUE_MAX_CHARS,
    }
    for field in DIAGNOSTIC_FIELDS:
        result.update(_diagnostic_payload(field, diagnostics[field]))
    return result


def result_payload(
    *,
    status: str,
    current_sha256: str | None,
    current_file_count: int | None,
    cohort: dict | None,
    signature_count: int,
    expected: set[str],
    scan: dict,
    invalid_registrations: list[str],
) -> dict:
    """Project a stable operational response from validated cohort state."""
    return {
        "status": status,
        "current_source_sha256": current_sha256,
        "current_source_file_count": current_file_count,
        **_cohort_payload(cohort),
        "cohort_signature_count": signature_count,
        **_scan_payload(expected, scan, invalid_registrations),
    }
