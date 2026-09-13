import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_API_ORIGIN, resolveApiOrigin } from "../api-origin.mjs";
import { isAllowedUiHost } from "../host-policy.mjs";

test("API origin defaults to the production loopback backend", () => {
  assert.equal(resolveApiOrigin(""), DEFAULT_API_ORIGIN);
  assert.equal(resolveApiOrigin(undefined), "http://127.0.0.1:8000");
});

test("API origin accepts an explicit alternate loopback port", () => {
  assert.equal(resolveApiOrigin("http://127.0.0.1:18000"), "http://127.0.0.1:18000");
});

test("API origin rejects non-loopback or ambiguous destinations", () => {
  for (const value of [
    "https://127.0.0.1:18000",
    "http://localhost:18000",
    "http://0.0.0.0:18000",
    "http://example.test:18000",
    "http://127.0.0.1",
    "http://user@127.0.0.1:18000",
    "http://127.0.0.1:18000/path",
    "http://127.0.0.1:18000?query=yes",
    "not-a-url",
  ]) {
    assert.throws(() => resolveApiOrigin(value), /explicit 127\.0\.0\.1|absolute loopback/);
  }
});

test("UI host policy accepts only loopback names with valid optional ports", () => {
  for (const value of [
    "127.0.0.1",
    "127.0.0.1:3000",
    "localhost",
    "localhost:3100",
    "LOCALHOST:3000",
  ]) {
    assert.equal(isAllowedUiHost(value), true);
  }
  for (const value of [
    undefined,
    "",
    "attacker.invalid",
    "attacker.invalid:3000",
    "localhost.attacker.invalid:3000",
    "localhost:3000.attacker.invalid",
    "localhost:0",
    "localhost:65536",
    "localhost:not-a-port",
  ]) {
    assert.equal(isAllowedUiHost(value), false);
  }
});
