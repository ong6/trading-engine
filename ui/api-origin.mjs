export const DEFAULT_API_ORIGIN = "http://127.0.0.1:8000";

export function resolveApiOrigin(value = process.env.UI_INTERNAL_API_ORIGIN) {
  const candidate = value || DEFAULT_API_ORIGIN;
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("UI_INTERNAL_API_ORIGIN must be an absolute loopback HTTP origin");
  }
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    !parsed.port ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("UI_INTERNAL_API_ORIGIN must be an explicit 127.0.0.1 HTTP origin");
  }
  return parsed.origin;
}
