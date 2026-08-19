import { cancelling, cancelRun, documentLabel, events, job, running, stageLabel, timeline } from "../run";
import { Timeline } from "./Timeline";

/**
 * The live log.
 *
 * It exists because a run is 10 to 60 seconds of silence per stage. On a terminal that is
 * fine; in a browser it looks like the thing has crashed. Every row here is a moment the
 * pipeline was genuinely between two blocking calls.
 */
export function StageLog() {
  const snapshot = job.value;
  if (!snapshot) return null;

  const items = timeline(events.value);
  const latest = events.value[events.value.length - 1];
  const where = latest?.attempt
    ? `${documentLabel(latest.document ?? "resume")} attempt ${latest.attempt}`
    : "";

  return (
    <section class="card">
      <header class="run-head">
        <div>
          <h2>{running.value ? "Running" : snapshot.cancelled ? "Cancelled" : "Finished"}</h2>
          {snapshot.run_id && <code class="run-id">{snapshot.run_id}</code>}
        </div>
        {running.value && (
          <button class="secondary" disabled={cancelling.value} onClick={() => void cancelRun()}>
            {snapshot.cancel_requested ? "Stopping…" : "Cancel"}
          </button>
        )}
      </header>

      {/* One short sentence rather than aria-live on the list: a live region wrapping every row
          gets re-read whole on each poll, which turns a four-iteration run into a monologue. */}
      <p class="sr-only" aria-live="polite">
        {latest ? `${stageLabel(latest.stage)}${where ? `, ${where}` : ""}` : "starting"}
      </p>

      {snapshot.cancel_requested && running.value && (
        <p class="field-hint">
          Stopping at the next stage boundary. Cancelling mid-render would leave a half-written
          PDF that nothing can tell is corrupt.
        </p>
      )}

      <Timeline items={items} live={running.value} />

      {snapshot.error && <p class="error">{snapshot.error}</p>}
    </section>
  );
}
