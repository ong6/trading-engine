// Public composition contract for the operational and prospective status exposed by /meta.

import { isMetaAutomation } from "./meta-automation-contracts.js";
import { hasExactFields } from "./meta-contract-utils.js";
import { isMetaCore } from "./meta-core-contracts.js";
import { isMetaEvidence } from "./meta-evidence-contracts.js";
import { isMetaExposure } from "./meta-exposure-contracts.js";
import { isMetaForwardEvidence } from "./meta-forward-contracts.js";
import { isMetaJobState } from "./meta-job-contracts.js";

const META_FIELDS = [
  "meta",
  "meta_file",
  "latest_prices_date",
  "freshness_days",
  "market_freshness",
  "price_verification",
  "queue",
  "nightly_evidence",
  "miner_evidence",
  "sweep_evidence",
  "liquidity_evidence",
  "stale_exposure",
  "price_quarantines",
  "price_quarantines_limit",
  "price_quarantines_matching_count",
  "price_quarantines_truncated",
  "scheduler",
  "friday_postflight",
  "source_control",
  "nightly",
  "weekly_verify",
  "weekly_sweeps",
  "weekly_liquidity",
  "weekly_walkforward",
  "walkforward_evidence",
  "forward_review",
  "xs_forward_review",
  "e1_forward",
];

export function isMetaProjection(data) {
  return (
    hasExactFields(data, META_FIELDS) &&
    isMetaCore(data) &&
    isMetaJobState(data) &&
    isMetaAutomation(data) &&
    isMetaEvidence(data) &&
    isMetaExposure(data) &&
    isMetaForwardEvidence(data)
  );
}
