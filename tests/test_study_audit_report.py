import copy
import json

import pytest

from farm.study import audit_report


def _report():
    counts = {"expected": 4, "complete_inputs": 2, "missing_inputs": 2,
              "invalid_inputs": 0, "late_inputs": 0, "unknown_inputs": 0,
              "unresolved_eligibility": 0, "coverage": 0.5}
    return {"schema_version": 1, "audit_id": "a" * 64, "study_id": "fictional",
            "decision": "unusable",
            "checks": {"coverage": {"status": "fail", "evidence_basis": "independent_reference",
                                    "reason": "two omitted securities"}},
            "sessions": [{"session": "2024-03-28", **counts,
                          "bins": {"at_least_20000000": counts}}],
            "snapshots": {"audited": "b" * 64, "reference": "c" * 64},
            "limitations": ["Diagnostic evidence only."],
            "evidence": {"examined": 4, "sample_limit": 1, "truncated": True,
                         "rows": [{"ticker": "OMITTED", "status": "missing"}]},
            "outcomes": {"attempted": 4, "completed": 2, "missing_entry": 2}}


def test_json_markdown_parity_and_atomic_sidecar_preserve_existing_reports(tmp_path):
    payload = _report()
    original = copy.deepcopy(payload)
    (tmp_path / "report.json").write_bytes(b"frozen study JSON")
    (tmp_path / "report.md").write_bytes(b"frozen study Markdown")
    markdown_path, json_path = audit_report.write_audit(tmp_path, payload)
    assert json_path.read_bytes() == audit_report.json_bytes(payload)
    assert json.loads(json_path.read_text()) == payload
    rendered = markdown_path.read_text()
    embedded = rendered.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(embedded) == payload
    assert "| 2024-03-28 | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0.5 |" in rendered
    assert payload == original
    assert (tmp_path / "report.json").read_bytes() == b"frozen study JSON"
    assert (tmp_path / "report.md").read_bytes() == b"frozen study Markdown"
    assert not list(tmp_path.glob("*.tmp"))


def test_mapping_order_does_not_change_canonical_bytes_or_markdown():
    payload = _report()
    reversed_keys = dict(reversed(list(payload.items())))
    assert audit_report.json_bytes(payload) == audit_report.json_bytes(reversed_keys)
    assert audit_report.markdown(payload) == audit_report.markdown(reversed_keys)


def test_null_coverage_and_unknowns_stay_explicit_and_labels_are_escaped():
    payload = _report()
    payload["study_id"] = "<script>|[untrusted](bad)"
    payload["sessions"][0]["coverage"] = None
    payload["sessions"][0]["unresolved_eligibility"] = 1
    payload["evidence"]["examined"] = 5
    bin_row = payload["sessions"][0]["bins"]["at_least_20000000"]
    bin_row["coverage"], bin_row["unresolved_eligibility"] = None, 1
    payload["decision"] = "limited"
    payload["checks"]["coverage"]["status"] = "unknown"
    payload["limitations"] = ["`````\n# imported text"]
    rendered = audit_report.markdown(payload)
    assert "&lt;script&gt;\\|\\[untrusted\\]\\(bad\\)" in rendered
    assert "| 2024-03-28 | 4 | 2 | 2 | 0 | 0 | 0 | 1 | unavailable |" in rendered
    assert "``````json\n" in rendered
    assert json.loads(audit_report.json_bytes(payload))["sessions"][0]["coverage"] is None


@pytest.mark.parametrize("fault", ["nan", "missing", "status", "count", "bound", "shape",
                                 "contract", "hash"])
def test_malformed_payload_never_writes_a_successful_artifact(tmp_path, fault):
    payload = _report()
    if fault == "nan":
        payload["sessions"][0]["coverage"] = float("nan")
    elif fault == "missing":
        del payload["audit_id"]
    elif fault == "status":
        payload["checks"]["coverage"]["status"] = ["pass"]
    elif fault == "count":
        payload["sessions"][0]["expected"] = True
    elif fault == "bound":
        payload["evidence"]["rows"] *= 2
    elif fault == "contract":
        payload["contract"] = []
    elif fault == "hash":
        payload["snapshots"]["reference"] = {}
    else:
        payload["sessions"][0]["bins"] = []
    with pytest.raises(audit_report.AuditReportError):
        audit_report.write_audit(tmp_path / "output", payload)
    assert not (tmp_path / "output").exists()


def test_output_cannot_target_operational_or_tracked_data_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_report, "__file__", str(tmp_path / "farm/study/audit_report.py"))
    for name in ("data", "store"):
        with pytest.raises(audit_report.AuditReportError, match="outside"):
            audit_report.write_audit(tmp_path / name / "audit", _report())
        assert not (tmp_path / name).exists()


@pytest.mark.parametrize("fault", ["decision", "ratio", "population", "bins"])
def test_contradictory_semantics_are_rejected(fault):
    payload = _report()
    if fault == "decision":
        payload["decision"] = "supported"
    elif fault == "ratio":
        payload["sessions"][0]["coverage"] = 1.0
    elif fault == "population":
        payload["sessions"][0]["complete_inputs"] = 10
    else:
        payload["sessions"][0]["bins"] = {}
    with pytest.raises(audit_report.AuditReportError):
        audit_report.json_bytes(payload)


def test_required_flags_and_finding_totals_preserve_uncapped_population():
    payload = _report()
    payload["contract"] = {"required_checks": ["coverage"]}
    payload["checks"]["price_basis"] = {"status": "unknown", "required": True}
    payload["findings"] = [{"reason": "missing"}]
    payload["finding_summary"] = {"total": 2, "displayed": 1, "truncated": True,
                                  "reason_counts": {"missing": 2}}
    encoded = json.loads(audit_report.json_bytes(payload))
    assert encoded["finding_summary"]["total"] == 2
    payload["finding_summary"]["displayed"] = 2
    with pytest.raises(audit_report.AuditReportError, match="finding totals"):
        audit_report.json_bytes(payload)
    payload["finding_summary"]["displayed"] = 1
    payload["checks"]["coverage"]["status"] = "pass"
    payload["decision"] = "supported"
    with pytest.raises(audit_report.AuditReportError, match="decision"):
        audit_report.json_bytes(payload)
    payload["decision"] = "limited"
    audit_report.json_bytes(payload)
    payload["checks"]["price_basis"]["required"] = 1
    with pytest.raises(audit_report.AuditReportError, match="status"):
        audit_report.json_bytes(payload)
