// Mirrors the JSON the Python side emits. Hand-written rather than generated: the surface
// is a dozen shapes, and a codegen step would be more machinery than the thing it types.
//
// Sources of truth, if one of these ever looks wrong:
//   doctor.Check / doctor.Report      -> DoctorCheck / DoctorReport
//   runrecord.RunSummary / RunRecord  -> RunSummary / RunRecord
//   jobs.JobState.snapshot()          -> JobSnapshot
//   main.api_analyze()                -> Analysis
//   document.CoverLetter              -> CoverLetterFile

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
  /** ground.summarize() on `rejected`, Repair.summary() on `repaired` — e.g. `unsupported_termx2`. */
  reason?: string;
  /** How many claims the repair cut out. Only on `repaired`. */
  dropped?: number;
  ok?: boolean;
}

/** meter.Meter.as_dict(). Deliberately not a price — see meter.py. */
export interface Usage {
  calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  seconds?: number;
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
  /** Live, so the price of another iteration is visible while there is time to cancel one. */
  usage?: Usage;
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

export interface JobRecord {
  title: string;
  company: string;
  seniority: string;
  min_years: number | null;
  hard_skills: string[];
  keywords: string[];
  qualifications: string[];
}

/** score.Ceiling plus the threshold it is being judged against. */
export interface CeilingPreview {
  total: number;
  /** name -> raw fraction. Keyed by score component name, not labelled by the server. */
  components: Record<string, number>;
  /** Keywords nothing in the record supports, so no grounded document could contain them. */
  unreachable: string[];
  threshold: number;
  reachable: boolean;
}

/** POST /api/analyze — the lexicon pass and the ceiling, with no model call behind either. */
export interface Analysis {
  deterministic: boolean;
  jd: JobRecord;
  ceiling: CeilingPreview;
  /** Keywords the record already supports. */
  covered: string[];
}

export interface LetterParagraph {
  text: string;
  source_ids: string[];
}

/** cover_letter.json, read straight from the run directory. */
export interface CoverLetterFile {
  addressee: string;
  paragraphs: LetterParagraph[];
  signoff: string;
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

// A run.json is a file on disk, not a live API: the four ceiling fields were added later, so a
// record written before them has no such key at all. Optional rather than `| null` because
// `ceiling: number | null` is a promise the older files on disk do not keep, and reading them as
// though they did took the whole run view down with one `.toFixed`.
export interface ScoreRecord {
  total: number;
  threshold: number;
  met: boolean;
  /** The highest score this record could reach for this posting. */
  ceiling?: number | null;
  /** The loop got everything out of the record there was to get. */
  at_ceiling?: boolean;
  /** Keywords no grounded document could ever contain, because the record has not got them. */
  unreachable?: string[];
  /** Which stopping rule ended the loop: threshold | ceiling | plateau | exhausted | ... */
  stop_reason?: string;
  components: ScoreComponent[];
  matched: string[];
  /** Not in the record at all — a fact about you, which no rewrite closes. */
  gaps_absent: Gap[];
  /** In the record but not surfaced — a tailoring miss, fixable by editing profile.yaml. */
  gaps_unsurfaced: Gap[];
  stuffed: string[];
  unaddressed_qualifications: string[];
  /** Words from the posting's own job title the résumé never uses. The cheapest points here. */
  title_words_missing?: string[];
}

export interface VerifyRecord {
  ok: boolean;
  page_count: number;
  missing: string[];
  checks: Record<string, boolean>;
}

/**
 * One check from `ats.py` (a résumé) or `letter_review.py` (a letter).
 *
 * `kind` is "parsing" | "reading" for a résumé and "blocking" | "advisory" for a letter.
 * The two vocabularies mean the same thing on each side — the first value is the one that is
 * not a matter of taste — and the UI treats them as one distinction.
 */
export interface RubricCheck {
  name: string;
  ok: boolean;
  detail: string;
  kind: string;
  /** What to do about it, in the second person. A check that only says "no" makes you guess. */
  fix: string;
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
  /** The rubric this document was checked against. Empty on runs made before it existed. */
  ats?: RubricCheck[];
}

export interface RunRecord {
  schema_version: number;
  run_id: string;
  created_at: string;
  mode: string;
  ok: boolean;
  cancelled: boolean;
  jd: JobRecord;
  settings: Record<string, string | number | boolean>;
  /** What the run cost: calls, tokens, seconds. Empty on runs made before it was counted. */
  usage?: Usage;
  score: ScoreRecord | null;
  documents: DocumentRecord[];
  legacy?: false;
}

/**
 * What `/api/runs/{id}` answers with for a directory that has no run.json: the summary, and
 * nothing else. It is a genuinely different shape — no `jd`, no `documents` — and treating it
 * as a RunRecord took the run view down rather than showing the two facts it does have.
 */
export interface LegacyRunRecord extends RunSummary {
  legacy: true;
}

export type LoadedRun = RunRecord | LegacyRunRecord;

/**
 * A run directory with no run.json. Its files are still there; nothing structured is.
 *
 * The flag is what the server sets deliberately, so it leads. The structural check behind it
 * is not redundancy for its own sake: this shape is the *absence* of the fields everything
 * downstream reads, and getting it wrong takes the whole view down rather than one panel.
 */
export function isLegacy(run: LoadedRun): run is LegacyRunRecord {
  return run.legacy === true || (run as RunRecord).jd === undefined;
}
