import {
  activeRunId,
  canSubmit,
  jdText,
  maxIter,
  mode,
  pages,
  setJd,
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

  function submit(): void {
    if (canSubmit.value) void startRun();
  }

  return (
    <form
      class="card"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      // Enter inside a textarea is a newline, so the posting box would otherwise be the one
      // place in the form from which the form cannot be submitted — and it is where the
      // cursor always is.
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submit();
        }
      }}
    >
      <div class="field">
        <label class="field-label" for="jd">
          Job description
        </label>
        {/* Paste only, by design: no upload endpoint means no multipart handling and no
            server-side fetch of a URL somebody typed. */}
        <textarea
          id="jd"
          rows={14}
          placeholder="Paste the posting here…"
          disabled={disabled}
          aria-describedby="jd-hint"
          value={jdText.value}
          onInput={(event) => setJd((event.target as HTMLTextAreaElement).value)}
        />
        <span class="field-hint" id="jd-hint">
          {jdText.value.trim() ? `${jdText.value.trim().split(/\s+/).length} words` : " "}
        </span>
      </div>

      <fieldset class="modes" disabled={disabled}>
        <legend class="field-label">Generate</legend>
        {MODES.map((option) => (
          <div class="mode" key={option.value}>
            <input
              type="radio"
              id={`mode-${option.value}`}
              name="mode"
              checked={mode.value === option.value}
              onChange={() => (mode.value = option.value)}
            />
            <label for={`mode-${option.value}`}>
              <span>{option.label}</span>
              <small>{option.hint}</small>
            </label>
          </div>
        ))}
      </fieldset>

      <button
        type="button"
        class="link advanced-toggle"
        aria-expanded={showAdvanced.value}
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
            <Numeric
              id="threshold"
              label="Score threshold"
              value={threshold}
              placeholder="80"
              disabled={disabled}
            />
            <Numeric
              id="max-iter"
              label="Max iterations"
              value={maxIter}
              placeholder="4"
              disabled={disabled}
            />
            <Numeric
              id="pages"
              label="Page budget"
              value={pages}
              placeholder="1"
              disabled={disabled}
            />
          </div>
          <div class="checkbox">
            <input
              type="checkbox"
              id="strict"
              disabled={disabled}
              checked={strict.value}
              onChange={(event) => (strict.value = (event.target as HTMLInputElement).checked)}
            />
            <label for="strict">
              Fail the run if the score stays below the threshold
              <small>
                Off by default: the gate stopped the loop inflating the number, so a low ceiling is
                the answer rather than an error.
              </small>
            </label>
          </div>
        </div>
      )}

      {submitError.value && <p class="error">{submitError.value}</p>}

      <div class="actions">
        <button type="submit" class="primary" disabled={!canSubmit.value}>
          {submitting.value ? "Starting…" : "Generate"}
        </button>
        <span class="field-hint">
          {activeRunId.value ? (
            <>
              started <code>{activeRunId.value}</code>
            </>
          ) : (
            <>
              <kbd>Ctrl</kbd>/<kbd>⌘</kbd> + <kbd>Enter</kbd>
            </>
          )}
        </span>
      </div>
    </form>
  );
}

function Numeric({
  id,
  label,
  value,
  placeholder,
  disabled,
}: {
  id: string;
  label: string;
  value: { value: string };
  placeholder: string;
  disabled: boolean;
}) {
  return (
    <div class="field">
      <label class="field-label" for={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        placeholder={placeholder}
        disabled={disabled}
        value={value.value}
        onInput={(event) => (value.value = (event.target as HTMLInputElement).value)}
      />
    </div>
  );
}
