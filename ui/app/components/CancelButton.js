"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "../lib/api";

// Cancels a pending discretionary order via its ticket id. Confirms first, then
// POSTs through the proxy and refreshes the server-rendered table.
export default function CancelButton({ ticketId }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function onCancel() {
    if (!ticketId) return;
    if (!window.confirm(`Cancel pending order for ticket #${ticketId}?`)) return;
    setBusy(true);
    setMsg(null);
    const res = await apiPost(`/tickets/${ticketId}/cancel`, {});
    setBusy(false);
    if (res.busy) {
      setMsg("db busy — retry");
      return;
    }
    if (!res.ok) {
      setMsg(res.error || "failed");
      return;
    }
    router.refresh();
  }

  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <button className="danger" onClick={onCancel} disabled={busy}>
        {busy ? "cancelling…" : "cancel"}
      </button>
      {msg && <span className="neg" style={{ fontSize: 11 }}>{msg}</span>}
    </span>
  );
}
