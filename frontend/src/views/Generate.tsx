import {
  activeRunId,
  canSubmit,
  jdText,
  maxIter,
  mode,
  pages,
  setupOk,
  showAdvanced,
  startRun,
  strict,
  submitError,
  submitting,
  threshold,
} from "../state";
import type { Mode } from "../types";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "both", label: "Both", hint: "résumé and cover letter" },
  { value: "resume", label: "Résumé", hint: "résumé only" },
  { value: "cover", label: "Cover letter", hint: "cover letter only" },
];

export function GenerateForm() {
  const disabled = !setupOk.value;

  return (
    <form
      class="card"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit.value) void startRun();
      }}
    >
      <label class="field">
        <span class="field-label">Job description</span>
        {/* Paste only, by design: no upload endpoint means no multipart handling and no
            server-side fetch of a URL somebody typed. */}
        <textarea
          rows={14}
          placeholder="Paste the posting here…"
          disabled={disabled}
          value={jdText.value}
          onInput={(event) => (jdText.value = (event.target as HTMLTextAreaElement).value)}
        />
        <span class="field-hint">
          {jdText.value.trim() ? `${jdText.value.trim().split(/\s+/).length} words` : " "}
        </span>
      </label>

      <fieldset class="modes" disabled={disabled}>
        <legend class="field-label">Generate</legend>
        {MODES.map((option) => (
          <label class="mode" key={option.value}>
            <input
              type="radio"
              name="mode"
              checked={mode.value === option.value}
              onChange={() => (mode.value = option.value)}
            />
            <span>{option.label}</span>
            <small>{option.hint}</small>
          </label>
        ))}
      </fieldset>

      <button
        type="button"
        class="link advanced-toggle"
        onClick={() => (showAdvanced.value = !showAdvanced.value)}
      >
        {showAdvanced.value ? "▾" : "▸"} Advanced
      </button>

      {showAdvanced.value && (
        <div class="advanced">
          <p class="field-hint">
            Blank means “use the value in <code>.env</code>”. Threshold and iterations are what to
            reach for when a run ceilings low — they are also what costs money.
          </p>
          <div class="advanced-grid">
            <Numeric label="Score threshold" value={threshold} placeholder="80" disabled={disabled} />
            <Numeric label="Max iterations" value={maxIter} placeholder="4" disabled={disabled} />
            <Numeric label="Page budget" value={pages} placeholder="1" disabled={disabled} />
          </div>
          <label class="checkbox">
            <input
              type="checkbox"
              disabled={disabled}
              checked={strict.value}
              onChange={(event) => (strict.value = (event.target as HTMLInputElement).checked)}
            />
            <span>
              Fail the run if the score stays below the threshold
              <small>
                Off by default: the gate stopped the loop inflating the number, so a low ceiling is
                the answer rather than an error.
              </small>
            </span>
          </label>
        </div>
      )}

      {submitError.value && <p class="error">{submitError.value}</p>}

      <div class="actions">
        <button type="submit" class="primary" disabled={!canSubmit.value}>
          {submitting.value ? "Starting…" : "Generate"}
        </button>
        {activeRunId.value && (
          <span class="field-hint">
            started <code>{activeRunId.value}</code>
          </span>
        )}
      </div>
    </form>
  );
}

function Numeric({
  label,
  value,
  placeholder,
  disabled,
}: {
  label: string;
  value: { value: string };
  placeholder: string;
  disabled: boolean;
}) {
  return (
    <label class="field">
      <span class="field-label">{label}</span>
      <input
        type="number"
        inputMode="decimal"
        placeholder={placeholder}
        disabled={disabled}
        value={value.value}
        onInput={(event) => (value.value = (event.target as HTMLInputElement).value)}
      />
    </label>
  );
}
