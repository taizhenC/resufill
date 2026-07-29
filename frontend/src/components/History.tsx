import { history, openRun } from "../run";

/** `out/` is the source of truth; this is a directory read with a link into each run. */
export function History() {
  if (!history.value.length) return null;

  return (
    <section class="card">
      <h2>Past runs</h2>
      <ul class="history">
        {history.value.map((summary) => (
          <li key={summary.run_id}>
            <button class="history-row" onClick={() => void openRun(summary.run_id)}>
              <span class="history-title">
                {summary.title || summary.run_id}
                {summary.company && <small> {summary.company}</small>}
              </span>
              <span class="history-meta">
                {summary.total !== null && <span class="score-chip">{summary.total.toFixed(1)}</span>}
                {summary.cancelled && <span class="pill pill-warn">cancelled</span>}
                {/* A run made before run.json existed. Listed and downloadable; there is
                    simply nothing structured to show for it. */}
                {summary.legacy && <span class="pill pill-muted">no record</span>}
                {!summary.legacy && !summary.cancelled && (
                  <span class={`pill ${summary.ok ? "pill-ok" : "pill-bad"}`}>
                    {summary.ok ? "ok" : "failed"}
                  </span>
                )}
                <time>{summary.created_at.slice(0, 16).replace("T", " ")}</time>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
