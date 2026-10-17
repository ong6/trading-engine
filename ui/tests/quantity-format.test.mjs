import assert from "node:assert/strict";
import test from "node:test";

import { fmtInt, fmtQty } from "../app/lib/format.js";

test("fractional position and sell-order quantities do not display as zero", () => {
  assert.equal(fmtQty(0.44830419936492766), "0.4483");
  assert.equal(fmtQty(0.4103906224964111), "0.4104");
});

test("quantities round to at most four decimal places and trim trailing zeros", () => {
  assert.equal(fmtQty(1.23456), "1.2346");
  assert.equal(fmtQty(12.34), "12.34");
  assert.equal(fmtQty(12.00001), "12");
  assert.equal(fmtQty(999.99999), "1,000");
  assert.equal(fmtQty(-1.23456), "-1.2346");
});

test("whole quantities retain grouping and actual zero remains zero", () => {
  assert.equal(fmtQty(1234567), "1,234,567");
  assert.equal(fmtQty(0), "0");
  assert.equal(fmtQty(-0), "0");
});

test("positive quantities below one ten-thousandth remain visibly nonzero", () => {
  for (const qty of [Number.MIN_VALUE, 0.00000001, 0.000049, 0.00009999]) {
    assert.equal(fmtQty(qty), "<0.0001");
  }
  assert.equal(fmtQty(0.0001), "0.0001");
  assert.equal(fmtQty(0.000149), "0.0001");
});

test("missing, non-finite, and nonnumeric quantities remain unknown", () => {
  for (const qty of [null, undefined, NaN, Infinity, -Infinity, "0.4483", "", false]) {
    assert.equal(fmtQty(qty), "—");
  }
});

test("integer counts and identifiers retain their existing formatting", () => {
  assert.equal(fmtInt(1933), "1,933");
  assert.equal(fmtInt(347), "347");
  assert.equal(fmtInt(12.6), "13");
  assert.equal(fmtInt(null), "—");
});
