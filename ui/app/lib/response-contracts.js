// Shared primitives for pure runtime contracts.
//
// These helpers do not fetch, mutate, or format data. Pages combine them with
// validateApiResponse so malformed HTTP-200 payloads become visible failures.

export const PUBLIC_PORTFOLIO_ID_MAX_CHARS = 128;
export const PUBLIC_SAFE_INTEGER_MAX = 9007199254740991;

export function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function compareUnicodeCodePoints(left, right) {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0));
  const rightPoints = Array.from(right, (value) => value.codePointAt(0));
  const commonLength = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < commonLength; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

export function isBoundedCollection(
  data,
  itemsKey,
  limitKey = "limit",
  countKey = "matching_count",
  truncatedKey = "truncated",
) {
  const items = data?.[itemsKey];
  const limit = data?.[limitKey];
  const count = data?.[countKey];
  const truncated = data?.[truncatedKey];
  return (
    Array.isArray(items) &&
    Number.isSafeInteger(limit) &&
    limit > 0 &&
    Number.isSafeInteger(count) &&
    count >= 0 &&
    items.length === Math.min(count, limit) &&
    typeof truncated === "boolean" &&
    truncated === (count > limit)
  );
}

export function isIsoDate(value) {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;

  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

export function isNullableFiniteNumber(value) {
  return value === null || Number.isFinite(value);
}

export function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

export function isBoundedPrintableLine(value, maxChars) {
  return (
    isNonEmptyString(value) &&
    value === value.trim() &&
    [...value].length <= maxChars &&
    [...value].every(
      (character) => character === " " || !/[\p{C}\p{Z}]/u.test(character),
    )
  );
}

export function isPublicPortfolioId(value) {
  return isBoundedPrintableLine(value, PUBLIC_PORTFOLIO_ID_MAX_CHARS);
}

export function isNonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= PUBLIC_SAFE_INTEGER_MAX;
}

export function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0 && value <= PUBLIC_SAFE_INTEGER_MAX;
}

export function isRiskGateResult(gate) {
  return (
    isRecord(gate) &&
    isNonEmptyString(gate.name) &&
    ["pass", "fail", "unknown"].includes(gate.status) &&
    typeof gate.detail === "string"
  );
}

export function isNullableString(value) {
  return value === null || typeof value === "string";
}

export function isIsoTimestamp(value) {
  if (typeof value !== "string") return false;
  const match = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|([+-])([01]\d|2[0-3]):([0-5]\d))?$/.exec(
    value,
  );
  if (!match || !isIsoDate(match[1])) return false;
  const offsetHour = Number(match[3] || 0);
  const offsetMinute = Number(match[4] || 0);
  return (
    (offsetHour < 14 || (offsetHour === 14 && offsetMinute === 0)) &&
    Number.isFinite(Date.parse(value))
  );
}
