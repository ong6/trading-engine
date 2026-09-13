import ReviewDoneButton from "./ReviewDoneButton";

export default function JournalCircuitBreaker() {
  return (
    <div className="card" style={{ marginBottom: 8 }}>
      <h3 style={{ margin: "0 0 6px" }}>Circuit breaker</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        After reviewing a losing streak, clear the breaker so new tickets can
        pass the circuit-breaker gate again.
      </p>
      <ReviewDoneButton />
    </div>
  );
}
