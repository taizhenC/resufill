// Mirrors the JSON the Python side emits. Hand-written rather than generated: the surface
// is a dozen shapes, and a codegen step would be more machinery than the thing it types.
//
// Sources of truth, if one of these ever looks wrong:
//   doctor.Check / doctor.Report      -> DoctorCheck / DoctorReport
//   runrecord.RunSummary / RunRecord  -> RunSummary / RunRecord
//   jobs.JobState.snapshot()          -> JobSnapshot

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
  /** False for things the tool works without — a missing blog corpus, for instance. */
  blocking: boolean;
  fix: string;
}

export interface DoctorReport {
  /** Blocking failures only. Warnings are for the human, not for the gate. */
  ok: boolean;
  checks: DoctorCheck[];
}

export type Mode = "resume" | "cover" | "both";

export interface RunRequest {
  jd: string;
  mode: Mode;
  threshold?: number | null;
  max_iter?: number | null;
  pages?: number | null;
  strict?: boolean;
}

export interface StageEvent {
  stage: string;
  at_ms: number;
  document?: string;
  attempt?: number;
  attempts?: number;
  score?: number;
  parses?: boolean;
  pages?: number;
  words?: number;
  reason?: string;
  ok?: boolean;
}

export interface JobSnapshot {
  idle?: boolean;
  id: number;
  mode: string;
  run_id: string;
  stage: string;
  detail: Record<string, unknown>;
  events: StageEvent[];
  event_count: number;
  started_at_ms: number;
  finished_at_ms: number | null;
  cancel_requested: boolean;
  cancelled: boolean;
  done: boolean;
  ok: boolean;
  error: string | null;
}

export interface RunSummary {
  run_id: string;
  created_at: string;
  mode: string;
  ok: boolean;
  cancelled: boolean;
  title: string;
  company: string;
  total: number | null;
  threshold: number | null;
  pdfs: string[];
  /** A run made before run.json existed. Listed, downloadable, nothing structured to show. */
  legacy: boolean;
}

export interface CitedSource {
  id: string;
  label: string;
  /** Embedded at generation time, so the audit stays true after profile.yaml is edited. */
  text: string;
}

export interface Claim {
  where: string;
  text: string;
  sources: CitedSource[];
}

export interface ScoreComponent {
  name: string;
  label: string;
  weight: number;
  raw: number;
  points: number;
  detail: string;
}

export interface Gap {
  keyword: string;
  in_record: boolean;
  where: string;
}

export interface ScoreRecord {
  total: number;
  threshold: number;
  met: boolean;
  components: ScoreComponent[];
  matched: string[];
  /** Not in the record at all — a fact about you, which no rewrite closes. */
  gaps_absent: Gap[];
  /** In the record but not surfaced — a tailoring miss, fixable by editing profile.yaml. */
  gaps_unsurfaced: Gap[];
  stuffed: string[];
  unaddressed_qualifications: string[];
}

export interface VerifyRecord {
  ok: boolean;
  page_count: number;
  missing: string[];
  checks: Record<string, boolean>;
}

export interface DocumentRecord {
  kind: "resume" | "cover_letter";
  pdf: string;
  ok: boolean;
  iterations: number;
  verify: VerifyRecord | null;
  claims: Claim[];
  blocked_terms: string[];
  violations: string[];
  /** What the gate cut out of the draft so the rest could be kept. */
  removed: string[];
}

export interface RunRecord {
  schema_version: number;
  run_id: string;
  created_at: string;
  mode: string;
  ok: boolean;
  cancelled: boolean;
  jd: {
    title: string;
    company: string;
    seniority: string;
    min_years: number | null;
    hard_skills: string[];
    keywords: string[];
    qualifications: string[];
  };
  settings: Record<string, string | number | boolean>;
  score: ScoreRecord | null;
  documents: DocumentRecord[];
  legacy?: boolean;
}
