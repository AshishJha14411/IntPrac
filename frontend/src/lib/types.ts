/**
 * Hand-written mirrors of the API contract.
 *
 * These exist so the app compiles before the backend is running. The real
 * source of truth is the backend's OpenAPI schema -- run
 * `npm run gen:api --schema=http://backend:8080/openapi.json` to regenerate
 * `api-types.ts` and switch these imports over.
 *
 * ⚠ Two traps when you do (Appendix D.6): regenerate against the **service
 * name** from inside a container, not `localhost`; and expect the generated
 * types to surface real drift -- fields the UI reads that the API never
 * returned. That fallout is the payoff, not a setback.
 */

export type Seniority = "fresher" | "junior" | "mid" | "senior";
export type InterviewMode = "resume" | "jd" | "combined";
export type Verdict = "covered" | "partial" | "missing" | "contradicted";

export type User = {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  organization_id: string;
  role: string;
};

export type SessionSummary = {
  id: string;
  status: string;
  mode: string;
  purpose: string;
  seniority: string;
  target_minutes: number;
  question_count: number;
  created_at: string;
  completed_at: string | null;
};

export type SessionPage = {
  items: SessionSummary[];
  /** Keyset cursor over `(created_at, id)`. Null when the page is the last. */
  next_cursor: string | null;
};

/** One competency's score in one completed session, and the move since last time. */
export type ProgressPoint = {
  session_id: string;
  completed_at: string | null;
  competency_id: string;
  /** 0..1. */
  score: number;
  /** Null on the first session that touched this competency. */
  delta: number | null;
};

export type PlannedQuestion = {
  id: string;
  ordinal: number;
  competency_id: string;
  prompt: string;
};

export type SessionPlan = {
  session: SessionSummary;
  questions: PlannedQuestion[];
  competencies: string[];
  discarded_candidates?: string[];
};

export type Turn = {
  question_id: string;
  ordinal: number;
  total: number;
  prompt: string;
  competency_id: string;
  hints_used: number;
  followups_used: number;
  is_followup: boolean;
  followup_prompt: string | null;
  remaining_minutes: number;
};

export type AnswerResult = {
  answer_id: string;
  accepted: boolean;
  replayed: boolean;
  session_completed: boolean;
  next_turn: Turn | null;
};

export type Hint = {
  level: string;
  text: string;
  remaining: number;
  scoring_note: string;
};

export type ConceptLine = {
  concept_id: string;
  label: string;
  weight: string;
  verdict: Verdict;
  why_it_matters: string;
  evidence_quote: string | null;
  improvement_note: string | null;
  hint_discounted: boolean;
};

export type QuestionReport = {
  question_id: string;
  ordinal: number;
  competency_id: string;
  prompt: string;
  transcript: string;
  band: number | null;
  raw_score: number | null;
  hint_adjusted_score: number | null;
  hints_used: number;
  status: string;
  covered: ConceptLine[];
  partial: ConceptLine[];
  missed: ConceptLine[];
  terminology_notes: string[];
  unsubstantiated_claim: boolean;
};

export type CompetencyRollup = {
  competency_id: string;
  band: number;
  band_anchor: string;
  raw: number;
  hint_adjusted: number;
  question_count: number;
};

export type SessionReport = {
  session_id: string;
  status: string;
  mode: string;
  seniority: string;
  overall_raw: number;
  overall_hint_adjusted: number;
  recommendation: string;
  graded_questions: number;
  pending_questions: number;
  competencies: CompetencyRollup[];
  questions: QuestionReport[];
  top_improvements: { competency_id: string; concept: string; why_it_matters: string; what_to_add: string }[];
  cost_usd: number;
};
