import { api } from "../api";
import { DocumentPanel } from "../components/DocumentPanel";
import { GapPanel, ScorePanel } from "../components/Score";
import { StageLog } from "../components/StageLog";
import { closeRun, record, recordError, running } from "../run";
import { isLegacy } from "../types";
import type { LegacyRunRecord } from "../types";

export function RunView() {
  const run = record.value;

  return (
    <>
      <StageLog />

      {recordError.value && <p class="error">{recordError.value}</p>}

      {run &&
        (isLegacy(run) ? (
          <LegacyRun run={run} />
        ) : (
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
            </section>

            {run.score && <ScorePanel score={run.score} />}
            {run.score && <GapPanel score={run.score} />}
            {run.documents.map((document) => (
              <DocumentPanel key={document.kind} runId={run.run_id} document={document} />
            ))}
          </>
        ))}

      {!run && !running.value && !recordError.value && (
        <p class="field-hint">Loading the run…</p>
      )}
    </>
  );
}

/** All there is to show: the run predates run.json, so the files are the whole record. */
function LegacyRun({ run }: { run: LegacyRunRecord }) {
  return (
    <section class="card">
      <header class="run-head">
        <div>
          <h2>{run.title || run.run_id}</h2>
          <p class="field-hint">
            {run.company || "unknown company"} · {run.mode}
          </p>
        </div>
        <button class="secondary" onClick={closeRun}>
          New run
        </button>
      </header>
      <p class="field-hint">
        This run predates the structured record, so there is no score, no gap list and no
        citation audit to show for it — only what it wrote.
      </p>
      {run.pdfs.length > 0 && (
        <ul class="chips">
          {run.pdfs.map((name) => (
            <li key={name}>
              <a class="chip" href={api.fileUrl(run.run_id, name)} download={name}>
                {name}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
