// Renders the 8-gate risk checklist: green pass / red fail / amber unknown, each
// with the backend's detail string. Used both after a ticket POST and in the
// journal (gates persisted per ticket).
export default function GateList({ gates }) {
  if (!Array.isArray(gates) || gates.length === 0) {
    return <div className="empty">No gate results.</div>;
  }
  return (
    <div className="gates">
      {gates.map((g, i) => {
        const status = (g.status || "unknown").toLowerCase();
        return (
          <div key={`${g.name}-${i}`} className={`gate ${status}`}>
            <span className="gname">{g.name}</span>
            <span className="gstatus">{status}</span>
            <span className="gdetail">{g.detail}</span>
          </div>
        );
      })}
    </div>
  );
}
