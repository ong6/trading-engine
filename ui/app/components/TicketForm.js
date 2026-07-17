"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, apiPost } from "../lib/api";
import { fmtMoney } from "../lib/format";
import GateList from "./GateList";

const EMOTIONS = ["calm", "fomo", "revenge", "anxious", "confident"];
const DEFAULT_EQUITY = 39000; // INITIAL_CASH — used only if no live equity source.

// Candidate -> Ticket form. Prefills entry_ref = latest_close, and suggests qty
// as floor(1%-risk / (entry-stop)) once entry & stop are set. On submit it POSTs
// to /tickets through the proxy and renders the full 8-gate checklist from the
// response, whether accepted or rejected. On rejection the form stays populated.
export default function TicketForm({ ticker, latestClose }) {
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

  const [equity, setEquity] = useState(DEFAULT_EQUITY);
  const [equitySource, setEquitySource] = useState("default (no live book yet)");

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // { allowed, gates, reasons, status, ... }
  const [error, setError] = useState(null);

  // Equity for the 1%-risk qty hint: prefer the live discretionary book's
  // equity from /league; fall back to INITIAL_CASH. (/journal does not expose
  // book equity, so /league's discretionary row is the real live source.)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await apiFetch("/league");
      if (cancelled || !res.ok || !res.data) return;
      const rows = res.data.rows || [];
      const disc = rows.find((r) => r.id === "discretionary");
      if (disc && typeof disc.equity === "number") {
        setEquity(disc.equity);
        setEquitySource("live discretionary book (/league)");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const entryN = parseFloat(entry);
  const stopN = parseFloat(stop);
  const rPerShare =
    Number.isFinite(entryN) && Number.isFinite(stopN) && entryN > stopN
      ? entryN - stopN
      : null;

  const suggestedQty = useMemo(() => {
    if (!rPerShare) return null;
    return Math.floor((0.01 * equity) / rPerShare);
  }, [rPerShare, equity]);

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
    const res = await apiPost("/tickets", body);
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
        <div className="field">
          <label>Side</label>
          <input type="text" value="buy" readOnly className="mono-input" />
          <span className="hint">buy only in v1</span>
        </div>
        <div className="field">
          <label>Entry ref</label>
          <input
            type="number"
            step="0.01"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            placeholder="latest close"
          />
          <span className="hint">prefilled from latest close</span>
        </div>
        <div className="field">
          <label>Stop</label>
          <input
            type="number"
            step="0.01"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
          />
        </div>
        <div className="field">
          <label>Target</label>
          <input
            type="number"
            step="0.01"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
        </div>
        <div className="field">
          <label>Qty</label>
          <input
            type="number"
            step="1"
            value={qty}
            onChange={(e) => {
              setQtyTouched(true);
              setQty(e.target.value);
            }}
          />
          <span className="hint">
            {suggestedQty != null
              ? `1%-risk suggestion: ${suggestedQty} sh · equity ${fmtMoney(
                  equity
                )} · ${equitySource}`
              : "set entry > stop for a 1%-risk suggestion"}
          </span>
        </div>
        <div className="field">
          <label>Playbook</label>
          <input
            type="text"
            value={playbook}
            onChange={(e) => setPlaybook(e.target.value)}
            placeholder="e.g. breakout"
          />
        </div>
        <div className="field">
          <label>Emotion</label>
          <select value={emotion} onChange={(e) => setEmotion(e.target.value)}>
            {EMOTIONS.map((em) => (
              <option key={em} value={em}>
                {em}
              </option>
            ))}
          </select>
        </div>
        <div className="field full">
          <label>Notes</label>
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
        <div className="field check">
          <input
            id="ack"
            type="checkbox"
            checked={ackEarnings}
            onChange={(e) => setAckEarnings(e.target.checked)}
          />
          <label htmlFor="ack">
            Acknowledge earnings window (no earnings data — checked manually)
          </label>
        </div>
        <div className="field check">
          <input
            id="ovr"
            type="checkbox"
            checked={overrideRegime}
            onChange={(e) => setOverrideRegime(e.target.checked)}
          />
          <label htmlFor="ovr">Override regime gate (risk-off)</label>
        </div>
        {overrideRegime && (
          <div className="field full">
            <label>Override reason</label>
            <input
              type="text"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              placeholder="why override the risk-off regime?"
            />
          </div>
        )}
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

      {result && (
        <div style={{ marginTop: 16 }}>
          <h3>Risk gates</h3>
          <GateList gates={result.gates} />
          {Array.isArray(result.reasons) && result.reasons.length > 0 && (
            <div className="notice error" style={{ marginTop: 10 }}>
              <strong>Blocked by:</strong>
              <ul style={{ margin: "6px 0 0 18px" }}>
                {result.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
