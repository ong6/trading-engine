export const ALLOWED_UI_HOSTNAMES = new Set(["127.0.0.1", "localhost"]);

export function isAllowedUiHost(value) {
  if (typeof value !== "string") return false;
  const match = /^(127\.0\.0\.1|localhost)(?::([0-9]+))?$/i.exec(value);
  if (!match || !ALLOWED_UI_HOSTNAMES.has(match[1].toLowerCase())) return false;
  if (match[2] === undefined) return true;
  const port = Number(match[2]);
  return Number.isInteger(port) && port >= 1 && port <= 65_535;
}
