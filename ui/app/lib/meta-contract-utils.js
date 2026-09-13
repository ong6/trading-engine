import {
  isIsoTimestamp,
  isNonEmptyString,
  isRecord,
} from "./response-contracts.js";

const CANONICAL_OFFSET_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.(\d{6}))?(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/;

export function isNullable(value, validator) {
  return value === null || validator(value);
}

export function hasOptional(data, field, validator) {
  return !Object.prototype.hasOwnProperty.call(data, field) || validator(data[field]);
}

export function hasExactFields(value, required, optional = []) {
  if (!isRecord(value)) return false;
  const allowed = new Set([...required, ...optional]);
  return (
    required.every((field) => Object.prototype.hasOwnProperty.call(value, field)) &&
    Object.keys(value).every((field) => allowed.has(field))
  );
}

export function isStringArray(value) {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

export function isOffsetIsoTimestamp(value) {
  const match =
    typeof value === "string" ? CANONICAL_OFFSET_TIMESTAMP.exec(value) : null;
  return (
    match !== null &&
    match[1] !== "000000" &&
    isIsoTimestamp(value)
  );
}

export function compareOffsetIsoTimestamps(left, right) {
  const leftMatch =
    typeof left === "string" ? CANONICAL_OFFSET_TIMESTAMP.exec(left) : null;
  const rightMatch =
    typeof right === "string" ? CANONICAL_OFFSET_TIMESTAMP.exec(right) : null;
  if (
    leftMatch === null ||
    rightMatch === null ||
    !isOffsetIsoTimestamp(left) ||
    !isOffsetIsoTimestamp(right)
  ) {
    return null;
  }
  const millisecondOrder = Math.sign(Date.parse(left) - Date.parse(right));
  if (millisecondOrder !== 0) return millisecondOrder;
  const leftSubmilliseconds = Number((leftMatch[1] || "000000").slice(3));
  const rightSubmilliseconds = Number((rightMatch[1] || "000000").slice(3));
  return Math.sign(leftSubmilliseconds - rightSubmilliseconds);
}

export function hasStatus(evidence, statuses) {
  return isRecord(evidence) && statuses.has(evidence.status);
}
