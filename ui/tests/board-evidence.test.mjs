import assert from "node:assert/strict";
import test from "node:test";
import { isMetaForwardEvidence } from "../app/lib/meta-forward-contracts.js";
import { isMetaEvidence } from "../app/lib/meta-evidence-contracts.js";
import { countedEvidenceLabel, e1EvidenceLabel, nightlyEvidenceAlert } from "../app/lib/header-status.js";

const invalid = { status: "INVALID", paper_only: true, automatic_action: "none" };
const xs = (status) => ({ status, paper_only: true, automatic_action: "none",
  runtime_contract_version: 21, runtime_contract_sha256: "a".repeat(64),
  paired_complete_months: 0, minimum_paired_months: 48,
  signal_date: "2026-09-30", eligible_after: "2031-10-01",
});

test("XS admits an early kill but keeps mature verdicts gated", () => {
  const value = (status) => ({ forward_review: invalid, e1_forward: invalid, xs_forward_review: xs(status) });
  assert.equal(isMetaForwardEvidence(value("REVIEW-KILL")), true);
  for (const status of ["PASS-FORWARD", "INCONCLUSIVE"]) {
    assert.equal(isMetaForwardEvidence(value(status)), false);
    const mature = value(status); mature.xs_forward_review.paired_complete_months = 48;
    assert.equal(isMetaForwardEvidence(mature), true);
  }
});

test("nightly incomplete is admitted as an operational alert", () => {
  const data = { nightly_evidence: {status: "incomplete", active_portfolios: 25, portfolios_with_equity: 24},
    miner_evidence: {status: "invalid"}, sweep_evidence: {status: "invalid", reason: "projection-error"},
    liquidity_evidence: {status: "not-yet-run", reason: "no-scheduled-run"},
    walkforward_evidence: {status: "invalid", reason: "projection-error"},
  };
  assert.equal(isMetaEvidence(data), true);
  assert.equal(nightlyEvidenceAlert(data.nightly_evidence), true);
  assert.equal(nightlyEvidenceAlert({status: "current"}), false);
});

test("sparse invalid evidence labels never invent counters or versions", () => {
  assert.equal(e1EvidenceLabel(invalid), "invalid");
  assert.equal(countedEvidenceLabel({status: "invalid"}, "current", "expected"), "invalid");
  assert.equal(countedEvidenceLabel({status: "invalid", reason: "projection-error"}, "current_charters", "open_charters"), "invalid");
  assert.equal(e1EvidenceLabel({...invalid, observations: 0, target_observations: 40, runtime_contract_version: 6}), "invalid (0/40, v6)");
  assert.equal(countedEvidenceLabel({status: "issues", current: 0, expected: 5}, "current", "expected"), "issues (0/5)");
});
