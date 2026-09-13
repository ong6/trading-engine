const EMOTIONS = ["calm", "fomo", "revenge", "anxious", "confident"];
const PLAYBOOK_MAX_CHARS = 128;
const NOTES_MAX_CHARS = 4_096;
const OVERRIDE_REASON_MAX_CHARS = 512;

export default function TicketJournalFields({
  playbook,
  setPlaybook,
  emotion,
  setEmotion,
  notes,
  setNotes,
  ackEarnings,
  setAckEarnings,
  overrideRegime,
  setOverrideRegime,
  overrideReason,
  setOverrideReason,
}) {
  return (
    <>
      <div className="field">
        <label>Playbook</label>
        <input
          type="text"
          maxLength={PLAYBOOK_MAX_CHARS}
          value={playbook}
          onChange={(event) => setPlaybook(event.target.value)}
          placeholder="e.g. breakout"
        />
      </div>
      <div className="field">
        <label>Emotion</label>
        <select value={emotion} onChange={(event) => setEmotion(event.target.value)}>
          {EMOTIONS.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>
      <div className="field full">
        <label>Notes</label>
        <textarea
          rows={2}
          maxLength={NOTES_MAX_CHARS}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </div>
      <div className="field check">
        <input
          id="ack"
          type="checkbox"
          checked={ackEarnings}
          onChange={(event) => setAckEarnings(event.target.checked)}
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
          onChange={(event) => setOverrideRegime(event.target.checked)}
        />
        <label htmlFor="ovr">Override regime gate (risk-off)</label>
      </div>
      {overrideRegime && (
        <div className="field full">
          <label>Override reason</label>
          <input
            type="text"
            maxLength={OVERRIDE_REASON_MAX_CHARS}
            value={overrideReason}
            onChange={(event) => setOverrideReason(event.target.value)}
            placeholder="why override the risk-off regime?"
          />
        </div>
      )}
    </>
  );
}
