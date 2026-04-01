from datetime import datetime

from pydantic import BaseModel, Field


class SafetySignal(BaseModel):
    name: str
    weight: float
    evidence: str


class SafetyCaseRecord(BaseModel):
    record_index: int
    source_url: str
    title: str | None = None
    risk_score: float
    risk_band: str = "low"
    signals: list[SafetySignal]
    media_hashes: list[str] = []


class SafetyCase(BaseModel):
    case_id: str
    status: str = "open"
    job_id: str
    title: str
    notes: str | None = None
    created_at: datetime
    total_records_evaluated: int
    flagged_records_count: int
    average_risk_score: float
    highest_risk_band: str = "low"
    submission_checklist: list["SafetyCaseReportChecklistItem"] = Field(default_factory=list)
    signoff: "SafetyCaseReportSignoff | None" = None
    records: list[SafetyCaseRecord]


class SafetyCaseSummary(BaseModel):
    case_id: str
    status: str
    job_id: str
    title: str
    created_at: datetime
    flagged_records_count: int
    average_risk_score: float
    highest_risk_band: str = "low"
    checklist_completed_count: int = 0
    checklist_total_count: int = 0
    signoff_approved: bool = False
    signoff_reviewer_id: str | None = None
    destination_channel: str | None = None
    signoff_approved_at: datetime | None = None


class SafetyCaseCreateFromJobRequest(BaseModel):
    job_id: str
    title: str | None = None
    notes: str | None = None
    record_limit: int = Field(default=100, ge=1, le=1000)
    min_risk_score: float = Field(default=0.45, ge=0.0, le=1.0)


class SafetyPersonaTemplate(BaseModel):
    template_id: str
    purpose: str
    message: str


class SafetyPersonaEscalationRule(BaseModel):
    rule_id: str
    trigger: str
    severity: str
    action: str


class SafetyPersonaRiskBand(BaseModel):
    label: str
    min_score: float = Field(ge=0.0, le=1.0)
    max_score: float = Field(ge=0.0, le=1.0)
    guidance: str


class SafetyPersonaSpec(BaseModel):
    persona_id: str
    display_name: str
    profile_bio: str
    disclosure: str
    interaction_principles: list[str]
    first_message_templates: list[SafetyPersonaTemplate]
    hard_stop_rules: list[str]
    escalation_rules: list[SafetyPersonaEscalationRule]
    risk_rubric: dict[str, float]
    risk_bands: list[SafetyPersonaRiskBand]
    evidence_requirements: list[str]


class SafetyCaseReportEvidenceItem(BaseModel):
    record_index: int
    source_url: str
    title: str | None = None
    risk_score: float
    risk_band: str
    signal_names: list[str]
    evidence_terms: list[str]
    media_hashes: list[str]


class SafetyCaseReportSummary(BaseModel):
    case_id: str
    job_id: str
    title: str
    status: str
    created_at: datetime
    flagged_records_count: int
    average_risk_score: float
    highest_risk_band: str


class SafetyCaseReportChecklistItem(BaseModel):
    item_id: str
    label: str
    completed: bool = False
    notes: str | None = None


class SafetyCaseReportSignoff(BaseModel):
    reviewer_id: str | None = None
    approved: bool = False
    approved_at: datetime | None = None
    destination_channel: str | None = None


class SafetyCaseReportChecklistUpdate(BaseModel):
    item_id: str = Field(min_length=1)
    completed: bool | None = None
    notes: str | None = None


class SafetyCaseReportSignoffUpdate(BaseModel):
    reviewer_id: str | None = None
    approved: bool | None = None
    destination_channel: str | None = None


class SafetyCaseReportWorkflowUpdateRequest(BaseModel):
    checklist_updates: list[SafetyCaseReportChecklistUpdate] = Field(default_factory=list)
    signoff: SafetyCaseReportSignoffUpdate | None = None


class SafetyCaseReportWorkflowState(BaseModel):
    case_id: str
    submission_checklist: list[SafetyCaseReportChecklistItem]
    signoff: SafetyCaseReportSignoff


class SafetyCaseBulkWorkflowUpdateRequest(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    workflow: SafetyCaseReportWorkflowUpdateRequest


class SafetyCaseBulkWorkflowUpdateResult(BaseModel):
    updated_case_ids: list[str] = Field(default_factory=list)
    missing_case_ids: list[str] = Field(default_factory=list)


class SafetyCaseReportPackage(BaseModel):
    report_id: str
    generated_at: datetime
    reviewer: str | None = None
    case_summary: SafetyCaseReportSummary
    legal_notice: str
    chain_of_custody: list[str]
    submission_checklist: list[SafetyCaseReportChecklistItem]
    signoff: SafetyCaseReportSignoff
    evidence_manifest: list[SafetyCaseReportEvidenceItem]
