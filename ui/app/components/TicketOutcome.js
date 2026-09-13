import GateList from "./GateList";

export default function TicketOutcome({ result }) {
  if (!result) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <h3>Risk gates</h3>
      <GateList gates={result.gates} />
      {Array.isArray(result.reasons) && result.reasons.length > 0 && (
        <div className="notice error" style={{ marginTop: 10 }}>
          <strong>Blocked by:</strong>
          <ul style={{ margin: "6px 0 0 18px" }}>
            {result.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
