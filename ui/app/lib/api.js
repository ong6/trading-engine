// Single fetch helper used by both server components and the browser.
//
// Browser requests go through the /api/* proxy (rewritten to FastAPI on :8000)
// so there is no CORS. Server components call the loopback API directly and do
// not take an extra trip through the Next server.
//
// apiFetch never throws: it always resolves to { ok, status, data, error, busy }
// so pages can render an honest state instead of crashing. Only the two reviewed
// 503 envelopes for a held single-writer DuckDB lock are flagged as `busy`.

import { isRecord } from "./response-contracts.js";
import { resolveApiOrigin } from "../../api-origin.mjs";

const SERVER_API_ORIGIN = resolveApiOrigin();
export const API_ERROR_MAX_CHARS = 4_096;
export const API_VALIDATION_ERROR_MAX_ITEMS = 16;
export const API_RESPONSE_MAX_BYTES = 1_048_576;
const API_ERROR_ELLIPSIS = "…";
const API_RESPONSE_TOO_LARGE = `response exceeds ${API_RESPONSE_MAX_BYTES} bytes`;

function apiUrl(path) {
  return typeof window === "undefined"
    ? `${SERVER_API_ORIGIN}${path}`
    : `/api${path}`;
}

export function validateApiResponse(res, label, isValid) {
  if (!res.ok || isValid(res.data)) return res;
  return { ...res, ok: false, error: `invalid ${label} response`, busy: false };
}

function boundedErrorText(value) {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/[\p{C}\p{Z}\s]+/gu, " ").trim();
  if (!normalized) return null;
  const characters = [...normalized];
  if (characters.length <= API_ERROR_MAX_CHARS) return normalized;
  return `${characters.slice(0, API_ERROR_MAX_CHARS - 1).join("")}${API_ERROR_ELLIPSIS}`;
}

function validationErrorMessage(item) {
  if (typeof item === "string") return boundedErrorText(item);
  if (!isRecord(item)) return null;
  const message = boundedErrorText(item.msg);
  if (!message) return null;
  if (!Array.isArray(item.loc)) return `request: ${message}`;
  const segments = item.loc.slice(0, 8);
  const normalizedSegments = segments.map((part) =>
    typeof part === "string"
      ? boundedErrorText(part)
      : Number.isSafeInteger(part)
        ? String(part)
        : null,
  );
  if (segments.length !== item.loc.length || normalizedSegments.some((part) => !part)) {
    return `request: ${message}`;
  }
  const location = boundedErrorText(normalizedSegments.join(".")) || "request";
  return `${location}: ${message}`;
}

function combinedValidationError(messages, omitted) {
  const body = messages.join("; ");
  if (!omitted) return boundedErrorText(body);

  const suffix = "additional validation errors omitted";
  if (!body) return suffix;
  const separator = "; ";
  const suffixLength = [...separator, ...suffix].length;
  const bodyCharacters = [...body];
  const available = API_ERROR_MAX_CHARS - suffixLength;
  const boundedBody =
    bodyCharacters.length <= available
      ? body
      : `${bodyCharacters.slice(0, available - 1).join("")}${API_ERROR_ELLIPSIS}`;
  return `${boundedBody}${separator}${suffix}`;
}

function apiError(data, status) {
  const direct = boundedErrorText(data);
  if (direct) return direct;
  const detail = isRecord(data) ? data.detail : null;
  const detailText = boundedErrorText(detail);
  if (detailText) return detailText;
  if (Array.isArray(detail)) {
    const messages = detail
      .slice(0, API_VALIDATION_ERROR_MAX_ITEMS)
      .map(validationErrorMessage)
      .filter(Boolean);
    const combined = combinedValidationError(
      messages,
      detail.length > API_VALIDATION_ERROR_MAX_ITEMS,
    );
    if (combined) return combined;
  }
  return `HTTP ${status}`;
}

function isDatabaseBusy(data, status) {
  if (status !== 503 || !isRecord(data)) return false;
  const fields = Object.keys(data);
  return (
    (fields.length === 1 &&
      fields[0] === "detail" &&
      data.detail === "database busy (nightly run?) — retry later") ||
    (fields.length === 3 &&
      fields.includes("ok") &&
      fields.includes("status") &&
      fields.includes("db_readable") &&
      data.ok === false &&
      data.status === "busy" &&
      data.db_readable === false)
  );
}

async function cancelResponseBody(response) {
  try {
    await response.body?.cancel();
  } catch {
    // The size failure is authoritative even when the transport cannot cancel.
  }
}

function declaredResponseTooLarge(value) {
  if (!/^\d+$/.test(value || "")) return false;
  const normalized = value.replace(/^0+/, "") || "0";
  const maximum = String(API_RESPONSE_MAX_BYTES);
  return (
    normalized.length > maximum.length ||
    (normalized.length === maximum.length && normalized > maximum)
  );
}

async function boundedResponseText(response) {
  const contentLength = response.headers?.get?.("content-length");
  if (declaredResponseTooLarge(contentLength)) {
    await cancelResponseBody(response);
    return null;
  }

  if (!response.body || typeof response.body.getReader !== "function") {
    const text = await response.text();
    return new TextEncoder().encode(text).byteLength <= API_RESPONSE_MAX_BYTES ? text : null;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytesRead = 0;
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytesRead += value.byteLength;
      if (bytesRead > API_RESPONSE_MAX_BYTES) {
        try {
          await reader.cancel();
        } catch {
          // The size failure is authoritative even when the transport cannot cancel.
        }
        return null;
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

export async function apiFetch(path, opts = {}) {
  const url = apiUrl(path);
  try {
    const { headers = {}, ...requestOptions } = opts;
    const requestHeaders = new Headers(headers);
    if (!requestHeaders.has("content-type")) {
      requestHeaders.set("content-type", "application/json");
    }
    const res = await fetch(url, {
      cache: "no-store",
      ...requestOptions,
      headers: requestHeaders,
    });
    let data = null;
    const text = await boundedResponseText(res);
    if (text === null) {
      return {
        ok: false,
        status: res.status,
        data: null,
        error: API_RESPONSE_TOO_LARGE,
        busy: false,
      };
    }
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        data,
        error: apiError(data, res.status),
        busy: isDatabaseBusy(data, res.status),
      };
    }
    return { ok: true, status: res.status, data, error: null, busy: false };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      data: null,
      error: boundedErrorText(e?.message) || "network error",
      busy: false,
    };
  }
}

// POST JSON helper (client-side use).
export async function apiPost(path, body) {
  return apiFetch(path, {
    method: "POST",
    body: JSON.stringify(body || {}),
  });
}
