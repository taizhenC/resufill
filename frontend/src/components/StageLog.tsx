import { cancelling, cancelRun, documentLabel, events, job, running, stageLabel } from "../run";
import type { StageEvent } from "../types";

/**
 * The live log.
 *
 * It exists because a run is 10 to 60 seconds of silence per stage. On a terminal that is
 * fine; in a browser it looks like the thing has crashed. Every line here is a moment the
 * pipeline was genuinely between two blocking calls.
 */
export function StageLog() {
  const snapshot = job.value;
  if (!snapshot) return null;

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

      {snapshot.cancel_requested && running.value && (
        <p class="field-hint">
          Stopping at the next stage boundary. Cancelling mid-render would leave a half-written
          PDF that nothing can tell is corrupt.
        </p>
      )}

      <ol class="stages">
        {events.value.map((event, index) => (
          <StageRow key={index} event={event} last={index === events.value.length - 1} />
        ))}
      </ol>

      {snapshot.error && <p class="error">{snapshot.error}</p>}
    </section>
  );
}

function StageRow({ event, last }: { event: StageEvent; last: boolean }) {
  const spinning = last && running.value;
  const where =
    event.attempt !== undefined
      ? `${documentLabel(event.document ?? "resume")} ${event.attempt}/${event.attempts}`
      : "";

  return (
    <li class={`stage ${event.stage === "rejected" ? "stage-bad" : ""} ${spinning ? "stage-live" : ""}`}>
      <span class="stage-dot" aria-hidden="true" />
      <span class="stage-name">{stageLabel(event.stage)}</span>
      {where && <span class="stage-where">{where}</span>}
      <span class="stage-detail">
        {event.score !== undefined && `score ${event.score}`}
        {event.pages !== undefined && ` · ${event.pages} page${event.pages === 1 ? "" : "s"}`}
        {event.parses !== undefined && ` · ${event.parses ? "parses" : "failed its checks"}`}
        {event.words !== undefined && ` · ${event.words} words`}
        {event.reason && event.reason}
      </span>
    </li>
  );
}
