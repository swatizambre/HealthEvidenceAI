"""Typed API contracts. Request models reject undeclared fields."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from fastapi import Path
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.safety import AUTONOMOUS_DECISION_VALUES

PatientPath = Annotated[str, Path(pattern=r"^PAT-\d{6}$")]
PolicyPath = Annotated[str, Path(pattern=r"^POL-\d{6}$")]
DocumentPath = Annotated[str, Path(pattern=r"^DOC-[A-Z0-9]+$")]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ErrorResponse(ResponseModel):
    error_code: str
    message: str
    request_id: str


class HealthResponse(ResponseModel):
    status: Literal["ok"]


class ReadyResponse(ResponseModel):
    status: Literal["ok", "not_ready"]
    database: Literal["ok", "error"]
    detail: str = ""
    environment: str = ""
    auth_mode: str = ""
    org_scope: bool = False
    hospital_mode: str = ""
    phi_live: bool = False
    oidc_configured: bool = False
    seed_on_startup: bool = False
    # demo | trial | practice — drives the UI banner; never includes secrets.
    mode: str = ""
    trial_site_org_code: str = ""
    trial_end_date: str = ""
    banner: str = ""


class BreakGlassRequest(APIModel):
    patient_id: str = Field(pattern=r"^PAT-\d{6}$")
    reason: str = Field(min_length=10, max_length=500)


class BreakGlassResponse(ResponseModel):
    break_glass_id: str
    patient_id: str
    actor: str
    reason: str
    expires_in_seconds: int = 3600
    disclaimer: str


class Demographics(ResponseModel):
    patient_id: str
    synthetic_name: str
    date_of_birth: date
    sex: str


class MedicationOut(ResponseModel):
    medication_id: str
    name: str
    dose: str
    status: str
    started_at: datetime


class LabOut(ResponseModel):
    lab_id: str
    test_name: str
    value: str
    unit: str
    collected_at: datetime


class ProcedureOut(ResponseModel):
    procedure_id: str
    name: str
    performed_at: datetime


class ImagingOut(ResponseModel):
    imaging_id: str
    modality: str
    body_part: str
    study_date: datetime
    description: str


class NoteOut(ResponseModel):
    note_id: str
    note_type: str
    content: str
    authored_at: datetime
    document_id: str


class ClaimOut(ResponseModel):
    claim_id: str
    status: str
    amount_cents: int
    service_date: datetime


class PatientSummary(ResponseModel):
    patient_id: str
    synthetic_name: str
    date_of_birth: date
    sex: str
    conditions: list[str]


class PatientListResponse(ResponseModel):
    patients: list[PatientSummary]
    total: int


class PatientDetail(ResponseModel):
    patient_id: str
    demographics: Demographics
    conditions: list[str]
    medications: list[MedicationOut]
    labs: list[LabOut]
    procedures: list[ProcedureOut]
    imaging: list[ImagingOut]
    clinical_notes: list[NoteOut]
    claims: list[ClaimOut]


class TimelineEvent(ResponseModel):
    event_id: str
    event_type: str
    timestamp: datetime
    source: str
    description: str
    classification: Literal["FACT"] = "FACT"
    specialty: str = "General medicine"
    facility_name: str = ""
    document_id: str | None = None
    title: str = ""


class TimelineResponse(ResponseModel):
    patient_id: str
    events: list[TimelineEvent]


class LifelongEventOut(ResponseModel):
    event_id: str
    category: str
    title: str
    summary: str
    occurred_on: date | None = None
    facility_name: str = ""
    specialty: str = "General medicine"
    body_site: str = "Unspecified"
    disorders: list[str] = []
    source: str = ""
    why_it_matters: str = ""
    demo_synthetic: bool = False


class LifelongGroupOut(ResponseModel):
    key: str
    label: str
    count: int
    events: list[LifelongEventOut]


class LifelongSummaryResponse(ResponseModel):
    patient_id: str
    patient_name: str
    facilities_count: int
    facilities: list[str]
    specialties: list[str] = []
    specialties_count: int = 0
    body_sites: list[str] = []
    body_sites_count: int = 0
    disorders: list[str] = []
    disorders_count: int = 0
    events: list[LifelongEventOut]
    by_facility: list[LifelongGroupOut] = []
    by_specialty: list[LifelongGroupOut] = []
    by_body_site: list[LifelongGroupOut] = []
    by_disorder: list[LifelongGroupOut] = []
    doctor_brief: str
    patient_brief: str = ""
    includes_demo_synthetic: bool = False
    demo_synthetic_disclaimer: str = ""


class CriterionOut(ResponseModel):
    criterion_id: str
    description: str
    position: int


class PolicySummary(ResponseModel):
    policy_id: str
    title: str
    payer_name: str
    procedure: str


class PolicyListResponse(ResponseModel):
    policies: list[PolicySummary]
    total: int


class PolicyDetail(PolicySummary):
    version: str
    content: str
    document_id: str
    criteria: list[CriterionOut]


class DocumentOut(ResponseModel):
    document_id: str
    patient_id: str | None
    document_type: str
    source: str
    created_at: datetime
    content: str
    metadata: dict[str, str | int | float | bool]
    chunk_count: int


class DocumentListResponse(ResponseModel):
    documents: list[DocumentOut]


class DocumentCreate(APIModel):
    document_type: Literal["clinical_note", "policy", "lab_result"]
    source: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
    patient_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_patient(self) -> Self:
        if self.patient_id is not None and re.fullmatch(r"PAT-\d{6}", self.patient_id) is None:
            raise ValueError("patient_id is invalid")
        if self.document_type == "clinical_note" and self.patient_id is None:
            raise ValueError("patient_id is required for clinical notes")
        return self


class EvidenceSearchRequest(APIModel):
    query: str = Field(min_length=3, max_length=1000)
    patient_id: str | None = Field(default=None, pattern=r"^PAT-\d{6}$")
    document_type: Literal["clinical_note", "lab_result", "policy"] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SourceRef(ResponseModel):
    document_id: str
    chunk_id: str
    document_type: str
    score: float


class EvidenceSearchResponse(ResponseModel):
    answer: str
    sources: list[SourceRef]


class AuthorizationReviewRequest(APIModel):
    patient_id: str = Field(pattern=r"^PAT-\d{6}$")
    policy_id: str = Field(pattern=r"^POL-\d{6}$")
    procedure: str = Field(min_length=3, max_length=200)
    case_id: str | None = Field(default=None, pattern=r"^PA-\d{6}$")
    # When true, pause at human_review instead of auto-acking.
    interactive: bool = False

    @field_validator("procedure")
    @classmethod
    def procedure_is_not_a_decision(cls, value: str) -> str:
        if value.upper() in AUTONOMOUS_DECISION_VALUES:
            raise ValueError("Procedure must describe a service, not a clinical decision.")
        return value


class EvidenceRef(ResponseModel):
    document_id: str
    chunk_id: str
    source: str
    text_reference: str


class CriterionResult(ResponseModel):
    criterion_id: str
    criterion: str
    status: Literal["SUPPORTED", "NOT_SUPPORTED", "MISSING", "UNKNOWN"]
    evidence: list[EvidenceRef]
    reason: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class ContradictionOut(ResponseModel):
    criterion: str
    description: str
    evidence: list[EvidenceRef]
    conflict: bool = True
    evidence_a: str = ""
    evidence_b: str = ""
    resolution: str = "human_review"


class AgentTraceStep(ResponseModel):
    agent: str
    node: str
    detail: str = ""
    status: str = "ok"


class PathwayStepOut(ResponseModel):
    step: int
    title: str
    detail: str = ""
    agent: str = ""
    focus: str = ""
    priority: str = "info"
    criterion_id: str = ""
    confidence: float | None = None


class ReadinessScorecardOut(ResponseModel):
    handoff_readiness_percent: int = 0
    checklist_supported_ratio: float = 0.0
    supported_count: int = 0
    open_count: int = 0
    conflict_count: int = 0
    documentation_risk: Literal["low", "moderate", "high"] = "moderate"
    blockers: list[str] = []
    critic_flags: list[str] = []
    pace_note: str = ""
    recommendation: str = ""
    disclaimer: str = ""


class SeniorAssistFocusIn(APIModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=800)
    severity: str = Field(default="moderate", max_length=32)


class SeniorAssistSnapshot(APIModel):
    """Senior-edited AI review brief persisted with HITL resume (desk coaching only)."""

    briefing: str = Field(default="", max_length=1200)
    focus_items: list[SeniorAssistFocusIn] = Field(default_factory=list, max_length=12)
    suggested_clinician_note: str = Field(default="", max_length=2000)
    recommended_desk_action: str = Field(default="", max_length=64)
    recommended_desk_action_label: str = Field(default="", max_length=120)
    source: str = Field(default="", max_length=64)
    edited: bool = False


class AuthorizationReviewResponse(ResponseModel):
    case_id: str | None
    patient_id: str
    policy_id: str
    procedure: str
    review_type: Literal["evidence_review"]
    criteria: list[CriterionResult]
    missing_evidence: list[str]
    contradictions: list[ContradictionOut]
    human_review_required: bool
    awaiting_human_review: bool = False
    evidence_coverage: Literal["NONE", "AVAILABLE", "COMPLETE"]
    citations: list[EvidenceRef]
    disclaimer: str
    run_id: str = ""
    trace_id: str = ""
    scoring_path: str = ""
    report_summary: str = ""
    human_review_reason: str = ""
    agent_trace: list[AgentTraceStep] = []
    observability: list[dict[str, object]] = []
    evidence_panel: list[dict[str, object]] = []
    critic_summary: str = ""
    critic_notes: list[str] = []
    documentation_pathway: list[PathwayStepOut] = []
    pathway_summary: str = ""
    readiness_scorecard: ReadinessScorecardOut | None = None
    senior_assist: SeniorAssistSnapshot | None = None


class HumanReviewResumeRequest(APIModel):
    decision: Literal["acknowledged", "needs_documentation"] = "acknowledged"
    notes: str = Field(default="", max_length=2000)
    senior_assist: SeniorAssistSnapshot | None = None


class PacketPrepareRequest(APIModel):
    patient_id: str = Field(pattern=r"^PAT-\d{6}$")
    policy_id: str = Field(pattern=r"^POL-\d{6}$")
    procedure: str | None = Field(default=None, min_length=3, max_length=200)
    case_id: str | None = Field(default=None, pattern=r"^PA-\d{6}$")

    @field_validator("procedure")
    @classmethod
    def procedure_is_not_a_decision(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.upper() in AUTONOMOUS_DECISION_VALUES:
            raise ValueError("Procedure must describe a service, not a clinical decision.")
        return value


class PacketCriterionOut(ResponseModel):
    criterion_id: str
    criterion: str
    status: Literal["SUPPORTED", "NOT_SUPPORTED", "MISSING", "UNKNOWN"]
    plain_status: str
    reason: str
    citation_count: int = 0


class PacketGapOut(ResponseModel):
    label: str
    focus: str
    action: str
    priority: int = 0
    estimated_minutes: int = 8
    specialty_hint: str = "General medicine"
    draft_suggestion: str = ""
    draft_source: str = "template"
    agent: str = "ClinicalEvidenceAgent"
    evidence_snippets: list[str] = []


class PacketNextActionOut(ResponseModel):
    label: str
    focus: str
    action: str
    specialty_hint: str = "General medicine"
    estimated_minutes: int = 8
    why: str = ""
    draft_suggestion: str = ""
    draft_source: str = "template"


class PacketPrepareResponse(ResponseModel):
    patient_id: str
    case_id: str
    case_created: bool
    policy_id: str
    policy_title: str
    procedure: str
    readiness_percent: int
    evidence_coverage: Literal["NONE", "AVAILABLE", "COMPLETE"]
    human_review_required: bool
    supported_count: int
    gap_count: int
    criteria: list[PacketCriterionOut]
    gaps: list[PacketGapOut]
    specialties: list[str] = []
    next_best_action: PacketNextActionOut | None = None
    estimated_prep_minutes: int = 0
    documentation_risk: Literal["low", "moderate", "high"] = "low"
    documentation_risk_label: str = ""
    citation_strength: Literal["strong", "mixed", "weak"] = "mixed"
    citation_strength_label: str = ""
    packet_summary: str
    next_steps: list[str]
    report_summary: str = ""
    run_id: str = ""
    scoring_path: str = ""
    cycle_elapsed_minutes: int | None = None
    agent_trace: list[AgentTraceStep] = []
    ai_brief: str = ""
    ai_assist: dict[str, object] = Field(default_factory=dict)
    mcp_tools_used: list[str] = []
    critic_summary: str = ""
    documentation_pathway: list[PathwayStepOut] = []
    pathway_summary: str = ""
    readiness_scorecard: ReadinessScorecardOut | None = None
    disclaimer: str


class AuthorizationCaseOut(ResponseModel):
    case_id: str
    patient_id: str
    policy_id: str
    policy_title: str
    procedure: str
    status: Literal[
        "queued",
        "needs_documentation",
        "ready_for_human",
        "closed_as_draft",
    ] = "queued"
    last_run_id: str | None = None
    lifecycle_note: str = ""
    cycle_elapsed_minutes: int | None = None


class AuthorizationCaseListResponse(ResponseModel):
    cases: list[AuthorizationCaseOut]


class StatsResponse(ResponseModel):
    patients: int
    authorization_cases: int
    policies: int
    system_status: Literal["ok"]


class WorklistPatientOut(ResponseModel):
    patient_id: str
    display_name: str
    sex: str
    condition_summary: str
    specialties: list[str] = []


class WorklistCaseOut(ResponseModel):
    case_id: str
    patient_id: str
    procedure: str
    policy_title: str
    policy_id: str = ""
    status: Literal[
        "queued",
        "needs_documentation",
        "ready_for_human",
        "closed_as_draft",
    ] = "queued"
    next_hint: str = ""
    gap_label: str = ""
    gap_focus: str = ""
    specialty_hint: str = ""
    cycle_elapsed_minutes: int | None = None
    sla_minutes: int | None = None
    sla_breached: bool = False
    assigned_to: str | None = None
    assigned_to_me: bool = False


class WorklistResponse(ResponseModel):
    recent_patients: list[WorklistPatientOut]
    open_cases: list[WorklistCaseOut]
    my_cases: list[WorklistCaseOut] = []
    unassigned_cases: list[WorklistCaseOut] = []
    assignment_enabled: bool = True


class CaseAssignRequest(APIModel):
    assigned_to: str | None = Field(
        default=None,
        max_length=120,
        description="JWT subject to assign; omit or null to clear.",
    )


class CaseAssignResponse(ResponseModel):
    case_id: str
    assigned_to: str | None = None
    disclaimer: str


class PacketCycleMetricsOut(ResponseModel):
    sample_size: int
    median_minutes: float | None = None
    p75_minutes: float | None = None
    mean_minutes: float | None = None
    open_aging_sample_size: int = 0
    open_aging_median_minutes: float | None = None
    sla_minutes: int = 240
    sla_breach_count: int = 0
    unit: str = "minutes"
    definition: str = ""


class OpsMetricsResponse(ResponseModel):
    packet_cycle: PacketCycleMetricsOut
    organization_count: int = 0
    allow_phi: bool = False
    disclaimer: str


class OrganizationOut(ResponseModel):
    org_id: str
    org_code: str
    name: str
    facility_type: str
    active: bool = True


class OrganizationListResponse(ResponseModel):
    organizations: list[OrganizationOut]


class GraphNodeOut(ResponseModel):
    id: str
    type: str
    label: str


class GraphEdgeOut(ResponseModel):
    source: str
    target: str
    type: str


class EvidenceGraphResponse(ResponseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    disclaimer: str


class ImagingAnalyzeRequest(APIModel):
    study_id: str = Field(min_length=1, max_length=64)
    modality: str = Field(default="unknown", max_length=64)
    body_part: str = Field(default="unspecified", max_length=120)


class ImagingAnalyzeResponse(ResponseModel):
    study_id: str
    observations: list[str]
    confidence: float
    human_review_required: bool
    disclaimer: str
    backend: str = "monai"


class ImagingCompareRequest(APIModel):
    study_a: str = Field(min_length=1, max_length=64)
    study_b: str = Field(min_length=1, max_length=64)
    metadata_a: dict[str, str] = Field(default_factory=dict)
    metadata_b: dict[str, str] = Field(default_factory=dict)


class ImagingCompareResponse(ResponseModel):
    study_a: str
    study_b: str
    changed: list[str]
    unchanged: list[str]
    uncertain: list[str]
    human_review_required: bool
    disclaimer: str
    backend: str = "monai"


class PermissionCheckRequest(APIModel):
    agent: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=32)
    resource: str = Field(min_length=1, max_length=64)


class PermissionCheckResponse(ResponseModel):
    allowed: bool
    agent: str
    action: str
    resource: str
    reason: str


class PromptInspectRequest(APIModel):
    content: str = Field(min_length=1, max_length=20000)


class PromptInspectResponse(ResponseModel):
    safe: bool
    findings: list[str]
    labeled_content: str


class ToolPatientSummaryResponse(ResponseModel):
    patient_id: str
    conditions: list[str]
    medication_count: int
    lab_count: int
    note_count: int
    disclaimer: str


class McpToolOut(ResponseModel):
    name: str
    permission: str
    description: str
    agents: list[str] = []


class McpToolCatalogResponse(ResponseModel):
    tools: list[McpToolOut]
    agents: list[str]
    disclaimer: str


class McpToolInvokeRequest(APIModel):
    tool_name: str = Field(min_length=1, max_length=64)
    agent: str = Field(default="ClinicalEvidenceAgent", min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpToolInvokeResponse(ResponseModel):
    tool_name: str
    agent: str
    result: dict[str, Any]
    disclaimer: str


class DeskInsightOut(ResponseModel):
    insight_id: str
    severity: Literal["info", "action", "urgent"] = "info"
    title: str
    detail: str
    agent: str = "Orchestrator"
    patient_id: str | None = None
    case_id: str | None = None
    href: str = ""
    cta: str = ""


class DeskInsightsResponse(ResponseModel):
    insights: list[DeskInsightOut]
    agent_fleet: list[str]
    scoring_mode: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    disclaimer: str


class A2AMessageRequest(APIModel):
    sender: str = Field(min_length=1, max_length=64)
    recipient: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    payload: dict[str, object] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=64)


class A2AMessageResponse(ResponseModel):
    request: dict[str, object]
    reply: dict[str, object]


class A2ACapabilitiesResponse(ResponseModel):
    capabilities: dict[str, list[str]]


class DevTokenRequest(APIModel):
    subject: str = Field(default="dev-user", max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["staff"])
    patient_id: str | None = Field(default=None, pattern=r"^PAT-\d{6}$")
    org_id: str | None = Field(default=None, max_length=64)
    org_code: str | None = Field(default=None, max_length=32)


class StreamTicketResponse(ResponseModel):
    ticket: str
    expires_in: int


class DevTokenResponse(ResponseModel):
    access_token: str
    token_type: str = "bearer"
    auth_mode: str = "dev-jwt"
    roles: list[str] = Field(default_factory=list)
    patient_id: str | None = None
    org_id: str | None = None
    org_code: str | None = None


class AuthMeResponse(ResponseModel):
    subject: str
    email: str = ""
    roles: list[str] = Field(default_factory=list)
    product_roles: list[str] = Field(default_factory=list)
    auth_mode: str = "none"
    patient_id: str | None = None
    org_id: str | None = None
    org_code: str | None = None
    demo_signin_allowed: bool = False
    enforce_org_scope: bool = False


class OidcStatusResponse(ResponseModel):
    auth_mode: str
    oidc_ready: bool
    issuer_configured: bool
    jwks_configured: bool
    audience: str = ""
    roles_claim: str = "roles"
    client_id_configured: bool = False
    detail: str = ""
    discovered_jwks_url: str = ""
    discovered_issuer: str = ""


class AuditEventOut(ResponseModel):
    event_id: str
    action: str
    actor: str
    resource_type: str
    resource_id: str
    status: str
    detail: str = ""
    created_at: datetime


class AuditEventListResponse(ResponseModel):
    total: int
    events: list[AuditEventOut]


class OpdLabIn(APIModel):
    test_name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=64)
    unit: str = Field(default="", max_length=64)
    loinc_code: str = Field(default="", max_length=32)
    collected_at: datetime | None = None


class OpdMedicationIn(APIModel):
    name: str = Field(min_length=1, max_length=120)
    status: Literal["active", "discontinued"] = "active"
    dose: str = Field(default="as prescribed", max_length=120)
    frequency: str = Field(default="", max_length=64)
    route: str = Field(default="", max_length=64)
    rxnorm_code: str = Field(default="", max_length=32)


class OpdDiagnosisIn(APIModel):
    display: str = Field(min_length=1, max_length=200)
    code: str = Field(default="", max_length=32)
    code_system: Literal["ICD-10", "SNOMED", "ICD-10-CM", "local", ""] = "ICD-10"


class OpdVitalIn(APIModel):
    name: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=64)
    unit: str = Field(default="", max_length=32)


class OpdIngestRequest(APIModel):
    """Hospital-compatible OPD encounter packet (synthetic / practice use only).

    Field aliases accept common HIS labels (MRN/UHID, visit number) used by
    Epic, Cerner/Oracle Health, Meditech, and regional hospital systems.
    """

    external_patient_id: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices(
            "external_patient_id",
            "mrn",
            "uhid",
            "hospital_patient_id",
            "medical_record_number",
        ),
    )
    encounter_id: str = Field(
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices(
            "encounter_id",
            "visit_id",
            "visit_number",
            "encounter_number",
        ),
    )
    encounter_at: datetime | None = None
    facility_name: str = Field(default="", max_length=120)
    department: str = Field(default="OPD", max_length=80)
    visit_type: Literal["outpatient", "ambulatory", "telehealth", "day_care"] = "outpatient"
    attending_provider: str = Field(default="", max_length=120)
    chief_complaint: str = Field(default="", max_length=500)
    history_of_present_illness: str = Field(default="", max_length=8000)
    assessment_and_plan: str = Field(default="", max_length=8000)
    note: str = Field(default="", max_length=20000)
    diagnoses: list[OpdDiagnosisIn] = Field(default_factory=list, max_length=40)
    vitals: list[OpdVitalIn] = Field(default_factory=list, max_length=40)
    labs: list[OpdLabIn] = Field(default_factory=list, max_length=40)
    medications: list[OpdMedicationIn] = Field(default_factory=list, max_length=40)
    procedure: str = Field(min_length=3, max_length=200)
    policy_id: str | None = Field(default=None, pattern=r"^POL-\d{6}$")
    patient_id: str | None = Field(default=None, pattern=r"^PAT-\d{6}$")
    source: Literal[
        "opd_manual",
        "opd_export",
        "his_export",
        "fhir_r4",
        "hl7_mapped",
    ] = "opd_manual"
    synthetic: bool = True
    consent_attested: bool = False
    sex: str = Field(default="unknown", max_length=16)
    birth_date: date | None = None
    display_name: str = Field(default="", max_length=120)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("procedure")
    @classmethod
    def procedure_is_not_a_decision(cls, value: str) -> str:
        if value.upper() in AUTONOMOUS_DECISION_VALUES:
            raise ValueError("Procedure must describe a service, not a clinical decision.")
        return value

    @model_validator(mode="after")
    def require_clinical_content(self) -> Self:
        has_note = bool(self.note.strip())
        has_structured = bool(
            self.chief_complaint.strip()
            or self.history_of_present_illness.strip()
            or self.assessment_and_plan.strip()
            or self.diagnoses
        )
        if not has_note and not has_structured:
            raise ValueError(
                "Provide a visit note or structured clinical sections "
                "(chief complaint, HPI, assessment/plan, or diagnoses)."
            )
        return self


class OpdFhirIngestRequest(APIModel):
    """FHIR R4 Bundle (or resource set) mapped into an OPD encounter packet."""

    bundle: dict[str, Any]
    procedure: str = Field(default="Evidence pack documentation", min_length=3, max_length=200)
    policy_id: str | None = Field(default=None, pattern=r"^POL-\d{6}$")
    patient_id: str | None = Field(
        default=None,
        pattern=r"^PAT-\d{6}$",
        description="Optional known chart id when the hospital MRN already maps to a patient.",
    )
    synthetic: bool = True
    consent_attested: bool = False


class OpdIngestResponse(ResponseModel):
    ingest_id: str
    patient_id: str
    encounter_id: str
    external_patient_id: str
    document_ids: list[str]
    case_id: str | None
    created: bool
    source: str = "opd_manual"
    disclaimer: str


class HospitalPipelineRunOut(ResponseModel):
    run_id: str
    status: Literal["ok", "error"]
    source: str
    patient_id: str | None = None
    case_id: str | None = None
    encounter_id: str | None = None
    ingest_id: str | None = None
    readiness_percent: int | None = None
    gap_count: int | None = None
    auto_prepared: bool = False
    detail: str = ""
    ts: float = 0
    document_ids: list[str] = Field(default_factory=list)
    created: bool | None = None
    disclaimer: str = ""


class HospitalPipelineStatusOut(ResponseModel):
    pipeline: str
    mode: str
    realtime: bool = True
    auto_prepare_supported: bool = True
    simulate_allowed: bool = True
    phi_live: bool = False
    ai: dict[str, object] = Field(default_factory=dict)
    recent_ok: int = 0
    recent_total: int = 0
    runs: list[HospitalPipelineRunOut] = Field(default_factory=list)
    disclaimer: str


class HospitalSimulateRequest(APIModel):
    patient_id: str = Field(default="PAT-000001", pattern=r"^PAT-\d{6}$")
    policy_id: str = Field(default="POL-000001", pattern=r"^POL-\d{6}$")
    auto_prepare: bool = True


class HospitalHisPipelineRequest(OpdIngestRequest):
    """HIS/interface-engine visit with optional auto evidence-pack prepare."""

    auto_prepare: bool = True


class HospitalFhirPipelineRequest(OpdFhirIngestRequest):
    auto_prepare: bool = True


class EssentialsSectionOut(ResponseModel):
    key: str
    label: str
    status: Literal["present", "thin", "missing", "unknown"]
    count: int = 0
    highlights: list[str] = []
    action: str = ""
    tab: str = "file"
    note: str = ""


class PatientEssentialsResponse(ResponseModel):
    patient_id: str
    display_name: str
    completeness_percent: int
    sections: list[EssentialsSectionOut]
    missing_keys: list[str]
    next_actions: list[str]
    doctor_brief: str
    disclaimer: str


class HelpTopicOut(ResponseModel):
    id: str
    title: str
    prompt: str


class HelpTopicsResponse(ResponseModel):
    topics: list[HelpTopicOut]


class HelpChatRequest(APIModel):
    message: str = Field(min_length=1, max_length=2000)
    pathname: str | None = Field(default=None, max_length=200)
    patient_id: str | None = Field(default=None, pattern=r"^PAT-\d{6}$")
    case_id: str | None = Field(default=None, pattern=r"^PA-\d{6}$")
    policy_id: str | None = Field(default=None, pattern=r"^POL-\d{6}$")


class HelpChatResponse(ResponseModel):
    reply: str
    matched_topic: str | None = None
    suggested_links: list[str] = []
    context_used: list[str] = []
    disclaimer: str