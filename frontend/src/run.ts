import { computed, signal } from "@preact/signals";

import { api, ApiError } from "./api";
import type { JobSnapshot, LoadedRun, RunSummary, StageEvent } from "./types";

/** ~1s. Stages are seconds apart, so polling loses nothing a push would gain. */
const POLL_MS = 1000;

export const job = signal<JobSnapshot | null>(null);
/** Accumulated client-side: the server only sends what we have not seen. */
export const events = signal<StageEvent[]>([]);
export const record = signal<LoadedRun | null>(null);
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
  repaired: "Cutting what could not be traced",
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

/** One attempt at one document, with every stage it went through folded into it. */
export interface AttemptGroup {
  document: string;
  attempt: number;
  attempts: number;
  /** The last stage reported — what it is doing now, or where it stopped. */
  stage: string;
  score?: number;
  parses?: boolean;
  pages?: number;
  words?: number;
  /** The gate cut the unsupportable parts out and the rest passed: shipped, but smaller. */
  repaired: boolean;
  dropped: number;
  /** ground.summarize() — the kinds of violation and how many of each. */
  reason: string;
  /** `open` covers both "still working" and "the run ended before this attempt did". */
  outcome: "open" | "rejected" | "finished";
}

export type TimelineItem =
  | { kind: "milestone"; key: string; event: StageEvent }
  | { kind: "attempt"; key: string; group: AttemptGroup };

/**
 * The event log as one row per attempt rather than one row per stage.
 *
 * A four-iteration `both` run emits fifty-odd events, and read flat they are a wall in which
 * the two that matter — a draft thrown away, a draft trimmed and kept — scroll past with the
 * same weight as "rendering". Attempts are what a person is actually tracking.
 */
export function timeline(log: StageEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const groups = new Map<string, AttemptGroup>();

  for (const event of log) {
    if (event.attempt === undefined) {
      items.push({ kind: "milestone", key: `m${items.length}`, event });
      continue;
    }
    const document = event.document ?? "resume";
    const key = `${document}#${event.attempt}`;
    let group = groups.get(key);
    if (group === undefined) {
      group = {
        document,
        attempt: event.attempt,
        attempts: event.attempts ?? event.attempt,
        stage: event.stage,
        repaired: false,
        dropped: 0,
        reason: "",
        outcome: "open",
      };
      groups.set(key, group);
      items.push({ kind: "attempt", key, group });
    }
    group.stage = event.stage;
    if (event.score !== undefined) group.score = event.score;
    if (event.parses !== undefined) group.parses = event.parses;
    if (event.pages !== undefined) group.pages = event.pages;
    if (event.words !== undefined) group.words = event.words;
    if (event.stage === "repaired") {
      group.repaired = true;
      group.dropped = event.dropped ?? 0;
      group.reason = event.reason ?? "";
    }
    // A rejection ends the attempt; a repair does not, so only the first sets the outcome.
    if (event.stage === "rejected") {
      group.outcome = "rejected";
      group.reason = event.reason ?? "";
    }
    if (event.stage === "scored") group.outcome = "finished";
  }
  return items;
}
