import { isBoundedPrintableLine } from "./response-contracts.js";

export const CANDIDATE_TICKER_MAX_CHARS = 32;

export function isCandidateTicker(value) {
  if (!isBoundedPrintableLine(value, CANDIDATE_TICKER_MAX_CHARS)) return false;
  try {
    encodeURIComponent(value);
  } catch {
    return false;
  }
  return true;
}

export function decodeCandidateSegment(segment) {
  if (typeof segment !== "string") return null;
  try {
    const ticker = decodeURIComponent(segment).toUpperCase();
    return isCandidateTicker(ticker) ? ticker : null;
  } catch {
    return null;
  }
}

export function candidateHref(ticker) {
  return isCandidateTicker(ticker)
    ? `/candidates/${encodeURIComponent(ticker)}`
    : null;
}
