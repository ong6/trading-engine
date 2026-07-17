// Regime badge — colours risk-on green, risk-off red, anything else neutral.
export default function RegimeBadge({ regime }) {
  const r = (regime || "").toLowerCase();
  const cls = r === "risk-on" ? "risk-on" : r === "risk-off" ? "risk-off" : "unknown";
  return <span className={`badge ${cls}`}>{regime || "unknown"}</span>;
}
