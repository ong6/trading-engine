import { driverAlert, walkforwardLabel } from "../lib/header-status";

export default function HeaderResearchStatus({ res, data }) {
  const weeklySweeps = data.weekly_sweeps || null;
  const weekly = data.weekly_walkforward || null;
  const weeklyLiquidity = data.weekly_liquidity || null;
  const walkforwardEvidence = data.walkforward_evidence || null;
  const forward = data.forward_review || null;
  const xsForward = data.xs_forward_review || null;
  const e1Forward = data.e1_forward || null;
  const queue = data.queue || {};
  const minerEvidence = data.miner_evidence || null;
  const sweepEvidence = data.sweep_evidence || null;
  const liquidityEvidence = data.liquidity_evidence || null;
  const staleExposure = data.stale_exposure || {};
  const queueCounts = queue.counts || {};
  const refreshCounts =
    (weekly && (weekly.refresh_job_counts || weekly.recovery_job_counts)) || null;
  const actionableQueueFailures = queue.actionable_failure_count || 0;
  const sweepsAlert = driverAlert(weeklySweeps);
  const researchAlert = driverAlert(weekly);
  const liquidityAlert = driverAlert(weeklyLiquidity);
  const evidenceAlert =
    walkforwardEvidence && !["updating", "current"].includes(walkforwardEvidence.status);
  const forwardAlert = forward && ["INVALID", "REVIEW-KILL"].includes(forward.status);
  const xsForwardAlert =
    xsForward && ["INVALID", "REVIEW-KILL"].includes(xsForward.status);
  const e1ForwardAlert = e1Forward && ["INVALID", "KILLED"].includes(e1Forward.status);
  const liquidityEvidenceAlert =
    liquidityEvidence &&
    !["not-yet-run", "updating", "current"].includes(liquidityEvidence.status);

  return (
    <>
      <span className={sweepsAlert ? "research-fail" : ""}>
        <span className="k">research sweeps </span>
        {res.busy ? "db busy" : weeklySweeps ? weeklySweeps.status : "not yet run"}
      </span>
      {sweepEvidence ? (
        <span
          className={
            !["idle", "current", "updating"].includes(sweepEvidence.status)
              ? "research-fail"
              : ""
          }
        >
          <span className="k">sweep evidence </span>
          {sweepEvidence.status === "idle"
            ? "idle (no open charter)"
            : `${sweepEvidence.status} (${sweepEvidence.current_charters || 0}/${sweepEvidence.open_charters || 0})`}
        </span>
      ) : null}
      <span className={researchAlert ? "research-fail" : ""}>
        <span className="k">weekly research </span>
        {res.busy ? "db busy" : walkforwardLabel(weekly, refreshCounts)}
      </span>
      <span className={liquidityAlert ? "research-fail" : ""}>
        <span className="k">liquidity refresh </span>
        {res.busy
          ? "db busy"
          : weeklyLiquidity
            ? `${weeklyLiquidity.status}${weeklyLiquidity.stage ? ` (${weeklyLiquidity.stage})` : ""}`
            : "not yet run"}
      </span>
      {liquidityEvidence ? (
        <span className={liquidityEvidenceAlert ? "research-fail" : ""}>
          <span className="k">liquidity evidence </span>
          {liquidityEvidence.status}
        </span>
      ) : null}
      {walkforwardEvidence ? (
        <span className={evidenceAlert ? "research-fail" : ""}>
          <span className="k">WF evidence </span>
          {walkforwardEvidence.status}
        </span>
      ) : null}
      <span className={forwardAlert ? "research-fail" : ""}>
        <span className="k">sector forward </span>
        {res.busy
          ? "db busy"
          : forward
            ? `${forward.status.toLowerCase()}${forward.runtime_contract_version ? ` (v${forward.runtime_contract_version})` : ""}`
            : "unknown"}
      </span>
      <span className={xsForwardAlert ? "research-fail" : ""}>
        <span className="k">XS forward </span>
        {res.busy
          ? "db busy"
          : xsForward
            ? `${xsForward.status.toLowerCase()}${xsForward.runtime_contract_version ? ` (v${xsForward.runtime_contract_version})` : ""}`
            : "unknown"}
      </span>
      <span className={e1ForwardAlert ? "research-fail" : ""}>
        <span className="k">E1 forward </span>
        {res.busy
          ? "db busy"
          : e1Forward
            ? `${e1Forward.status.toLowerCase()} (${e1Forward.observations || 0}/${e1Forward.target_observations || 40}, v${e1Forward.runtime_contract_version})`
            : "unknown"}
      </span>
      {queueCounts.pending || queueCounts.running || actionableQueueFailures ? (
        <span className={actionableQueueFailures ? "research-fail" : ""}>
          <span className="k">queue </span>
          {queueCounts.running || 0} running · {queueCounts.pending || 0} pending ·{" "}
          {actionableQueueFailures} actionable failed
        </span>
      ) : null}
      {minerEvidence && minerEvidence.status !== "current" ? (
        <span className="research-fail">
          <span className="k">miner evidence </span>
          {`${minerEvidence.status} (${minerEvidence.current || 0}/${minerEvidence.expected || 0})`}
        </span>
      ) : null}
      {staleExposure.position_count || staleExposure.pending_order_count ? (
        <span className="research-fail">
          <span className="k">stale exposure </span>
          {staleExposure.ticker_count || 0} names · {staleExposure.position_count || 0}
          {" held · "}{staleExposure.pending_order_count || 0} pending
        </span>
      ) : null}
    </>
  );
}
