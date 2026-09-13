import {
  isIsoDate,
  isNonnegativeInteger,
  isPositiveInteger,
  isRecord,
} from "./response-contracts.js";

function hasRuntimeContract(evidence) {
  return (
    isPositiveInteger(evidence.runtime_contract_version) &&
    typeof evidence.runtime_contract_sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(evidence.runtime_contract_sha256)
  );
}

function hasForwardEnvelope(evidence, statuses) {
  return (
    isRecord(evidence) &&
    statuses.includes(evidence.status) &&
    evidence.paper_only === true &&
    evidence.automatic_action === "none"
  );
}

function isInvalidForward(evidence) {
  return (
    evidence.status === "INVALID" &&
    Object.keys(evidence).length === 3 &&
    Object.prototype.hasOwnProperty.call(evidence, "paper_only") &&
    Object.prototype.hasOwnProperty.call(evidence, "automatic_action")
  );
}

function isSectorForward(evidence) {
  if (!hasForwardEnvelope(evidence, ["ACCUMULATING", "CONTINUE", "INVALID", "REVIEW-KILL"])) {
    return false;
  }
  if (evidence.status === "INVALID") return isInvalidForward(evidence);
  return (
    hasRuntimeContract(evidence) &&
    isNonnegativeInteger(evidence.shared_sessions) &&
    isPositiveInteger(evidence.minimum_shared_sessions) &&
    isIsoDate(evidence.eligible_after) &&
    (!["CONTINUE", "REVIEW-KILL"].includes(evidence.status) ||
      evidence.shared_sessions >= evidence.minimum_shared_sessions)
  );
}

function isXsForward(evidence) {
  if (
    !hasForwardEnvelope(evidence, [
      "ACCUMULATING",
      "CONTINUE",
      "INCONCLUSIVE",
      "INVALID",
      "PASS-FORWARD",
      "REVIEW-KILL",
      "WAITING",
    ])
  ) {
    return false;
  }
  if (evidence.status === "INVALID") return isInvalidForward(evidence);
  return (
    hasRuntimeContract(evidence) &&
    isNonnegativeInteger(evidence.paired_complete_months) &&
    isPositiveInteger(evidence.minimum_paired_months) &&
    isIsoDate(evidence.signal_date) &&
    isIsoDate(evidence.eligible_after) &&
    evidence.signal_date <= evidence.eligible_after &&
    (evidence.status !== "WAITING" || evidence.paired_complete_months === 0) &&
    (!["INCONCLUSIVE", "PASS-FORWARD", "REVIEW-KILL"].includes(evidence.status) ||
      evidence.paired_complete_months >= evidence.minimum_paired_months)
  );
}

function isE1Forward(evidence) {
  if (!hasForwardEnvelope(evidence, ["ACCUMULATING", "INVALID", "KILLED", "SURVIVED"])) {
    return false;
  }
  if (evidence.status === "INVALID") return isInvalidForward(evidence);
  return (
    hasRuntimeContract(evidence) &&
    isNonnegativeInteger(evidence.observations) &&
    isPositiveInteger(evidence.target_observations) &&
    isIsoDate(evidence.sample_end) &&
    (evidence.status !== "ACCUMULATING" ||
      evidence.observations < evidence.target_observations) &&
    (!["KILLED", "SURVIVED"].includes(evidence.status) ||
      evidence.observations >= evidence.target_observations)
  );
}

export function isMetaForwardEvidence(data) {
  return (
    isSectorForward(data.forward_review) &&
    isXsForward(data.xs_forward_review) &&
    isE1Forward(data.e1_forward)
  );
}
