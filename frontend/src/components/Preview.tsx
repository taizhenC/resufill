import { useState } from "preact/hooks";

import { analysing, analysis, analysisError, jdText } from "../state";
import type { Analysis, CeilingPreview } from "../types";
import { Meter } from "./Meter";

/**
 * What this posting asks for and how far the record can get — before spending anything.
 *
 * The endpoint behind it runs the lexicon pass and the ceiling, neither of which calls a
 * model, so this fires on typing and costs nothing. It answers the question people open the
 * tool with — *is this one worth applying to, and what will it say I am missing?* — which a
 * full run answers too, a minute and an API bill later.
 */
export function PostingPreview() {
  const report = analysis.value;

  // No text, no request, no panel. The column still says what will appear here, because an
  // empty half of the screen reads as something broken rather than something not yet done.
  if (!jdText.value.trim()) {
    return (
      <div class="preview-idle">
        <p>
          Paste a posting and this fills in: what the parser detected, the highest score your
          record can reach against it, and which keywords it cannot support.
        </p>
        <p class="field-hint">No model call, no spend — it reads your record and the text.</p>
      </div>
    );
  }

  if (!report) {
    return (
      <section class="card preview" aria-live="polite">
        <h2>Posting preview</h2>
        <p class="field-hint">{analysisError.value ?? "Reading the posting…"}</p>
      </section>
    );
  }

  return (
    <section class={`card preview ${analysing.value ? "preview-stale" : ""}`} aria-live="polite">
      <header class="run-head">
        <h2>Posting preview</h2>
        <span class="pill pill-muted">{analysing.value ? "re-reading…" : "free"}</span>
      </header>

      <Detected report={report} />
      <Ceiling ceiling={report.ceiling} />

      <Keywords
        title="Already in your record"
        hint="The posting names these and something in the record backs them, so a tailored document can carry them."
        terms={report.covered}
        tone="chip-ok"
      />
      <Keywords
        title="Out of reach for this record"
        hint="Nothing in profile.yaml or the evidence corpus supports these, so no grounded document can contain them. They are not an error — they are why the ceiling sits where it does, and what the role would need you to go and do."
        terms={report.ceiling.unreachable}
        tone="chip-gap"
      />

      {report.jd.qualifications.length > 0 && (
        <div class="gap-group">
          <h3>What it asks for</h3>
          <ul class="gap-list">
            {report.jd.qualifications.map((qualification) => (
              <li key={qualification}>{qualification}</li>
            ))}
          </ul>
        </div>
      )}

      <p class="caveat">
        <strong>Deterministic pass only.</strong> A lexicon read the posting and the ceiling came
        from your record — no model was asked and nothing was spent. A run’s model pass finds more
        than this: it fills in a title the lexicon missed and pulls out keywords this list does not
        have. Read it as the floor, not the last word.
      </p>
    </section>
  );
}

function Detected({ report }: { report: Analysis }) {
  const { title, company, seniority, min_years: minYears } = report.jd;
  return (
    <>
      <dl class="detected">
        <Fact label="Title" value={title} />
        <Fact label="Company" value={company} />
        <Fact label="Seniority" value={seniority} />
        <Fact label="Minimum years" value={minYears === null ? "" : `${minYears}`} />
      </dl>
      {!title && (
        // Said outright rather than left as a blank field: a missing title is usually a posting
        // pasted without its header, and it drags the title-fit component of the ceiling down
        // with it — so the number below is reading a badly-pasted posting, not a bad record.
        <p class="field-hint">
          No title came out of this text, which usually means the header was left behind in the
          paste. A run’s model pass often recovers it; until it does, the title-fit part of the
          ceiling below is pessimistic.
        </p>
      )}
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div class="fact">
      <dt>{label}</dt>
      <dd class={value ? "" : "fact-none"}>{value || "not detected"}</dd>
    </div>
  );
}

/** Below this many points of headroom, reaching the threshold takes everything the record has. */
const TIGHT_MARGIN = 5;

function Ceiling({ ceiling }: { ceiling: CeilingPreview }) {
  const margin = ceiling.total - ceiling.threshold;
  const verdict = !ceiling.reachable ? "capped" : margin < TIGHT_MARGIN ? "tight" : "clear";

  return (
    <div class={`ceiling ceiling-${verdict}`}>
      <div class="ceiling-head">
        <div>
          <span class="ceiling-total">{ceiling.total.toFixed(1)}</span>
          <span class="ceiling-outof">reachable of 100</span>
        </div>
        <span class="ceiling-threshold">threshold {ceiling.threshold}</span>
      </div>

      {/* value and ceiling are the same number here: everything past it is hatched, which is
          the whole point — with a capped posting the threshold mark lands inside the hatch. */}
      <Meter
        what="ceiling"
        value={ceiling.total}
        threshold={ceiling.threshold}
        ceiling={ceiling.total}
      />

      {verdict === "clear" && (
        <p class="ceiling-say">
          <strong>The threshold is reachable with room to spare.</strong> Your record tops out at{" "}
          {ceiling.total.toFixed(1)} against this posting, so the loop should hit {ceiling.threshold}{" "}
          and stop rather than spend its whole iteration budget.
        </p>
      )}
      {verdict === "tight" && (
        <p class="ceiling-say">
          <strong>Reachable, but only just</strong> — {margin.toFixed(1)} points of headroom above{" "}
          {ceiling.threshold}. Expect the run to use most of its iterations, and if it lands short
          that is a tailoring miss rather than a missing skill.
        </p>
      )}
      {verdict === "capped" && (
        <p class="ceiling-say">
          <strong>{ceiling.threshold} is not reachable here.</strong> {ceiling.total.toFixed(1)} is
          the highest this record can score against this posting, whatever the model writes — the
          grounding gate exists to make sure no rewrite can invent the difference. That is a fact
          about the role against your record, not a failed run. The documents are still worth
          generating; the number is not going to get there.
        </p>
      )}

      <Components components={ceiling.components} />
    </div>
  );
}

// The server sends raw fractions keyed by component name and no labels. These mirror score.py's
// Component labels; the weights are deliberately not duplicated here, because they are settings
// the frontend would silently get wrong the day someone changes them.
const COMPONENT_LABEL: Record<string, string> = {
  hard_skills: "Hard-skill coverage vs JD",
  qualifications: "Required qualifications addressed",
  title_fit: "Title / seniority alignment",
  keywords_in_context: "Keyword presence in context",
  format: "Format checks passed",
};

function Components({ components }: { components: Record<string, number> }) {
  const [open, setOpen] = useState(false);
  const rows = Object.entries(components);
  if (!rows.length) return null;

  return (
    <div class="ceiling-components">
      <button type="button" class="link" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "▾" : "▸"} Where the ceiling is lost
      </button>
      {open && (
        <ul class="meter-list">
          {rows.map(([name, raw]) => (
            <li key={name}>
              <span class="meter-name">{COMPONENT_LABEL[name] ?? name.replace(/_/g, " ")}</span>
              <span class="bar" style={{ "--fill": `${Math.round(raw * 100)}%` }}>
                {Math.round(raw * 100)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Keywords({
  title,
  hint,
  terms,
  tone,
}: {
  title: string;
  hint: string;
  terms: string[];
  tone: string;
}) {
  if (!terms.length) return null;
  return (
    <div class="gap-group">
      <h3>
        {title} <span class="count">{terms.length}</span>
      </h3>
      <p class="field-hint">{hint}</p>
      <ul class="chips">
        {terms.map((term) => (
          <li class={`chip ${tone}`} key={term}>
            {term}
          </li>
        ))}
      </ul>
    </div>
  );
}
