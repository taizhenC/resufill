import { computed, signal } from "@preact/signals";

import { api, ApiError } from "./api";
import type { DoctorReport, Mode, RunRequest } from "./types";

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
