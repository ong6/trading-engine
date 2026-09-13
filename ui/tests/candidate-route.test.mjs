import assert from "node:assert/strict";
import test from "node:test";

import {
  CANDIDATE_TICKER_MAX_CHARS,
  candidateHref,
  decodeCandidateSegment,
  isCandidateTicker,
} from "../app/lib/candidate-route.js";

test("candidate route parser safely decodes and normalizes valid symbols", () => {
  assert.equal(decodeCandidateSegment("brk.b"), "BRK.B");
  assert.equal(decodeCandidateSegment("BRK%2EB"), "BRK.B");
  assert.equal(decodeCandidateSegment("%25"), "%");
});

test("candidate route parser rejects malformed, blank, and oversized segments", () => {
  for (const value of [
    undefined,
    "%E0%A4%A",
    "%C0%AF",
    "%ED%A0%80",
    "%F0%28%8C%28",
    "%20",
    "A".repeat(CANDIDATE_TICKER_MAX_CHARS + 1),
    " AAA",
    "AAA ",
    "AA\nA",
    "AA\tA",
  ]) {
    assert.equal(decodeCandidateSegment(value), null, String(value));
  }
});

test("candidate links encode route structure and reject unsafe text", () => {
  assert.equal(candidateHref("BRK.B"), "/candidates/BRK.B");
  assert.equal(candidateHref("A/B"), "/candidates/A%2FB");
  assert.equal(candidateHref("A B"), "/candidates/A%20B");
  assert.equal(candidateHref(""), null);
  assert.equal(candidateHref(" "), null);
  assert.equal(candidateHref("\ud800"), null);
  assert.equal(isCandidateTicker("A".repeat(CANDIDATE_TICKER_MAX_CHARS)), true);
  assert.equal(isCandidateTicker("A".repeat(CANDIDATE_TICKER_MAX_CHARS + 1)), false);
});
