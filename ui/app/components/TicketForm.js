"use client";

import { useEffect, useMemo, useState } from "react";
import { apiPost, validateApiResponse } from "../lib/api";
import {
  isSizingContext,
  isTicketMutationProjection,
  suggestedTicketQty,
} from "../lib/mutation-contracts";
import TicketJournalFields from "./TicketJournalFields";
import TicketOutcome from "./TicketOutcome";
import TicketTradeFields from "./TicketTradeFields";

function ticketResponse(res) {
  return validateApiResponse(res, "ticket", isTicketMutationProjection);
}

// Candidate -> Ticket form. Prefills entry_ref = latest_close, and suggests qty
// from the server-declared risk fraction once entry & stop are set. On submit it
// POSTs to /tickets through the proxy and renders the full risk-control checklist from the
// response, whether accepted or rejected. On rejection the form stays populated.
export default function TicketForm({ ticker, latestClose, latestCloseDate, contextRes }) {
  const [entry, setEntry] = useState(
    typeof latestClose === "number" ? String(latestClose.toFixed(2)) : ""
  );
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [qty, setQty] = useState("");
  const [qtyTouched, setQtyTouched] = useState(false);
  const [playbook, setPlaybook] = useState("");
  const [emotion, setEmotion] = useState("calm");
  const [notes, setNotes] = useState("");
  const [ackEarnings, setAckEarnings] = useState(false);
  const [overrideRegime, setOverrideRegime] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // { allowed, gates, reasons, status, ... }
  const [error, setError] = useState(null);

  // This server-rendered context comes from the same state calculation and
  // constants as the submission gates. Invalid/inactive state yields no hint.
  const context = contextRes?.ok ? contextRes.data : null;
  const contextValid = isSizingContext(context, latestCloseDate);
  const equity = contextValid ? context.equity : null;
  const riskPct = contextValid ? context.risk_pct : null;
  const equitySource =
    context?.status === "active"
      ? "current discretionary equity"
      : "configured initial paper capital (book not created)";
  const equityError = contextRes?.ok
    ? context?.status === "inactive"
      ? "discretionary portfolio is inactive"
      : context?.as_of && context.as_of !== latestCloseDate
        ? "candidate has no real quote on the operational market date"
      : "ticket sizing context is unavailable"
    : contextRes?.error || "ticket sizing context is unavailable";

  const suggestedQty = useMemo(
    () => suggestedTicketQty(entry, stop, equity, riskPct),
    [entry, stop, equity, riskPct],
  );

  // Auto-fill qty with the suggestion until the user edits it themselves.
  useEffect(() => {
    if (!qtyTouched && suggestedQty != null && suggestedQty >= 0) {
      setQty(String(suggestedQty));
    }
  }, [suggestedQty, qtyTouched]);

  async function onSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const body = {
      ticker,
      side: "buy",
      entry_ref: entry === "" ? null : Number(entry),
      stop: stop === "" ? null : Number(stop),
      target: target === "" ? null : Number(target),
      qty: qty === "" ? 0 : Number(qty),
      playbook,
      emotion,
      notes,
      acknowledge_earnings: ackEarnings,
      override_regime: overrideRegime,
      override_reason: overrideReason,
    };
    const res = ticketResponse(await apiPost("/tickets", body));
    setSubmitting(false);
    if (res.busy) {
      setError("Nightly run in progress — database busy. Retry in a moment.");
      return;
    }
    if (!res.ok || !res.data) {
      setError(res.error || "Ticket submission failed.");
      return;
    }
    setResult(res.data); // keep form populated; just show the outcome
  }

  return (
    <div>
      <form className="form-grid" onSubmit={onSubmit}>
        <TicketTradeFields
          entry={entry}
          setEntry={setEntry}
          stop={stop}
          setStop={setStop}
          target={target}
          setTarget={setTarget}
          qty={qty}
          setQty={setQty}
          setQtyTouched={setQtyTouched}
          contextValid={contextValid}
          equityError={equityError}
          suggestedQty={suggestedQty}
          riskPct={riskPct}
          equity={equity}
          equitySource={equitySource}
        />
        <TicketJournalFields
          playbook={playbook}
          setPlaybook={setPlaybook}
          emotion={emotion}
          setEmotion={setEmotion}
          notes={notes}
          setNotes={setNotes}
          ackEarnings={ackEarnings}
          setAckEarnings={setAckEarnings}
          overrideRegime={overrideRegime}
          setOverrideRegime={setOverrideRegime}
          overrideReason={overrideReason}
          setOverrideReason={setOverrideReason}
        />
        <div className="field full row-actions">
          <button type="submit" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit ticket"}
          </button>
          {result && (
            <span
              className={result.allowed ? "pos" : "neg"}
              style={{ fontWeight: 700 }}
            >
              {result.allowed
                ? `Accepted — order #${result.order_id} (${result.status})`
                : "Rejected — fix the failing gates and resubmit"}
            </span>
          )}
        </div>
      </form>

      {error && <div className="notice error">{error}</div>}

      <TicketOutcome result={result} />
    </div>
  );
}
