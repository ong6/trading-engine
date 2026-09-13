"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost, validateApiResponse } from "../lib/api";
import { isReviewCompletionProjection } from "../lib/mutation-contracts";

// Clears the circuit breaker via POST /review-done. Confirms before posting.
export default function ReviewDoneButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function onClick() {
    if (
      !window.confirm(
        "Mark review done? This clears the discretionary circuit breaker so new tickets can pass the circuit-breaker gate."
      )
    )
      return;
    setBusy(true);
    setMsg(null);
    const res = validateApiResponse(
      await apiPost("/review-done", {}),
      "review completion",
      isReviewCompletionProjection,
    );
    setBusy(false);
    if (res.busy) {
      setMsg("db busy — retry in a moment");
      return;
    }
    if (!res.ok) {
      setMsg(res.error || "failed");
      return;
    }
    setMsg("circuit breaker cleared");
    router.refresh();
  }

  return (
    <span style={{ display: "inline-flex", gap: 10, alignItems: "center" }}>
      <button onClick={onClick} disabled={busy}>
        {busy ? "posting…" : "Review done — clear circuit breaker"}
      </button>
      {msg && <span className="muted">{msg}</span>}
    </span>
  );
}
