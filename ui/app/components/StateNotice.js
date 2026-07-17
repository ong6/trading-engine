// Friendly state for a failed fetch. A 503 (single-writer DuckDB held by the
// nightly run) becomes a retry-later message; anything else shows the error.
export default function StateNotice({ res }) {
  if (!res) return null;
  if (res.busy) {
    return (
      <div className="notice">
        Nightly run in progress — the database is briefly locked. Retry in a
        moment.
      </div>
    );
  }
  return (
    <div className="notice error">
      Could not load data: {res.error || "unknown error"}
    </div>
  );
}
