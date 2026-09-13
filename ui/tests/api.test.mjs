import assert from "node:assert/strict";
import test from "node:test";

import {
  API_ERROR_MAX_CHARS,
  API_RESPONSE_MAX_BYTES,
  API_VALIDATION_ERROR_MAX_ITEMS,
  apiFetch,
} from "../app/lib/api.js";

function response(status, body, headers = {}) {
  return new Response(body === null ? null : JSON.stringify(body), { status, headers });
}

function textResponse(status, body, headers = {}) {
  return new Response(body, { status, headers });
}

async function withFetch(t, implementation) {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = implementation;
}

test("apiFetch recognizes only the two reviewed database-busy envelopes", async (t) => {
  const payloads = [
    { detail: "database busy (nightly run?) — retry later" },
    { ok: false, status: "busy", db_readable: false },
  ];
  let call = 0;
  await withFetch(t, async () => response(503, payloads[call++]));

  const lockError = await apiFetch("/meta");
  const healthBusy = await apiFetch("/health");

  assert.equal(lockError.busy, true);
  assert.equal(healthBusy.busy, true);
});

test("apiFetch does not mislabel unreadable or unrelated 503 responses as busy", async (t) => {
  const payloads = [
    { ok: false, status: "unreadable", db_readable: false },
    { detail: "service unavailable" },
    { detail: "database busy (nightly run?) — retry later", extra: true },
  ];
  let call = 0;
  await withFetch(t, async () => response(503, payloads[call++]));

  const unreadable = await apiFetch("/health");
  const unavailable = await apiFetch("/meta");
  const widened = await apiFetch("/meta");

  assert.deepEqual(
    [unreadable.busy, unavailable.busy, widened.busy],
    [false, false, false],
  );
  assert.equal(unreadable.error, "HTTP 503");
  assert.equal(unavailable.error, "service unavailable");
});

test("apiFetch converts structured validation details into readable text", async (t) => {
  await withFetch(t, async () =>
    response(422, {
      detail: [
        { loc: ["query", "page"], msg: "Input should be greater than 0", type: "greater_than" },
        { loc: ["body", "ticker"], msg: "Field required", type: "missing" },
      ],
    }),
  );

  const result = await apiFetch("/screen/latest?page=0");

  assert.equal(result.busy, false);
  assert.equal(
    result.error,
    "query.page: Input should be greater than 0; body.ticker: Field required",
  );
});

test("apiFetch bounds and single-lines arbitrary public error text", async (t) => {
  const oversized = `first line\nsecond\tline\u0000${"💥".repeat(API_ERROR_MAX_CHARS)}`;
  await withFetch(t, async () => response(502, oversized));

  const result = await apiFetch("/meta");

  assert.equal([...result.error].length, API_ERROR_MAX_CHARS);
  assert.match(result.error, /^first line second line /);
  assert.equal(result.error.endsWith("…"), true);
  assert.doesNotMatch(result.error, /[\p{C}\r\n\t]/u);
  assert.equal(result.error.includes(" "), true);
});

test("apiFetch limits structured validation issue fan-out", async (t) => {
  const detail = Array.from({ length: API_VALIDATION_ERROR_MAX_ITEMS + 4 }, (_, index) => ({
    loc: ["body", index],
    msg: `issue-${index}`,
  }));
  await withFetch(t, async () => response(422, { detail }));

  const result = await apiFetch("/tickets");

  assert.match(result.error, /^body\.0: issue-0/);
  assert.match(result.error, /body\.15: issue-15/);
  assert.doesNotMatch(result.error, /issue-16/);
  assert.match(result.error, /additional validation errors omitted$/);
  assert.ok([...result.error].length <= API_ERROR_MAX_CHARS);
});

test("apiFetch retains the omission marker when validation messages are oversized", async (t) => {
  const detail = Array.from({ length: API_VALIDATION_ERROR_MAX_ITEMS + 1 }, (_, index) => ({
    loc: ["body", index],
    msg: "💥".repeat(API_ERROR_MAX_CHARS),
  }));
  await withFetch(t, async () => response(422, { detail }));

  const result = await apiFetch("/tickets");

  assert.equal([...result.error].length, API_ERROR_MAX_CHARS);
  assert.match(result.error, /…; additional validation errors omitted$/);
});

test("apiFetch replaces malformed validation locations with request", async (t) => {
  await withFetch(t, async () =>
    response(422, {
      detail: [{ loc: ["body", { unsafe: true }], msg: "bad\nvalue" }],
    }),
  );

  const result = await apiFetch("/tickets");

  assert.equal(result.error, "request: bad value");
});

test("apiFetch normalizes valid validation location segments", async (t) => {
  await withFetch(t, async () =>
    response(422, {
      detail: [{ loc: ["body\nfield", 3], msg: "bad value" }],
    }),
  );

  const result = await apiFetch("/tickets");

  assert.equal(result.error, "body field.3: bad value");
});

test("apiFetch retains default and caller-provided request headers", async (t) => {
  let request;
  await withFetch(t, async (url, options) => {
    request = { url, options };
    return response(200, { ok: true });
  });

  const result = await apiFetch("/example", {
    method: "POST",
    headers: { "x-request-id": "test-request" },
    body: "{}",
  });

  assert.equal(result.ok, true);
  assert.equal(request.url, "http://127.0.0.1:8000/example");
  assert.equal(request.options.headers.get("content-type"), "application/json");
  assert.equal(request.options.headers.get("x-request-id"), "test-request");
});

test("apiFetch permits an explicit content-type override", async (t) => {
  let requestHeaders;
  await withFetch(t, async (_url, options) => {
    requestHeaders = options.headers;
    return response(200, { ok: true });
  });

  await apiFetch("/example", {
    headers: new Headers([["Content-Type", "application/problem+json"]]),
  });

  assert.equal(requestHeaders.get("content-type"), "application/problem+json");
});

test("apiFetch reports network failures without throwing", async (t) => {
  await withFetch(t, async () => {
    throw new Error("connection\nrefused");
  });

  assert.deepEqual(await apiFetch("/health"), {
    ok: false,
    status: 0,
    data: null,
    error: "connection refused",
    busy: false,
  });
});

test("apiFetch admits a response at the byte ceiling", async (t) => {
  const padding = "x".repeat(API_RESPONSE_MAX_BYTES - '{"value":""}'.length);
  await withFetch(t, async () => textResponse(200, JSON.stringify({ value: padding })));

  const result = await apiFetch("/example");

  assert.equal(result.ok, true);
  assert.equal(result.data.value.length, padding.length);
});

test("apiFetch rejects a streamed response above the byte ceiling", async (t) => {
  const body = `"${"💥".repeat(Math.floor(API_RESPONSE_MAX_BYTES / 4))}"`;
  await withFetch(t, async () => textResponse(200, body));

  const result = await apiFetch("/example");

  assert.deepEqual(result, {
    ok: false,
    status: 200,
    data: null,
    error: `response exceeds ${API_RESPONSE_MAX_BYTES} bytes`,
    busy: false,
  });
});

test("apiFetch rejects a declared oversized body before reading it", async (t) => {
  let cancelled = false;
  let read = false;
  await withFetch(t, async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ "content-length": String(API_RESPONSE_MAX_BYTES + 1) }),
    body: {
      async cancel() {
        cancelled = true;
      },
      getReader() {
        read = true;
        throw new Error("body must not be read");
      },
    },
  }));

  const result = await apiFetch("/example");

  assert.equal(result.error, `response exceeds ${API_RESPONSE_MAX_BYTES} bytes`);
  assert.equal(cancelled, true);
  assert.equal(read, false);
});

test("apiFetch rejects an attacker-sized content length without integer parsing", async (t) => {
  let cancelled = false;
  await withFetch(t, async () => ({
    ok: true,
    status: 200,
    headers: { get: () => "9".repeat(100_000) },
    body: {
      async cancel() {
        cancelled = true;
      },
    },
  }));

  const result = await apiFetch("/example");

  assert.equal(result.error, `response exceeds ${API_RESPONSE_MAX_BYTES} bytes`);
  assert.equal(cancelled, true);
});
