import { computed, signal } from "@preact/signals";

import { api, ApiError } from "./api";
import type { JobSnapshot, RunRecord, RunSummary, StageEvent } from "./types";

/** ~1s. Stages are seconds apart, so polling loses nothing a push would gain. */
const POLL_MS = 1000;

export const job = signal<JobSnapshot | null>(null);
/** Accumulated client-side: the server only sends what we have not seen. */
export const events = signal<StageEvent[]>([]);
export const record = signal<RunRecord | null>(null);
export const recordError = signal<string | null>(null);
export const history = signal<RunSummary[]>([]);
export const cancelling = signal(false);

export const running = computed(() => job.value !== null && !job.value.done);
/** The run view takes over whenever there is something to watch or read. */
export const showRun = computed(() => job.value !== null || record.value !== null);

let timer: ReturnType<typeof setTimeout> | undefined;

export async function refreshHistory(): Promise<void> {
  try {
    history.value = await api.runs();
  } catch {
    // A failed history read must not disturb a run in progress; it is a list.
  }
}

async function tick(): Promise<void> {
  try {
    const snapshot = await api.current(events.value.length);
    if (snapshot.idle) {
      timer = undefined;
      return;
    }
    job.value = snapshot;
    if (snapshot.events.length) events.value = [...events.value, ...snapshot.events];

    if (snapshot.done) {
      timer = undefined;
      await Promise.all([loadRecord(snapshot.run_id), refreshHistory()]);
      return;
    }
  } catch {
    // Keep polling through a transient failure: the run is still going, and giving up
    // would leave the page frozen on whatever it happened to show last.
  }
  timer = setTimeout(() => void tick(), POLL_MS);
}

export function watch(snapshot: JobSnapshot): void {
  job.value = snapshot;
  events.value = snapshot.events ?? [];
  record.value = null;
  recordError.value = null;
  if (timer !== undefined) clearTimeout(timer);
  timer = setTimeout(() => void tick(), POLL_MS);
}

/** Reattach to a run already in flight — a page reload mid-run should just resume. */
export async function resumeIfRunning(): Promise<void> {
  try {
    const snapshot = await api.current(0);
    if (!snapshot.idle && !snapshot.done) watch(snapshot);
  } catch {
    /* no server yet; the doctor banner says so */
  }
}

export async function loadRecord(runId: string): Promise<void> {
  if (!runId) return;
  try {
    record.value = await api.run(runId);
    recordError.value = null;
  } catch (error) {
    record.value = null;
    recordError.value = error instanceof ApiError ? error.message : String(error);
  }
}

export async function openRun(runId: string): Promise<void> {
  job.value = null;
  events.value = [];
  await loadRecord(runId);
}

export async function cancelRun(): Promise<void> {
  cancelling.value = true;
  try {
    await api.cancel();
  } catch {
    /* already finished; the next poll will show it */
  } finally {
    cancelling.value = false;
  }
}

export function closeRun(): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = undefined;
  job.value = null;
  events.value = [];
  record.value = null;
  recordError.value = null;
}

// --- presentation helpers -------------------------------------------------

const STAGE_LABEL: Record<string, string> = {
  parsing_jd: "Reading the posting",
  tailoring: "Writing",
  grounding: "Checking every claim",
  rejected: "Rejected — a claim could not be traced",
  rendering: "Rendering the PDF",
  verifying: "Reading the PDF back",
  scoring: "Scoring",
  scored: "Attempt finished",
  writing_report: "Writing the report",
  done: "Finished",
  cancelled: "Cancelled",
};

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? stage;
}

export function documentLabel(kind: string): string {
  return kind === "cover_letter" ? "Cover letter" : "Résumé";
}
