from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class EntityIngestPayload(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=512)
    entity_type: str = Field(default="person")  # person, location, organization, vehicle
    aliases: list[str] = Field(default_factory=list)
    source_name: str = Field(default="unknown", max_length=256)
    extra_metadata: dict = Field(default_factory=dict)


class IngestRequest(BaseModel):
    entities: list[EntityIngestPayload] = Field(min_length=1)
    source_name: str = Field(default="unknown", max_length=256)
    raw_text: str | None = None
    source_url: str | None = None


class IngestResponse(BaseModel):
    job_id: str
    status: str
    entities_queued: int
    resolved_entity_ids: list[str] = Field(default_factory=list)
    disclaimer: str


# ---------------------------------------------------------------------------
# Entity Resolution
# ---------------------------------------------------------------------------


class EntityResolveResult(BaseModel):
    entity_id: str
    canonical_name: str
    action: str  # created | merged | linked
    match_score: float | None
    match_strategy: str | None
    matched_alias: str | None
    disclaimer: str


# ---------------------------------------------------------------------------
# Entity read models
# ---------------------------------------------------------------------------


class AliasOut(BaseModel):
    alias: str
    alias_type: str
    source: str | None

    model_config = {"from_attributes": True}


class EntityOut(BaseModel):
    entity_id: str
    canonical_name: str
    display_name: str
    entity_type: str
    confidence: float
    source_count: int
    is_pii_masked: bool
    data_class: str = "standard"
    usage: str = "analysis"
    source_label: str = "unknown"
    record_badge: str | None = None
    created_at: datetime
    updated_at: datetime
    aliases: list[AliasOut] = []
    disclaimer: str = "Outputs are intelligence leads, not verified conclusions."

    model_config = {"from_attributes": True}


class EntityListResponse(BaseModel):
    entities: list[EntityOut]
    total: int
    disclaimer: str


# ---------------------------------------------------------------------------
# NLP / Analysis
# ---------------------------------------------------------------------------


class SignalOut(BaseModel):
    signal_type: str
    label: str
    confidence: float
    evidence: str
    source_name: str | None = None
    trust_level: str = "unvalidated_osint"
    usage: str | None = None


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    source_url: str | None = None
    source_name: str | None = None
    entity_id: str | None = None


class AnalyzeResponse(BaseModel):
    entity_id: str | None
    signals: list[SignalOut]
    risk_score: float
    confidence_score: float
    system_confidence: float
    explanation: str
    case_id: str | None = None
    alert_id: str | None = None
    disclaimer: str


# ---------------------------------------------------------------------------
# Risk Scoring
# ---------------------------------------------------------------------------


class RiskScoreDetail(BaseModel):
    factor: str
    contribution: float
    notes: str


class RiskScoreOut(BaseModel):
    risk_score: float          # 0–100
    risk_band: str             # low | medium | high | critical
    confidence_score: float    # 0–1
    system_confidence: float   # 0–1 (calibrated trust in this output)
    factors: list[RiskScoreDetail]
    explanation: str
    calibration: dict = Field(default_factory=dict)
    disclaimer: str


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class CaseOut(BaseModel):
    case_id: str
    status: str
    risk_score: float
    confidence_score: float
    system_confidence: float = 0.0
    priority_score: float | None = None
    priority_band: str | None = None
    priority_explanation: str | None = None
    corroboration_tier: str | None = None
    independent_corroboration: dict = Field(default_factory=dict)
    explanation: str
    entity_ids: list[str]
    assigned_analyst: str | None
    created_at: datetime
    disclaimer: str

    model_config = {"from_attributes": True}


class CaseListResponse(BaseModel):
    cases: list[CaseOut]
    total: int
    disclaimer: str


class CaseEvaluateRequest(BaseModel):
    entity_id: str
    text: str = Field(min_length=1, max_length=50_000)
    source_name: str | None = None
    source_url: str | None = None


class CaseSummaryOut(BaseModel):
    case_id: str
    status: str
    risk_score: float
    confidence_score: float
    system_confidence: float
    narrative: str
    event_count: int
    recent_event_count_7d: int
    source_count: int
    alert_count: int
    unacknowledged_alert_count: int
    disclaimer: str


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertOut(BaseModel):
    alert_id: str
    case_id: str
    severity: str
    message: str
    triggered_at: datetime
    acknowledged: bool
    acknowledged_at: datetime | None

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    alerts: list[AlertOut]
    total: int
    unacknowledged_count: int


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str   # Entity | Location | Event | Signal
    properties: dict


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str
    properties: dict = Field(default_factory=dict)


class GraphResponse(BaseModel):
    entity_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    disclaimer: str


class EntityEventOut(BaseModel):
    event_id: str
    entity_id: str
    event_type: str
    source_name: str | None
    source_url: str | None
    location: str | None
    summary: str
    event_timestamp: datetime
    event_metadata: dict

    model_config = {"from_attributes": True}


class EntityTimelineResponse(BaseModel):
    entity_id: str
    events: list[EntityEventOut]
    total: int
    disclaimer: str


class EntityCorrelationResponse(BaseModel):
    entity_id: str
    found: bool
    source_diversity: int
    cross_source_reinforcement: float
    shared_identifier_hits: int
    temporal_burst_24h: int
    event_count: int = 0
    confidence: float = 0.0
    interpretation: str = (
        "Potential correlation detected between records and external signals; this is not a legal determination."
    )
    disclaimer: str


class GraphAnalyticsResponse(BaseModel):
    entity_id: str
    node_count: int
    edge_count: int
    signal_node_count: int
    connected_entity_count: int
    centrality_hint: float
    community_count: int
    influence_score: float
    insight: str
    disclaimer: str


class CaseClusterOut(BaseModel):
    cluster_id: str
    size: int
    case_ids: list[str]
    avg_risk_score: float


class CaseClusterResponse(BaseModel):
    clusters: list[CaseClusterOut]
    total_clusters: int
    disclaimer: str


class TrustConfigOut(BaseModel):
    risk_medium_threshold: float
    risk_high_threshold: float
    risk_critical_threshold: float
    cluster_similarity_threshold: float
    false_positive_penalty: float
    updated_at: datetime
    disclaimer: str

    model_config = {"from_attributes": True}


class TrustConfigUpdateRequest(BaseModel):
    risk_medium_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    risk_high_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    risk_critical_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    cluster_similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    false_positive_penalty: float | None = Field(default=None, ge=0.0, le=1.0)


class FeedbackIn(BaseModel):
    case_id: str
    analyst_id: str
    is_false_positive: bool = False
    corrected_risk_score: float | None = Field(default=None, ge=0.0, le=100.0)
    notes: str | None = None


class AnalystDecisionIn(BaseModel):
    analyst_id: str
    analyst_role: str = Field(default="junior_analyst", pattern="^(junior_analyst|senior_analyst|trusted_operator)$")
    decision_type: str = Field(pattern="^(confirm_convergence|reject_correlation|mark_high_priority)$")
    notes: str | None = None
    corrected_risk_score: float | None = Field(default=None, ge=0.0, le=100.0)


class AnalystDecisionOut(BaseModel):
    feedback_id: str
    case_id: str
    analyst_id: str
    analyst_role: str = "junior_analyst"
    decision_weight: float = 1.0
    decision_type: str | None
    is_false_positive: bool
    corrected_risk_score: float | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackOut(BaseModel):
    feedback_id: str
    case_id: str
    analyst_id: str
    is_false_positive: bool
    corrected_risk_score: float | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackStats(BaseModel):
    total_feedback: int
    false_positive_rate: float
    adaptive_penalty: float
    disclaimer: str


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------


class SignalContributionOut(BaseModel):
    signal_type: str
    label: str
    confidence: float
    evidence: str
    source_name: str
    weight_pct: float


class ConfidenceBreakdownOut(BaseModel):
    signal_avg: float
    signal_weight: float
    entity_confidence: float
    entity_weight: float
    diversity_bonus: float
    diversity_weight: float
    calibration_penalty: float
    final_system_confidence: float
    raw_score_before_calibration: float = 0.0
    source_class_cap: float | None = None
    confidence_cap: float | None = None
    reference_only_penalty: float = 0.0
    corroboration_boost: float = 0.0
    cross_source_unlock: str | None = None
    final_risk_score: float = 0.0


class FeedbackEntryOut(BaseModel):
    analyst_id: str
    decision_type: str | None = None
    is_false_positive: bool
    corrected_risk_score: float | None
    notes: str
    created_at: str | None


class FeedbackSummaryOut(BaseModel):
    feedback_count: int
    false_positive_count: int
    false_positive_rate: float
    avg_corrected_risk_score: float | None
    decision_counts: dict = Field(default_factory=dict)
    recent_feedback: list[FeedbackEntryOut]


class TrustConfigContextOut(BaseModel):
    risk_medium_threshold: float
    risk_high_threshold: float
    risk_critical_threshold: float
    false_positive_penalty: float


class CaseExplainabilityResponse(BaseModel):
    case_id: str
    case_status: str
    risk_score: float
    system_confidence: float
    signal_count: int
    signal_contributions: list[SignalContributionOut]
    confidence_breakdown: ConfidenceBreakdownOut
    feedback_summary: FeedbackSummaryOut
    trust_config_context: TrustConfigContextOut
    explanation: str
    entity_ids: list[str]
    created_at: str | None
    updated_at: str | None
    disclaimer: str
    source_impact: dict = Field(default_factory=dict)
    score_calibration: dict = Field(default_factory=dict)
    priority: dict = Field(default_factory=dict)


class FeedbackHistoryEntry(BaseModel):
    feedback_id: str
    analyst_id: str
    decision_type: str | None = None
    is_false_positive: bool
    corrected_risk_score: float | None
    notes: str
    created_at: str | None


class FeedbackHistoryResponse(BaseModel):
    case_id: str
    days: int
    feedback_count: int
    history: list[FeedbackHistoryEntry]
    disclaimer: str = "Feedback records are audit-trailed and immutable for compliance."
