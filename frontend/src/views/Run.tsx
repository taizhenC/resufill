import { DocumentPanel } from "../components/DocumentPanel";
import { GapPanel, ScorePanel } from "../components/Score";
import { StageLog } from "../components/StageLog";
import { closeRun, record, recordError, running } from "../run";

export function RunView() {
  const run = record.value;

  return (
    <>
      <StageLog />

      {recordError.value && <p class="error">{recordError.value}</p>}

      {run && (
        <>
          <section class="card">
            <header class="run-head">
              <div>
                <h2>{run.jd.title || "Untitled role"}</h2>
                <p class="field-hint">
                  {run.jd.company || "unknown company"}
                  {run.jd.seniority && ` · ${run.jd.seniority}`} · {run.mode}
                </p>
              </div>
              <button class="secondary" onClick={closeRun}>
                New run
              </button>
            </header>
            {run.cancelled && (
              <p class="field-hint">
                This run was cancelled. What finished before then was kept.
              </p>
            )}
            {run.legacy && (
              <p class="field-hint">
                This run predates the structured record, so only its files are available.
              </p>
            )}
          </section>

          {run.score && <ScorePanel score={run.score} />}
          {run.score && <GapPanel score={run.score} />}
          {run.documents.map((document) => (
            <DocumentPanel key={document.kind} runId={run.run_id} document={document} />
          ))}
        </>
      )}

      {!run && !running.value && !recordError.value && (
        <p class="field-hint">Loading the run…</p>
      )}
    </>
  );
}
