/**
 * Typed client for the India TPA desk API (docs/TPA_DESK_CONTRACT.md, v1).
 * All routes live under /api/v1/desk and share auth with api.ts.
 */
import { ApiError, apiRequest } from "./api";

export type Stage =
  | "draft"
  | "ready_to_send"
  | "sent"
  | "query"
  | "approved"
  | "enhancement"
  | "discharge_pending"
  | "discharge_sent"
  | "closed";

export const STAGES: readonly Stage[] = [
  "draft",
  "ready_to_send",
  "sent",
  "query",
  "approved",
  "enhancement",
  "discharge_pending",
  "discharge_sent",
  "closed",
];

export function isStage(value: string): value is Stage {
  return (STAGES as readonly string[]).includes(value);
}

export type PayerType = "insurer" | "tpa" | "pmjay" | "cghs" | "self_pay";
export const PAYER_LABEL: Record<PayerType, string> = {
  insurer: "Insurer (direct)",
  tpa: "TPA",
  pmjay: "PM-JAY",
  cghs: "CGHS",
  self_pay: "Self-pay",
};

export type AdmissionType = "planned" | "emergency";
export type ClockKind = "query_response" | "insurer_decision" | "final_approval" | "prep" | "none";

export interface DeskClock {
  kind: ClockKind;
  label: string;
  due_at: string | null;
  minutes_left: number | null;
  overdue: boolean;
}

export interface WorklistItem {
  case_id: string;
  patient_id: string;
  patient_name: string;
  mrn: string;
  age: number | null;
  sex: string;
  payer_type: PayerType;
  insurer_name: string;
  tpa_name: string;
  policy_last4: string;
  proposed_treatment: string;
  estimated_cost_inr: number | null;
  stage: Stage;
  stage_label: string;
  readiness_percent: number;
  open_items: number;
  clock: DeskClock;
  assigned_to: string | null;
  updated_at: string;
}

export type StageCounts = Partial<Record<Stage | "overdue", number>>;

export interface DeskWorklist {
  items: WorklistItem[];
  total: number;
  counts: StageCounts;
}

export interface DeskStats {
  overdue: number;
  due_within_60m: number;
  queries_open: number;
  ready_to_send: number;
  awaiting_senior: number;
  median_prep_minutes: number | null;
}

export type ChecklistStatus = "SUPPORTED" | "MISSING" | "UNKNOWN" | "NOT_SUPPORTED";
export type ChecklistGroup = "form" | "clinical" | "documents";

export interface DeskCitation {
  document_id: string;
  chunk_id: string;
  source: string;
  excerpt: string;
  date: string | null;
}

export interface ChecklistItem {
  item_id: string;
  group: ChecklistGroup;
  label: string;
  status: ChecklistStatus;
  required: boolean;
  reason: string;
  fix_hint: string;
  citations: DeskCitation[];
}

export interface DeskCase {
  case_id: string;
  patient_id: string;
  policy_id?: string | null;
  procedure?: string | null;
  payer_type: PayerType;
  insurer_name: string;
  tpa_name: string;
  policy_number: string;
  admission_type: AdmissionType;
  admitted_at: string | null;
  expected_discharge_at: string | null;
  treating_doctor: string;
  provisional_diagnosis: string;
  icd10_code: string;
  proposed_treatment: string;
  estimated_cost_inr: number | null;
  approved_amount_inr: number | null;
  stage: Stage;
  stage_label: string;
  sent_at: string | null;
  decision_due_at: string | null;
  approved_at: string | null;
  discharge_requested_at: string | null;
  final_due_at: string | null;
  assigned_to?: string | null;
  clock: DeskClock;
}

export interface DeskPatient {
  patient_id: string;
  name: string;
  mrn: string;
  age: number | null;
  sex: string;
}

export interface Readiness {
  percent: number;
  required: number;
  supported: number;
  missing: number;
  unknown: number;
  not_supported: number;
  label: string;
}

export interface DeskQuery {
  query_id: string;
  raised_at: string;
  text: string;
  response_due_at: string | null;
  responded_at: string | null;
  response: string;
}

export interface TimelineEntry {
  at: string;
  event: string;
  actor_label: string;
}

export type ReviewState = "not_started" | "awaiting_senior" | "acknowledged" | "needs_documentation";

export interface CaseReview {
  state: ReviewState;
  by_label: string;
  at: string | null;
  notes: string;
  /** Not in contract v1; used when the server includes it. */
  run_id?: string | null;
}

export interface CaseWorkspace {
  case: DeskCase;
  patient: DeskPatient;
  readiness: Readiness;
  checklist: ChecklistItem[];
  queries: DeskQuery[];
  timeline: TimelineEntry[];
  review: CaseReview;
  disclaimer: string;
}

export interface PreauthField {
  key: string;
  label: string;
  value: string;
  source: "chart" | "case" | "missing";
  required: boolean;
}

export interface PreauthSection {
  title: string;
  fields: PreauthField[];
}

export interface PreauthAttachment {
  label: string;
  status: "SUPPORTED" | "MISSING";
  citations: DeskCitation[];
}

export interface PreauthForm {
  form_version: string;
  sections: PreauthSection[];
  missing_required: string[];
  attachments: PreauthAttachment[];
}

export type FindingSeverity = "blocker" | "warning" | "info";

export interface DischargeFinding {
  severity: FindingSeverity;
  code: string;
  message: string;
  expected: string;
  found: string;
  citations: DeskCitation[];
}

export interface DischargeCheck {
  status: "ok" | "warnings" | "blockers";
  findings: DischargeFinding[];
}

/** Fields the desk may edit via PATCH (never stage or clocks). */
export interface CaseEditable {
  payer_type?: PayerType;
  insurer_name?: string;
  tpa_name?: string;
  policy_number?: string;
  admission_type?: AdmissionType;
  admitted_at?: string | null;
  expected_discharge_at?: string | null;
  treating_doctor?: string;
  provisional_diagnosis?: string;
  icd10_code?: string;
  proposed_treatment?: string;
  estimated_cost_inr?: number | null;
}

export type StageAction =
  | { action: "mark_sent" }
  | { action: "record_query"; text: string; response_due_hours?: number }
  | { action: "answer_query"; query_id: string; response: string }
  | { action: "record_approval"; approved_amount_inr: number }
  | { action: "request_enhancement"; revised_estimate_inr: number; reason: string }
  | { action: "start_discharge" }
  | { action: "mark_discharge_sent"; override_reason?: string }
  | { action: "close" };

export type StageActionName = StageAction["action"];

const BASE = "/api/v1/desk";

export function getDeskWorklist(options?: {
  stage?: Stage | "";
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<DeskWorklist> {
  const params = new URLSearchParams();
  if (options?.stage) params.set("stage", options.stage);
  if (options?.q?.trim()) params.set("q", options.q.trim());
  params.set("limit", String(options?.limit ?? 50));
  params.set("offset", String(options?.offset ?? 0));
  return apiRequest(`${BASE}/worklist?${params.toString()}`);
}

export function getDeskStats(): Promise<DeskStats> {
  return apiRequest(`${BASE}/stats`);
}

export function getCaseWorkspace(caseId: string): Promise<CaseWorkspace> {
  return apiRequest(`${BASE}/cases/${encodeURIComponent(caseId)}`);
}

export function patchCase(caseId: string, body: CaseEditable): Promise<CaseWorkspace> {
  return apiRequest(`${BASE}/cases/${encodeURIComponent(caseId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function createCase(
  body: CaseEditable & { patient_id: string; policy_id?: string; payer_type: PayerType },
): Promise<CaseWorkspace> {
  return apiRequest(`${BASE}/cases`, { method: "POST", body: JSON.stringify(body) });
}

export function postStageAction(caseId: string, body: StageAction): Promise<CaseWorkspace> {
  return apiRequest(`${BASE}/cases/${encodeURIComponent(caseId)}/stage`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getPreauthForm(caseId: string): Promise<PreauthForm> {
  return apiRequest(`${BASE}/cases/${encodeURIComponent(caseId)}/preauth-form`);
}

export function getDischargeCheck(caseId: string): Promise<DischargeCheck> {
  return apiRequest(`${BASE}/cases/${encodeURIComponent(caseId)}/discharge-check`);
}

/** Plain message for an error from the desk API, with a clear note for undeployed routes. */
export function deskErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.endpointMissing) {
      return "This desk feature is not available on this server yet. Ask your administrator to update the HealthEvidence API.";
    }
    if (error.status === 409) {
      return error.message || "That step is not allowed at the case's current stage.";
    }
    return error.message || fallback;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

export function isEndpointMissing(error: unknown): boolean {
  return error instanceof ApiError && error.endpointMissing;
}

/** Policy numbers are masked except the last 4 characters. */
export function maskPolicy(value: string | null | undefined): string {
  const raw = (value || "").trim();
  if (!raw) return "";
  const last4 = raw.slice(-4);
  return `•••• ${last4}`;
}
