"""India TPA desk API contract (docs/TPA_DESK_CONTRACT.md). Add fields; never rename/remove."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PayerType = Literal["insurer", "tpa", "pmjay", "cghs", "self_pay"]
AdmissionType = Literal["planned", "emergency"]
Stage = Literal[
    "draft",
    "ready_to_send",
    "sent",
    "query",
    "approved",
    "enhancement",
    "discharge_pending",
    "discharge_sent",
    "closed",
]
StageAction = Literal[
    "mark_sent",
    "record_query",
    "answer_query",
    "record_approval",
    "request_enhancement",
    "start_discharge",
    "mark_discharge_sent",
    "close",
]
ItemStatus = Literal["SUPPORTED", "MISSING", "UNKNOWN", "NOT_SUPPORTED"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- requests


class _CaseFieldsBase(_Request):
    tpa_name: str | None = Field(default=None, max_length=160)
    policy_number: str | None = Field(default=None, max_length=64)
    admitted_at: datetime | None = None
    expected_discharge_at: datetime | None = None
    treating_doctor: str | None = Field(default=None, max_length=160)
    provisional_diagnosis: str | None = Field(default=None, max_length=300)
    icd10_code: str | None = Field(default=None, max_length=16)
    estimated_cost_inr: int | None = Field(default=None, ge=0, le=1_000_000_000)
    # Contract additions: cost estimate lines and extra pre-auth form fields (merged).
    cost_breakdown_inr: dict[str, int | None] | None = None
    form_extra: dict[str, Any] | None = None


class DeskCaseFields(_CaseFieldsBase):
    """Editable case fields (PATCH). Stage and clock fields are not editable."""

    payer_type: PayerType | None = None
    insurer_name: str | None = Field(default=None, max_length=160)
    admission_type: AdmissionType | None = None
    proposed_treatment: str | None = Field(default=None, max_length=300)


class DeskCaseCreate(_CaseFieldsBase):
    patient_id: str = Field(pattern=r"^PAT-\d{6}$")
    policy_id: str | None = Field(default=None, pattern=r"^POL-\d{6}$")
    payer_type: PayerType
    insurer_name: str = Field(min_length=1, max_length=160)
    admission_type: AdmissionType = "planned"
    proposed_treatment: str = Field(min_length=3, max_length=300)


class DeskStageRequest(_Request):
    action: StageAction
    text: str | None = Field(default=None, max_length=2000)
    response_due_hours: float | None = Field(default=None, gt=0, le=336)
    query_id: str | None = Field(default=None, pattern=r"^Q-\d{6}$")
    response: str | None = Field(default=None, max_length=4000)
    approved_amount_inr: int | None = Field(default=None, gt=0, le=1_000_000_000)
    revised_estimate_inr: int | None = Field(default=None, gt=0, le=1_000_000_000)
    reason: str | None = Field(default=None, max_length=500)
    override_reason: str | None = Field(default=None, max_length=500)
    raised_by: str | None = Field(default=None, max_length=120)


# --------------------------------------------------------------------------- responses


class DeskClock(_Response):
    kind: Literal["query_response", "insurer_decision", "final_approval", "prep", "none"]
    label: str
    due_at: datetime | None = None
    minutes_left: int | None = None
    overdue: bool = False


class DeskCitation(_Response):
    document_id: str
    chunk_id: str
    source: str = ""
    excerpt: str = ""
    date: datetime | None = None


class DeskWorklistItem(_Response):
    case_id: str
    patient_id: str
    patient_name: str
    mrn: str
    age: int | None = None
    sex: str = ""
    payer_type: PayerType | None = None
    insurer_name: str = ""
    tpa_name: str = ""
    policy_last4: str = ""
    proposed_treatment: str = ""
    estimated_cost_inr: int | None = None
    approved_amount_inr: int | None = None
    stage: Stage
    stage_label: str
    readiness_percent: int
    readiness_label: str = ""
    open_items: int
    open_queries: int = 0
    clock: DeskClock
    assigned_to: str | None = None
    updated_at: datetime | None = None


class DeskWorklistResponse(_Response):
    items: list[DeskWorklistItem]
    total: int
    counts: dict[str, int]


class DeskCaseOut(_Response):
    case_id: str
    patient_id: str
    policy_id: str = ""
    checklist_title: str = ""
    procedure: str = ""
    payer_type: PayerType | None = None
    insurer_name: str = ""
    tpa_name: str = ""
    policy_number: str = ""
    policy_last4: str = ""
    admission_type: AdmissionType = "planned"
    admitted_at: datetime | None = None
    expected_discharge_at: datetime | None = None
    treating_doctor: str = ""
    provisional_diagnosis: str = ""
    icd10_code: str = ""
    proposed_treatment: str = ""
    estimated_cost_inr: int | None = None
    approved_amount_inr: int | None = None
    stage: Stage
    stage_label: str
    clock: DeskClock
    sent_at: datetime | None = None
    decision_due_at: datetime | None = None
    approved_at: datetime | None = None
    discharge_requested_at: datetime | None = None
    final_due_at: datetime | None = None
    revised_estimate_inr: int | None = None
    enhancement_reason: str = ""
    enhancement_requested_at: datetime | None = None
    enhancement_count: int = 0
    discharge_override_reason: str = ""
    closed_at: datetime | None = None
    cost_breakdown_inr: dict[str, Any] = {}
    form_extra: dict[str, Any] = {}
    assigned_to: str | None = None
    last_run_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeskPatientOut(_Response):
    patient_id: str
    name: str
    mrn: str
    age: int | None = None
    sex: str = ""


class DeskReadinessOut(_Response):
    percent: int
    required: int
    supported: int
    missing: int
    unknown: int
    not_supported: int
    label: str


class DeskChecklistItem(_Response):
    item_id: str
    group: Literal["form", "clinical", "documents"]
    label: str
    status: ItemStatus
    required: bool
    reason: str = ""
    fix_hint: str = ""
    citations: list[DeskCitation] = []


class DeskQueryOut(_Response):
    query_id: str
    raised_at: datetime | None = None
    text: str
    response_due_at: datetime | None = None
    responded_at: datetime | None = None
    response: str = ""
    raised_by: str = ""
    responded_by: str = ""


class DeskTimelineEvent(_Response):
    at: datetime
    event: str
    actor_label: str = ""


class DeskReviewOut(_Response):
    state: Literal["not_started", "awaiting_senior", "acknowledged", "needs_documentation"]
    by_label: str = ""
    at: datetime | None = None
    notes: str = ""
    # Review run to resume via POST /authorization/review/{run_id}/resume (senior only).
    run_id: str = ""


class DeskWorkspaceResponse(_Response):
    case: DeskCaseOut
    patient: DeskPatientOut
    readiness: DeskReadinessOut
    checklist: list[DeskChecklistItem]
    queries: list[DeskQueryOut]
    timeline: list[DeskTimelineEvent]
    review: DeskReviewOut
    payer_label: str = ""
    disclaimer: str


class DeskFormField(_Response):
    key: str
    label: str
    value: str | None = None
    source: Literal["chart", "case", "missing"]
    required: bool
    # v1.2: flag next to the value (e.g. implant cost without a quotation on file) and
    # a staff hint (e.g. "Confirm before printing" for chart-derived investigations).
    warning: str | None = None
    hint: str | None = None


class DeskChecklistOpenItem(_Response):
    item_id: str
    label: str
    group: str
    status: str


class DeskFormSection(_Response):
    title: str
    fields: list[DeskFormField]


class DeskAttachment(_Response):
    label: str
    status: Literal["SUPPORTED", "MISSING"]
    required: bool = True
    citations: list[DeskCitation] = []


class DeskPreauthFormResponse(_Response):
    form_version: str
    case_id: str = ""
    sections: list[DeskFormSection]
    missing_required: list[str]
    checklist_open: list[DeskChecklistOpenItem] = []
    attachments: list[DeskAttachment]
    disclaimer: str = ""


class DeskFinding(_Response):
    severity: Literal["blocker", "warning", "info"]
    code: str
    message: str
    expected: str | None = None
    found: str | None = None
    citations: list[DeskCitation] = []


class DeskDischargeCheckResponse(_Response):
    status: Literal["ok", "warnings", "blockers"]
    findings: list[DeskFinding]


class DeskStatsResponse(_Response):
    overdue: int
    due_within_60m: int
    queries_open: int
    ready_to_send: int
    awaiting_senior: int
    median_prep_minutes: int | None = None
    total_cases: int = 0
