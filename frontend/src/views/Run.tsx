import { api } from "../api";
import { DocumentPanel } from "../components/DocumentPanel";
import { GapPanel, ScorePanel } from "../components/Score";
import { StageLog } from "../components/StageLog";
import { closeRun, record, recordError, running } from "../run";
import { isLegacy } from "../types";
import type { LegacyRunRecord } from "../types";

export function RunView() {
  const loaded = record.value;
  // A directory with no run.json answers with a RunSummary: no jd, no documents, no score.
  // Reading it as though it were a full record is what took this view down on any run made
  // before that file existed — and those runs are still real, and their PDFs still open.
  const run = loaded && !isLegacy(loaded) ? loaded : null;
  const legacy = loaded && isLegacy(loaded) ? loaded : null;

  return (
    <>
      <StageLog />

      {recordError.value && <p class="error">{recordError.value}</p>}

      {legacy && <LegacyRun run={legacy} />}

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

      {!loaded && !running.value && !recordError.value && (
        <p class="field-hint">Loading the run…</p>
      )}
    </>
  );
}

/** A run from before run.json existed. Nothing structured to show, and the files still open. */
function LegacyRun({ run }: { run: LegacyRunRecord }) {
  return (
    <section class="card">
      <header class="run-head">
        <div>
          <h2>{run.title || run.run_id}</h2>
          <p class="field-hint">
            This run predates the structured record, so only its files are available.
          </p>
        </div>
        <button class="secondary" onClick={closeRun}>
          New run
        </button>
      </header>
      <ul class="gap-list">
        {run.pdfs.map((name) => (
          <li key={name}>
            <a href={api.fileUrl(run.run_id, name)} target="_blank" rel="noreferrer">
              {name}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
