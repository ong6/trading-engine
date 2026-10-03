"""Deterministic, atomic JSON/Markdown sidecars, separate from study reports."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Mapping

from engine.lib.resources import write_text_atomic

STATUSES = {"pass", "fail", "unknown", "not_applicable"}
DECISIONS = {"supported", "unusable", "limited"}
COUNTS = ("expected", "complete_inputs", "missing_inputs", "invalid_inputs",
          "late_inputs", "unknown_inputs", "unresolved_eligibility")


class AuditReportError(ValueError):
    """The supplied payload cannot be rendered as a successful audit."""


def _validated(report: Mapping) -> dict:
    try:
        payload = json.loads(json.dumps(report, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise AuditReportError("audit payload must contain finite JSON values") from exc
    required = {"schema_version", "audit_id", "study_id", "decision", "checks",
                "sessions", "evidence", "snapshots", "limitations"}
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise AuditReportError("audit payload is missing required fields")
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or not isinstance(payload["audit_id"], str)
            or re.fullmatch(r"[0-9a-f]{64}", payload["audit_id"]) is None
            or not isinstance(payload["decision"], str) or payload["decision"] not in DECISIONS
            or not isinstance(payload["study_id"], str)):
        raise AuditReportError("audit identity, version or decision is invalid")
    if (not isinstance(payload["checks"], dict)
            or not isinstance(payload["sessions"], list)
            or not isinstance(payload["snapshots"], dict)
            or not isinstance(payload["evidence"], dict)
            or not isinstance(payload["limitations"], list)):
        raise AuditReportError("audit sections have invalid shapes")
    for check in payload["checks"].values():
        if (not isinstance(check, dict) or not isinstance(check.get("status"), str)
                or check["status"] not in STATUSES
                or "required" in check and type(check["required"]) is not bool):
            raise AuditReportError("audit check status is invalid")
    for row in payload["sessions"]:
        if (not isinstance(row, dict) or not isinstance(row.get("session"), str)
                or not isinstance(row.get("bins", {}), dict)):
            raise AuditReportError("audit session is invalid")
        for counts in (row, *row.get("bins", {}).values()):
            if (not isinstance(counts, dict) or "coverage" not in counts
                    or any(type(counts.get(key)) is not int or counts[key] < 0 for key in COUNTS)):
                raise AuditReportError("audit counts must be nonnegative integers")
            coverage = counts.get("coverage")
            if coverage is not None and (
                    isinstance(coverage, bool) or not isinstance(coverage, (int, float))
                    or not 0 <= coverage <= 1):
                raise AuditReportError("audit coverage must be null or between zero and one")
            if sum(counts[key] for key in COUNTS[1:-1]) != counts["expected"]:
                raise AuditReportError("audit input categories must sum to the expected population")
            if type(counts.get("denominator_complete", True)) is not bool:
                raise AuditReportError("audit denominator completeness must be boolean")
            expected_ratio = (counts["complete_inputs"] / counts["expected"]
                              if counts["expected"] and not counts["unresolved_eligibility"]
                              and counts.get("denominator_complete", True) else None)
            if ((expected_ratio is None) != (coverage is None)
                    or expected_ratio is not None and not math.isclose(
                        coverage, expected_ratio, rel_tol=0, abs_tol=1e-12)):
                raise AuditReportError("audit coverage disagrees with its population counts")
        if "bins" in row and any(sum(bin_row[key] for bin_row in row["bins"].values()) != row[key]
                                 for key in COUNTS):
            raise AuditReportError("audit liquidity bins must sum to session counts")
    checks = payload["checks"]
    contract = payload.get("contract", {})
    if not isinstance(contract, dict):
        raise AuditReportError("audit contract must be a JSON object")
    required_checks = contract.get("required_checks", [
        name for name, check in checks.items() if check.get("required", True)])
    if (not isinstance(required_checks, list)
            or any(not isinstance(name, str) or name not in checks for name in required_checks)):
        raise AuditReportError("audit required checks are invalid")
    required_checks = sorted(set(required_checks) | {
        name for name, check in checks.items() if check.get("required") is True})
    statuses = [checks[name]["status"] for name in required_checks]
    decision = ("unusable" if "fail" in statuses or checks.get("price_basis", {}).get("status") == "fail"
                else "limited" if "unknown" in statuses else "supported")
    if payload["decision"] != decision:
        raise AuditReportError("audit decision disagrees with required check statuses")
    if any(not isinstance(payload["snapshots"].get(name), str)
           or re.fullmatch(r"[0-9a-f]{64}", payload["snapshots"][name]) is None
           for name in ("audited", "reference")):
        raise AuditReportError("audit snapshot digests are invalid")
    evidence = payload["evidence"]
    if (type(evidence.get("examined")) is not int or evidence["examined"] < 0
            or type(evidence.get("sample_limit")) is not int or evidence["sample_limit"] < 0
            or type(evidence.get("truncated")) is not bool
            or not isinstance(evidence.get("rows"), list)
            or len(evidence["rows"]) > min(evidence["sample_limit"], evidence["examined"])
            or evidence["examined"] != sum(row["expected"] + row["unresolved_eligibility"]
                                           for row in payload["sessions"])
            or evidence["truncated"] != (evidence["examined"] > len(evidence["rows"]))):
        raise AuditReportError("audit evidence counts or sample bound are invalid")
    if "finding_summary" in payload:
        summary, findings = payload["finding_summary"], payload.get("findings")
        if (not isinstance(summary, dict) or not isinstance(findings, list)
                or type(summary.get("total")) is not int or summary["total"] < 0
                or type(summary.get("displayed")) is not int
                or summary["displayed"] != len(findings)
                or len(findings) > min(summary["total"], evidence["sample_limit"])
                or type(summary.get("truncated")) is not bool
                or summary["truncated"] != (summary["total"] > len(findings))):
            raise AuditReportError("audit finding totals disagree with bounded samples")
    return payload


def json_bytes(report: Mapping) -> bytes:
    """Canonical sidecar bytes; do not add run time or host metadata."""
    return (json.dumps(_validated(report), indent=2, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def _text(value: object) -> str:
    text = "unavailable" if value is None else str(value)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()|])", r"\\\1", text).replace("\n", " ")


def _row(label: str, row: dict) -> str:
    values = [label, *(row[key] for key in COUNTS), row["coverage"]]
    return "| " + " | ".join(_text(value) for value in values) + " |"


def markdown(report: Mapping) -> str:
    """Display canonical values directly; full bounded evidence stays inspectable."""
    payload = _validated(report)
    lines = ["# Market-data audit", "", "Synthetic or supplied diagnostic; "
             "data fitness does not establish profitability.", "",
             f"Study: {_text(payload['study_id'])}  ",
             f"Audit identity: `{payload['audit_id']}`  ",
             f"Decision: **{payload['decision']}**", "", "## Checks", "",
             "| Check | Status | Evidence basis | Reason |", "|---|---|---|---|"]
    for name, check in sorted(payload["checks"].items()):
        values = (name, check["status"], check.get("evidence_basis"), check.get("reason"))
        lines.append("| " + " | ".join(_text(value) for value in values) + " |")
    lines += ["", "## Decision-session input coverage", "",
              "Unknown eligibility remains separate from the known expected population. "
              "A null coverage is unavailable, never zero or 100%.", "",
              "| Session / liquidity bin | Expected | Complete | Missing | Invalid | Late | "
              "Unknown inputs | Unresolved eligibility | Coverage |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in payload["sessions"]:
        lines.append(_row(row["session"], row))
        for name, counts in sorted(row.get("bins", {}).items()):
            lines.append(_row(f"{row['session']} / {name}", counts))
    lines += ["", "## Limitations", ""]
    lines.extend("- " + _text(value) for value in payload["limitations"] or ["None declared."])
    encoded = json_bytes(payload).decode("utf-8").rstrip("\n")
    longest = max((len(match.group()) for match in re.finditer(r"`+", encoded)), default=0)
    fence = "`" * max(3, longest + 1)
    lines += ["", "## Canonical evidence", "",
              "The complete sidecar below preserves snapshot binding, outcome populations, "
              "finding totals and bounded samples exactly.", "", fence + "json", encoded, fence]
    return "\n".join(lines) + "\n"


def write_audit(output_dir: str | Path, report: Mapping) -> tuple[Path, Path]:
    """Validate both artifacts before writing; never overwrite a study report."""
    encoded, rendered = json_bytes(report), markdown(report)
    target = Path(output_dir).resolve()
    root = Path(__file__).resolve().parents[2]
    if any(target.is_relative_to(root / name) for name in ("data", "store")):
        raise AuditReportError("audit output must be outside repository data and store directories")
    json_path, markdown_path = target / "audit.json", target / "audit.md"
    write_text_atomic(json_path, encoded.decode("utf-8"))
    write_text_atomic(markdown_path, rendered)
    return markdown_path, json_path
