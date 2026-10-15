/** Quiet product strip — patient lifelong record first; TPA desk is a later hospital module. */
export const VALUE_STRIP =
  "Your lifelong health record · Doctor view with sources · Emergency card";

/** Footer honesty — never lead the chrome with this. */
export const FOOTER_DISCLAIMER =
  "Organises and shows health records with sources. Not a medical device. Does not diagnose, prescribe, approve, or deny care.";

export interface PatientSummary {
  patient_id: string;
  synthetic_name: string;
  date_of_birth: string;
  sex: string;
  conditions: string[];
  /** Optional enrichments (shown when the server provides them). */
  mrn?: string | null;
  last_visit_at?: string | null;
}

export interface PatientDetail {
  patient_id: string;
  demographics: {
    patient_id: string;
    synthetic_name: string;
    date_of_birth: string;
    sex: string;
  };
  conditions: string[];
  medications: { medication_id: string; name: string; dose: string; status: string }[];
  labs: {
    lab_id: string;
    test_name: string;
    value: string;
    unit: string;
    collected_at: string;
    document_id?: string | null;
    has_file?: boolean;
  }[];
  procedures: { procedure_id: string; name: string; performed_at: string }[];
  imaging: {
    imaging_id: string;
    modality: string;
    body_part: string;
    study_date: string;
    description: string;
    document_id?: string | null;
    has_file?: boolean;
  }[];
  clinical_notes: {
    note_id: string;
    note_type: string;
    content: string;
    authored_at: string;
    document_id: string;
  }[];
  claims?: { claim_id: string; status: string; amount_cents: number; service_date: string }[];
}

export interface TimelineEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  description: string;
  classification: string;
  specialty?: string;
  facility_name?: string;
  document_id?: string | null;
  title?: string;
}

export interface PolicyDetail {
  policy_id: string;
  title: string;
  payer_name: string;
  procedure: string;
  criteria: { criterion_id: string; description: string; position: number }[];
}

export interface AuthCase {
  case_id: string;
  patient_id: string;
  policy_id: string;
  policy_title: string;
  procedure: string;
  status?: "queued" | "needs_documentation" | "ready_for_human" | "closed_as_draft";
  last_run_id?: string | null;
  lifecycle_note?: string;
  cycle_elapsed_minutes?: number | null;
  assigned_to?: string | null;
}

export interface EvidenceRef {
  document_id: string;
  chunk_id: string;
  source: string;
  text_reference: string;
}

export interface Review {
  case_id: string | null;
  patient_id: string;
  policy_id: string;
  procedure: string;
  review_type: string;
  criteria: {
    criterion_id: string;
    criterion: string;
    status: "SUPPORTED" | "NOT_SUPPORTED" | "MISSING" | "UNKNOWN";
    evidence: EvidenceRef[];
    reason: string;
  }[];
  missing_evidence: string[];
  contradictions: {
    criterion: string;
    description: string;
    evidence: EvidenceRef[];
    conflict?: boolean;
    evidence_a?: string;
    evidence_b?: string;
    resolution?: string;
  }[];
  human_review_required: boolean;
  awaiting_human_review?: boolean;
  evidence_coverage: string;
  citations: EvidenceRef[];
  disclaimer: string;
  run_id?: string;
  trace_id?: string;
  report_summary?: string;
  human_review_reason?: string;
  scoring_path?: string;
  agent_trace?: { agent: string; node: string; detail: string; status: string }[];
  observability?: Record<string, unknown>[];
  evidence_panel?: {
    document_id: string;
    chunk_id: string;
    criterion_id: string;
    score?: number;
    content: string;
  }[];
  critic_notes?: string[];
  senior_assist?: SeniorReviewAssist & { edited?: boolean };
}

export interface Stats {
  patients: number;
  authorization_cases: number;
  policies: number;
  system_status: string;
}

let cachedToken: string | null = null;
let tokenPromise: Promise<string | null> | null = null;
let tokenRolesKey = "";

function bootRolesFromStorage(): string[] {
  try {
    const raw = localStorage.getItem("he.ai.deskRole");
    if (
      raw === "patient" ||
      raw === "staff" ||
      raw === "resident" ||
      raw === "senior_clinician" ||
      raw === "admin"
    ) {
      return [raw];
    }
  } catch {
    /* ignore */
  }
  return ["staff"];
}

/** Active desk role used when minting the local JWT (set by RoleProvider). */
let activeDeskRoles: string[] = bootRolesFromStorage();
tokenRolesKey = activeDeskRoles.slice().sort().join(",");

/** Bound patient_id for patient-role tokens (server enforces isolation). */
let activePatientId: string | null = bootPatientIdFromStorage();

/** Facility org_code for care-team tokens when ENFORCE_ORG_SCOPE is on. */
let activeOrgCode: string | null = bootOrgCodeFromStorage();

function bootPatientIdFromStorage(): string | null {
  try {
    const role = localStorage.getItem("he.ai.deskRole");
    const raw = localStorage.getItem("he.ai.myPatientId");
    if (role === "patient" && raw && /^PAT-\d{6}$/.test(raw)) {
      return raw.toUpperCase();
    }
  } catch {
    /* ignore */
  }
  return null;
}

function bootOrgCodeFromStorage(): string | null {
  try {
    const role = localStorage.getItem("he.ai.deskRole");
    if (role === "patient") {
      return null;
    }
    const raw = localStorage.getItem("he.ai.orgCode");
    if (raw && /^ORG-\d{6}$/i.test(raw.trim())) {
      return raw.trim().toUpperCase();
    }
  } catch {
    /* ignore */
  }
  return "ORG-000001";
}

export function setAuthRoles(roles: string[]): void {
  const next = roles.length ? roles : ["staff"];
  const key = next.slice().sort().join(",");
  activeDeskRoles = next;
  tokenRolesKey = key;
  // Drop cached + in-flight mints so a role switch cannot keep a stale staff token.
  cachedToken = null;
  tokenPromise = null;
}

/** Bind (or clear) patient_id claim for the next JWT mint. */
export function setAuthPatientId(patientId: string | null): void {
  const next =
    patientId && /^PAT-\d{6}$/i.test(patientId.trim()) ? patientId.trim().toUpperCase() : null;
  if (next === activePatientId) {
    return;
  }
  activePatientId = next;
  cachedToken = null;
  tokenPromise = null;
}

/** Bind (or clear) org_code claim for care-team JWT mint. */
export function setAuthOrgCode(orgCode: string | null): void {
  const next =
    orgCode && /^ORG-\d{6}$/i.test(orgCode.trim()) ? orgCode.trim().toUpperCase() : null;
  if (next === activeOrgCode) {
    return;
  }
  activeOrgCode = next;
  try {
    if (next) {
      localStorage.setItem("he.ai.orgCode", next);
    } else {
      localStorage.removeItem("he.ai.orgCode");
    }
  } catch {
    /* ignore */
  }
  cachedToken = null;
  tokenPromise = null;
}

export function clearAuthToken(): void {
  cachedToken = null;
  tokenPromise = null;
}

/** Current bearer for the signed-in desk — mint if needed. */
export async function getAccessToken(): Promise<string | null> {
  try {
    return await ensureDevToken();
  } catch {
    return cachedToken;
  }
}

/**
 * Short-lived (~60 s), single-use SSE ticket. EventSource cannot send an
 * Authorization header, so the bearer token never goes into the stream URL.
 * Returns null when auth is off (the stream then needs no credential).
 */
export async function getStreamTicket(): Promise<string | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = await getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch("/api/v1/events/stream-ticket", { method: "POST", headers });
  if (!response.ok) {
    throw new Error(`Stream ticket request failed (${response.status})`);
  }
  const body = (await response.json()) as { ticket?: string };
  return typeof body.ticket === "string" && body.ticket ? body.ticket : null;
}

async function ensureDevToken(): Promise<string | null> {
  if (cachedToken) {
    return cachedToken;
  }
  const rolesSnapshot = activeDeskRoles.slice();
  const keySnapshot = tokenRolesKey;
  const patientSnapshot = activePatientId;
  const orgSnapshot = activeOrgCode;
  if (!tokenPromise) {
    tokenPromise = (async () => {
      const body: {
        subject: string;
        roles: string[];
        patient_id?: string;
        org_code?: string;
      } = {
        subject: "local-ui",
        roles: rolesSnapshot,
      };
      if (rolesSnapshot.includes("patient") && patientSnapshot) {
        body.patient_id = patientSnapshot;
        body.subject = patientSnapshot;
      } else if (orgSnapshot && !rolesSnapshot.includes("admin")) {
        body.org_code = orgSnapshot;
      }
      const response = await fetch("/api/v1/auth/dev-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) {
          return null;
        }
        const errBody = (await response.json().catch(() => ({}))) as { message?: string };
        throw new Error(errBody.message || `Auth token request failed (${response.status})`);
      }
      const tokenBody = (await response.json()) as { access_token: string };
      // Role, patient, or org binding changed while minting — discard this token.
      if (
        tokenRolesKey !== keySnapshot ||
        activePatientId !== patientSnapshot ||
        activeOrgCode !== orgSnapshot
      ) {
        return null;
      }
      cachedToken = tokenBody.access_token;
      return cachedToken;
    })().finally(() => {
      tokenPromise = null;
    });
  }
  const token = await tokenPromise;
  if (
    !token &&
    (tokenRolesKey !== keySnapshot ||
      activePatientId !== patientSnapshot ||
      activeOrgCode !== orgSnapshot)
  ) {
    return ensureDevToken();
  }
  return token;
}

/** Error thrown by every API helper; carries the HTTP status and server error code. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** True when the route itself is not deployed on this server (generic 404). */
  get endpointMissing(): boolean {
    return this.status === 404 && (this.code === "NOT_FOUND" || this.code === "");
  }
}

/** Shared authenticated JSON request (used by deskApi.ts). */
export function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (!path.startsWith("/health") && path !== "/") {
    try {
      const token = await ensureDevToken();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      /* proceed without bearer when mint fails */
    }
  }
  const response = await fetch(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      message?: string;
      error_code?: string;
    };
    throw new ApiError(
      friendlyApiMessage(body.error_code, body.message, response.status),
      response.status,
      body.error_code || "",
    );
  }
  return (await response.json()) as T;
}

function friendlyApiMessage(
  errorCode: string | undefined,
  message: string | undefined,
  status: number,
): string {
  const raw = (message || "").trim();
  const lower = raw.toLowerCase();
  if (
    errorCode === "OIDC_FORBIDDEN" ||
    errorCode === "RBAC_FORBIDDEN" ||
    lower.includes("principal lacks required role") ||
    lower.includes("lacks required role") ||
    (lower.includes("have=") && lower.includes("need="))
  ) {
    return "This action isn’t available for the current signed-in role.";
  }
  if (errorCode === "OIDC_UNAUTHORIZED" || status === 401) {
    return "Please sign in again to continue.";
  }
  if (errorCode === "ORG_SCOPE_REQUIRED") {
    return "Your sign-in needs a facility assignment before opening charts.";
  }
  if (errorCode === "ORG_SCOPE_FORBIDDEN") {
    return "This chart belongs to another facility.";
  }
  if (errorCode === "CONSENT_REQUIRED") {
    return raw || "A recorded, active patient consent is required before saving this visit.";
  }
  if (raw) {
    return raw;
  }
  return `Request failed (${status})`;
}

export interface AuthMe {
  subject: string;
  email: string;
  roles: string[];
  product_roles: string[];
  auth_mode: string;
  patient_id: string | null;
  org_id: string | null;
  org_code: string | null;
  demo_signin_allowed: boolean;
  enforce_org_scope: boolean;
}

/** Deployment mode banner contract (server: Settings.deployment_banner). */
export type DeploymentMode = "demo" | "trial" | "practice";

export interface DeploymentInfo {
  mode: DeploymentMode;
  trial_site_org_code: string;
  trial_end_date: string;
  banner: string;
}

/** Text shown in the always-visible top banner for each deployment mode. */
export function deploymentBannerText(info: DeploymentInfo): string {
  // Server text is authoritative (it knows when a real-data trial has ended).
  if (info.banner) {
    return info.banner;
  }
  if (info.mode === "trial") {
    const site = info.trial_site_org_code || "unconfigured site";
    const until = info.trial_end_date || "unset date";
    return `REAL-DATA TRIAL — ${site} until ${until}`;
  }
  if (info.mode === "demo") {
    return "DEMO — synthetic data";
  }
  return "PRACTICE — synthetic / consented test data only";
}

export interface AuthCapabilities {
  auth_mode: string;
  demo_signin_allowed: boolean;
  enforce_org_scope: boolean;
  docs_exposed: boolean;
  deployment: DeploymentInfo | null;
}

/** Public capabilities for chrome (demo sign-in vs OIDC identity). */
export async function getAuthCapabilities(): Promise<AuthCapabilities> {
  const response = await fetch("/api/v1/auth/capabilities");
  if (!response.ok) {
    return {
      auth_mode: "dev-jwt",
      demo_signin_allowed: true,
      enforce_org_scope: false,
      docs_exposed: true,
      deployment: null,
    };
  }
  const body = (await response.json()) as Partial<AuthCapabilities>;
  return {
    auth_mode: body.auth_mode ?? "dev-jwt",
    demo_signin_allowed: body.demo_signin_allowed ?? true,
    enforce_org_scope: body.enforce_org_scope ?? false,
    docs_exposed: body.docs_exposed ?? false,
    deployment: body.deployment ?? null,
  };
}

/** Optional-auth identity endpoint — hydrate after dig-token mint / OIDC login. */
export async function getAuthMe(): Promise<AuthMe> {
  const caps = await getAuthCapabilities();
  const headers: Record<string, string> = {};
  if (cachedToken) {
    headers.Authorization = `Bearer ${cachedToken}`;
  }
  const response = await fetch("/api/v1/auth/me", { headers });
  if (!response.ok) {
    return {
      subject: "anonymous",
      email: "",
      roles: [],
      product_roles: [],
      auth_mode: caps.auth_mode,
      patient_id: null,
      org_id: null,
      org_code: null,
      demo_signin_allowed: caps.demo_signin_allowed,
      enforce_org_scope: caps.enforce_org_scope,
    };
  }
  const body = (await response.json()) as AuthMe;
  return {
    ...body,
    demo_signin_allowed: body.demo_signin_allowed ?? caps.demo_signin_allowed,
    enforce_org_scope: body.enforce_org_scope ?? caps.enforce_org_scope,
  };
}

export function getHealth(): Promise<{ status: string }> {
  return request("/health");
}

export function getStats(): Promise<Stats> {
  return request("/api/v1/stats");
}

export function getPatients(options?: {
  limit?: number;
  offset?: number;
  q?: string;
}): Promise<{ patients: PatientSummary[]; total: number }> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  params.set("offset", String(options?.offset ?? 0));
  if (options?.q?.trim()) {
    params.set("q", options.q.trim());
  }
  return request(`/api/v1/patients?${params.toString()}`);
}

export function getPatient(patientId: string): Promise<PatientDetail> {
  return request(`/api/v1/patients/${patientId}`);
}

export function getPatientTimeline(
  patientId: string,
): Promise<{ patient_id: string; events: TimelineEvent[] }> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/timeline`);
}

export interface LifelongEvent {
  event_id: string;
  category: string;
  title: string;
  summary: string;
  occurred_on: string | null;
  facility_name: string;
  specialty: string;
  body_site?: string;
  disorders?: string[];
  source: string;
  why_it_matters: string;
  demo_synthetic?: boolean;
}

export interface LifelongGroup {
  key: string;
  label: string;
  count: number;
  events: LifelongEvent[];
}

export interface LifelongSummary {
  patient_id: string;
  patient_name: string;
  facilities_count: number;
  facilities: string[];
  specialties?: string[];
  specialties_count?: number;
  body_sites?: string[];
  body_sites_count?: number;
  disorders?: string[];
  disorders_count?: number;
  events: LifelongEvent[];
  by_facility?: LifelongGroup[];
  by_specialty?: LifelongGroup[];
  by_body_site?: LifelongGroup[];
  by_disorder?: LifelongGroup[];
  doctor_brief: string;
  patient_brief: string;
  includes_demo_synthetic?: boolean;
  demo_synthetic_disclaimer?: string;
}

export function getLifelongSummary(patientId: string): Promise<LifelongSummary> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/lifelong`);
}

export function getSpecialties(): Promise<{ specialties: string[] }> {
  return request("/api/v1/specialties");
}

export function getPolicy(policyId: string): Promise<PolicyDetail> {
  return request(`/api/v1/policies/${policyId}`);
}

export function getCases(): Promise<{ cases: AuthCase[] }> {
  return request("/api/v1/authorization/cases");
}

export interface WorklistPatient {
  patient_id: string;
  display_name: string;
  sex: string;
  condition_summary: string;
  specialties?: string[];
}

export interface WorklistCase {
  case_id: string;
  patient_id: string;
  procedure: string;
  policy_title: string;
  policy_id?: string;
  status?: "queued" | "needs_documentation" | "ready_for_human" | "closed_as_draft";
  next_hint?: string;
  gap_label?: string;
  gap_focus?: string;
  specialty_hint?: string;
  cycle_elapsed_minutes?: number | null;
  sla_minutes?: number | null;
  sla_breached?: boolean;
  assigned_to?: string | null;
  assigned_to_me?: boolean;
}

export interface Worklist {
  recent_patients: WorklistPatient[];
  open_cases: WorklistCase[];
  my_cases?: WorklistCase[];
  unassigned_cases?: WorklistCase[];
  assignment_enabled?: boolean;
}

export function getWorklist(): Promise<Worklist> {
  return request("/api/v1/worklist");
}

export function assignCase(
  caseId: string,
  assignedTo: string | null,
): Promise<{ case_id: string; assigned_to: string | null }> {
  return request(`/api/v1/authorization/cases/${encodeURIComponent(caseId)}/assign`, {
    method: "POST",
    body: JSON.stringify({ assigned_to: assignedTo }),
  });
}

export interface CaseAuditEvent {
  event_id: string;
  action: string;
  actor: string;
  resource_type: string;
  resource_id: string;
  status: string;
  detail: string;
  created_at: string;
}

export function getCaseAudit(caseId: string): Promise<{ total: number; events: CaseAuditEvent[] }> {
  return request(`/api/v1/authorization/cases/${encodeURIComponent(caseId)}/audit`);
}

export interface PacketCycleMetrics {
  sample_size: number;
  median_minutes: number | null;
  p75_minutes: number | null;
  mean_minutes: number | null;
  open_aging_sample_size: number;
  open_aging_median_minutes: number | null;
  unit: string;
  definition: string;
}

export interface OpsMetrics {
  packet_cycle: PacketCycleMetrics;
  organization_count: number;
  allow_phi: boolean;
  disclaimer: string;
}

export function getOpsMetrics(): Promise<OpsMetrics> {
  return request("/api/v1/metrics/ops");
}

export interface DeskInsight {
  insight_id: string;
  severity: "info" | "action" | "urgent";
  title: string;
  detail: string;
  agent: string;
  patient_id?: string | null;
  case_id?: string | null;
  href: string;
  cta: string;
}

export interface DeskInsights {
  insights: DeskInsight[];
  agent_fleet: string[];
  scoring_mode: string;
  llm_provider: string;
  llm_model: string;
  disclaimer: string;
}

export function getDeskInsights(): Promise<DeskInsights> {
  return request("/api/v1/insights");
}

export interface McpToolInfo {
  name: string;
  permission: string;
  description: string;
  agents: string[];
}

export function getMcpTools(): Promise<{ tools: McpToolInfo[]; agents: string[]; disclaimer: string }> {
  return request("/api/v1/tools");
}

export function searchEvidence(body: {
  query: string;
  patient_id?: string;
  limit?: number;
}): Promise<{ answer: string; sources: { document_id: string; chunk_id: string; score: number }[] }> {
  return request("/api/v1/evidence/search", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface SeniorReviewAssist {
  briefing: string;
  focus_items: { title: string; detail: string; severity: string }[];
  suggested_clinician_note: string;
  recommended_desk_action: "needs_documentation" | "acknowledge_after_check" | string;
  recommended_desk_action_label: string;
  source: string;
  disclaimer: string;
}

export function seniorReviewAssist(body: {
  patient_id: string;
  case_id?: string | null;
  procedure?: string;
  criteria?: { criterion: string; status: string; reason?: string }[];
  missing_evidence?: string[];
  contradictions?: string[];
  critic_notes?: string[];
  report_summary?: string;
}): Promise<SeniorReviewAssist> {
  return request("/api/v1/ai/senior-review", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface OrganizationSummary {
  org_id: string;
  org_code: string;
  name: string;
  facility_type: string;
  active: boolean;
}

export function getOrganizations(): Promise<{ organizations: OrganizationSummary[] }> {
  return request("/api/v1/organizations");
}

export function reviewCase(body: {
  patient_id: string;
  policy_id: string;
  procedure: string;
  case_id: string;
  interactive?: boolean;
}): Promise<Review> {
  return request("/api/v1/authorization/review", {
    method: "POST",
    body: JSON.stringify({ interactive: true, ...body }),
  });
}

export function resumeReview(
  runId: string,
  body: {
    decision: "acknowledged" | "needs_documentation";
    notes?: string;
    senior_assist?: SeniorReviewAssist & { edited?: boolean };
  },
): Promise<Review> {
  return request(`/api/v1/authorization/review/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface PacketCriterion {
  criterion_id: string;
  criterion: string;
  status: "SUPPORTED" | "NOT_SUPPORTED" | "MISSING" | "UNKNOWN";
  plain_status: string;
  reason: string;
  citation_count: number;
}

export interface PacketGap {
  label: string;
  focus: string;
  action: string;
  priority?: number;
  estimated_minutes?: number;
  specialty_hint?: string;
  draft_suggestion?: string;
  draft_source?: string;
  agent?: string;
  evidence_snippets?: string[];
}

export interface PacketNextAction {
  label: string;
  focus: string;
  action: string;
  specialty_hint: string;
  estimated_minutes: number;
  why: string;
  draft_suggestion?: string;
  draft_source?: string;
}

export interface EvidencePacket {
  patient_id: string;
  case_id: string;
  case_created: boolean;
  policy_id: string;
  policy_title: string;
  procedure: string;
  readiness_percent: number;
  evidence_coverage: string;
  human_review_required: boolean;
  supported_count: number;
  gap_count: number;
  criteria: PacketCriterion[];
  gaps: PacketGap[];
  specialties: string[];
  next_best_action?: PacketNextAction | null;
  estimated_prep_minutes?: number;
  documentation_risk?: "low" | "moderate" | "high";
  documentation_risk_label?: string;
  citation_strength?: "strong" | "mixed" | "weak";
  citation_strength_label?: string;
  packet_summary: string;
  next_steps: string[];
  report_summary?: string;
  run_id?: string;
  scoring_path?: string;
  cycle_elapsed_minutes?: number | null;
  agent_trace?: { agent: string; node: string; detail: string; status: string }[];
  ai_brief?: string;
  ai_assist?: {
    scoring_path?: string;
    gap_drafts_ai?: number;
    gap_drafts_total?: number;
  };
  mcp_tools_used?: string[];
  critic_summary?: string;
  documentation_pathway?: {
    step: number;
    title: string;
    detail?: string;
    agent?: string;
    priority?: string;
  }[];
  pathway_summary?: string;
  readiness_scorecard?: {
    handoff_readiness_percent: number;
    documentation_risk: "low" | "moderate" | "high";
    blockers: string[];
    recommendation: string;
    pace_note?: string;
    disclaimer?: string;
  } | null;
  disclaimer: string;
}

export function preparePacket(body: {
  patient_id: string;
  policy_id: string;
  procedure?: string;
  case_id?: string;
}): Promise<EvidencePacket> {
  return request("/api/v1/authorization/prepare", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getDocument(documentId: string): Promise<{
  document_id: string;
  content: string;
  document_type: string;
  has_file?: boolean;
  original_filename?: string;
  content_type?: string;
  file_url?: string | null;
}> {
  return request(`/api/v1/documents/${documentId}`);
}

export interface ReportItem {
  document_id: string;
  patient_id: string;
  document_type: string;
  title: string;
  source: string;
  created_at: string | null;
  has_file: boolean;
  original_filename: string;
  content_type: string;
  byte_size: number;
  preview_kind: "pdf" | "image" | "text" | "other" | string;
  content_excerpt: string;
  file_url: string | null;
  content?: string | null;
}

export function listPatientReports(patientId: string): Promise<{ reports: ReportItem[]; patient_id: string }> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/reports`);
}

export async function uploadPatientReport(
  patientId: string,
  file: File,
  documentKind:
    | "auto"
    | "lab_report"
    | "imaging_report"
    | "prescription"
    | "clinical_note" = "auto",
): Promise<ReportItem> {
  const token = await getAccessToken();
  const body = new FormData();
  body.append("file", file);
  body.append("patient_id", patientId);
  body.append("document_kind", documentKind);
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch("/api/v1/reports/upload", {
    method: "POST",
    headers,
    body,
  });
  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      message?: string;
      error_code?: string;
    };
    throw new Error(friendlyApiMessage(errBody.error_code, errBody.message, response.status));
  }
  return (await response.json()) as ReportItem;
}

export async function attachDocumentFile(documentId: string, file: File): Promise<ReportItem> {
  const token = await getAccessToken();
  const body = new FormData();
  body.append("file", file);
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}/file`, {
    method: "POST",
    headers,
    body,
  });
  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      message?: string;
      error_code?: string;
    };
    throw new Error(friendlyApiMessage(errBody.error_code, errBody.message, response.status));
  }
  return (await response.json()) as ReportItem;
}

/** Authenticated blob URL for inline PDF/image preview — revoke when done. */
export async function fetchDocumentFileBlob(documentId: string): Promise<{ blob: Blob; contentType: string }> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}/file`, {
    headers,
  });
  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      message?: string;
      error_code?: string;
    };
    throw new Error(friendlyApiMessage(errBody.error_code, errBody.message, response.status));
  }
  const blob = await response.blob();
  const contentType = response.headers.get("content-type") || blob.type || "application/octet-stream";
  return { blob, contentType };
}

export interface PolicySummary {
  policy_id: string;
  title: string;
  payer_name: string;
  procedure: string;
}

export interface OpdIngestResult {
  ingest_id: string;
  patient_id: string;
  encounter_id: string;
  external_patient_id: string;
  document_ids: string[];
  case_id: string | null;
  created: boolean;
  source?: string;
  consent_id?: string | null;
  disclaimer: string;
}

export type OpdIngestBody = {
  mrn?: string;
  external_patient_id?: string;
  visit_number?: string;
  encounter_id?: string;
  facility_name?: string;
  department?: string;
  visit_type?: "outpatient" | "ambulatory" | "telehealth" | "day_care";
  attending_provider?: string;
  display_name?: string;
  sex?: string;
  birth_date?: string;
  chief_complaint?: string;
  history_of_present_illness?: string;
  assessment_and_plan?: string;
  note?: string;
  diagnoses?: { display: string; code?: string; code_system?: string }[];
  vitals?: { name: string; value: string; unit?: string }[];
  labs: { test_name: string; value: string; unit: string; loinc_code?: string }[];
  medications: {
    name: string;
    status: "active" | "discontinued";
    dose?: string;
    frequency?: string;
    route?: string;
  }[];
  procedure: string;
  policy_id?: string;
  patient_id?: string;
  source?: "opd_manual" | "opd_export" | "his_export" | "fhir_r4" | "hl7_mapped";
  synthetic: boolean;
  consent_attested: boolean;
  consent_id?: string;
  consent?: ConsentInput;
};

export function getPolicies(): Promise<{ policies: PolicySummary[]; total: number }> {
  return request("/api/v1/policies");
}

export function ingestOpdPacket(body: OpdIngestBody): Promise<OpdIngestResult> {
  return request("/api/v1/opd/ingest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface DocumentExtractResult {
  document_kind: "lab_report" | "prescription" | "clinical_note" | "unknown";
  extraction_method: "heuristic" | "llm" | "llm_vision";
  media_kind: "pdf" | "text" | "image";
  filename?: string | null;
  page_count?: number;
  chief_complaint?: string;
  history_of_present_illness?: string;
  assessment_and_plan?: string;
  note?: string;
  procedure?: string;
  diagnoses?: { display: string; code?: string }[];
  labs?: { test_name: string; value: string; unit?: string }[];
  medications?: {
    name: string;
    dose?: string;
    frequency?: string;
    route?: string;
    status?: "active" | "discontinued";
  }[];
  vitals?: { name: string; value: string; unit?: string }[];
  source_excerpt?: string;
  warnings?: string[];
  disclaimer?: string;
}

/** AI/heuristic extract from PDF/image/text — does not write the chart. */
export async function extractOpdDocument(
  file: File,
  documentKind: "auto" | "lab_report" | "prescription" | "clinical_note" = "auto",
): Promise<DocumentExtractResult> {
  const token = await getAccessToken();
  const body = new FormData();
  body.append("file", file);
  body.append("document_kind", documentKind);
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch("/api/v1/opd/extract", {
    method: "POST",
    headers,
    body,
  });
  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      message?: string;
      error_code?: string;
    };
    throw new Error(friendlyApiMessage(errBody.error_code, errBody.message, response.status));
  }
  return (await response.json()) as DocumentExtractResult;
}

export interface HospitalPipelineRun {
  run_id: string;
  status: "ok" | "error";
  source: string;
  patient_id?: string | null;
  case_id?: string | null;
  encounter_id?: string | null;
  ingest_id?: string | null;
  readiness_percent?: number | null;
  gap_count?: number | null;
  auto_prepared?: boolean;
  detail?: string;
  ts?: number;
  document_ids?: string[];
  created?: boolean | null;
  disclaimer?: string;
}

export interface HospitalPipelineStatus {
  pipeline: string;
  mode: string;
  realtime: boolean;
  auto_prepare_supported: boolean;
  simulate_allowed?: boolean;
  phi_live?: boolean;
  recent_ok: number;
  recent_total: number;
  runs: HospitalPipelineRun[];
  disclaimer: string;
}

export function getHospitalPipelineStatus(): Promise<HospitalPipelineStatus> {
  return request("/api/v1/hospital/pipeline/status");
}

export function simulateHospitalVisit(body?: {
  patient_id?: string;
  policy_id?: string;
}): Promise<HospitalPipelineRun> {
  return request("/api/v1/hospital/pipeline/simulate", {
    method: "POST",
    body: JSON.stringify({
      patient_id: body?.patient_id || "PAT-000001",
      policy_id: body?.policy_id || "POL-000001",
      auto_prepare: true,
    }),
  });
}

export function ingestOpdFhir(body: {
  bundle: Record<string, unknown>;
  procedure?: string;
  policy_id?: string;
  synthetic: boolean;
  consent_attested: boolean;
  consent_id?: string;
  consent?: ConsentInput;
  patient_id?: string;
}): Promise<OpdIngestResult> {
  return request("/api/v1/opd/ingest/fhir", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface EssentialsSection {
  key: string;
  label: string;
  status: "present" | "thin" | "missing" | "unknown";
  count: number;
  highlights: string[];
  action: string;
  tab: string;
  note: string;
}

export interface PatientEssentials {
  patient_id: string;
  display_name: string;
  completeness_percent: number;
  sections: EssentialsSection[];
  missing_keys: string[];
  next_actions: string[];
  doctor_brief: string;
  disclaimer: string;
}

export function getPatientEssentials(patientId: string): Promise<PatientEssentials> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/essentials`);
}

export interface HelpTopic {
  id: string;
  title: string;
  prompt: string;
}

export interface HelpChatReply {
  reply: string;
  matched_topic: string | null;
  suggested_links: string[];
  context_used?: string[];
  disclaimer: string;
}

export function getHelpTopics(): Promise<{ topics: HelpTopic[] }> {
  return request("/api/v1/help/topics");
}

export function askHelp(
  message: string,
  pathname?: string,
  options?: {
    patient_id?: string;
    case_id?: string;
    policy_id?: string;
    history?: { role: "user" | "assistant"; content: string }[];
  },
): Promise<HelpChatReply> {
  return request("/api/v1/help/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      pathname: pathname || undefined,
      patient_id: options?.patient_id,
      case_id: options?.case_id,
      policy_id: options?.policy_id,
      history: options?.history?.slice(-6),
    }),
  });
}

/* ---------- Legal notices / emergency card / share / family / doctor brief ---------- */

export interface LegalNotice {
  id: string;
  notice_version: string;
  language: string;
  format: string;
  body: string;
}

export function getLegalNotice(id: string, lang = "en"): Promise<LegalNotice> {
  return request(`/api/v1/legal/notices/${encodeURIComponent(id)}?lang=${encodeURIComponent(lang)}`);
}

export interface EmergencyCard {
  patient_id: string;
  display_name: string;
  sex: string;
  date_of_birth: string;
  blood_group: string;
  allergies: string[];
  conditions: string[];
  medications: { name: string; dose: string; status: string }[];
  implants: string;
  emergency_contacts: { name?: string; phone?: string; relation?: string }[];
  notes: string;
  show_on_lock_screen: boolean;
  qr_payload: string;
  disclaimer: string;
}

export function getMyEmergencyCard(): Promise<EmergencyCard> {
  return request("/api/v1/me/emergency-card");
}

export function patchMyEmergencyCard(body: Partial<EmergencyCard>): Promise<EmergencyCard> {
  return request("/api/v1/me/emergency-card", { method: "PATCH", body: JSON.stringify(body) });
}

export function getPatientEmergencyCard(patientId: string): Promise<EmergencyCard> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/emergency-card`);
}

export interface RecordShare {
  share_id: string;
  label: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  view_count: number;
  last_viewed_at: string | null;
  created_at: string | null;
  token?: string | null;
  path?: string | null;
}

export function listMyShares(): Promise<{ shares: RecordShare[] }> {
  return request("/api/v1/me/shares");
}

export function createMyShare(body: {
  scopes: string[];
  hours: number;
  label?: string;
}): Promise<RecordShare> {
  return request("/api/v1/me/shares", { method: "POST", body: JSON.stringify(body) });
}

export function revokeMyShare(shareId: string): Promise<RecordShare> {
  return request(`/api/v1/me/shares/${encodeURIComponent(shareId)}`, { method: "DELETE" });
}

export function getPublicShare(token: string): Promise<Record<string, unknown>> {
  return request(`/api/v1/share/${encodeURIComponent(token)}`);
}

export interface CareRelationship {
  relationship_id: string;
  related_display_name: string;
  relationship_type: string;
  related_patient_code: string | null;
  access_level: string;
  created_at: string | null;
}

export function listMyFamily(): Promise<{ relationships: CareRelationship[] }> {
  return request("/api/v1/me/family");
}

export function createMyFamily(body: {
  related_display_name: string;
  relationship_type: string;
  related_patient_code?: string;
  access_level?: string;
}): Promise<CareRelationship> {
  return request("/api/v1/me/family", { method: "POST", body: JSON.stringify(body) });
}

export interface DoctorBrief {
  patient_id: string;
  display_name: string;
  brief_lines: { text: string; source: string }[];
  risk_flags: { kind: string; label: string; source: string }[];
  medications: {
    medications: { name: string; dose: string; status: string; generic_key: string }[];
    duplicate_groups: { generic_key: string; names: string[] }[];
    disclaimer: string;
  };
  completeness_percent: number;
  disclaimer: string;
}

export function getDoctorBrief(patientId: string): Promise<DoctorBrief> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/doctor-brief`);
}

export function askChart(patientId: string, question: string): Promise<{
  patient_id: string;
  question: string;
  answers: { text: string; source: string }[];
  disclaimer: string;
}> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/chart-ask`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function getAbdmStatus(): Promise<{ status: string; message: string; sandbox: boolean }> {
  return request("/api/v1/abdm/status");
}

/* ---------- Consent records & patient rights (DPDP / HIPAA) ---------- */

export type ConsentPurpose = "prior_auth_evidence" | "continuity_of_care" | "research_trial";
export type ConsentMethod = "written" | "electronic" | "verbal_witnessed";

export interface ConsentInput {
  purpose: ConsentPurpose;
  method: ConsentMethod;
  notice_version: string;
  granted_by_name: string;
  language?: string;
  scope?: string;
  evidence_ref?: string;
  granted_at?: string;
  expires_at?: string;
}

export interface ConsentRecord {
  consent_id: string;
  patient_id: string;
  purpose: string;
  scope: string;
  method: string;
  language: string;
  notice_version: string;
  granted_by_name: string;
  recorded_by: string;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_reason: string;
  evidence_ref: string;
  created_at: string;
  active: boolean;
}

export interface ConsentList {
  patient_id: string;
  consents: ConsentRecord[];
  total: number;
}

export function listConsents(patientId: string): Promise<ConsentList> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/consents`);
}

export function recordConsent(patientId: string, body: ConsentInput): Promise<ConsentRecord> {
  return request(`/api/v1/patients/${encodeURIComponent(patientId)}/consents`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function revokeConsent(
  patientId: string,
  consentId: string,
  reason: string,
): Promise<ConsentRecord> {
  const path =
    `/api/v1/patients/${encodeURIComponent(patientId)}` +
    `/consents/${encodeURIComponent(consentId)}/revoke`;
  return request(path, { method: "POST", body: JSON.stringify({ reason }) });
}

/** Consent policy for visit ingest: "stored_required" on attested PHI desks. */
export interface ConsentCapabilities {
  phi_live: boolean;
  consent_mode: "stored_required" | "attestation";
}

export async function getConsentCapabilities(): Promise<ConsentCapabilities> {
  try {
    const response = await fetch("/api/v1/auth/capabilities");
    if (!response.ok) {
      return { phi_live: false, consent_mode: "attestation" };
    }
    const body = (await response.json()) as Partial<ConsentCapabilities>;
    return {
      phi_live: Boolean(body.phi_live),
      consent_mode: body.consent_mode === "stored_required" ? "stored_required" : "attestation",
    };
  } catch {
    return { phi_live: false, consent_mode: "attestation" };
  }
}

export interface AccessLogEntry {
  event_id: string;
  occurred_at: string;
  actor_label: string;
  actor_category:
    | "you"
    | "care_team"
    | "care_team_emergency"
    | "system"
    | "other_patient"
    | "unknown";
  action: string;
  action_label: string;
  outcome: "allowed" | "denied";
}

export interface AccessLog {
  patient_id: string;
  total: number;
  limit: number;
  offset: number;
  entries: AccessLogEntry[];
  disclaimer: string;
}

export function getMyAccessLog(options?: { limit?: number; offset?: number }): Promise<AccessLog> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 20));
  params.set("offset", String(options?.offset ?? 0));
  return request(`/api/v1/me/access-log?${params.toString()}`);
}

/** Full JSON copy of the signed-in patient's own record. */
export function getMyExport(): Promise<Record<string, unknown> & { generated_at: string }> {
  return request("/api/v1/me/export");
}

export type DataSubjectRequestType = "correction" | "erasure" | "grievance" | "nominee";

export interface DataSubjectRequest {
  request_id: string;
  patient_id: string;
  request_type: string;
  details: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string;
  outcome: string;
  handled_by: string | null;
}

export function getMyRequests(): Promise<{ total: number; requests: DataSubjectRequest[] }> {
  return request("/api/v1/me/requests");
}

export function createMyRequest(body: {
  request_type: DataSubjectRequestType;
  details: string;
}): Promise<DataSubjectRequest> {
  return request("/api/v1/me/requests", { method: "POST", body: JSON.stringify(body) });
}
