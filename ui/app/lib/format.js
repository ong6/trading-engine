// Number / date formatting. Never invents data: null/undefined/NaN render as an
// em dash, so an empty backend value is visibly empty rather than "0.00".

const DASH = "—";

function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

// Prices: 2 decimal places.
export function fmtPrice(v) {
  return isNum(v) ? v.toFixed(2) : DASH;
}

// R-multiples: 2 decimal places, signed.
export function fmtR(v) {
  if (!isNum(v)) return DASH;
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`;
}

// Percentages: input is a fraction (0.0123 -> "1.2%"), 1 decimal place, signed.
export function fmtPct(v) {
  if (!isNum(v)) return DASH;
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

// Plain integer / count.
export function fmtInt(v) {
  return isNum(v) ? Math.round(v).toLocaleString("en-US") : DASH;
}

// Dollar money, no decimals.
export function fmtMoney(v) {
  return isNum(v) ? `$${Math.round(v).toLocaleString("en-US")}` : DASH;
}

// Generic number with fixed dp.
export function fmtNum(v, dp = 2) {
  return isNum(v) ? v.toFixed(dp) : DASH;
}

// Date -> YYYY-MM-DD (accepts ISO strings or date-only strings).
export function fmtDate(v) {
  if (!v) return DASH;
  const s = String(v);
  return s.length >= 10 ? s.slice(0, 10) : s;
}

// ISO timestamp -> "YYYY-MM-DD HH:MM UTC" for freshness display.
export function fmtTime(v) {
  if (!v) return DASH;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(
    d.getUTCDate()
  )} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}
