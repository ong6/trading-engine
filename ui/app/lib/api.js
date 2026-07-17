// Single fetch helper used by both server components and the browser.
//
// Everything goes through the /api/* proxy (rewritten to the FastAPI backend on
// :8000) so the browser only ever talks to :3000 and there is no CORS. On the
// server there is no relative-URL base, so we prepend the local origin — this
// re-enters Next and gets rewritten exactly like a browser call would.
//
// apiFetch never throws: it always resolves to { ok, status, data, error, busy }
// so pages can render an honest state instead of crashing. A 503 from the
// single-writer DuckDB (nightly run holding the write lock) is flagged as `busy`.

const SERVER_ORIGIN = process.env.UI_INTERNAL_ORIGIN || "http://127.0.0.1:3000";

function baseUrl() {
  return typeof window === "undefined" ? SERVER_ORIGIN : "";
}

export async function apiFetch(path, opts = {}) {
  const url = `${baseUrl()}/api${path}`;
  try {
    const res = await fetch(url, {
      cache: "no-store",
      headers: { "content-type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      const detail =
        (data && typeof data === "object" && data.detail) ||
        (typeof data === "string" && data) ||
        `HTTP ${res.status}`;
      return {
        ok: false,
        status: res.status,
        data,
        error: detail,
        busy: res.status === 503,
      };
    }
    return { ok: true, status: res.status, data, error: null, busy: false };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      data: null,
      error: e && e.message ? e.message : "network error",
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
