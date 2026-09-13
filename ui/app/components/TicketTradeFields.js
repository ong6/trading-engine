import { fmtMoney } from "../lib/format";

export default function TicketTradeFields({
  entry,
  setEntry,
  stop,
  setStop,
  target,
  setTarget,
  qty,
  setQty,
  setQtyTouched,
  contextValid,
  equityError,
  suggestedQty,
  riskPct,
  equity,
  equitySource,
}) {
  return (
    <>
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
          onChange={(event) => setEntry(event.target.value)}
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
          onChange={(event) => setStop(event.target.value)}
        />
      </div>
      <div className="field">
        <label>Target</label>
        <input
          type="number"
          step="0.01"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
        />
      </div>
      <div className="field">
        <label>Qty</label>
        <input
          type="number"
          step="1"
          value={qty}
          onChange={(event) => {
            setQtyTouched(true);
            setQty(event.target.value);
          }}
        />
        <span className="hint">
          {!contextValid
            ? `Sizing suggestion unavailable: ${equityError}. Enter quantity manually; server risk gates use current equity.`
            : suggestedQty != null
              ? `${(riskPct * 100).toFixed(2)}%-risk suggestion: ${suggestedQty} sh · equity ${fmtMoney(equity)} · ${equitySource}`
              : `set entry > stop for a ${(riskPct * 100).toFixed(2)}%-risk suggestion · equity ${fmtMoney(equity)} · ${equitySource}`}
        </span>
      </div>
    </>
  );
}
