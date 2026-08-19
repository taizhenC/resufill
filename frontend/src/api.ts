import type {
  Analysis,
  CoverLetterFile,
  DoctorReport,
  JobSnapshot,
  LoadedRun,
  RunRequest,
  RunSummary,
} from "./types";

/** A failed request that still carries what the server said, so the UI can show it. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // FastAPI puts the message under `detail`, sometimes as an object when the endpoint
    // wants to attach structure (the 412 from /api/runs carries the failed checks).
    const detail = (body as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : ((detail as { detail?: string })?.detail ?? `${response.status} ${response.statusText}`);
    throw new ApiError(response.status, message, detail);
  }
  return body as T;
}

export const api = {
  doctor: (deep = false) => request<DoctorReport>(`/api/doctor${deep ? "?deep=1" : ""}`),

  runs: () => request<{ runs: RunSummary[] }>("/api/runs").then((body) => body.runs),

  run: (runId: string) => request<LoadedRun>(`/api/runs/${encodeURIComponent(runId)}`),

  /** Only the events the caller has not seen — a long run's snapshot stays small. */
  current: (since = 0) => request<JobSnapshot>(`/api/runs/current?since=${since}`),

  start: (payload: RunRequest) =>
    request<JobSnapshot>("/api/runs", { method: "POST", body: JSON.stringify(payload) }),

  cancel: () => request<{ cancel_requested: boolean }>("/api/runs/current/cancel", { method: "POST" }),

  /** Free: the lexicon pass and the ceiling, neither of which calls a model. Safe to fire on typing. */
  analyze: (jd: string) => request<Analysis>("/api/analyze", { method: "POST", body: JSON.stringify({ jd }) }),

  coverLetter: (runId: string) =>
    request<CoverLetterFile>(
      `/api/runs/${encodeURIComponent(runId)}/files/cover_letter.json`,
    ),

  fileUrl: (runId: string, name: string) =>
    `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`,
};
