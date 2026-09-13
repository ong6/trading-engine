import assert from "node:assert/strict";
import test from "node:test";

import {
  isReviewCompletionProjection,
  isSizingContext,
  isTicketCancellationProjection,
  isTicketContextProjection,
  isTicketMutationProjection,
  suggestedTicketQty,
} from "../app/lib/mutation-contracts.js";

test("ticket mutation accepts only coherent submitted or rejected outcomes", () => {
  const submitted = {
    ticket_id: 1,
    allowed: true,
    status: "submitted",
    order_id: 2,
    signal_date: "2026-09-08",
    gates: [{ name: "stop_present", status: "pass", detail: "valid stop" }],
    reasons: [],
  };
  assert.equal(isTicketMutationProjection(submitted), true);
  assert.equal(isTicketMutationProjection({ ...submitted, internal: true }), false);
  assert.equal(
    isTicketMutationProjection({
      ...submitted,
      gates: [{ ...submitted.gates[0], internal: true }],
    }),
    false,
  );
  assert.equal(
    isTicketMutationProjection({ ...submitted, ticket_id: Number.MAX_SAFE_INTEGER + 1 }),
    false,
  );
  assert.equal(isTicketMutationProjection({ ...submitted, order_id: null }), false);
  assert.equal(
    isTicketMutationProjection({
      ...submitted,
      allowed: false,
      status: "rejected",
      order_id: null,
      reasons: ["risk gate"],
    }),
    true,
  );
  assert.equal(
    isTicketMutationProjection({ ...submitted, allowed: false, status: "submitted" }),
    false,
  );
  for (const invalid of [
    { ticket_id: 0 },
    { order_id: 0 },
    { signal_date: "2026-02-30" },
    { gates: [] },
    { gates: [{ name: "", status: "pass", detail: "valid stop" }] },
    { gates: [{ name: "stop_present", status: "passed", detail: "valid stop" }] },
    { gates: [{ name: "stop_present", status: "pass", detail: null }] },
    { gates: [{ name: "x".repeat(129), status: "pass", detail: "valid stop" }] },
    { gates: [{ name: "stop_present", status: "pass", detail: "x".repeat(4097) }] },
    { reasons: ["risk gate", null] },
    { reasons: [" "] },
    { reasons: ["x".repeat(4242)] },
    { reasons: ["unexpected block"] },
  ]) {
    assert.equal(isTicketMutationProjection({ ...submitted, ...invalid }), false);
  }
  assert.equal(
    isTicketMutationProjection({
      ...submitted,
      allowed: false,
      status: "rejected",
      order_id: null,
      reasons: [],
    }),
    false,
  );
});

test("ticket cancellation must confirm the requested ticket and cancelled status", () => {
  const valid = { ticket_id: 7, order_id: 11, status: "cancelled" };
  assert.equal(isTicketCancellationProjection(valid, 7), true);
  assert.equal(isTicketCancellationProjection({ ...valid, internal: true }, 7), false);
  assert.equal(isTicketCancellationProjection(valid, 8), false);
  assert.equal(isTicketCancellationProjection({ ...valid, status: "pending" }, 7), false);
  assert.equal(isTicketCancellationProjection({ ...valid, order_id: null }, 7), false);
  assert.equal(isTicketCancellationProjection({ ...valid, ticket_id: 0 }, 0), false);
  assert.equal(isTicketCancellationProjection({ ...valid, order_id: 0 }, 7), false);
  assert.equal(
    isTicketCancellationProjection(
      { ...valid, order_id: Number.MAX_SAFE_INTEGER + 1 },
      7,
    ),
    false,
  );
});

test("review completion explicitly confirms the circuit-breaker marker", () => {
  const valid = {
    ok: true,
    kind: "circuit_breaker",
    ts: "2026-09-08T12:00:00Z",
    detail: "circuit breaker cleared",
  };
  assert.equal(isReviewCompletionProjection(valid), true);
  assert.equal(isReviewCompletionProjection({ ...valid, internal: true }), false);
  assert.equal(isReviewCompletionProjection({ ...valid, ok: false }), false);
  assert.equal(isReviewCompletionProjection({ ...valid, kind: "other" }), false);
  assert.equal(isReviewCompletionProjection({ ...valid, ts: null }), false);
  assert.equal(
    isReviewCompletionProjection({ ...valid, ts: "2026-09-08T12:00:00" }),
    false,
  );
  assert.equal(
    isReviewCompletionProjection({ ...valid, ts: "2026-02-30T12:00:00Z" }),
    false,
  );
  assert.equal(isReviewCompletionProjection({ ...valid, detail: "" }), false);
});

test("ticket context requires status-specific equity provenance and numeric risk", () => {
  const active = {
    portfolio_id: "discretionary",
    status: "active",
    as_of: "2026-09-04",
    equity: 40_000,
    equity_source: "current_discretionary_equity",
    risk_pct: 0.005,
    experiment_max_pct: 0.0025,
    max_open_r: 5,
  };
  assert.equal(isTicketContextProjection(active), true);
  assert.equal(isTicketContextProjection({ ...active, internal: true }), false);
  const missingField = { ...active };
  delete missingField.max_open_r;
  assert.equal(isTicketContextProjection(missingField), false);

  assert.equal(isTicketContextProjection({ ...active, risk_pct: true }), false);
  assert.equal(
    isTicketContextProjection({ ...active, equity_source: "configured_initial_cash" }),
    false,
  );
  assert.equal(
    isTicketContextProjection({
      ...active,
      status: "unavailable",
      as_of: null,
      equity: null,
      equity_source: null,
    }),
    true,
  );
  assert.equal(
    isTicketContextProjection({
      ...active,
      status: "unavailable",
      equity: null,
      equity_source: null,
    }),
    false,
  );
});

test("sizing context is same-date and uses status-specific equity provenance", () => {
  const active = {
    status: "active",
    portfolio_id: "discretionary",
    equity_source: "current_discretionary_equity",
    as_of: "2026-09-04",
    equity: 40_000,
    risk_pct: 0.005,
  };
  assert.equal(isSizingContext(active, "2026-09-04"), true);
  assert.equal(isSizingContext(active, "2026-09-03"), false);
  assert.equal(isSizingContext({ ...active, as_of: "2026-02-30" }, "2026-02-30"), false);
  assert.equal(isSizingContext({ ...active, risk_pct: true }, "2026-09-04"), false);
  assert.equal(
    isSizingContext(
      {
        ...active,
        status: "not-created",
        equity_source: "configured_initial_cash",
      },
      "2026-09-04",
    ),
    true,
  );
});

test("quantity suggestion uses declared risk and valid positive per-share risk", () => {
  assert.equal(suggestedTicketQty("100", "95", 40_000, 0.005), 40);
  assert.equal(suggestedTicketQty("100.50", "100", 40_000, 0.005), 400);
  assert.equal(suggestedTicketQty("95", "100", 40_000, 0.005), null);
  assert.equal(suggestedTicketQty("bad", "95", 40_000, 0.005), null);
  assert.equal(suggestedTicketQty("100", "95", null, 0.005), null);
  assert.equal(suggestedTicketQty("100", "95", 40_000, 0), null);
  assert.equal(suggestedTicketQty("100", "95", 40_000, 1.1), null);
});
