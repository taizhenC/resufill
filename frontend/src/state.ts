import { computed, signal } from "@preact/signals";

import { api, ApiError } from "./api";
import { watch } from "./run";
import type { Analysis, DoctorReport, Mode, RunRequest } from "./types";

export const doctorReport = signal<DoctorReport | null>(null);
export const doctorError = signal<string | null>(null);

/** Until the checks come back, assume nothing: the form stays disabled. */
export const setupOk = computed(() => doctorReport.value?.ok === true);
export const blockers = computed(() => (doctorReport.value?.checks ?? []).filter((c) => !c.ok && c.blocking));
export const warnings = computed(() => (doctorReport.value?.checks ?? []).filter((c) => !c.ok && !c.blocking));

export async function refreshDoctor(): Promise<void> {
  try {
    doctorReport.value = await api.doctor();
    doctorError.value = null;
  } catch (error) {
    doctorReport.value = null;
    doctorError.value =
      error instanceof ApiError
        ? error.message
        : "cannot reach the resume-fill server — is `resume-fill serve` still running?";
  }
}

// --- the run form ---------------------------------------------------------

export const jdText = signal("");
export const mode = signal<Mode>("both");
export const showAdvanced = signal(false);
export const threshold = signal<string>("");
export const maxIter = signal<string>("");
export const pages = signal<string>("");
export const strict = signal(false);

export const submitting = signal(false);
export const submitError = signal<string | null>(null);
export const activeRunId = signal<string | null>(null);

// --- the free preview ------------------------------------------------------

export const analysis = signal<Analysis | null>(null);
export const analysisError = signal<string | null>(null);
export const analysing = signal(false);

/** Long enough that a paste is one request and typing is not one per keystroke. */
const ANALYZE_DEBOUNCE_MS = 600;

let analyzeTimer: ReturnType<typeof setTimeout> | undefined;
// Responses can land out of order once a slow request overlaps a fast one. The last request
// sent is the only one whose answer describes what is in the box.
let analyzeSeq = 0;

/** The only way to set the posting: every edit is also a preview trigger. */
export function setJd(value: string): void {
  jdText.value = value;
  if (analyzeTimer !== undefined) clearTimeout(analyzeTimer);
  if (!value.trim()) {
    // Nothing to analyse, so nothing is sent and whatever is in flight is disowned.
    analyzeSeq += 1;
    analysis.value = null;
    analysisError.value = null;
    analysing.value = false;
    return;
  }
  analyzeTimer = setTimeout(() => void analyze(), ANALYZE_DEBOUNCE_MS);
}

async function analyze(): Promise<void> {
  const jd = jdText.value;
  if (!jd.trim()) return;
  const seq = ++analyzeSeq;
  analysing.value = true;
  try {
    const result = await api.analyze(jd);
    if (seq !== analyzeSeq) return;
    analysis.value = result;
    analysisError.value = null;
  } catch (error) {
    if (seq !== analyzeSeq) return;
    analysis.value = null;
    // Never fatal. The preview is a free extra; the run is the product, and its button
    // stays live whatever happens here.
    analysisError.value =
      error instanceof ApiError
        ? error.status === 412
          ? // The one failure worth acting on: a run reads the same file and would hit the
            // same wall, so this is not the usual "never mind, it is only the preview".
            `The preview could not read your record. ${error.message} — a run reads the same file, so this is worth fixing first.`
          : `${error.message} — the preview is an extra; generating still works.`
        : "Could not reach the server for the preview. It is an extra — generating is unaffected.";
  } finally {
    if (seq === analyzeSeq) analysing.value = false;
  }
}

/** Blank means "use the .env value" — an empty box is not a zero. */
function optionalNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

export function runRequest(): RunRequest {
  return {
    jd: jdText.value,
    mode: mode.value,
    threshold: optionalNumber(threshold.value),
    max_iter: optionalNumber(maxIter.value),
    pages: optionalNumber(pages.value),
    strict: strict.value,
  };
}

export const canSubmit = computed(
  () => setupOk.value && jdText.value.trim().length > 0 && !submitting.value,
);

export async function startRun(): Promise<void> {
  submitting.value = true;
  submitError.value = null;
  try {
    const snapshot = await api.start(runRequest());
    activeRunId.value = snapshot.run_id || null;
    // Hand straight to the poller: the run id is not known until the JD has been parsed,
    // so the first snapshot is mostly empty and the live view fills in from there.
    watch(snapshot);
  } catch (error) {
    submitError.value =
      error instanceof ApiError
        ? error.status === 409
          ? "a run is already in progress — one at a time"
          : error.message
        : String(error);
  } finally {
    submitting.value = false;
  }
}
