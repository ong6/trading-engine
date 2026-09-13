import { fmtDate, fmtTime } from "../lib/format";
import { driverAlert, fridayPostflightAlert, schedulerLabel } from "../lib/header-status";
import RegimeBadge from "./RegimeBadge";

export default function HeaderOperationalStatus({ res, data }) {
  const meta = data.meta || {};
  const metaFile = data.meta_file || null;
  const marketFreshness = data.market_freshness || null;
  const priceVerification = data.price_verification || null;
  const nightly = data.nightly || null;
  const scheduler = data.scheduler || null;
  const fridayPostflight = data.friday_postflight || null;
  const sourceControl = data.source_control || null;
  const weeklyVerify = data.weekly_verify || null;
  const apiAlert = !res.ok;
  const schedulerAlert = !scheduler || scheduler.status !== "ok";
  const postflightAlert = fridayPostflightAlert(fridayPostflight);
  const sourceControlAlert = !sourceControl || sourceControl.status !== "current";
  const nightlyAlert = driverAlert(nightly);
  const verifyAlert = driverAlert(weeklyVerify);
  const priceEvidenceAlert = priceVerification && priceVerification.status !== "current";

  return (
    <>
      {apiAlert ? (
        <span className="research-fail">
          <span className="k">API </span>
          {res.busy ? "database busy" : res.status ? `error ${res.status}` : "unavailable"}
        </span>
      ) : null}
      <span>
        <span className="k">regime </span>
        <RegimeBadge regime={meta.regime || null} />
      </span>
      {metaFile && metaFile.status !== "ok" ? (
        <span className="research-fail">
          <span className="k">health snapshot </span>
          {metaFile.status}
        </span>
      ) : null}
      {marketFreshness && marketFreshness.status !== "ok" ? (
        <span className="research-fail">
          <span className="k">market data </span>
          {marketFreshness.status === "stale"
            ? `${marketFreshness.missing_completed_sessions} completed session${marketFreshness.missing_completed_sessions === 1 ? "" : "s"} stale`
            : marketFreshness.status}
        </span>
      ) : null}
      <span>
        <span className="k">last run </span>
        {res.busy ? "db busy" : fmtTime(meta.last_run)}
      </span>
      <span>
        <span className="k">last screen </span>
        {res.busy
          ? "db busy"
          : meta.last_screen
            ? fmtTime(meta.last_screen)
            : fmtDate(meta.screen_date)}
      </span>
      <span className={schedulerAlert ? "research-fail" : ""}>
        <span className="k">automation </span>
        {res.busy ? "db busy" : schedulerLabel(scheduler)}
      </span>
      {postflightAlert ? (
        <span className="research-fail">
          <span className="k">Friday postflight </span>
          {res.busy ? "db busy" : fridayPostflight?.status || "unknown"}
        </span>
      ) : null}
      <span className={sourceControlAlert ? "research-fail" : ""}>
        <span className="k">git tracking </span>
        {res.busy
          ? "db busy"
          : sourceControl
            ? `${sourceControl.status}${sourceControl.ahead != null ? ` (${sourceControl.ahead} ahead · ${sourceControl.behind} behind)` : ""}`
            : "unknown"}
      </span>
      <span className={nightlyAlert ? "research-fail" : ""}>
        <span className="k">nightly </span>
        {res.busy ? "db busy" : nightly ? nightly.status : "unknown"}
      </span>
      {data.nightly_evidence ? (
        <span
          className={
            !["updating", "current"].includes(data.nightly_evidence.status)
              ? "research-fail"
              : ""
          }
        >
          <span className="k">nightly evidence </span>
          {data.nightly_evidence.status}
        </span>
      ) : null}
      <span className={verifyAlert ? "research-fail" : ""}>
        <span className="k">weekly verifier </span>
        {res.busy ? "db busy" : weeklyVerify ? weeklyVerify.status : "not yet run"}
      </span>
      {priceVerification ? (
        <span className={priceEvidenceAlert ? "research-fail" : ""}>
          <span className="k">price evidence </span>
          {`${priceVerification.status}${priceVerification.names_selected != null ? ` (${priceVerification.names_checked || 0}/${priceVerification.names_selected})` : ""}`}
        </span>
      ) : null}
    </>
  );
}
