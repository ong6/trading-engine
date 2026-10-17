import { fmtDate, fmtInt } from "../lib/format";

export default function RetainedBarWarning({ quality }) {
  if (!quality?.invalid_count) return null;
  const reason = quality.reason === "public candidate OHLC geometry is invalid"
    ? "invalid OHLC geometry" : quality.reason.replace(/^public candidate /, "");
  return (
    <span className="retained-bar-warning" role="note">
      ⚠ {fmtInt(quality.invalid_count)}/{fmtInt(quality.retained_count)} invalid bars
      <br />Latest {fmtDate(quality.latest_invalid_date)} · {reason}
    </span>
  );
}
